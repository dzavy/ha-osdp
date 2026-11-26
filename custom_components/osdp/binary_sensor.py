"""Binary sensors for the OSDP integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import OSDPConfigEntry
from .entity import OSDPControllerEntity, OSDPReaderEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OSDPConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OSDP binary sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = [OSDPBusConnectedSensor(coordinator)]
    for reader in entry.runtime_data.hub.readers:
        entities.append(OSDPReaderOnlineSensor(coordinator, reader, "online"))
        entities.append(OSDPReaderSecureSensor(coordinator, reader, "secure_channel"))
    async_add_entities(entities)


class OSDPBusConnectedSensor(OSDPControllerEntity, BinarySensorEntity):
    """Whether the serial adapter is present and open."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "serial_connection")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.connected)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        hub = self.coordinator.hub
        return {"port": hub.port, "last_error": hub.channel.last_error}


class OSDPReaderOnlineSensor(OSDPReaderEntity, BinarySensorEntity):
    """Whether the reader answers polls."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.reader.address in self.coordinator.data.online


class OSDPReaderSecureSensor(OSDPReaderEntity, BinarySensorEntity):
    """Whether the OSDP Secure Channel is established with the reader."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.reader.address in self.coordinator.data.secure
