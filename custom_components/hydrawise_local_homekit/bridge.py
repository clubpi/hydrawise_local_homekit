from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
import logging
from pathlib import Path

from pyhap.accessory import Accessory, Bridge
from pyhap.accessory_driver import AccessoryDriver
from pyhap.const import CATEGORY_SPRINKLER

from homeassistant import components
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_PIN, CONF_PORT, CONF_RELAYS, CONF_SOURCE_ENTRY

_LOGGER = logging.getLogger(__name__)


class IrrigationSystemAccessory(Accessory):
    """Single HomeKit accessory containing one IrrigationSystem and all linked Valve services."""

    category = CATEGORY_SPRINKLER

    def __init__(self, driver, hass: HomeAssistant, coordinator, entry: ConfigEntry):
        super().__init__(driver, "Hydrawise Bewässerungssystem")
        self.hass = hass
        self.coordinator = coordinator
        self.entry = entry

        self.set_info_service(
            manufacturer="clubpi",
            model="Hydrawise HomeKit System",
            serial_number=f"{coordinator.api.host}-irrigation",
        )

        # Apple HomeKit ADK explicitly models a sprinkler controller as one
        # IrrigationSystem with one or more linked Valve services.
        system = self.add_preload_service(
            "IrrigationSystem",
            chars=["RemainingDuration", "StatusFault"],
            unique_id="hydrawise-system",
        )
        self.char_system_active = system.configure_char(
            "Active", value=0, setter_callback=self._set_system_active
        )
        self.char_system_program = system.configure_char("ProgramMode", value=0)
        self.char_system_in_use = system.configure_char("InUse", value=0)
        self.char_system_remaining = system.configure_char(
            "RemainingDuration",
            value=0,
            properties={"maxValue": 86400},
        )
        self.char_system_fault = system.configure_char("StatusFault", value=0)
        self.set_primary_service(system)
        self.system_service = system
        self.zone_services = {}
        self.zone_chars = {}

        selected_relays = self.entry.options.get(
            CONF_RELAYS,
            self.entry.data.get(CONF_RELAYS, [str(relay) for relay in coordinator.data]),
        )
        selected_relays = {int(relay) for relay in selected_relays}
        for index, relay in enumerate(
            sorted(relay for relay in coordinator.data if relay in selected_relays),
            start=1,
        ):
            zone = coordinator.data[relay]
            valve = self.add_preload_service(
                "Valve",
                chars=[
                    "SetDuration",
                    "RemainingDuration",
                    "ServiceLabelIndex",
                    "ConfiguredName",
                    "StatusFault",
                ],
                unique_id=f"hydrawise-zone-{relay}",
            )
            valve.configure_char("ConfiguredName", value=zone.name)
            valve.configure_char("ValveType", value=1)  # Irrigation
            valve.configure_char("ServiceLabelIndex", value=index)
            valve.configure_char("StatusFault", value=0)

            active = valve.configure_char(
                "Active",
                value=0,
                setter_callback=partial(self._set_zone_active, relay),
            )
            in_use = valve.configure_char("InUse", value=0)

            duration = int(coordinator.duration_seconds.get(relay, 300))
            set_duration = valve.configure_char(
                "SetDuration",
                value=duration,
                setter_callback=partial(self._set_zone_duration, relay),
                properties={"minValue": 60, "maxValue": 10800, "minStep": 60},
            )
            remaining = valve.configure_char(
                "RemainingDuration",
                value=0,
                getter_callback=partial(self._get_zone_remaining, relay),
                properties={"maxValue": 10800},
            )

            # HAP-python's Service supports linked services through linked_services.
            # Keeping these valve services inside the same accessory is the
            # HomeKit ADK's "collocated valves" model.
            if not hasattr(system, "linked_services"):
                system.linked_services = []
            system.linked_services.append(valve)

            self.zone_services[relay] = valve
            self.zone_chars[relay] = {
                "active": active,
                "in_use": in_use,
                "duration": set_duration,
                "remaining": remaining,
            }

        self._remove_listener = coordinator.async_add_listener(self._sync_from_coordinator)
        self._sync_from_coordinator()

    def _set_automatic(self, value: int | bool) -> None:
        enabled = bool(value)
        self.char_automatic.set_value(enabled)
        if not hasattr(self.coordinator, "async_set_automatic"):
            _LOGGER.warning("Hydrawise Local Pro ohne Automatik-Schalter geladen")
            return
        self.hass.loop.call_soon_threadsafe(
            lambda: self.hass.async_create_task(
                self.coordinator.async_set_automatic(enabled)
            )
        )

    def _zone_state(self, relay: int) -> tuple[int, int]:
        zone = self.coordinator.data.get(relay)
        if zone is None:
            return 0, 0
        if zone.is_running:
            return 1, 1
        if relay in getattr(self.coordinator, "pending_relays", []):
            # Selected / queued, but not physically watering yet.
            return 1, 0
        return 0, 0

    @callback
    def _sync_from_coordinator(self) -> None:
        any_requested = False
        any_in_use = False
        total_remaining = 0

        pending = list(getattr(self.coordinator, "pending_relays", []))

        for relay, chars in self.zone_chars.items():
            active, in_use = self._zone_state(relay)
            chars["active"].set_value(active)
            chars["in_use"].set_value(in_use)

            duration = int(self.coordinator.duration_seconds.get(relay, 300))
            chars["duration"].set_value(duration)

            remaining = self._get_zone_remaining(relay)
            chars["remaining"].set_value(remaining)

            any_requested = any_requested or bool(active)
            any_in_use = any_in_use or bool(in_use)

            zone = self.coordinator.data.get(relay)
            if zone and zone.is_running:
                total_remaining += remaining

        # Include queued zones in total remaining duration, in queue order.
        for relay in pending:
            zone = self.coordinator.data.get(relay)
            if zone and not zone.is_running:
                total_remaining += int(self.coordinator.duration_seconds.get(relay, 300))

        self.char_system_active.set_value(1 if any_requested else 0)
        self.char_system_in_use.set_value(1 if any_in_use else 0)
        self.char_system_program.set_value(1 if any_requested else 0)
        self.char_system_remaining.set_value(max(0, total_remaining))

    def _set_system_active(self, value: int | bool) -> None:
        # System OFF = stop everything and clear queue.
        # System ON alone does not start an arbitrary zone.
        if bool(value):
            self.char_system_active.set_value(1)
            return

        async def _stop_all():
            try:
                pending = list(getattr(self.coordinator, "pending_relays", []))
                if hasattr(self.coordinator, "pending_relays"):
                    self.coordinator.pending_relays.clear()

                for relay, zone in list(self.coordinator.data.items()):
                    if zone.is_running:
                        await self.coordinator.async_stop(relay)

                # If coordinator keeps queued commands elsewhere, try known queue attr.
                if hasattr(self.coordinator, "queue"):
                    try:
                        self.coordinator.queue.clear()
                    except Exception:
                        pass

                self._sync_from_coordinator()
            except Exception:
                _LOGGER.exception("Fehler beim Stoppen des Bewässerungssystems")

        self.hass.loop.call_soon_threadsafe(
            lambda: self.hass.async_create_task(_stop_all())
        )

    def _set_zone_active(self, relay: int, value: int | bool) -> None:
        requested = bool(value)
        chars = self.zone_chars[relay]

        # Immediate HomeKit state:
        # queued = Active yes, InUse no.
        if requested:
            chars["active"].set_value(1)
            zone = self.coordinator.data.get(relay)
            chars["in_use"].set_value(1 if zone and zone.is_running else 0)
        else:
            chars["active"].set_value(0)

        async def _apply():
            try:
                if requested:
                    await self.coordinator.async_start(relay)
                else:
                    # If merely queued, cancel request rather than stopping current zone.
                    pending = getattr(self.coordinator, "pending_relays", None)
                    if pending is not None and relay in pending:
                        try:
                            pending.remove(relay)
                        except (ValueError, KeyError):
                            pass
                        if hasattr(self.coordinator, "async_update_listeners"):
                            self.coordinator.async_update_listeners()
                    else:
                        await self.coordinator.async_stop(relay)
            except Exception:
                _LOGGER.exception(
                    "Fehler beim %s von Hydrawise-Zone %s",
                    "Anfordern" if requested else "Abwählen",
                    relay,
                )
            finally:
                self._sync_from_coordinator()

        self.hass.loop.call_soon_threadsafe(
            lambda: self.hass.async_create_task(_apply())
        )

    def _set_zone_duration(self, relay: int, value: int) -> None:
        seconds = max(60, min(10800, int(value)))
        self.coordinator.duration_seconds[relay] = seconds
        self.zone_chars[relay]["duration"].set_value(seconds)

        if hasattr(self.coordinator, "async_update_listeners"):
            self.hass.loop.call_soon_threadsafe(
                self.coordinator.async_update_listeners
            )

    def _get_zone_remaining(self, relay: int) -> int:
        zone = self.coordinator.data.get(relay)
        if zone is None:
            return 0

        if zone.is_running:
            if zone.remaining_seconds is not None:
                return max(0, int(zone.remaining_seconds))
            end = getattr(self.coordinator, "command_ends", {}).get(relay)
            if end is not None:
                return max(
                    0,
                    int((end - datetime.now(timezone.utc)).total_seconds()),
                )

        if relay in getattr(self.coordinator, "pending_relays", []):
            return int(self.coordinator.duration_seconds.get(relay, 300))

        return 0

    async def stop(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await super().stop()


class AutomationAccessory(Accessory):
    """Separate HomeKit tile for the irrigation automation lock."""

    def __init__(self, driver, hass: HomeAssistant, coordinator):
        super().__init__(driver, "Bewässerungsautomatik")
        self.hass = hass
        self.coordinator = coordinator
        self.set_info_service(
            manufacturer="clubpi",
            model="Hydrawise Local HomeKit",
            serial_number=f"{coordinator.api.host}-automation",
        )
        switch = self.add_preload_service("Switch", unique_id="hydrawise-automatic")
        self.char_automatic = switch.configure_char(
            "On",
            value=bool(getattr(coordinator, "automatic_enabled", True)),
            setter_callback=self._set_automatic,
        )
        self._remove_listener = coordinator.async_add_listener(self._sync)
        self._sync()

    def _set_automatic(self, value: int | bool) -> None:
        enabled = bool(value)
        self.char_automatic.set_value(enabled)
        if hasattr(self.coordinator, "async_set_automatic"):
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(
                    self.coordinator.async_set_automatic(enabled)
                )
            )

    @callback
    def _sync(self) -> None:
        self.char_automatic.set_value(
            bool(getattr(self.coordinator, "automatic_enabled", True))
        )

    async def stop(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await super().stop()


class HydrawiseHomeKitSystemBridge:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.driver: AccessoryDriver | None = None

    async def async_start(self) -> None:
        source_entry = self.hass.config_entries.async_get_entry(
            self.entry.data[CONF_SOURCE_ENTRY]
        )
        if source_entry is None or not getattr(source_entry, "runtime_data", None):
            raise RuntimeError("Hydrawise Local Pro ist nicht geladen")

        coordinator = source_entry.runtime_data.coordinator
        aiozc = await zeroconf.async_get_async_instance(self.hass)

        persist_file = str(
            Path(self.hass.config.path(".storage"))
            / f"hydrawise_local_homekit_{self.entry.entry_id}_bridge_v2.state"
        )
        pin = self.entry.data[CONF_PIN].encode()

        # HAP-python loads resource JSON during construction, so initialize it in
        # Home Assistant's executor instead of blocking the event loop.
        self.driver = await self.hass.async_add_executor_job(
            partial(
                AccessoryDriver,
                port=int(self.entry.data[CONF_PORT]),
                persist_file=persist_file,
                pincode=bytearray(pin),
                loop=self.hass.loop,
                async_zeroconf_instance=aiozc,
            )
        )

        irrigation = IrrigationSystemAccessory(
            self.driver,
            self.hass,
            coordinator,
            self.entry,
        )
        automation = AutomationAccessory(self.driver, self.hass, coordinator)
        homekit_bridge = Bridge(self.driver, "Hydrawise Local HomeKit")
        homekit_bridge.add_accessory(irrigation)
        homekit_bridge.add_accessory(automation)
        await self.hass.async_add_executor_job(
            self.driver.add_accessory, homekit_bridge
        )
        await self.driver.async_start()

        _LOGGER.warning(
            "Hydrawise HomeKit System gestartet auf Port %s; PIN %s",
            self.entry.data[CONF_PORT],
            self.entry.data[CONF_PIN],
        )

    async def async_stop(self) -> None:
        if self.driver is not None:
            await self.driver.async_stop()
            self.driver = None
