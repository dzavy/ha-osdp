import serial
import asyncio
import struct
from osdp import *
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

class SerialChannel(Channel):
    def __init__(self, device: str, speed: int):
        self.dev = serial.Serial(device, speed, timeout=0)

    def read(self, max_read: int):
        return self.dev.read(max_read)

    def write(self, data: bytes):
        return self.dev.write(data)

    def flush(self):
        self.dev.flush()

    def __del__(self):
        self.dev.close()


async def async_setup(hass: HomeAssistant, config: ConfigType):

    def osdp_event_handler(id: int, event: dict):
        #hass.bus.async_fire("osdp_event", x)
        if event["event"] == 1:
          event_data = {
            "nfctag": struct.unpack('>L', event["data"])[0],
            "type": "card_detected"
          }
          hass.bus.fire("osdp_event", event_data)

        return 0


    channel = SerialChannel("/dev/ttyUSB0", 115200)

    pd_info = [
        PDInfo(0, channel, scbk=None),
    ]

    cp = ControlPanel(pd_info, log_level=LogLevel.Info)
    cp.start()
    cp.set_event_handler(osdp_event_handler)
    return True
