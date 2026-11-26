"""Actions for controlling reader LEDs, buzzer and outputs."""

from __future__ import annotations

import osdp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, reader_identifier

SERVICE_SET_LED = "set_led"
SERVICE_BEEP = "beep"
SERVICE_SET_OUTPUT = "set_output"

ATTR_COLOR = "color"
ATTR_OFF_COLOR = "off_color"
ATTR_ON_TIME = "on_time"
ATTR_OFF_TIME = "off_time"
ATTR_DURATION = "duration"
ATTR_LED_NUMBER = "led_number"
ATTR_REPEAT = "repeat"
ATTR_OUTPUT = "output"
ATTR_STATE = "state"

LED_COLORS = {
    "off": osdp.CommandLEDColor.Black,
    "red": osdp.CommandLEDColor.Red,
    "green": osdp.CommandLEDColor.Green,
    "amber": osdp.CommandLEDColor.Amber,
    "blue": osdp.CommandLEDColor.Blue,
    "magenta": osdp.CommandLEDColor.Magenta,
    "cyan": osdp.CommandLEDColor.Cyan,
    "white": osdp.CommandLEDColor.White,
}

# OSDP timings are in units of 100 ms and (in the libosdp binding) one byte.
_MAX_TICKS = 255
_MAX_SECONDS = _MAX_TICKS / 10
_MAX_MS = _MAX_TICKS * 100

_TIME_MS = vol.All(vol.Coerce(int), vol.Range(min=0, max=_MAX_MS))
_DURATION_S = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=_MAX_SECONDS))

SET_LED_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_COLOR): vol.In(LED_COLORS),
        vol.Optional(ATTR_OFF_COLOR, default="off"): vol.In(LED_COLORS),
        vol.Optional(ATTR_ON_TIME, default=0): _TIME_MS,
        vol.Optional(ATTR_OFF_TIME, default=0): _TIME_MS,
        vol.Optional(ATTR_DURATION): _DURATION_S,
        vol.Optional(ATTR_LED_NUMBER, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
    }
)

BEEP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_ON_TIME, default=500): vol.All(
            vol.Coerce(int), vol.Range(min=100, max=_MAX_MS)
        ),
        vol.Optional(ATTR_OFF_TIME, default=0): _TIME_MS,
        vol.Optional(ATTR_REPEAT, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=255)
        ),
    }
)

SET_OUTPUT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_OUTPUT, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
        vol.Required(ATTR_STATE): cv.boolean,
        vol.Optional(ATTR_DURATION): _DURATION_S,
    }
)


def _ticks(ms: float) -> int:
    return max(0, min(_MAX_TICKS, round(ms / 100)))


def _resolve(hass: HomeAssistant, device_id: str):
    """Return (hub, address) for a reader device id."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_device",
            translation_placeholders={"device_id": device_id},
        )
    entry = hass.config_entries.async_get_entry(device.config_entry_id)
    if entry is not None and entry.domain == DOMAIN:
        if entry.state is not ConfigEntryState.LOADED:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_loaded"
            )
        hub = entry.runtime_data.hub
        for reader in hub.readers:
            if reader_identifier(entry.entry_id, reader.address) in device.identifiers:
                return hub, reader.address
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="not_a_reader",
        translation_placeholders={"device_id": device_id},
    )


async def _submit(hass: HomeAssistant, device_id: str, command: dict) -> None:
    hub, address = _resolve(hass, device_id)
    coordinator = hub.entry.runtime_data.coordinator
    if coordinator.data is None or address not in coordinator.data.online:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="reader_offline",
            translation_placeholders={"address": str(address)},
        )
    ok = await hass.async_add_executor_job(hub.submit_command, address, command)
    if not ok:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"address": str(address)},
        )


async def _async_set_led(call: ServiceCall) -> None:
    data = call.data
    on_color = LED_COLORS[data[ATTR_COLOR]]
    off_color = LED_COLORS[data[ATTR_OFF_COLOR]]
    on_time, off_time = data[ATTR_ON_TIME], data[ATTR_OFF_TIME]
    if not on_time and not off_time:
        # Steady colour: OSDP expresses this as on_time > 0 and off_time == 0.
        on_count, off_count = 1, 0
    else:
        on_count, off_count = _ticks(on_time), _ticks(off_time)

    command = {
        "command": osdp.Command.LED,
        "reader": 0,
        "led_number": data[ATTR_LED_NUMBER],
        "on_color": on_color,
        "off_color": off_color,
        "on_count": on_count,
        "off_count": off_count,
    }
    if ATTR_DURATION in data:
        # Temporary state, reverts to the permanent state when the timer expires.
        command.update(
            temporary=True,
            control_code=2,
            timer_count=_ticks(data[ATTR_DURATION] * 1000),
        )
    else:
        command.update(temporary=False, control_code=1)
    await _submit(call.hass, data[ATTR_DEVICE_ID], command)


async def _async_beep(call: ServiceCall) -> None:
    data = call.data
    command = {
        "command": osdp.Command.Buzzer,
        "reader": 0,
        "control_code": 2,  # default tone
        "on_count": max(1, _ticks(data[ATTR_ON_TIME])),
        "off_count": _ticks(data[ATTR_OFF_TIME]),
        "rep_count": data[ATTR_REPEAT],
    }
    await _submit(call.hass, data[ATTR_DEVICE_ID], command)


async def _async_set_output(call: ServiceCall) -> None:
    data = call.data
    state: bool = data[ATTR_STATE]
    if ATTR_DURATION in data:
        # 5: temporary on, then off; 6: temporary off, then on.
        control_code = 5 if state else 6
        timer = _ticks(data[ATTR_DURATION] * 1000)
    else:
        # 4: permanent on, 3: permanent off; both cancel a running timer.
        control_code = 4 if state else 3
        timer = 0
    command = {
        "command": osdp.Command.Output,
        "output_no": data[ATTR_OUTPUT],
        "control_code": control_code,
        "timer_count": timer,
    }
    await _submit(call.hass, data[ATTR_DEVICE_ID], command)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(DOMAIN, SERVICE_SET_LED, _async_set_led, SET_LED_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_BEEP, _async_beep, BEEP_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_OUTPUT, _async_set_output, SET_OUTPUT_SCHEMA
    )
