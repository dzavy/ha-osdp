"""Polling coordinator for an OSDP bus."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, UPDATE_INTERVAL, reader_identifier
from .hub import BusState, OSDPHub, ReaderIdentity

_LOGGER = logging.getLogger(__name__)


@dataclass
class OSDPRuntimeData:
    """Runtime data stored on the config entry."""

    hub: OSDPHub
    coordinator: OSDPCoordinator


type OSDPConfigEntry = ConfigEntry[OSDPRuntimeData]


class OSDPCoordinator(DataUpdateCoordinator[BusState]):
    """Polls reader online / secure-channel status for the whole bus at once."""

    config_entry: OSDPConfigEntry

    def __init__(self, hass: HomeAssistant, entry: OSDPConfigEntry, hub: OSDPHub) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {hub.port}",
            update_interval=UPDATE_INTERVAL,
        )
        self.hub = hub
        self._published: dict[int, ReaderIdentity] = {}

    async def _async_update_data(self) -> BusState:
        state = await self.hass.async_add_executor_job(self.hub.poll)
        self._publish_identities(state)
        return state

    def _publish_identities(self, state: BusState) -> None:
        """Write newly learned reader identity into the device registry."""
        devreg = dr.async_get(self.hass)
        for address, ident in state.identities.items():
            if self._published.get(address) == ident:
                continue
            device = devreg.async_get_device_by_identifier(
                reader_identifier(self.config_entry.entry_id, address),
                self.config_entry.entry_id,
            )
            if device is None:
                continue
            devreg.async_update_device(
                device.id,
                manufacturer=ident.manufacturer,
                model=ident.model,
                hw_version=ident.hw_version,
                serial_number=ident.serial_number,
                sw_version=ident.sw_version,
            )
            self._published[address] = ident
