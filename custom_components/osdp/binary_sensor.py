from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, signal_reader_update

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up OSDP binary sensors for each reader."""
    domain_data = hass.data[DOMAIN][entry.entry_id]
    readers = domain_data["readers"]  # list of ints
    port = domain_data["port"]

    entities = [OSDPCardPresentBinarySensor(entry.entry_id, port, rid) for rid in readers]
    async_add_entities(entities)


class OSDPCardPresentBinarySensor(BinarySensorEntity):
    """Binary sensor indicating if a card is present at the reader."""

    _attr_has_entity_name = True
    _attr_name = "Card present"

    def __init__(self, entry_id: str, port: str, reader_id: int) -> None:
        self._entry_id = entry_id
        self._port = port
        self._reader_id = reader_id
        self._attr_unique_id = f"osdp_card_present_{entry_id}_{reader_id}"
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

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_reader_update(self._entry_id, self._reader_id),
                self._handle_event,
            )
        )

    async def _handle_event(self, event: Any) -> None:
        etype = event.get("event")
        if etype == "CARD_READ":
            self._is_on = True
        elif etype == "CARD_REMOVED":
            self._is_on = False
        self.async_write_ha_state()