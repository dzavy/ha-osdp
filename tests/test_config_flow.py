"""Tests for the config, reconfigure and options flows."""

from __future__ import annotations

from unittest.mock import patch

import serial

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.osdp.const import (
    CONF_ADDRESS,
    CONF_BAUDRATE,
    CONF_CONTROLLER_NAME,
    CONF_NAME,
    CONF_PORT,
    CONF_READERS,
    CONF_RUN_AS_USER,
    CONF_SCBK,
    DOMAIN,
)

from .conftest import PORT


async def test_user_flow(hass: HomeAssistant, mock_osdp) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "custom_components.osdp.config_flow.serial.Serial",
        side_effect=serial.SerialException("busy"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PORT: "/dev/ttyBAD", CONF_BAUDRATE: 9600, CONF_CONTROLLER_NAME: "Bus"},
        )
    assert result["errors"] == {CONF_PORT: "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PORT: PORT, CONF_BAUDRATE: 9600, CONF_CONTROLLER_NAME: "Bus"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_PORT: PORT, CONF_BAUDRATE: 9600, CONF_CONTROLLER_NAME: "Bus"}
    assert result["options"] == {CONF_READERS: []}


async def test_user_flow_duplicate(hass, mock_osdp, config_entry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PORT: PORT, CONF_BAUDRATE: 9600, CONF_CONTROLLER_NAME: "Bus"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass, mock_osdp, config_entry) -> None:
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PORT: "/dev/ttyUSB7", CONF_BAUDRATE: 115200}
    )
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PORT] == "/dev/ttyUSB7"
    assert config_entry.data[CONF_BAUDRATE] == 115200
    assert config_entry.unique_id == f"{DOMAIN}_/dev/ttyUSB7"


async def _options_step(hass, entry, step: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def test_add_reader_applies_immediately(hass, mock_osdp, config_entry) -> None:
    """Regression: options used to be mutated in place so no reload happened."""
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(mock_osdp.instances) == 1

    result = await _options_step(hass, config_entry, "add_reader")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ADDRESS: 1}
    )
    assert result["errors"] == {CONF_ADDRESS: "duplicate"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ADDRESS: 5, CONF_SCBK: "zz"}
    )
    assert result["errors"] == {CONF_SCBK: "invalid_scbk"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_ADDRESS: 5, CONF_NAME: "Garage", CONF_SCBK: "00112233445566778899aabbccddeeff"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    readers = config_entry.options[CONF_READERS]
    assert readers[-1] == {
        CONF_ADDRESS: 5,
        CONF_NAME: "Garage",
        CONF_SCBK: "00112233445566778899AABBCCDDEEFF",
    }
    # The entry was reloaded with the new reader.
    assert len(mock_osdp.instances) == 2
    pd = mock_osdp.instances[-1].pd_infos[-1]
    assert pd.address == 5 and pd.scbk == bytes.fromhex("00112233445566778899aabbccddeeff")


async def test_add_reader_rejects_broadcast(hass, mock_osdp, config_entry) -> None:
    import voluptuous as vol
    import pytest

    result = await _options_step(hass, config_entry, "add_reader")
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ADDRESS: 127}
        )


async def test_edit_and_remove_reader(hass, mock_osdp, config_entry) -> None:
    result = await _options_step(hass, config_entry, "edit_reader")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"reader": "2"}
    )
    assert result["step_id"] == "edit_reader_details"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Rear door"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_READERS][1][CONF_NAME] == "Rear door"

    result = await _options_step(hass, config_entry, "remove_reader")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_READERS: ["1"]}
    )
    assert [r[CONF_ADDRESS] for r in config_entry.options[CONF_READERS]] == [2]


async def test_settings_run_as_user(hass, mock_osdp, config_entry, hass_admin_user) -> None:
    result = await _options_step(hass, config_entry, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_RUN_AS_USER: hass_admin_user.id}
    )
    assert config_entry.options[CONF_RUN_AS_USER] == hass_admin_user.id
    assert len(config_entry.options[CONF_READERS]) == 2

    result = await _options_step(hass, config_entry, "settings")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert CONF_RUN_AS_USER not in config_entry.options
