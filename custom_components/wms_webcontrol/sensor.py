"""Sensor platform: awning status, next timer switching time, box clock."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.cover import CoverDeviceClass
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import helpers
from .client import ChannelInfo, TimerEntry
from .const import AWNING_STATES, CONF_DEVICE_CLASSES, CONF_INVERT
from .coordinator import ShadeInfo, WmsConfigEntry, WmsWebControlCoordinator
from .entity import hub_device_info

_VALID_DEVICE_CLASSES = {cls.value for cls in CoverDeviceClass}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a status sensor for every channel that resolves to an awning."""
    coordinator = entry.runtime_data
    dc_overrides: dict[str, str] = entry.options.get(CONF_DEVICE_CLASSES, {})
    invert_overrides: dict[str, bool] = entry.options.get(CONF_INVERT, {})

    entities: list[SensorEntity] = [WmsClockOffset(coordinator, entry)]
    single_product = len(coordinator.products) == 1
    for channel in coordinator.products:
        device_class = helpers.device_class_for(
            channel.name, channel.product_type, dc_overrides, _VALID_DEVICE_CLASSES
        )
        invert = helpers.resolve_invert(channel.name, device_class, invert_overrides)
        entities.append(
            WmsNextSwitch(coordinator, entry, channel, invert, single_product)
        )
        if device_class == CoverDeviceClass.AWNING.value:
            entities.append(WmsAwningStatus(coordinator, entry, channel, invert))
    async_add_entities(entities)


class WmsAwningStatus(CoordinatorEntity[WmsWebControlCoordinator], SensorEntity):
    """Reports an awning's state in plain words (eingefahren/ausgefahren/…)."""

    _attr_has_entity_name = True
    _attr_translation_key = "awning_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = AWNING_STATES

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        channel: ChannelInfo,
        invert: bool,
    ) -> None:
        """Initialise the status sensor."""
        super().__init__(coordinator)
        self._key = channel.key
        self._invert = invert
        self._attr_unique_id = f"{entry.entry_id}_{channel.key}_status"
        self._attr_device_info = hub_device_info(entry, coordinator.url)

    @property
    def _info(self) -> ShadeInfo | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._key)

    @property
    def available(self) -> bool:
        """Return whether the shade is reachable."""
        return super().available and self._info is not None

    @property
    def native_value(self) -> str | None:
        """Return the current status option key."""
        info = self._info
        if info is None or info.position is None:
            return None
        ha_position = helpers.ha_from_lib(info.position, self._invert)
        return helpers.awning_state(
            ha_position, info.is_moving, self.coordinator.targets.get(self._key)
        )


_DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _entry_text(entry: TimerEntry, invert: bool) -> str:
    text = f"{_DAYS[entry.day]} {entry.hour:02d}:{entry.minute:02d}"
    if entry.position is not None:
        text += f" → {helpers.ha_from_lib(entry.position / 2, invert)} %"
    return text


class WmsNextSwitch(CoordinatorEntity[WmsWebControlCoordinator], SensorEntity):
    """Next switching time of the timer stored in the actor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        channel: ChannelInfo,
        invert: bool,
        single_product: bool,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._key = channel.key
        self._invert = invert
        self._attr_translation_key = "next_switch" if single_product else None
        if not single_product:
            self._attr_name = f"{channel.name} nächste Schaltzeit"
        self._attr_unique_id = f"{entry.entry_id}_{channel.key}_next_switch"
        self._attr_device_info = hub_device_info(entry, coordinator.url)

    def _next(self) -> tuple[datetime, TimerEntry] | None:
        plan = self.coordinator.timers.get(self._key)
        if plan is None:
            return None
        local_now = dt_util.now().replace(tzinfo=None)
        return plan.next_switch_time(local_now)

    @property
    def available(self) -> bool:
        """Available once the timer has been read."""
        return self._key in self.coordinator.timers

    @property
    def native_value(self) -> datetime | None:
        """Return the next switching time (None if the timer is off or empty)."""
        found = self._next()
        if found is None:
            return None
        return found[0].replace(tzinfo=dt_util.get_default_time_zone())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Timer state, target of the next switch and the weekly plan."""
        plan = self.coordinator.timers.get(self._key)
        if plan is None:
            return {}
        found = self._next()
        attrs: dict[str, Any] = {
            "timer_enabled": plan.enabled,
            "plan": [_entry_text(entry, self._invert) for entry in plan.entries],
            "read_at": self.coordinator.timers_read_at,
        }
        if found is not None and found[1].position is not None:
            attrs["next_position"] = helpers.ha_from_lib(
                found[1].position / 2, self._invert
            )
        if self._key in self.coordinator.timer_errors:
            attrs["last_error"] = self.coordinator.timer_errors[self._key]
        return attrs


class WmsClockOffset(CoordinatorEntity[WmsWebControlCoordinator], SensorEntity):
    """How far the box clock is off from HA's local time."""

    _attr_has_entity_name = True
    _attr_translation_key = "clock_offset"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: WmsWebControlCoordinator, entry: WmsConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_clock_offset"
        self._attr_device_info = hub_device_info(entry, coordinator.url)

    @property
    def available(self) -> bool:
        """Available once the clock has been read."""
        return self.coordinator.clock_offset is not None

    @property
    def native_value(self) -> float | None:
        """Return box time minus HA time in seconds."""
        return self.coordinator.clock_offset

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Box time and when it was checked/set."""
        clock = self.coordinator.clock
        if clock is None:
            return {}
        return {
            "box_time": clock.time.isoformat(),
            "system_time_master": clock.system_time_master,
            "checked_at": self.coordinator.clock_checked_at,
            "set_at": self.coordinator.clock_set_at,
        }
