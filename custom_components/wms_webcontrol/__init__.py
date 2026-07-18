"""The WAREMA WMS WebControl integration."""

from __future__ import annotations

import requests

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import WmsConfigEntry, WmsWebControlCoordinator

PLATFORMS: list[Platform] = [Platform.COVER, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: WmsConfigEntry) -> bool:
    """Set up WAREMA WMS WebControl from a config entry."""
    coordinator = WmsWebControlCoordinator(hass, entry, entry.data[CONF_URL])

    try:
        await coordinator.async_setup()
    except (requests.RequestException, OSError, ValueError) as err:
        raise ConfigEntryNotReady(
            f"Could not connect to WebControl at {entry.data[CONF_URL]}: {err}"
        ) from err

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WmsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: WmsConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
