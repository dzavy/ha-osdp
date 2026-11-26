"""Config and options flows for the OSDP integration."""

from __future__ import annotations

import os
from typing import Any

import serial
import serial.tools.list_ports
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    COMMON_BAUDRATES,
    CONF_ADDRESS,
    CONF_BAUDRATE,
    CONF_CONTROLLER_NAME,
    CONF_NAME,
    CONF_PORT,
    CONF_READERS,
    CONF_RUN_AS_USER,
    CONF_SCBK,
    DEFAULT_BAUDRATE,
    DEFAULT_CONTROLLER_NAME,
    DOMAIN,
    MAX_ADDRESS,
    MIN_ADDRESS,
    SCBK_HEX_LENGTH,
)

BY_ID_DIR = "/dev/serial/by-id"
CONF_READER = "reader"


def _list_ports() -> list[SelectOptionDict]:
    """List serial ports, preferring stable /dev/serial/by-id paths (blocking)."""
    by_id: dict[str, str] = {}
    if os.path.isdir(BY_ID_DIR):
        for name in sorted(os.listdir(BY_ID_DIR)):
            path = os.path.join(BY_ID_DIR, name)
            by_id[os.path.realpath(path)] = path

    options: list[SelectOptionDict] = []
    for port in serial.tools.list_ports.comports():
        path = by_id.get(os.path.realpath(port.device), port.device)
        details = [port.device] if path != port.device else []
        if port.description and port.description != "n/a":
            details.append(port.description)
        label = f"{path} ({' - '.join(details)})" if details else path
        options.append(SelectOptionDict(value=path, label=label))
    return options


def _try_open(port: str, baudrate: int) -> None:
    """Open and close the port to check it is usable (blocking)."""
    serial.Serial(port, baudrate, timeout=0).close()


async def _validate_port(hass: HomeAssistant, port: str, baudrate: int) -> str | None:
    try:
        await hass.async_add_executor_job(_try_open, port, baudrate)
    except (serial.SerialException, OSError, ValueError):
        return "cannot_connect"
    return None


def _port_schema(ports: list[SelectOptionDict], defaults: dict[str, Any]) -> dict:
    port_key = (
        vol.Required(CONF_PORT, default=defaults[CONF_PORT])
        if defaults.get(CONF_PORT)
        else vol.Required(CONF_PORT)
    )
    return {
        port_key: SelectSelector(
            SelectSelectorConfig(
                options=ports, custom_value=True, mode=SelectSelectorMode.DROPDOWN
            )
        ),
        vol.Required(
            CONF_BAUDRATE, default=defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
        ): vol.In(COMMON_BAUDRATES),
    }


def _valid_scbk(value: str | None) -> bool:
    if not value:
        return True
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return len(value) == SCBK_HEX_LENGTH


class OSDPConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for an OSDP bus."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT].strip()
            await self.async_set_unique_id(f"{DOMAIN}_{port}")
            self._abort_if_unique_id_configured()
            if error := await _validate_port(self.hass, port, user_input[CONF_BAUDRATE]):
                errors[CONF_PORT] = error
            else:
                return self.async_create_entry(
                    title=user_input[CONF_CONTROLLER_NAME],
                    data={
                        CONF_PORT: port,
                        CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                        CONF_CONTROLLER_NAME: user_input[CONF_CONTROLLER_NAME],
                    },
                    options={CONF_READERS: []},
                )

        ports = await self.hass.async_add_executor_job(_list_ports)
        schema = vol.Schema(
            {
                **_port_schema(ports, user_input or {}),
                vol.Required(
                    CONF_CONTROLLER_NAME,
                    default=(user_input or {}).get(
                        CONF_CONTROLLER_NAME, DEFAULT_CONTROLLER_NAME
                    ),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "hint": "" if ports else "No serial ports were detected; type the device path."
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the serial port or baud rate of an existing bus."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT].strip()
            existing = await self.async_set_unique_id(f"{DOMAIN}_{port}")
            if existing is not None and existing.entry_id != entry.entry_id:
                return self.async_abort(reason="already_configured")
            if error := await _validate_port_unless_ours(
                self.hass, entry, port, user_input[CONF_BAUDRATE]
            ):
                errors[CONF_PORT] = error
            else:
                # The entry's update listener reloads it when the data changes.
                self.hass.config_entries.async_update_entry(
                    entry,
                    unique_id=f"{DOMAIN}_{port}",
                    data={
                        **entry.data,
                        CONF_PORT: port,
                        CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                    },
                )
                return self.async_abort(reason="reconfigure_successful")

        ports = await self.hass.async_add_executor_job(_list_ports)
        defaults = user_input or dict(entry.data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(_port_schema(ports, defaults)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OSDPOptionsFlowHandler:
        return OSDPOptionsFlowHandler()


async def _validate_port_unless_ours(
    hass: HomeAssistant, entry: ConfigEntry, port: str, baudrate: int
) -> str | None:
    """Our own entry holds its current port open, so don't test that one."""
    if port == entry.data.get(CONF_PORT):
        return None
    return await _validate_port(hass, port, baudrate)


class OSDPOptionsFlowHandler(OptionsFlow):
    """Manage readers on the bus and integration settings."""

    _edit_address: int | None = None

    @property
    def _readers(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.config_entry.options.get(CONF_READERS, [])]

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    def _reader_choices(self) -> list[SelectOptionDict]:
        return [
            SelectOptionDict(
                value=str(r[CONF_ADDRESS]),
                label=f"{r.get(CONF_NAME) or 'Reader'} (address {r[CONF_ADDRESS]})",
            )
            for r in sorted(self._readers, key=lambda r: r[CONF_ADDRESS])
        ]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        menu = ["add_reader"]
        if self._readers:
            menu += ["edit_reader", "remove_reader"]
        menu.append("settings")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_add_reader(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        readers = self._readers
        errors: dict[str, str] = {}
        if user_input is not None:
            address = int(user_input[CONF_ADDRESS])
            scbk = (user_input.get(CONF_SCBK) or "").strip().replace(" ", "")
            if any(r[CONF_ADDRESS] == address for r in readers):
                errors[CONF_ADDRESS] = "duplicate"
            elif not _valid_scbk(scbk):
                errors[CONF_SCBK] = "invalid_scbk"
            else:
                reader = {
                    CONF_ADDRESS: address,
                    CONF_NAME: user_input.get(CONF_NAME) or f"OSDP Reader {address}",
                }
                if scbk:
                    reader[CONF_SCBK] = scbk.upper()
                return self._save(readers=[*readers, reader])

        used = {r[CONF_ADDRESS] for r in readers}
        next_free = next(
            (a for a in range(MIN_ADDRESS + 1, MAX_ADDRESS + 1) if a not in used),
            MIN_ADDRESS,
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=next_free): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_ADDRESS,
                        max=MAX_ADDRESS,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_NAME): TextSelector(),
                vol.Optional(CONF_SCBK): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="add_reader",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_edit_reader(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_address = int(user_input[CONF_READER])
            return await self.async_step_edit_reader_details()
        return self.async_show_form(
            step_id="edit_reader",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_READER): SelectSelector(
                        SelectSelectorConfig(options=self._reader_choices())
                    )
                }
            ),
        )

    async def async_step_edit_reader_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        readers = self._readers
        current = next(r for r in readers if r[CONF_ADDRESS] == self._edit_address)
        errors: dict[str, str] = {}
        if user_input is not None:
            scbk = (user_input.get(CONF_SCBK) or "").strip().replace(" ", "")
            if not _valid_scbk(scbk):
                errors[CONF_SCBK] = "invalid_scbk"
            else:
                current[CONF_NAME] = (
                    user_input.get(CONF_NAME) or f"OSDP Reader {self._edit_address}"
                )
                if scbk:
                    current[CONF_SCBK] = scbk.upper()
                else:
                    current.pop(CONF_SCBK, None)
                return self._save(readers=readers)

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME): TextSelector(),
                vol.Optional(CONF_SCBK): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="edit_reader_details",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or current
            ),
            errors=errors,
            description_placeholders={"address": str(self._edit_address)},
        )

    async def async_step_remove_reader(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            remove = {int(a) for a in user_input[CONF_READERS]}
            return self._save(
                readers=[r for r in self._readers if r[CONF_ADDRESS] not in remove]
            )
        return self.async_show_form(
            step_id="remove_reader",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_READERS): SelectSelector(
                        SelectSelectorConfig(
                            options=self._reader_choices(), multiple=True
                        )
                    )
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {
                k: v for k, v in self.config_entry.options.items() if k != CONF_RUN_AS_USER
            }
            if user_input.get(CONF_RUN_AS_USER):
                options[CONF_RUN_AS_USER] = user_input[CONF_RUN_AS_USER]
            return self.async_create_entry(data=options)

        users = [
            SelectOptionDict(value=user.id, label=user.name or user.id)
            for user in await self.hass.auth.async_get_users()
            if not user.system_generated and user.is_active
        ]
        schema = vol.Schema(
            {
                vol.Optional(CONF_RUN_AS_USER): SelectSelector(
                    SelectSelectorConfig(options=users, mode=SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                schema, dict(self.config_entry.options)
            ),
        )
