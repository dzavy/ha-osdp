"""Base entities for the OSDP integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import controller_identifier, reader_identifier
from .coordinator import OSDPCoordinator
from .hub import ReaderConfig


class OSDPControllerEntity(CoordinatorEntity[OSDPCoordinator]):
    """Entity attached to the controller (bus) device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OSDPCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"osdp_{key}_{entry_id}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={controller_identifier(entry_id)})


class OSDPReaderEntity(CoordinatorEntity[OSDPCoordinator]):
    """Entity attached to a reader device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OSDPCoordinator, reader: ReaderConfig, key: str
    ) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self.reader = reader
        self._attr_unique_id = f"osdp_{key}_{entry_id}_{reader.address}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={reader_identifier(entry_id, reader.address)}
        )

    @property
    def available(self) -> bool:
        """Reader entities are unavailable while the serial bus is down."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.connected
        )
