"""OSDP bus handling: serial channel, ControlPanel lifecycle and polling."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging
import struct
import threading
from typing import Any

import osdp
import serial

from homeassistant.components import tag
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_ADDRESS,
    CONF_BAUDRATE,
    CONF_NAME,
    CONF_PORT,
    CONF_READERS,
    CONF_RUN_AS_USER,
    CONF_SCBK,
    DEFAULT_BAUDRATE,
    EVENT_OSDP,
    EVENT_TYPE_KEYPRESS,
    EVENT_TYPE_TAG_SCANNED,
    reader_identifier,
    signal_reader_event,
)

_LOGGER = logging.getLogger(__name__)

# OSDP keypad encoding: '*' is sent as 0x7F and '#' as 0x0D.
_KEYPAD_MAP = {0x7F: "*", 0x0D: "#"}


def _libosdp_log_level() -> int:
    """Map this integration's effective log level onto libosdp's."""
    level = _LOGGER.getEffectiveLevel()
    if level <= logging.DEBUG:
        return osdp.LogLevel.Debug
    if level <= logging.INFO:
        return osdp.LogLevel.Info
    if level <= logging.WARNING:
        return osdp.LogLevel.Warning
    return osdp.LogLevel.Error


@dataclass(frozen=True)
class ReaderConfig:
    """Configuration of one reader (peripheral device) on the bus."""

    address: int
    name: str
    scbk: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReaderConfig:
        """Build from the options dict representation."""
        return cls(
            address=int(data[CONF_ADDRESS]),
            name=data.get(CONF_NAME) or f"OSDP Reader {data[CONF_ADDRESS]}",
            scbk=data.get(CONF_SCBK) or None,
        )


@dataclass(frozen=True)
class ReaderIdentity:
    """Identity reported by a reader (osdp_PDID reply), formatted for display."""

    manufacturer: str
    model: str
    hw_version: str
    serial_number: str
    sw_version: str


@dataclass
class BusState:
    """Snapshot of the bus, produced by every coordinator poll."""

    connected: bool
    online: set[int] = field(default_factory=set)
    secure: set[int] = field(default_factory=set)
    identities: dict[int, ReaderIdentity] = field(default_factory=dict)


@lru_cache(maxsize=64)
def _vendor_name(vendor_code: int) -> str:
    """Resolve an IEEE OUI vendor code to a name (blocking, cached)."""
    tmphex = f"{vendor_code:0>6X}"
    oui = f"{tmphex[4:6]}:{tmphex[2:4]}:{tmphex[0:2]}"
    try:
        from ouilookup import OuiLookup  # noqa: PLC0415  (heavy import, lazy)

        result = OuiLookup().query(oui)
        name = next(iter(result[0].values()))
        if name:
            return str(name)
    except Exception:  # noqa: BLE001 - lookup is best effort
        _LOGGER.debug("OUI lookup failed for %s", oui, exc_info=True)
    return oui


def _format_identity(pd_id: Any) -> ReaderIdentity:
    """Turn a libosdp PdId into display strings (blocking: may do OUI lookup)."""
    serial_number = pd_id.serial_number
    if serial_number < 0:
        serial_number += 2**32
    serial_hex = f"{serial_number:0>8X}"
    fw_hex = f"{pd_id.firmware_version:0>6X}"
    return ReaderIdentity(
        manufacturer=_vendor_name(pd_id.vendor_code),
        model=f"{pd_id.model:0>2X}",
        hw_version=f"{pd_id.version:0>2X}",
        serial_number=f"{serial_hex[6:8]}{serial_hex[4:6]}{serial_hex[2:4]}{serial_hex[0:2]}",
        sw_version=f"{fw_hex[0:2]}.{fw_hex[2:4]}.{fw_hex[4:6]}",
    )


class SerialChannel(osdp.Channel):
    """osdp.Channel over pyserial that survives the adapter being unplugged.

    libosdp calls read/write/flush from its own thread. Any I/O error closes the
    port; the coordinator then calls ``reopen`` periodically from the executor.
    """

    def __init__(self, device: str, speed: int) -> None:
        super().__init__()
        self._device = device
        self._speed = speed
        self._lock = threading.Lock()
        self._dev: serial.Serial | None = None
        self.last_error: str | None = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    def open(self) -> None:
        """Open the port, raising on failure (blocking)."""
        with self._lock:
            if self._dev is None:
                self._dev = serial.Serial(self._device, self._speed, timeout=0)
                self.last_error = None

    def reopen(self) -> bool:
        """Try to reopen a closed port; return True if open afterwards."""
        try:
            self.open()
        except (serial.SerialException, OSError) as exc:
            self.last_error = str(exc)
            return False
        _LOGGER.info("Serial port %s reopened", self._device)
        return True

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:  # noqa: BLE001
                pass
            self._dev = None

    def _fail(self, exc: Exception) -> None:
        if self._dev is not None:
            _LOGGER.warning("Serial port %s failed: %s", self._device, exc)
        self.last_error = str(exc)
        self._close_locked()

    def read(self, max_read: int) -> bytes:
        with self._lock:
            if self._dev is None:
                return b""
            try:
                return self._dev.read(max_read)
            except (serial.SerialException, OSError) as exc:
                self._fail(exc)
                return b""

    def write(self, data: bytes) -> int:
        with self._lock:
            if self._dev is None:
                return 0
            try:
                return self._dev.write(data) or 0
            except (serial.SerialException, OSError) as exc:
                self._fail(exc)
                return 0

    def flush(self) -> None:
        with self._lock:
            if self._dev is None:
                return
            try:
                self._dev.flush()
            except (serial.SerialException, OSError) as exc:
                self._fail(exc)


class OSDPHub:
    """One OSDP bus (serial port) with its ControlPanel and readers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.port: str = entry.data[CONF_PORT]
        self.baudrate: int = int(entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
        self.readers: list[ReaderConfig] = [
            ReaderConfig.from_dict(r) for r in entry.options.get(CONF_READERS, [])
        ]
        self.channel = SerialChannel(self.port, self.baudrate)
        self.cp: osdp.ControlPanel | None = None
        # Identity is static; cache it once read so we don't redo the lookup.
        self._identities: dict[int, ReaderIdentity] = {}

    @property
    def addresses(self) -> list[int]:
        return [r.address for r in self.readers]

    # ----------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Open the port and start the ControlPanel (blocking).

        Raises serial.SerialException / OSError if the port can't be opened.
        """
        self.channel.open()
        if not self.readers:
            return
        pd_infos = [
            osdp.PDInfo(
                r.address,
                self.channel,
                scbk=bytes.fromhex(r.scbk) if r.scbk else None,
                name=r.name,
                flags=[osdp.LibFlag.EnforceSecure] if r.scbk else [],
            )
            for r in self.readers
        ]
        self.cp = osdp.ControlPanel(pd_infos, _libosdp_log_level(), self._event_handler)
        self.cp.start()

    def stop(self) -> None:
        """Stop the ControlPanel thread and close the port (blocking)."""
        if self.cp is not None:
            try:
                self.cp.stop()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Error stopping OSDP ControlPanel: %s", exc)
            self.cp = None
        self.channel.close()

    # -------------------------------------------------------------------- events

    def _event_handler(self, pd_index: int, event: dict) -> int:
        """Called by libosdp on its own thread; hand off to the event loop."""
        try:
            address = self.readers[pd_index].address
        except IndexError:
            _LOGGER.warning("Event for unknown PD index %s: %s", pd_index, event)
            return 0
        # libosdp also queues every event for its polling get_event() API, which
        # we don't use; drain it so the queue doesn't grow forever.
        if self.cp is not None:
            try:
                self.cp.event_queue[pd_index].get_nowait()
            except Exception:  # noqa: BLE001
                pass
        self.hass.loop.call_soon_threadsafe(self._async_handle_event, address, event)
        return 0

    @callback
    def _async_handle_event(self, address: int, event: dict) -> None:
        """Process a PD event on the event loop."""
        _LOGGER.debug("Reader %s event: %s", address, event)
        devreg = dr.async_get(self.hass)
        device = devreg.async_get_device({reader_identifier(self.entry.entry_id, address)})
        if device is None:
            return

        run_as = self.entry.options.get(CONF_RUN_AS_USER)
        ctx = Context(user_id=run_as) if run_as else Context()
        kind = event.get("event")

        if kind == osdp.Event.CardRead:
            tag_id = str(struct.unpack(">L", event["data"])[0])
            payload = {
                "type": EVENT_TYPE_TAG_SCANNED,
                "tag_id": tag_id,
                "device_id": device.id,
                "address": address,
                "reader_no": event.get("reader_no", 0),
            }
            self.hass.async_create_task(
                tag.async_scan_tag(self.hass, tag_id, device.id, ctx),
                eager_start=True,
            )
        elif kind == osdp.Event.KeyPress:
            keys = "".join(
                _KEYPAD_MAP.get(b, chr(b)) for b in event.get("data", b"")
            )
            payload = {
                "type": EVENT_TYPE_KEYPRESS,
                "keys": keys,
                "device_id": device.id,
                "address": address,
                "reader_no": event.get("reader_no", 0),
            }
        else:
            return

        self.hass.bus.async_fire(EVENT_OSDP, payload, context=ctx)
        async_dispatcher_send(
            self.hass, signal_reader_event(self.entry.entry_id, address), payload
        )

    # ------------------------------------------------------------------- polling

    def poll(self) -> BusState:
        """Collect bus state (blocking: takes the libosdp lock, may reopen port)."""
        if not self.channel.is_open and not self.channel.reopen():
            return BusState(connected=False)

        state = BusState(connected=True)
        cp = self.cp
        if cp is None:
            return state

        try:
            status = cp.status()
            sc_status = cp.sc_status()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Reading OSDP status failed: %s", exc)
            return state

        for idx, reader in enumerate(self.readers):
            if not status & (1 << idx):
                continue
            state.online.add(reader.address)
            if sc_status & (1 << idx):
                state.secure.add(reader.address)
            if reader.address not in self._identities:
                try:
                    pd_id = cp.get_pd_id(reader.address)
                except Exception:  # noqa: BLE001 - libosdp raises if no PDID yet
                    continue
                if pd_id is not None:
                    self._identities[reader.address] = _format_identity(pd_id)

        state.identities = dict(self._identities)
        return state

    # ------------------------------------------------------------------ commands

    def submit_command(self, address: int, command: dict) -> bool:
        """Queue a command for a reader (blocking: takes the libosdp lock)."""
        if self.cp is None:
            return False
        return bool(self.cp.submit_command(address, command))
