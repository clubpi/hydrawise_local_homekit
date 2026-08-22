from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HydrawiseHomeKitSystemConfigEntry

TO_REDACT = {"pin"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HydrawiseHomeKitSystemConfigEntry
) -> dict[str, Any]:
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "bridge_running": entry.runtime_data.bridge.driver is not None,
    }
