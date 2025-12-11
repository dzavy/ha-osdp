import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, CONF_CARD_ID

class NFCCardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is None:
            schema = vol.Schema({vol.Required(CONF_CARD_ID): str})
            return self.async_show_form(step_id="user", data_schema=schema)

        await self.async_set_unique_id(user_input[CONF_CARD_ID])
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"NFC Card {user_input[CONF_CARD_ID]}",
            data=user_input,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NFCCardOptionsFlow(config_entry)


class NFCCardOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema({vol.Required(CONF_CARD_ID, default=self._entry.data[CONF_CARD_ID]): str})
        return self.async_show_form(step_id="init", data_schema=schema)