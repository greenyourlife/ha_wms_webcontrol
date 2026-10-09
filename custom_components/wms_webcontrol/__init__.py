"""The WAREMA WMS WebControl integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change

from .client import WmsClient, WmsError
from .const import (
    CLOCK_SYNC_TIME,
    CONF_CLOCK_SYNC,
    DEFAULT_CLOCK_SYNC,
    DOMAIN,
    ISSUE_UNREACHABLE,
    LOGGER,
)
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

    clock_sync = entry.options.get(CONF_CLOCK_SYNC, DEFAULT_CLOCK_SYNC)

    async def _startup() -> None:
        # Slow radio reads run after setup so they never delay HA's start.
        await _check_clock(coordinator, sync=clock_sync)
        await coordinator.async_read_timers()

    entry.async_create_background_task(hass, _startup(), f"{DOMAIN} startup reads")

    @callback
    def _daily(_now: datetime) -> None:
        entry.async_create_background_task(
            hass, _check_clock(coordinator, sync=clock_sync), f"{DOMAIN} clock check"
        )

    hour, minute, second = CLOCK_SYNC_TIME
    entry.async_on_unload(
        async_track_time_change(hass, _daily, hour=hour, minute=minute, second=second)
    )
    return True


async def _check_clock(coordinator: WmsWebControlCoordinator, *, sync: bool) -> None:
    """Background clock check; failures are logged, never raised."""
    try:
        await coordinator.async_check_clock(sync=sync)
    except WmsError as err:
        LOGGER.warning("Could not check the box clock: %s", err)


async def async_unload_entry(hass: HomeAssistant, entry: WmsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: WmsConfigEntry) -> None:
    """Remove a leftover repair issue when the entry is deleted."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_UNREACHABLE}_{entry.entry_id}")


async def _async_update_listener(hass: HomeAssistant, entry: WmsConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
