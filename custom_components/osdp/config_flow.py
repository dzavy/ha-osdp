import voluptuous as vol
import serial.tools.list_ports
from homeassistant import config_entries
from homeassistant.core import callback
from .const import (
    DOMAIN,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_CONTROLLER_NAME,
    DEFAULT_BAUDRATE,
)

# Common baudrates for OSDP
COMMON_BAUDRATES = [9600, 19200, 38400, 57600, 115200]


def _available_ports() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports()]


class OSDPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is None:
            ports = _available_ports()
            if not ports:
                ports = ["<no serial ports found>"]

            schema = vol.Schema(
                {
                    vol.Required(CONF_PORT): vol.In(ports),
                    vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(COMMON_BAUDRATES),
                    vol.Optional(CONF_CONTROLLER_NAME, default="OSDP Controller"): str,
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema)

        await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_PORT]}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=user_input.get(CONF_CONTROLLER_NAME, f"OSDP ({user_input[CONF_PORT]})"),
            data=user_input,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OSDPOptionsFlowHandler(config_entry)

class OSDPOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        readers = self._entry.options.get("readers", [])
        errors = {}

        if user_input is not None:
            action = user_input.get("action")
            try:
                reader_id = int(user_input["reader_id"])
            except (ValueError, TypeError):
                errors["reader_id"] = "invalid_id"
            else:
                if reader_id < 0 or reader_id > 127:
                    errors["reader_id"] = "out_of_range"
                elif action == "add" and reader_id in readers:
                    errors["reader_id"] = "duplicate"
                elif action == "remove" and reader_id not in readers:
                    errors["reader_id"] = "not_found"

            if not errors:
                if action == "add":
                    readers.append(reader_id)
                elif action == "remove":
                    readers.remove(reader_id)
                return self.async_create_entry(
                    title="",
                    data={"readers": readers},
                )

        schema = vol.Schema(
            {
                vol.Required("action", default="add"): vol.In(["add", "remove"]),
                vol.Required("reader_id"): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)