"""Sensor platform: human-readable awning status (retracted/extended/…)."""

from __future__ import annotations

from homeassistant.components.cover import CoverDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import helpers
from .const import AWNING_STATES, CONF_DEVICE_CLASSES, CONF_INVERT, DOMAIN
from .coordinator import ShadeInfo, WmsConfigEntry, WmsWebControlCoordinator

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

    entities = []
    for key, info in (coordinator.data or {}).items():
        device_class = helpers.resolved_device_class(
            info.channel_name, dc_overrides, _VALID_DEVICE_CLASSES
        )
        if device_class != CoverDeviceClass.AWNING.value:
            continue
        invert = helpers.resolve_invert(info.channel_name, device_class, invert_overrides)
        entities.append(WmsAwningStatus(coordinator, entry, key, info, invert))
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
        key: str,
        info: ShadeInfo,
        invert: bool,
    ) -> None:
        """Initialise the status sensor."""
        super().__init__(coordinator)
        self._key = key
        self._invert = invert
        self._attr_unique_id = f"{entry.entry_id}_{key}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="WAREMA WMS WebControl",
            manufacturer="WAREMA",
            model="WMS WebControl",
            configuration_url=coordinator.url,
        )

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
        if info is None:
            return None
        ha_position = helpers.ha_from_lib(info.position, self._invert)
        return helpers.awning_state(
            ha_position, info.is_moving, self.coordinator.targets.get(self._key)
        )
