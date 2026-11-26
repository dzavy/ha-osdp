"""Event entities for card reads and key presses."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPE_KEYPRESS, EVENT_TYPE_TAG_SCANNED, signal_reader_event
from .coordinator import OSDPConfigEntry, OSDPCoordinator
from .entity import OSDPReaderEntity
from .hub import ReaderConfig

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OSDPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OSDP event entities."""
    coordinator = entry.runtime_data.coordinator
    entities: list[EventEntity] = []
    for reader in entry.runtime_data.hub.readers:
        entities.append(OSDPCardEvent(coordinator, reader))
        entities.append(OSDPKeypadEvent(coordinator, reader))
    async_add_entities(entities)


class _OSDPReaderEvent(OSDPReaderEntity, EventEntity):
    """Event entity fed by the hub through the dispatcher."""

    _source_type: str
    _event_type: str

    def __init__(self, coordinator: OSDPCoordinator, reader: ReaderConfig, key: str) -> None:
        super().__init__(coordinator, reader, key)
        self._attr_event_types = [self._event_type]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_reader_event(
                    self.coordinator.config_entry.entry_id, self.reader.address
                ),
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, payload: dict[str, Any]) -> None:
        if payload["type"] != self._source_type:
            return
        self._trigger_event(self._event_type, self._attributes(payload))
        self.async_write_ha_state()

    def _attributes(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class OSDPCardEvent(_OSDPReaderEvent):
    """Fires when a card is presented."""

    _source_type = EVENT_TYPE_TAG_SCANNED
    _event_type = "card_read"

    def __init__(self, coordinator: OSDPCoordinator, reader: ReaderConfig) -> None:
        super().__init__(coordinator, reader, "card")

    def _attributes(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"tag_id": payload["tag_id"], "reader_no": payload["reader_no"]}


class OSDPKeypadEvent(_OSDPReaderEvent):
    """Fires when keys are pressed on a reader keypad."""

    _source_type = EVENT_TYPE_KEYPRESS
    _event_type = "keypress"
    # Most readers have no keypad; enable it from the entity settings if yours does.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: OSDPCoordinator, reader: ReaderConfig) -> None:
        super().__init__(coordinator, reader, "keypad")

    def _attributes(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"keys": payload["keys"], "reader_no": payload["reader_no"]}
