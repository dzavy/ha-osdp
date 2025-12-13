from __future__ import annotations

import struct
import osdp

import voluptuous as vol
from typing import Any

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType

from .const import DOMAIN

# Supported trigger types
TRIGGER_TYPES = {"card_read"}

TRIGGER_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_PLATFORM): "device",
            vol.Required(CONF_DOMAIN): DOMAIN,
            vol.Required(CONF_DEVICE_ID): str,
            vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        }
    ),
)

async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """List device triggers for a given OSDP reader device."""
    triggers: list[dict[str, Any]] = []

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if not device:
        return []

    # Only expose triggers for reader devices (not controller)
    for ident_domain, ident in device.identifiers:
        if ident_domain == DOMAIN and ident.startswith("reader_"):
            for trig_type in TRIGGER_TYPES:
                triggers.append(
                    {
                        CONF_PLATFORM: "device",
                        CONF_DOMAIN: DOMAIN,
                        CONF_DEVICE_ID: device_id,
                        CONF_TYPE: trig_type,
                    }
                )
    return triggers


async def async_get_trigger_capabilities(
        hass: HomeAssistant, device_id: str, trigger: dict[str, Any]
) -> dict[str, Any]:
    """Return extra capabilities for a trigger (none for card_read)."""
    return {"extra_fields": vol.Schema({})}


async def async_attach_trigger(
        hass: HomeAssistant,
        device_id: str,
        trigger: dict[str, Any],
        action: TriggerActionType,
        trigger_info: dict[str, Any],
) -> Any:
    """Attach a trigger to listen for card_read events."""
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if not device:
        return None

    # Extract reader_id from identifier string
    reader_id = None
    for ident_domain, ident in device.identifiers:
        if ident_domain == DOMAIN and ident.startswith("reader_"):
            # ident looks like "reader_<port>_<rid>"
            try:
                reader_id = int(ident.split("_")[-1])
            except Exception:
                pass

    if reader_id is None:
        return None

    signal = f"osdp_update_{trigger_info['config_entry'].entry_id}_{reader_id}"

    async def _handle_event(event: dict) -> None:
        if trigger[CONF_TYPE] == "card_read" and event["event"] == osdp.Event.CardRead:
            await action({"card_number": struct.unpack('>L', event["data"])[0]})

    return async_dispatcher_connect(hass, signal, _handle_event)