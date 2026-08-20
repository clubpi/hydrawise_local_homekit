from __future__ import annotations

import re
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_PIN,
    CONF_PORT,
    CONF_RELAYS,
    CONF_SOURCE_ENTRY,
    DEFAULT_PORT,
    DOMAIN,
)

PIN_RE = re.compile(r"^\d{3}-\d{2}-\d{3}$")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        source_entries = self.hass.config_entries.async_entries("hydrawise_local_pro")
        if not source_entries:
            return self.async_abort(reason="no_local_pro")

        choices = {entry.entry_id: entry.title or entry.entry_id for entry in source_entries}
        source_entry = source_entries[0]
        relay_options = _relay_options(source_entry)

        if user_input is not None:
            if not PIN_RE.match(user_input[CONF_PIN]):
                errors["base"] = "invalid_pin"
            else:
                source_entry = self.hass.config_entries.async_get_entry(
                    user_input[CONF_SOURCE_ENTRY]
                )
                if source_entry is None:
                    errors["base"] = "source_missing"
                else:
                    await self.async_set_unique_id(source_entry.entry_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Hydrawise HomeKit System - {source_entry.title}",
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_ENTRY): vol.In(choices),
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                        vol.Coerce(int), vol.Range(min=1024, max=65535)
                    ),
                    vol.Required(CONF_PIN, default="731-26-420"): str,
                    vol.Required(
                        CONF_RELAYS,
                        default=[option["value"] for option in relay_options],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=relay_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler()


def _relay_options(source_entry) -> list[dict[str, str]]:
    if not getattr(source_entry, "runtime_data", None):
        return []
    return [
        {"value": str(relay), "label": zone.name}
        for relay, zone in sorted(source_entry.runtime_data.coordinator.data.items())
    ]


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        source_entry = self.hass.config_entries.async_get_entry(
            self.config_entry.data[CONF_SOURCE_ENTRY]
        )
        relay_options = _relay_options(source_entry)
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        selected = self.config_entry.options.get(
            CONF_RELAYS,
            self.config_entry.data.get(
                CONF_RELAYS,
                [option["value"] for option in relay_options],
            ),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RELAYS, default=selected): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=relay_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
