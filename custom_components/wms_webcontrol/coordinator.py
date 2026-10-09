"""Data update coordinator for the WAREMA WMS WebControl integration."""

from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ElemTree
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests
from warema_wms import Shade, WmsController

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    POLL_FAILURE_TOLERANCE,
    POST_COMMAND_SETTLE,
    PRESET_RESENDS,
    PRESET_RETRY_WAIT,
    PRESET_SEND_ATTEMPTS,
    SHADE_NUM_RETRIES,
    TIME_BETWEEN_CMDS,
    VERIFY_READS,
)

# Transport-level errors that should mark the box as (temporarily) unavailable
# instead of crashing the integration. ParseError (malformed XML) derives from
# SyntaxError, not ValueError, so it is listed explicitly.
TRANSPORT_ERRORS = (requests.RequestException, OSError, ValueError, ElemTree.ParseError)
# Everything that means "the box did not do what we asked".
COMMAND_ERRORS = (*TRANSPORT_ERRORS, helpers.WmsCommandError)

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
        # Consecutive failed polls, see POLL_FAILURE_TOLERANCE.
        self._poll_failures = 0
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
        except COMMAND_ERRORS as err:
            self._poll_failures += 1
            if self.data is not None and self._poll_failures <= POLL_FAILURE_TOLERANCE:
                # Short busy phases (e.g. while a motor runs) must not flap the
                # entities to unavailable: keep the last state, re-poll soon.
                LOGGER.info(
                    "Poll failed (%d/%d tolerated), keeping last known state: %s",
                    self._poll_failures,
                    POLL_FAILURE_TOLERANCE,
                    err,
                )
                self.update_interval = timedelta(seconds=FAST_UPDATE_INTERVAL)
                return self.data
            raise UpdateFailed(f"Error communicating with WebControl: {err}") from err
        self._poll_failures = 0

        # Once a shade has settled, forget its movement target.
        for key, info in data.items():
            if not info.is_moving:
                self.targets.pop(key, None)

        self._adjust_interval(any(info.is_moving for info in data.values()))
        return data

    def _poll(self) -> dict[str, ShadeInfo]:
        """Blocking poll of every discovered shade. Runs in the executor."""
        with self._lock:
            return self._read_all()

    def _read_all(self) -> dict[str, ShadeInfo]:
        """Read every shade's state. Caller must hold the lock.

        Uses :func:`helpers.read_state`, which waits for the box to be ready and
        raises instead of silently keeping a stale value when the box answers
        with an errorcode.
        """
        result: dict[str, ShadeInfo] = {}
        for shade in self.shades:
            position, is_moving = helpers.read_state(
                self.controller,
                shade.room.id,
                shade.channel.id,
                tries=NUM_RETRIES,
                wait=TIME_BETWEEN_CMDS,
            )
            key = shade_key(shade.room.id, shade.channel.id)
            result[key] = ShadeInfo(
                room_id=shade.room.id,
                channel_id=shade.channel.id,
                room_name=shade.get_room_name(),
                channel_name=shade.get_channel_name(),
                position=position,
                is_moving=is_moving,
                last_updated=datetime.now(),
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

        Uses the library's ``set_shade_position`` (which gates on the box's
        "check ready" response and resends if its own state check fails). The
        result is logged but not raised: callers such as the wind/rain safety
        script verify the final state themselves and must not abort on a single
        unconfirmed attempt.
        """
        with self._lock:
            if not shade.set_shade_position(lib_position):
                LOGGER.warning(
                    "Move of %s to %s not confirmed by the box",
                    shade.get_channel_name(),
                    lib_position,
                )

    async def async_send_raw(self, payload_hex: str) -> None:
        """Replay a raw preset payload and verify that a shade reacted.

        Raises :class:`HomeAssistantError` if the box is unreachable or does not
        accept the command, so a failed press is visible in the UI instead of
        being swallowed.
        """
        if self.controller is None:
            raise HomeAssistantError("WebControl not connected")
        try:
            await self.hass.async_add_executor_job(self._send_raw_verified, payload_hex)
        except COMMAND_ERRORS as err:
            raise HomeAssistantError(
                f"WebControl did not accept preset {payload_hex}: {err}"
            ) from err
        finally:
            self.trigger_fast_poll()
            await self.async_request_refresh()

    def _snapshot(self) -> dict[str, tuple[float, bool]]:
        """Best-effort state snapshot for movement verification. Holds no lock."""
        try:
            return {
                key: (info.position, info.is_moving)
                for key, info in self._read_all().items()
            }
        except COMMAND_ERRORS as err:
            LOGGER.debug("State snapshot failed: %s", err)
            return {}

    def _send_raw_verified(self, payload_hex: str) -> bool:
        """Blocking raw send with movement check. Runs in the executor.

        1. Snapshot all shades.
        2. Send the payload; :func:`helpers.send_raw` only returns once the box
           acknowledged it (``feedback=1``), otherwise it raises.
        3. Wait for the box to settle, then check up to ``VERIFY_READS`` times
           whether any shade moves or changed position.
        4. If nothing reacted, resend (``PRESET_RESENDS`` times). Nothing moved,
           so a resend cannot interrupt a running motor.

        Returns whether movement was detected. No movement after all resends is
        logged as a warning but not raised: the shade may already sit at the
        preset's target (e.g. "retract" on a retracted awning).
        """
        with self._lock:
            before = self._snapshot()
            attempts = 1 + PRESET_RESENDS
            for attempt in range(1, attempts + 1):
                helpers.send_raw(
                    self.controller,
                    payload_hex,
                    retries=PRESET_SEND_ATTEMPTS,
                    wait=TIME_BETWEEN_CMDS,
                    retry_wait=PRESET_RETRY_WAIT,
                    exceptions=TRANSPORT_ERRORS,
                )
                LOGGER.debug("Preset %s accepted by box (attempt %d)", payload_hex, attempt)
                for _ in range(VERIFY_READS):
                    time.sleep(POST_COMMAND_SETTLE)
                    after = self._snapshot()
                    if any(
                        helpers.movement_detected(before.get(key), state)
                        for key, state in after.items()
                    ):
                        LOGGER.debug("Preset %s: movement detected", payload_hex)
                        return True
                LOGGER.debug(
                    "Preset %s: no movement after attempt %d (before=%s, after=%s)",
                    payload_hex,
                    attempt,
                    before,
                    after,
                )
                if not before or not after:
                    # Without both snapshots we cannot tell "not moving" from
                    # "could not read" - do not risk resending into a moving motor.
                    LOGGER.warning(
                        "Preset %s accepted by the box, movement could not be "
                        "verified (state read failed); not resending",
                        payload_hex,
                    )
                    return False
            LOGGER.warning(
                "Preset %s was accepted by the box but no shade moved after %d "
                "attempt(s). Either it is already at the preset position or the "
                "radio command did not reach the motor",
                payload_hex,
                attempts,
            )
            return False
