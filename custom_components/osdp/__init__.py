"""The OSDP integration."""

from __future__ import annotations

import logging

import serial

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ADDRESS,
    CONF_BAUDRATE,
    CONF_CONTROLLER_NAME,
    CONF_NAME,
    CONF_PORT,
    CONF_READERS,
    DEFAULT_BAUDRATE,
    DEFAULT_CONTROLLER_NAME,
    DOMAIN,
    PLATFORMS,
    controller_identifier,
    reader_identifier,
)
from .coordinator import OSDPConfigEntry, OSDPCoordinator, OSDPRuntimeData
from .hub import OSDPHub
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-wide actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OSDPConfigEntry) -> bool:
    """Set up an OSDP controller and its readers from a config entry."""
    hub = OSDPHub(hass, entry)
    try:
        await hass.async_add_executor_job(hub.start)
    except (serial.SerialException, OSError) as exc:
        await hass.async_add_executor_job(hub.stop)
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_open_port",
            translation_placeholders={"port": hub.port, "error": str(exc)},
        ) from exc

    _async_register_devices(hass, entry, hub)

    coordinator = OSDPCoordinator(hass, entry, hub)
    entry.runtime_data = OSDPRuntimeData(hub=hub, coordinator=coordinator)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await hass.async_add_executor_job(hub.stop)
        raise

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.debug(
        "OSDP controller on %s @ %s set up with readers %s",
        hub.port,
        hub.baudrate,
        hub.addresses,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OSDPConfigEntry) -> bool:
    """Unload an OSDP config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.hub.stop)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: OSDPConfigEntry) -> None:
    """Options changed (readers added/removed/edited): rebuild everything."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_devices(
    hass: HomeAssistant, entry: OSDPConfigEntry, hub: OSDPHub
) -> None:
    """Create controller and reader devices; remove devices of deleted readers."""
    devreg = dr.async_get(hass)
    controller = devreg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={controller_identifier(entry.entry_id)},
        manufacturer="OSDP",
        model="OSDP Bus",
        name=entry.data.get(CONF_CONTROLLER_NAME, DEFAULT_CONTROLLER_NAME),
    )
    wanted = {controller.id}
    for reader in hub.readers:
        device = devreg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={reader_identifier(entry.entry_id, reader.address)},
            manufacturer="OSDP",
            model="Card Reader",
            name=reader.name,
            via_device_id=controller.id,
        )
        if device.name != reader.name:
            devreg.async_update_device(device.id, name=reader.name)
        wanted.add(device.id)

    for device in dr.async_entries_for_config_entry(devreg, entry.entry_id):
        if device.id not in wanted:
            devreg.async_remove_device(device.id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: OSDPConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a reader from its device page (removes it from options)."""
    if controller_identifier(entry.entry_id) in device.identifiers:
        return False

    readers = list(entry.options.get(CONF_READERS, []))
    remaining = [
        r
        for r in readers
        if reader_identifier(entry.entry_id, int(r[CONF_ADDRESS]))
        not in device.identifiers
    ]
    if len(remaining) != len(readers):
        # Triggers the update listener, which reloads the entry.
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_READERS: remaining}
        )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: OSDPConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 2:
        return False

    if entry.version == 1:
        port = entry.data[CONF_PORT]
        old_readers = [int(r) for r in entry.options.get(CONF_READERS, [])]

        data = {
            CONF_PORT: port,
            CONF_BAUDRATE: int(
                entry.options.get(
                    CONF_BAUDRATE, entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
                )
            ),
            CONF_CONTROLLER_NAME: entry.data.get(
                CONF_CONTROLLER_NAME, DEFAULT_CONTROLLER_NAME
            ),
        }
        options = {
            CONF_READERS: [
                {CONF_ADDRESS: rid, CONF_NAME: f"OSDP Reader {rid}"}
                for rid in old_readers
            ]
        }

        # Device identifiers were based on the port path; move them to the
        # entry id so a port rename no longer orphans devices. Device ids (and
        # thus automations referencing them) are preserved.
        devreg = dr.async_get(hass)
        remap = {(DOMAIN, f"controller_{port}"): controller_identifier(entry.entry_id)}
        for rid in old_readers:
            remap[(DOMAIN, f"reader_{port}_{rid}")] = reader_identifier(
                entry.entry_id, rid
            )
        for old, new in remap.items():
            if device := devreg.async_get_device_by_identifier(old, entry.entry_id):
                devreg.async_update_device(device.id, new_identifiers={new})

        # Reader identity moved from five sensors into the device registry and
        # the free-text controller status sensor was replaced.
        entreg = er.async_get(hass)
        for ent in er.async_entries_for_config_entry(entreg, entry.entry_id):
            if not ent.unique_id.startswith("osdp_online_"):
                entreg.async_remove(ent.entity_id)

        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=2
        )
        _LOGGER.info("Migrated OSDP config entry %s to version 2", entry.entry_id)

    return True
