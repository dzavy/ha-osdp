"""Constants for the OSDP integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "osdp"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]

# Config entry data
CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_CONTROLLER_NAME = "controller_name"

# Config entry options
CONF_READERS = "readers"
CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_SCBK = "scbk"
CONF_RUN_AS_USER = "run_as_user"

DEFAULT_BAUDRATE = 115200
DEFAULT_CONTROLLER_NAME = "OSDP Controller"
COMMON_BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400]

# OSDP addresses are 0..126; 0x7F (127) is the broadcast address.
MIN_ADDRESS = 0
MAX_ADDRESS = 126

# Secure Channel Base Key: 16 bytes, entered as 32 hex characters.
SCBK_HEX_LENGTH = 32

UPDATE_INTERVAL = timedelta(seconds=5)

# Event fired on the HA bus for every card read / key press (kept for
# backward compatibility with existing device triggers and automations).
EVENT_OSDP = "osdp_event"
EVENT_TYPE_TAG_SCANNED = "tag_scanned"
EVENT_TYPE_KEYPRESS = "keypress"


def signal_reader_event(entry_id: str, address: int) -> str:
    """Dispatcher signal used to deliver PD events to entities."""
    return f"{DOMAIN}_{entry_id}_{address}_event"


def controller_identifier(entry_id: str) -> tuple[str, str]:
    """Device registry identifier of the controller (bus) device."""
    return (DOMAIN, f"controller_{entry_id}")


def reader_identifier(entry_id: str, address: int) -> tuple[str, str]:
    """Device registry identifier of a reader (PD) device."""
    return (DOMAIN, f"reader_{entry_id}_{address}")
