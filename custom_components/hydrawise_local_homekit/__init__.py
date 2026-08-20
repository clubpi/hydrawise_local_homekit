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
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HydrawiseHomeKitSystemConfigEntry
) -> bool:
    await entry.runtime_data.bridge.async_stop()
    return True

