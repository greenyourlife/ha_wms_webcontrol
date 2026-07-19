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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import helpers
from .const import CONF_DEVICE_CLASSES, CONF_INVERT, DOMAIN
from .coordinator import ShadeInfo, WmsConfigEntry, WmsWebControlCoordinator

_VALID_DEVICE_CLASSES = {cls.value for cls in CoverDeviceClass}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up cover entities from a config entry."""
    coordinator = entry.runtime_data
    dc_overrides: dict[str, str] = entry.options.get(CONF_DEVICE_CLASSES, {})
    invert_overrides: dict[str, bool] = entry.options.get(CONF_INVERT, {})

    entities = [
        WmsCover(coordinator, entry, key, info, dc_overrides, invert_overrides)
        for key, info in (coordinator.data or {}).items()
    ]
    async_add_entities(entities)


class WmsCover(CoordinatorEntity[WmsWebControlCoordinator], CoverEntity):
    """A single WAREMA WMS shade/awning channel."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        key: str,
        info: ShadeInfo,
        dc_overrides: dict[str, str],
        invert_overrides: dict[str, bool],
    ) -> None:
        """Initialise the cover entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = info.channel_name
        device_class = helpers.resolved_device_class(
            info.channel_name, dc_overrides, _VALID_DEVICE_CLASSES
        )
        self._attr_device_class = CoverDeviceClass(device_class)
        self._invert = helpers.resolve_invert(
            info.channel_name, device_class, invert_overrides
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="WAREMA WMS WebControl",
            manufacturer="WAREMA",
            model="WMS WebControl",
            configuration_url=coordinator.url,
        )

    @property
    def _info(self) -> ShadeInfo | None:
        """Current snapshot for this shade, if available."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._key)

    @property
    def _target(self) -> int | None:
        """Last commanded HA target position for this shade."""
        return self.coordinator.targets.get(self._key)

    @property
    def available(self) -> bool:
        """Return whether the shade is reachable."""
        return super().available and self._info is not None

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position (0 = closed, 100 = open)."""
        info = self._info
        if info is None:
            return None
        return helpers.ha_from_lib(info.position, self._invert)

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def is_opening(self) -> bool:
        """Return if the cover is currently opening."""
        info = self._info
        if info is None:
            return False
        opening, _ = helpers.derive_movement(
            info.is_moving, self._target, self.current_cover_position
        )
        return opening

    @property
    def is_closing(self) -> bool:
        """Return if the cover is currently closing."""
        info = self._info
        if info is None:
            return False
        _, closing = helpers.derive_movement(
            info.is_moving, self._target, self.current_cover_position
        )
        return closing

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (HA position 100)."""
        self.coordinator.set_target(self._key, 100)
        await self.coordinator.async_set_position(
            self._key, helpers.lib_from_ha(100, self._invert)
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (HA position 0)."""
        self.coordinator.set_target(self._key, 0)
        await self.coordinator.async_set_position(
            self._key, helpers.lib_from_ha(0, self._invert)
        )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        ha_position = int(kwargs[ATTR_POSITION])
        self.coordinator.set_target(self._key, ha_position)
        await self.coordinator.async_set_position(
            self._key, helpers.lib_from_ha(ha_position, self._invert)
        )
