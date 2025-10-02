import serial
import asyncio
import struct
import osdp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

class SerialChannel(osdp.Channel):
    def __init__(self, device: str, speed: int):
        super().__init__()
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
        if event["event"] == osdp.Event.CardRead:
          event_data = {
            "nfctag": struct.unpack('>L', event["data"])[0],
            "type": "card_detected"
          }
          hass.bus.fire("osdp_event", event_data)

        return 0


    channel = SerialChannel("/dev/ttyUSB0", 115200)

    pd_info = [
        osdp.PDInfo(0, channel, scbk=None),
    ]

    cp = osdp.ControlPanel(pd_info, osdp.LogLevel.Info, osdp_event_handler)
    cp.start()
    return True
