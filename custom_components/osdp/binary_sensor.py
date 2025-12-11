from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up OSDP binary sensors for each reader."""
    domain_data = hass.data[DOMAIN][entry.entry_id]
    readers = domain_data["readers"]  # list of ints
    port = domain_data["port"]

    entities = [OSDPReaderOnlineBinarySensor(entry.entry_id, port, rid) for rid in readers]
    async_add_entities(entities)


class OSDPReaderOnlineBinarySensor(BinarySensorEntity):
    """Binary sensor indicating if the reader is online."""

    _attr_has_entity_name = True
    _attr_name = "Online"

    def __init__(self, entry_id: str, port: str, reader_id: int) -> None:
        self._entry_id = entry_id
        self._port = port
        self._reader_id = reader_id
        self._attr_unique_id = f"osdp_online_{entry_id}_{reader_id}"
        self._is_on: bool = False

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
    def is_on(self) -> bool:
        return self._is_on

    async def async_update(self) -> None:
        """Poll ControlPanel for online status."""
        domain_data = self.hass.data[DOMAIN].get(self._entry_id)
        cp = domain_data.get("cp") if domain_data else None
        if cp:
            try:
                self._is_on = cp.is_online(self._reader_id)
            except Exception as exc:
                _LOGGER.debug("is_online failed for reader %s: %s", self._reader_id, exc)
                self._is_on = False
