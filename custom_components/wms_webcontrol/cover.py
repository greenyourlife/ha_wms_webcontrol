"""Cover platform for WAREMA WMS WebControl."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import helpers
from .const import CONF_DEVICE_CLASSES, DOMAIN
from .coordinator import ShadeInfo, WmsConfigEntry, WmsWebControlCoordinator

_VALID_DEVICE_CLASSES = {cls.value for cls in CoverDeviceClass}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up cover entities from a config entry."""
    coordinator = entry.runtime_data
    overrides: dict[str, str] = entry.options.get(CONF_DEVICE_CLASSES, {})

    entities = [
        WmsCover(coordinator, entry, key, info, overrides)
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
        overrides: dict[str, str],
    ) -> None:
        """Initialise the cover entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = info.channel_name
        self._attr_device_class = self._resolve_device_class(info.channel_name, overrides)
        self._target_ha_position: int | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="WAREMA WMS WebControl",
            manufacturer="WAREMA",
            model="WMS WebControl",
            configuration_url=coordinator.url,
        )

    @staticmethod
    def _resolve_device_class(channel_name: str, overrides: dict[str, str]) -> CoverDeviceClass:
        """Pick a device class from overrides or fall back to a name heuristic."""
        override = overrides.get((channel_name or "").lower())
        if override in _VALID_DEVICE_CLASSES:
            return CoverDeviceClass(override)
        return CoverDeviceClass(helpers.guess_device_class(channel_name))

    @property
    def _info(self) -> ShadeInfo | None:
        """Current snapshot for this shade, if available."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.get(self._key)

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
        return helpers.invert_position(info.position)

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
            info.is_moving, self._target_ha_position, self.current_cover_position
        )
        return opening

    @property
    def is_closing(self) -> bool:
        """Return if the cover is currently closing."""
        info = self._info
        if info is None:
            return False
        _, closing = helpers.derive_movement(
            info.is_moving, self._target_ha_position, self.current_cover_position
        )
        return closing

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (library position 0)."""
        self._target_ha_position = 100
        await self.coordinator.async_set_position(self._key, 0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (library position 100)."""
        self._target_ha_position = 0
        await self.coordinator.async_set_position(self._key, 100)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        ha_position = int(kwargs[ATTR_POSITION])
        self._target_ha_position = ha_position
        await self.coordinator.async_set_position(
            self._key, helpers.to_lib_position(ha_position)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear the movement target once the shade has settled."""
        info = self._info
        if info is not None and not info.is_moving:
            self._target_ha_position = None
        super()._handle_coordinator_update()
