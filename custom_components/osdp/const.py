DOMAIN = "osdp"

PLATFORMS = ["sensor", "binary_sensor"]

CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_CONTROLLER_NAME = "controller_name"

DEFAULT_BAUDRATE = 115200

# Dispatcher signal template
def signal_reader_update(entry_id: str, reader_id: int) -> str:
    return f"osdp_update_{entry_id}_{reader_id}"