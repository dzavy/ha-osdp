"""Diagnostics support for the OSDP integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_RUN_AS_USER, CONF_SCBK
from .coordinator import OSDPConfigEntry

TO_REDACT = {CONF_SCBK, CONF_RUN_AS_USER}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OSDPConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    hub = entry.runtime_data.hub
    state = entry.runtime_data.coordinator.data
    return {
        "entry": {
            "version": entry.version,
            "data": dict(entry.data),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "bus": {
            "port_open": hub.channel.is_open,
            "last_error": hub.channel.last_error,
            "control_panel_running": hub.cp is not None,
        },
        "state": None
        if state is None
        else {
            "connected": state.connected,
            "online": sorted(state.online),
            "secure_channel": sorted(state.secure),
            "identities": {
                addr: asdict(ident) for addr, ident in state.identities.items()
            },
        },
    }
