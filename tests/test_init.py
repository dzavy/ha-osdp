"""Tests for setup, events, polling, actions and migration."""

from __future__ import annotations

import struct

import osdp
import pytest
import serial

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.osdp.const import (
    CONF_BAUDRATE,
    CONF_PORT,
    CONF_READERS,
    DOMAIN,
    EVENT_OSDP,
    reader_identifier,
)



async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_devices(hass, mock_osdp, config_entry) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    cp = mock_osdp.instances[0]
    assert cp.started
    assert [p.address for p in cp.pd_infos] == [1, 2]

    devreg = dr.async_get(hass)
    front = devreg.async_get_device({reader_identifier(config_entry.entry_id, 1)})
    assert front is not None and front.name == "Front door"


async def test_port_missing_retries(hass, mock_osdp, config_entry) -> None:
    from unittest.mock import patch

    with patch(
        "custom_components.osdp.hub.serial.Serial",
        side_effect=serial.SerialException("no such device"),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_card_read_routed_by_pd_index(hass, mock_osdp, config_entry) -> None:
    """A card on the PD at index 1 (address 2) is attributed to address 2,
    even though reader_no is 0."""
    await _setup(hass, config_entry)
    events = async_capture_events(hass, EVENT_OSDP)
    cp = mock_osdp.instances[0]

    cp.handler(
        1,
        {
            "event": osdp.Event.CardRead,
            "reader_no": 0,
            "format": 0,
            "data": struct.pack(">L", 123456),
        },
    )
    await hass.async_block_till_done()

    back = dr.async_get(hass).async_get_device(
        {reader_identifier(config_entry.entry_id, 2)}
    )
    assert len(events) == 1
    assert events[0].data["device_id"] == back.id
    assert events[0].data["tag_id"] == "123456"
    assert events[0].context.user_id is None

    state = hass.states.get("event.back_door_card")
    assert state.attributes["event_type"] == "card_read"
    assert state.attributes["tag_id"] == "123456"



async def test_keypress(hass, mock_osdp, config_entry) -> None:
    await _setup(hass, config_entry)
    events = async_capture_events(hass, EVENT_OSDP)
    mock_osdp.instances[0].handler(
        0, {"event": osdp.Event.KeyPress, "reader_no": 0, "data": b"12\x7f\x0d"}
    )
    await hass.async_block_till_done()
    assert events[0].data["type"] == "keypress"
    assert events[0].data["keys"] == "12*#"


async def test_status_polling_and_identity(hass, mock_osdp, config_entry) -> None:
    await _setup(hass, config_entry)
    cp = mock_osdp.instances[0]
    assert hass.states.get("binary_sensor.front_door_online").state == "off"
    assert hass.states.get("binary_sensor.front_door_bus_serial_connection").state == "on"

    cp.status_mask = 0b01  # address 1 online
    cp.sc_mask = 0b01
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.front_door_online").state == "on"
    assert hass.states.get("binary_sensor.front_door_secure_channel").state == "on"
    assert hass.states.get("binary_sensor.back_door_online").state == "off"
    assert hass.states.get("sensor.front_door_bus_readers_online").state == "1"

    device = dr.async_get(hass).async_get_device(
        {reader_identifier(config_entry.entry_id, 1)}
    )
    assert device.manufacturer == "Test Vendor"
    assert device.serial_number == "01020304"
    assert device.sw_version == "01.02.03"


async def test_actions(hass, mock_osdp, config_entry) -> None:
    await _setup(hass, config_entry)
    cp = mock_osdp.instances[0]
    device = dr.async_get(hass).async_get_device(
        {reader_identifier(config_entry.entry_id, 1)}
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "beep", {"device_id": device.id}, blocking=True
        )

    cp.status_mask = 0b01
    await config_entry.runtime_data.coordinator.async_refresh()

    await hass.services.async_call(
        DOMAIN,
        "set_led",
        {"device_id": device.id, "color": "green", "duration": 3},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "beep", {"device_id": device.id}, blocking=True)
    await hass.services.async_call(
        DOMAIN,
        "set_output",
        {"device_id": device.id, "state": True, "duration": 5},
        blocking=True,
    )
    (a1, led), (a2, beep), (a3, out) = cp.commands
    assert a1 == a2 == a3 == 1
    assert led["command"] == osdp.Command.LED
    assert led["temporary"] and led["control_code"] == 2 and led["timer_count"] == 30
    assert led["on_color"] == osdp.CommandLEDColor.Green
    assert beep["command"] == osdp.Command.Buzzer and beep["on_count"] == 5
    assert out["control_code"] == 5 and out["timer_count"] == 50


async def test_bus_disconnect_and_recover(hass, mock_osdp, config_entry) -> None:
    await _setup(hass, config_entry)
    hub = config_entry.runtime_data.hub
    hub.channel._dev.read.side_effect = serial.SerialException("unplugged")
    assert hub.channel.read(10) == b""
    assert not hub.channel.is_open

    from unittest.mock import patch

    with patch(
        "custom_components.osdp.hub.serial.Serial",
        side_effect=serial.SerialException("still gone"),
    ):
        await config_entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_bus_serial_connection").state == "off"
    assert hass.states.get("binary_sensor.front_door_online").state == "unavailable"

    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hub.channel.is_open
    assert hass.states.get("binary_sensor.front_door_bus_serial_connection").state == "on"


async def test_unload_closes_port(hass, mock_osdp, config_entry) -> None:
    await _setup(hass, config_entry)
    hub = config_entry.runtime_data.hub
    dev = hub.channel._dev
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert not mock_osdp.instances[0].started
    dev.close.assert_called_once()
    assert not hub.channel.is_open


async def test_remove_reader_device(hass, mock_osdp, config_entry, hass_ws_client) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "config", {})
    await _setup(hass, config_entry)
    device = dr.async_get(hass).async_get_device(
        {reader_identifier(config_entry.entry_id, 2)}
    )
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "config/device_registry/remove_config_entry",
            "config_entry_id": config_entry.entry_id,
            "device_id": device.id,
        }
    )
    resp = await client.receive_json()
    assert resp["success"]
    await hass.async_block_till_done()
    assert [r["address"] for r in config_entry.options[CONF_READERS]] == [1]


async def test_migrate_v1(hass, mock_osdp) -> None:
    port = "/dev/ttyUSB0"
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id=f"{DOMAIN}_{port}",
        data={CONF_PORT: port, CONF_BAUDRATE: 9600, "controller_name": "Old"},
        options={CONF_READERS: [3]},
    )
    entry.add_to_hass(hass)

    devreg = dr.async_get(hass)
    old_reader = devreg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"reader_{port}_3")}
    )
    entreg = er.async_get(hass)
    entreg.async_get_or_create(
        "sensor", DOMAIN, f"osdp_model_{entry.entry_id}_3", config_entry=entry
    )
    online = entreg.async_get_or_create(
        "binary_sensor", DOMAIN, f"osdp_online_{entry.entry_id}_3", config_entry=entry
    )

    await _setup(hass, entry)

    assert entry.version == 2
    assert entry.options[CONF_READERS] == [{"address": 3, "name": "OSDP Reader 3"}]
    migrated = devreg.async_get_device({reader_identifier(entry.entry_id, 3)})
    assert migrated is not None and migrated.id == old_reader.id
    assert entreg.async_get_entity_id("sensor", DOMAIN, f"osdp_model_{entry.entry_id}_3") is None
    assert entreg.async_get(online.entity_id) is not None
