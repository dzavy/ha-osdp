"""Sensors for the OSDP integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OSDPConfigEntry
from .entity import OSDPControllerEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OSDPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OSDP sensors."""
    async_add_entities([OSDPReadersOnlineSensor(entry.runtime_data.coordinator)])


class OSDPReadersOnlineSensor(OSDPControllerEntity, SensorEntity):
    """Number of configured readers currently online."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "readers_online")

    @property
    def native_value(self) -> int:
        data = self.coordinator.data
        return len(data.online) if data and data.connected else 0

    @property
    def extra_state_attributes(self) -> dict[str, list[int]]:
        data = self.coordinator.data
        return {
            "configured": self.coordinator.hub.addresses,
            "online": sorted(data.online) if data else [],
        }
