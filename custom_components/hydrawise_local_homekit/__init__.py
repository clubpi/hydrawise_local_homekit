from __future__ import annotations

from dataclasses import dataclass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .bridge import HydrawiseHomeKitSystemBridge


@dataclass
class RuntimeData:
    bridge: HydrawiseHomeKitSystemBridge


type HydrawiseHomeKitSystemConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: HydrawiseHomeKitSystemConfigEntry
) -> bool:
    bridge = HydrawiseHomeKitSystemBridge(hass, entry)
    await bridge.async_start()
    entry.runtime_data = RuntimeData(bridge=bridge)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(
    hass: HomeAssistant, entry: HydrawiseHomeKitSystemConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(
    hass: HomeAssistant, entry: HydrawiseHomeKitSystemConfigEntry
) -> bool:
    await entry.runtime_data.bridge.async_stop()
    return True
