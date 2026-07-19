"""Data update coordinator for the WAREMA WMS WebControl integration."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests
from warema_wms import Shade, WmsController

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import helpers
from .const import (
    CONF_EXCLUDE_CHANNELS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FAST_UPDATE_DURATION,
    FAST_UPDATE_INTERVAL,
    LOGGER,
    NUM_RETRIES,
    SHADE_NUM_RETRIES,
    TIME_BETWEEN_CMDS,
)

# Transport-level errors that should mark the box as (temporarily) unavailable
# instead of crashing the integration.
TRANSPORT_ERRORS = (requests.RequestException, OSError, ValueError)

type WmsConfigEntry = ConfigEntry["WmsWebControlCoordinator"]


@dataclass(slots=True)
class ShadeInfo:
    """Snapshot of a single shade's state (positions in library semantics)."""

    room_id: int
    channel_id: int
    room_name: str
    channel_name: str
    position: float  # 0 = open, 100 = closed (library semantics)
    is_moving: bool
    last_updated: datetime | None


def shade_key(room_id: int, channel_id: int) -> str:
    """Stable key identifying a shade within a config entry."""
    return f"{room_id}_{channel_id}"


class WmsWebControlCoordinator(DataUpdateCoordinator[dict[str, ShadeInfo]]):
    """Coordinates polling and command dispatch for one WebControl box."""

    config_entry: WmsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WmsConfigEntry, url: str) -> None:
        """Initialise the coordinator."""
        interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        self._base_interval = timedelta(seconds=interval)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._base_interval,
        )
        self.url = url
        self.controller: WmsController | None = None
        self.shades: list[Shade] = []
        self._fast_until: float | None = None
        # Last commanded HA target position per shade key, used to derive the
        # movement direction. Shared between the cover and the status sensor.
        self.targets: dict[str, int | None] = {}
        # Serialises all box I/O: the WebControl server shares a single command
        # counter and rejects overlapping/too-fast commands, so a poll and a
        # move must never run concurrently.
        self._lock = threading.Lock()

    async def async_setup(self) -> None:
        """Connect to the box and run auto-discovery (blocking I/O)."""
        await self.hass.async_add_executor_job(self._connect)

    def _connect(self) -> None:
        """Blocking connect + discovery. Runs in the executor."""
        self.controller = WmsController(self.url)
        shades = Shade.get_all_shades(
            self.controller,
            time_between_cmds=TIME_BETWEEN_CMDS,
            num_retries=SHADE_NUM_RETRIES,
        )
        excluded = self.config_entry.options.get(CONF_EXCLUDE_CHANNELS, [])
        self.shades = [
            shade
            for shade in shades
            if not helpers.is_excluded(shade.get_channel_name(), excluded)
        ]
        LOGGER.debug(
            "Discovered %d shade(s) on %s (%d after exclusions)",
            len(shades),
            self.url,
            len(self.shades),
        )

    async def _async_update_data(self) -> dict[str, ShadeInfo]:
        """Fetch the latest state of all shades."""
        try:
            data = await self.hass.async_add_executor_job(self._poll)
        except TRANSPORT_ERRORS as err:
            raise UpdateFailed(f"Error communicating with WebControl: {err}") from err

        # Once a shade has settled, forget its movement target.
        for key, info in data.items():
            if not info.is_moving:
                self.targets.pop(key, None)

        self._adjust_interval(any(info.is_moving for info in data.values()))
        return data

    def _poll(self) -> dict[str, ShadeInfo]:
        """Blocking poll of every discovered shade. Runs in the executor."""
        result: dict[str, ShadeInfo] = {}
        with self._lock:
            for shade in self.shades:
                position, is_moving, last_updated = shade.get_shade_state(force_update=True)
                key = shade_key(shade.room.id, shade.channel.id)
                result[key] = ShadeInfo(
                    room_id=shade.room.id,
                    channel_id=shade.channel.id,
                    room_name=shade.get_room_name(),
                    channel_name=shade.get_channel_name(),
                    position=position,
                    is_moving=is_moving,
                    last_updated=last_updated,
                )
        return result

    def _adjust_interval(self, any_moving: bool) -> None:
        """Speed up polling while shades are (or were just) moving."""
        now = self.hass.loop.time()
        if any_moving:
            self._fast_until = now + FAST_UPDATE_DURATION
        if self._fast_until is not None and now < self._fast_until:
            self.update_interval = timedelta(seconds=FAST_UPDATE_INTERVAL)
        else:
            self._fast_until = None
            self.update_interval = self._base_interval

    def trigger_fast_poll(self) -> None:
        """Enter the fast-poll window after issuing a command."""
        self._fast_until = self.hass.loop.time() + FAST_UPDATE_DURATION
        self.update_interval = timedelta(seconds=FAST_UPDATE_INTERVAL)

    def _shade_by_key(self, key: str) -> Shade:
        """Return the library Shade object for a coordinator key."""
        for shade in self.shades:
            if shade_key(shade.room.id, shade.channel.id) == key:
                return shade
        raise KeyError(key)

    def set_target(self, key: str, ha_position: int | None) -> None:
        """Record the last commanded HA target position for a shade."""
        self.targets[key] = ha_position

    async def async_set_position(self, key: str, lib_position: int) -> None:
        """Move a shade to a library position (0 = open, 100 = closed)."""
        shade = self._shade_by_key(key)
        await self.hass.async_add_executor_job(self._move, shade, lib_position)
        self.trigger_fast_poll()
        await self.async_request_refresh()

    def _move(self, shade: Shade, lib_position: int) -> None:
        """Move a shade via the library. Runs in the executor.

        Uses the library's ``set_shade_position`` (which correctly gates on the
        box's "check ready" response before sending the move). The coordinator
        lock keeps a concurrent poll from making the box busy, and the low
        per-shade retry count keeps the built-in verify loop short.
        """
        with self._lock:
            shade.set_shade_position(lib_position)

    async def async_send_raw(self, payload_hex: str) -> None:
        """Replay a raw preset payload verbatim."""
        if self.controller is None:
            raise UpdateFailed("Controller not connected")
        await self.hass.async_add_executor_job(self._send_raw, payload_hex)
        self.trigger_fast_poll()
        await self.async_request_refresh()

    def _send_raw(self, payload_hex: str) -> None:
        """Blocking raw send. Runs in the executor."""
        with self._lock:
            helpers.send_raw(
                self.controller,
                payload_hex,
                retries=NUM_RETRIES,
                wait=TIME_BETWEEN_CMDS,
                exceptions=TRANSPORT_ERRORS,
            )
