from __future__ import annotations

import voluptuous as vol
from typing import Any

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.helpers.typing import ConfigType

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

async def async_get_trigger_capabilities(hass: HomeAssistant, config: ConfigType) -> dict[str, vol.Schema]:
    """List trigger capabilities."""
    return {
        "extra_fields": vol.Schema(None)
    }

async def async_attach_trigger(hass, config, action, trigger_info):
    """Attach a trigger."""
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: "osdp_event",
            event_trigger.CONF_EVENT_DATA: {
                CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                CONF_TYPE: config[CONF_TYPE],
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
