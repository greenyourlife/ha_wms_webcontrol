"""The WAREMA WMS WebControl integration."""

from __future__ import annotations

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import WmsClient, WmsError
from .coordinator import WmsConfigEntry, WmsWebControlCoordinator, make_fetch

PLATFORMS: list[Platform] = [Platform.COVER, Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: WmsConfigEntry) -> bool:
    """Set up WAREMA WMS WebControl from a config entry."""
    url = entry.data[CONF_URL]
    client = WmsClient(make_fetch(hass, url))
    coordinator = WmsWebControlCoordinator(hass, entry, url, client)

    try:
        await coordinator.async_setup()
    except WmsError as err:
        raise ConfigEntryNotReady(f"Could not connect to WebControl at {url}: {err}") from err

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
