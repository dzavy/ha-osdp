from __future__ import annotations

import logging
import struct

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up OSDP sensors for each reader and the controller diagnostic sensor."""
    domain_data = hass.data[DOMAIN][entry.entry_id]
    readers = domain_data["readers"]  # list of ints
    port = domain_data["port"]
    baudrate = domain_data["baudrate"]
    name = domain_data["name"]

    entities = []

    # Per-reader sensors
    for rid in readers:
        entities.append(OSDPReaderInfoSensor(entry.entry_id, port, rid, "version", "Version"))
        entities.append(OSDPReaderInfoSensor(entry.entry_id, port, rid, "model", "Model"))
        entities.append(OSDPReaderInfoSensor(entry.entry_id, port, rid, "vendor_code", "Vendor Code"))
        entities.append(OSDPReaderInfoSensor(entry.entry_id, port, rid, "serial_number", "Serial Number"))
        entities.append(OSDPReaderInfoSensor(entry.entry_id, port, rid, "firmware_version", "Firmware Version"))

    # Controller diagnostic sensor
    entities.append(OSDPControllerStatusSensor(entry.entry_id, port, baudrate, name))

    async_add_entities(entities)

class OSDPReaderInfoSensor(SensorEntity):
    """Base class for reader info sensors populated from get_pd_id."""

    def __init__(self, entry_id: str, port: str, reader_id: int, field: str, name: str):
        self._entry_id = entry_id
        self._port = port
        self._reader_id = reader_id
        self._field = field
        self._attr_name = name
        self._attr_unique_id = f"osdp_{field}_{entry_id}_{reader_id}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._value: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"reader_{self._port}_{self._reader_id}")},
            name=f"OSDP Reader {self._reader_id}",
            manufacturer="OSDP",
            model="Card Reader",
            via_device=(DOMAIN, f"controller_{self._port}"),
        )

    @property
    def native_value(self) -> str | None:
        return self._value

    async def async_update(self) -> None:
        """Poll ControlPanel for PD ID info."""
        domain_data = self.hass.data[DOMAIN].get(self._entry_id)
        cp = domain_data.get("cp") if domain_data else None
        if cp:
            try:
                pd_info = cp.get_pd_id(self._reader_id)
                if pd_info:
                    self._value = struct.unpack('>L', getattr(pd_info, self._field, None))[0]
            except Exception as exc:
                _LOGGER.debug("get_pd_id failed for reader %s: %s", self._reader_id, exc)
                self._value = None

class OSDPControllerStatusSensor(SensorEntity):
    """Diagnostic sensor for the OSDP controller hub."""

    _attr_has_entity_name = True
    _attr_name = "Controller Status"

    def __init__(self, entry_id: str, port: str, baudrate: int, name: str):
        self._entry_id = entry_id
        self._port = port
        self._baudrate = baudrate
        self._name = name
        self._attr_unique_id = f"osdp_controller_status_{entry_id}"
        self._status = "running"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"controller_{self._port}")},
            manufacturer="OSDP",
            name=self._name,
            model="OSDP Bus",
        )

    @property
    def native_value(self):
        return f"{self._status} @ {self._baudrate} baud"

    @property
    def extra_state_attributes(self):
        domain_data = self.hass.data[DOMAIN].get(self._entry_id)
        readers = domain_data.get("readers", []) if domain_data else []
        return {
            "baudrate": self._baudrate,
            "port": self._port,
            "reader_count": len(readers),
            "readers": readers,
        }

    async def async_update(self):
        domain_data = self.hass.data[DOMAIN].get(self._entry_id)
        if domain_data and domain_data.get("cp"):
            self._status = "running"
            self._baudrate = domain_data.get("baudrate", self._baudrate)
        else:
            self._status = "stopped"