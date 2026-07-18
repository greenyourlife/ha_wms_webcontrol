"""Button platform for WAREMA WMS WebControl scene presets."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_PRESETS,
    DEFAULT_PRESETS,
    DOMAIN,
    PRESET_NAME,
    PRESET_PAYLOAD,
)
from .coordinator import WmsConfigEntry, WmsWebControlCoordinator
from .helpers import is_valid_payload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up preset button entities from a config entry."""
    coordinator = entry.runtime_data
    presets: list[dict[str, str]] = entry.options.get(CONF_PRESETS, DEFAULT_PRESETS)

    entities = [
        WmsPresetButton(coordinator, entry, preset)
        for preset in presets
        if preset.get(PRESET_NAME) and is_valid_payload(preset.get(PRESET_PAYLOAD, ""))
    ]
    async_add_entities(entities)


class WmsPresetButton(ButtonEntity):
    """A button that replays one captured WMS scene payload."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        preset: dict[str, str],
    ) -> None:
        """Initialise the preset button."""
        self._coordinator = coordinator
        self._payload = preset[PRESET_PAYLOAD].strip().lower()
        self._attr_name = preset[PRESET_NAME]
        self._attr_unique_id = f"{entry.entry_id}_preset_{self._payload}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="WAREMA WMS WebControl",
            manufacturer="WAREMA",
            model="WMS WebControl",
            configuration_url=coordinator.url,
        )

    @property
    def available(self) -> bool:
        """Presets are available while the box is reachable."""
        return self._coordinator.last_update_success

    async def async_press(self) -> None:
        """Replay the captured scene payload."""
        await self._coordinator.async_send_raw(self._payload)
