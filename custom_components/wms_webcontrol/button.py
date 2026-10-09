"""Button platform for WAREMA WMS WebControl: scenes, presets and wink."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import ChannelInfo, legacy_scene_payload
from .const import CONF_PRESETS, DEFAULT_PRESETS, PRESET_NAME, PRESET_PAYLOAD
from .coordinator import WmsConfigEntry, WmsWebControlCoordinator
from .entity import hub_device_info
from .helpers import is_valid_payload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WmsConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up scene, preset and wink buttons."""
    coordinator = entry.runtime_data
    presets: list[dict[str, str]] = entry.options.get(CONF_PRESETS, DEFAULT_PRESETS)
    preset_names = {
        preset.get(PRESET_PAYLOAD, "").strip().lower(): preset.get(PRESET_NAME)
        for preset in presets
    }

    entities: list[ButtonEntity] = []
    scene_payloads: set[str] = set()
    for scene in coordinator.scenes:
        payload = legacy_scene_payload(scene.room_id, scene.channel_id)
        scene_payloads.add(payload)
        name = preset_names.get(payload) or scene.name
        entities.append(WmsSceneButton(coordinator, entry, scene, payload, name))

    # Manually configured presets that are not a discovered scene (0.3.x style).
    for preset in presets:
        payload = preset.get(PRESET_PAYLOAD, "").strip().lower()
        if payload in scene_payloads or not preset.get(PRESET_NAME):
            continue
        if is_valid_payload(payload):
            entities.append(WmsPresetButton(coordinator, entry, preset[PRESET_NAME], payload))

    single_product = len(coordinator.products) == 1
    for channel in coordinator.products:
        entities.append(WmsWinkButton(coordinator, entry, channel, single_product))

    async_add_entities(entities)


class _WmsButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: WmsWebControlCoordinator, entry: WmsConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_device_info = hub_device_info(entry, coordinator.url)

    @property
    def available(self) -> bool:
        """Buttons are available while the box is reachable."""
        return self._coordinator.last_update_success


class WmsSceneButton(_WmsButton):
    """Recalls a scene stored in the box (discovered automatically)."""

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        scene: ChannelInfo,
        payload: str,
        name: str,
    ) -> None:
        """Initialise the scene button."""
        super().__init__(coordinator, entry)
        self._scene = scene
        self._attr_name = name
        # Same unique id scheme as the 0.3.x preset buttons, so entity ids of
        # presets that matched a scene are kept.
        self._attr_unique_id = f"{entry.entry_id}_preset_{payload}"
        self._attr_extra_state_attributes = {
            "room": scene.room_name,
            "scene_name": scene.name,
            "scene_index": scene.scene_index,
            "channel": scene.channel_id,
        }

    async def async_press(self) -> None:
        """Recall the scene."""
        await self._coordinator.async_run_scene(
            self._scene.room_id, self._scene.channel_id, self._attr_name or self._scene.name
        )


class WmsPresetButton(_WmsButton):
    """Replays a manually configured payload (0.3.x presets)."""

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        name: str,
        payload: str,
    ) -> None:
        """Initialise the preset button."""
        super().__init__(coordinator, entry)
        self._payload = payload
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_preset_{payload}"

    async def async_press(self) -> None:
        """Send the configured payload."""
        await self._coordinator.async_send_payload(self._payload, self._attr_name or self._payload)


class WmsWinkButton(_WmsButton):
    """Lets an actor move briefly to identify it."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: WmsWebControlCoordinator,
        entry: WmsConfigEntry,
        channel: ChannelInfo,
        single_product: bool = False,
    ) -> None:
        """Initialise the wink button."""
        super().__init__(coordinator, entry)
        self._key = channel.key
        # With one shade the channel name adds nothing and doubles up when the
        # device is named after the shade ("Markise Markise winken").
        self._attr_name = "Winken" if single_product else f"{channel.name} winken"
        self._attr_unique_id = f"{entry.entry_id}_{channel.key}_wink"

    async def async_press(self) -> None:
        """Wink."""
        await self._coordinator.async_wink(self._key)
