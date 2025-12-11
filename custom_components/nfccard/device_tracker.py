from __future__ import annotations
import logging
from datetime import datetime

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, CONF_CARD_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    card_id = entry.data[CONF_CARD_ID]
    tracker = NFCCardTracker(entry.entry_id, card_id)
    last_seen = NFCCardLastSeenSensor(entry.entry_id, card_id, tracker)
    async_add_entities([tracker, last_seen])


class NFCCardTracker(TrackerEntity):
    """Represents an NFC card as a device tracker."""

    def __init__(self, entry_id: str, card_id: str):
        self._entry_id = entry_id
        self._card_id = card_id
        self._attr_unique_id = f"nfc_card_{card_id}"
        self._attr_name = f"NFC Card {card_id}"
        self._attr_is_home = False
        self._last_seen: datetime | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._card_id)},
            name=f"NFC Card {self._card_id}",
            manufacturer="NFC",
            model="Card",
        )

    @property
    def last_seen(self) -> datetime | None:
        return self._last_seen

    def mark_seen(self):
        """Update last seen timestamp when card is detected."""
        self._last_seen = datetime.now()


class NFCCardLastSeenSensor(SensorEntity):
    """Sensor showing the last time the card was seen."""

    _attr_has_entity_name = True
    _attr_name = "Last seen"

    def __init__(self, entry_id: str, card_id: str, tracker: NFCCardTracker):
        self._entry_id = entry_id
        self._card_id = card_id
        self._tracker = tracker
        self._attr_unique_id = f"nfc_card_last_seen_{card_id}"
        self._value: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._card_id)},
            name=f"NFC Card {self._card_id}",
            manufacturer="NFC",
            model="Card",
        )

    @property
    def native_value(self) -> str | None:
        return self._value

    async def async_update(self):
        last_seen = self._tracker.last_seen
        if last_seen:
            self._value = last_seen.isoformat()
        else:
            self._value = None
