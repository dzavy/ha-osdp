"""Fixtures for OSDP tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.osdp.const import (
    CONF_ADDRESS,
    CONF_BAUDRATE,
    CONF_CONTROLLER_NAME,
    CONF_NAME,
    CONF_PORT,
    CONF_READERS,
    DOMAIN,
)

PORT = "/dev/serial/by-id/usb-test-if00"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


class FakeControlPanel:
    """Stand-in for osdp.ControlPanel that records what it was given."""

    instances: list[FakeControlPanel] = []

    def __init__(self, pd_infos, log_level, handler):
        self.pd_infos = pd_infos
        self.handler = handler
        self.started = False
        self.status_mask = 0
        self.sc_mask = 0
        self.commands: list[tuple[int, dict]] = []
        self.event_queue = [MagicMock() for _ in pd_infos]
        FakeControlPanel.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def status(self):
        return self.status_mask

    def sc_status(self):
        return self.sc_mask

    def get_pd_id(self, address):
        pd_id = MagicMock()
        pd_id.version = 1
        pd_id.model = 2
        pd_id.vendor_code = 0x2B1A00
        pd_id.serial_number = 0x04030201
        pd_id.firmware_version = 0x010203
        return pd_id

    def submit_command(self, address, cmd):
        self.commands.append((address, cmd))
        return True


@pytest.fixture
def mock_osdp() -> Generator[type[FakeControlPanel]]:
    """Patch libosdp and pyserial."""
    FakeControlPanel.instances = []
    with (
        patch("custom_components.osdp.hub.osdp.ControlPanel", FakeControlPanel),
        patch("custom_components.osdp.hub.serial.Serial") as mock_serial,
        patch("custom_components.osdp.config_flow.serial.Serial"),
        patch("custom_components.osdp.config_flow._list_ports", return_value=[]),
        patch("custom_components.osdp.hub._vendor_name", return_value="Test Vendor"),
    ):
        mock_serial.return_value.read.return_value = b""
        yield FakeControlPanel


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A v2 config entry with readers at addresses 1 and 2."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=f"{DOMAIN}_{PORT}",
        title="Front door bus",
        data={CONF_PORT: PORT, CONF_BAUDRATE: 9600, CONF_CONTROLLER_NAME: "Front door bus"},
        options={
            CONF_READERS: [
                {CONF_ADDRESS: 1, CONF_NAME: "Front door"},
                {CONF_ADDRESS: 2, CONF_NAME: "Back door"},
            ]
        },
    )
    entry.add_to_hass(hass)
    return entry
