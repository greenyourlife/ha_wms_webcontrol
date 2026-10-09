"""Cover platform for WAREMA WMS WebControl."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import helpers
from .client import ChannelInfo
from .const import CONF_DEVICE_CLASSES, CONF_INVERT
from .coordinator import ShadeInfo, WmsConfigEntry, WmsWebControlCoordinator
from .entity import hub_device_info

_VALID_DEVICE_CLASSES = {cls.value for cls in CoverDeviceClass}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up cover entities (one per actor, plus one per valance)."""
    coordinator = entry.runtime_data
    dc_overrides: dict[str, str] = entry.options.get(CONF_DEVICE_CLASSES, {})
    invert_overrides: dict[str, bool] = entry.options.get(CONF_INVERT, {})

    entities: list[CoverEntity] = []
    for channel in coordinator.products:
        device_class = helpers.device_class_for(
            channel.name, channel.product_type, dc_overrides, _VALID_DEVICE_CLASSES
        )
        invert = helpers.resolve_invert(channel.name, device_class, invert_overrides)
        entities.append(
            WmsCover(coordinator, entry, channel, device_class, invert)
        )
        for part in helpers.VOLANT_PARTS.get(channel.product_type or -1, ()):
            entities.append(WmsVolantCover(coordinator, entry, channel, part, invert))
    async_add_entities(entities)


class WmsCover(CoordinatorEntity[WmsWebControlCoordinator], CoverEntity):
    """A single WAREMA WMS actor (awning, shutter, blind ...)."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        channel: ChannelInfo,
        device_class: str,
        invert: bool,
    ) -> None:
        """Initialise the cover entity."""
        super().__init__(coordinator)
        self._key = channel.key
        # Same unique id as 0.3.x, so existing entity ids are kept.
        self._attr_unique_id = f"{entry.entry_id}_{channel.key}"
        self._attr_name = channel.name
        self._attr_device_class = CoverDeviceClass(device_class)
        self._invert = invert
        self._attr_device_info = hub_device_info(entry, coordinator.url)
        self._attr_extra_state_attributes = {
            "room": channel.room_name,
            "product_type": channel.product_type,
        }

    @property
    def _info(self) -> ShadeInfo | None:
        data = self.coordinator.data
        return None if data is None else data.get(self._key)

    @property
    def _target(self) -> int | None:
        return self.coordinator.targets.get(self._key)

    @property
    def available(self) -> bool:
        """Return whether the actor is reachable."""
        return super().available and self._info is not None

    def _lib_position(self, info: ShadeInfo) -> float | None:
        return info.position

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position (0 = closed, 100 = open)."""
        info = self._info
        if info is None:
            return None
        position = self._lib_position(info)
        if position is None:
            return None
        return helpers.ha_from_lib(position, self._invert)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def is_opening(self) -> bool:
        """Return if the cover is currently opening."""
        info = self._info
        if info is None:
            return False
        return helpers.derive_movement(
            info.is_moving, self._target, self.current_cover_position
        )[0]

    @property
    def is_closing(self) -> bool:
        """Return if the cover is currently closing."""
        info = self._info
        if info is None:
            return False
        return helpers.derive_movement(
            info.is_moving, self._target, self.current_cover_position
        )[1]

    async def _move_to(self, ha_position: int) -> None:
        self.coordinator.set_target(self._key, ha_position)
        await self.coordinator.async_move(
            self._key, helpers.lib_from_ha(ha_position, self._invert)
        )

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (HA position 100)."""
        await self._move_to(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (HA position 0)."""
        await self._move_to(0)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        await self._move_to(int(kwargs[ATTR_POSITION]))

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self.coordinator.async_stop(self._key)


class WmsVolantCover(WmsCover):
    """The valance (Volant) of an awning, moved independently."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        channel: ChannelInfo,
        part: str,
        invert: bool,
    ) -> None:
        """Initialise the valance entity."""
        super().__init__(coordinator, entry, channel, CoverDeviceClass.SHADE.value, invert)
        self._part = part
        self._attr_unique_id = f"{entry.entry_id}_{channel.key}_{part}"
        suffix = "Volant" if part == "volant1" and channel.product_type in (4, 6) else (
            "Volant 1" if part == "volant1" else "Volant 2"
        )
        self._attr_name = f"{channel.name} {suffix}"

    def _lib_position(self, info: ShadeInfo) -> float | None:
        return info.volant1 if self._part == "volant1" else info.volant2

    @property
    def is_opening(self) -> bool:
        """Direction is not tracked for valances."""
        return False

    @property
    def is_closing(self) -> bool:
        """Direction is not tracked for valances."""
        return False

    async def _move_to(self, ha_position: int) -> None:
        lib = helpers.lib_from_ha(ha_position, self._invert)
        if self._part == "volant1":
            await self.coordinator.async_move(self._key, None, volant1=lib)
        else:
            await self.coordinator.async_move(self._key, None, volant2=lib)
