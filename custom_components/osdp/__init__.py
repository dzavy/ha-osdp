from __future__ import annotations
import logging
from typing import List
import serial
import osdp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import async_get as async_get_devreg
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_CONTROLLER_NAME,
    DEFAULT_BAUDRATE,
    signal_reader_update,
)

_LOGGER = logging.getLogger(__name__)


class SerialChannel(osdp.Channel):
    """Simple serial channel implementing osdp.Channel interface."""

    def __init__(self, device: str, speed: int):
        super().__init__()
        self.dev = serial.Serial(device, speed, timeout=0)

    def read(self, max_read: int):
        return self.dev.read(max_read)

    def write(self, data: bytes):
        return self.dev.write(data)

    def flush(self):
        self.dev.flush()

    def __del__(self):
        try:
            self.dev.close()
        except Exception:
            pass


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an OSDP controller and its readers from a config entry."""
    data = entry.data
    port: str = data[CONF_PORT]
    baudrate: int = entry.options.get(CONF_BAUDRATE, data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
    name: str = data.get(CONF_CONTROLLER_NAME, f"OSDP Controller ({port})")

    readers_cfg: List[int] = entry.options.get("readers", [])

    # Controller-level callback
    def _controller_callback(id: int, event: dict) -> int:
        """Handle events from the OSDP ControlPanel and dispatch per reader."""
        _LOGGER.debug("Dispatching event")
        rid = event.get("reader_no")
        _LOGGER.debug("Dispatching event for reader %s", rid)

        if rid is not None:
            dispatcher_send(
                hass,
                signal_reader_update(entry.entry_id, rid),
                event,
            )
        return 0

    cp = None
    if readers_cfg:
        channel = SerialChannel(port, baudrate)
        pd_infos = [osdp.PDInfo(rid, channel) for rid in readers_cfg]
        cp = osdp.ControlPanel(pd_infos, osdp.LogLevel.Info, _controller_callback)
        cp.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "cp": cp,
        "readers": readers_cfg,
        "port": port,
        "baudrate": baudrate,
        "name": name,
    }

    # Register controller device
    devreg = async_get_devreg(hass)
    devreg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"controller_{port}")},
        manufacturer="OSDP",
        name=name,
        model="OSDP Bus",
    )

    # Register reader devices
    for rid in readers_cfg:
        devreg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"reader_{port}_{rid}")},
            manufacturer="OSDP",
            name=f"OSDP Reader {rid}",
            model="Card Reader",
            via_device=(DOMAIN, f"controller_{port}"),
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.info("OSDP controller on %s @ %s set up with readers: %s", port, baudrate, readers_cfg)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an OSDP config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and data["cp"]:
        try:
            data["cp"].stop()
        except Exception as exc:
            _LOGGER.warning("Error stopping ControlPanel: %s", exc)
    return unloaded


@callback
async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rebuild the ControlPanel when options (readers list or baudrate) change."""
    domain_data = hass.data[DOMAIN].get(entry.entry_id)
    if not domain_data:
        return

    old_cp: osdp.ControlPanel | None = domain_data["cp"]
    port: str = domain_data["port"]
    baudrate: int = entry.options.get(CONF_BAUDRATE, domain_data["baudrate"])
    name: str = domain_data["name"]

    old_readers_cfg: List[int] = domain_data["readers"]
    new_readers_cfg: List[int] = entry.options.get("readers", [])

    # Stop old CP
    if old_cp:
        try:
            old_cp.stop()
        except Exception as exc:
            _LOGGER.debug("Stopping previous ControlPanel failed: %s", exc)

    # Controller-level callback
    def _controller_callback(id: int, event: dict) -> int:
        _LOGGER.debug("Dispatching event")
        rid = event.get("reader_no")
        _LOGGER.debug("Dispatching event for reader %s", rid)
        if rid is not None:
            dispatcher_send(
                hass,
                signal_reader_update(entry.entry_id, rid),
                event,
            )
        return 0

    new_cp = None
    if new_readers_cfg:
        channel = SerialChannel(port, baudrate)
        pd_infos = [osdp.PDInfo(rid, channel) for rid in new_readers_cfg]
        new_cp = osdp.ControlPanel(pd_infos, osdp.LogLevel.Info, _controller_callback)
        new_cp.start()

    # Save new CP and readers
    domain_data["cp"] = new_cp
    domain_data["readers"] = new_readers_cfg
    domain_data["baudrate"] = baudrate

    devreg = dr.async_get(hass)

    # Remove devices for readers no longer present
    removed_ids = set(old_readers_cfg) - set(new_readers_cfg)
    for rid in removed_ids:
        dev = devreg.async_get_device({(DOMAIN, f"reader_{port}_{rid}")})
        if dev:
            devreg.async_remove_device(dev.id)
            _LOGGER.info("Removed OSDP Reader %s (port %s)", rid, port)

    # Ensure devices exist for new readers
    for rid in new_readers_cfg:
        devreg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"reader_{port}_{rid}")},
            manufacturer="OSDP",
            name=f"OSDP Reader {rid}",
            model="Card Reader",
            via_device=(DOMAIN, f"controller_{port}"),
        )

    # Reload entry so entities are recreated/removed accordingly
    await hass.config_entries.async_reload(entry.entry_id)