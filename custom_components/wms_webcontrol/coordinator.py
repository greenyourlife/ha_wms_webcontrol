"""Data update coordinator for the WAREMA WMS WebControl integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import helpers
from .client import (
    FC_SZENE_AUSFUEHREN,
    TEL_KANALBEDIENUNG,
    BoxClock,
    ChannelInfo,
    Fetch,
    TimerPlan,
    WmsClient,
    WmsConnectionError,
    WmsError,
    WmsPollError,
    parse_legacy_payload,
)
from .const import (
    CLOCK_MAX_DRIFT,
    CONF_EXCLUDE_CHANNELS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FAST_UPDATE_DURATION,
    FAST_UPDATE_INTERVAL,
    ISSUE_UNREACHABLE,
    ISSUE_UNREACHABLE_AFTER,
    LOGGER,
    MOVE_ATTEMPTS,
    POLL_FAILURE_TOLERANCE,
    POST_COMMAND_SETTLE,
    PRESET_RESENDS,
    REQUEST_TIMEOUT,
    TIMER_READ_RETRIES,
    TIMER_RETRY_WAIT,
    VERIFY_READS,
)

type WmsConfigEntry = ConfigEntry["WmsWebControlCoordinator"]


def make_fetch(hass: HomeAssistant, base_url: str) -> Fetch:
    """Return the HTTP transport for the client, using HA's shared session."""
    session = async_get_clientsession(hass)
    endpoint = f"{base_url.rstrip('/')}/protocol.xml"
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    async def fetch(query: str) -> str:
        try:
            async with session.get(f"{endpoint}?{query}", timeout=timeout) as resp:
                resp.raise_for_status()
                return await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WmsConnectionError(f"{type(err).__name__}: {err}") from err

    return fetch


def lib_position(raw: int | None) -> float | None:
    """Convert a raw protocol position (0..200) to 0..100 (library semantics)."""
    return None if raw is None else raw / 2


@dataclass(slots=True)
class ShadeInfo:
    """Snapshot of a single actor's state (positions 0..100, library semantics)."""

    room_id: int
    channel_id: int
    room_name: str
    channel_name: str
    position: float | None  # None while the box reports "unknown"
    is_moving: bool
    last_updated: datetime | None
    product_type: int | None = None
    volant1: float | None = None
    volant2: float | None = None


def shade_key(room_id: int, channel_id: int) -> str:
    """Stable key identifying a channel within a config entry."""
    return f"{room_id}_{channel_id}"


class WmsWebControlCoordinator(DataUpdateCoordinator[dict[str, ShadeInfo]]):
    """Coordinates polling and command dispatch for one WebControl box."""

    config_entry: WmsConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: WmsConfigEntry, url: str, client: WmsClient
    ) -> None:
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
        self.client = client
        self.products: list[ChannelInfo] = []
        self.scenes: list[ChannelInfo] = []
        self._fast_until: float | None = None
        # Consecutive failed polls, see POLL_FAILURE_TOLERANCE.
        self._poll_failures = 0
        # Last commanded HA target position per shade key, used to derive the
        # movement direction. Shared between the cover and the status sensor.
        self.targets: dict[str, int | None] = {}
        # Built-in timers of the actors (read at startup and on request).
        self.timers: dict[str, TimerPlan] = {}
        self.timer_errors: dict[str, str] = {}
        self.timers_read_at: datetime | None = None
        # Box clock and its offset to HA's local time (seconds, box - HA).
        self.clock: BoxClock | None = None
        self.clock_offset: float | None = None
        self.clock_checked_at: datetime | None = None
        self.clock_set_at: datetime | None = None
        self._unreachable_since: datetime | None = None

    # -- discovery -----------------------------------------------------------

    async def async_setup(self) -> None:
        """Discover products and scenes on the box."""
        channels = await self.client.discover()
        excluded = self.config_entry.options.get(CONF_EXCLUDE_CHANNELS, [])
        self.products = []
        self.scenes = []
        for channel in channels:
            if channel.is_scene:
                self.scenes.append(channel)
            elif not helpers.is_cover_type(channel.product_type):
                LOGGER.info(
                    "Skipping %s (product type %s is not a cover yet)",
                    channel.name,
                    channel.product_type,
                )
            elif helpers.is_excluded(channel.name, excluded):
                LOGGER.debug("Excluding %s by option", channel.name)
            else:
                self.products.append(channel)
        LOGGER.debug(
            "Discovered %d product(s) and %d scene(s) on %s",
            len(self.products),
            len(self.scenes),
            self.url,
        )

    def product(self, key: str) -> ChannelInfo:
        """Return the product channel for a key."""
        for channel in self.products:
            if channel.key == key:
                return channel
        raise KeyError(key)

    # -- polling -------------------------------------------------------------

    async def _read(self, channel: ChannelInfo) -> ShadeInfo:
        state = await self.client.read_state(channel.room_id, channel.channel_id)
        return ShadeInfo(
            room_id=channel.room_id,
            channel_id=channel.channel_id,
            room_name=channel.room_name,
            channel_name=channel.name,
            position=lib_position(state.position),
            is_moving=state.moving,
            last_updated=datetime.now(),
            product_type=channel.product_type,
            volant1=lib_position(state.volant1),
            volant2=lib_position(state.volant2),
        )

    async def _read_all(
        self, channels: list[ChannelInfo] | None = None
    ) -> dict[str, ShadeInfo]:
        result: dict[str, ShadeInfo] = {}
        for channel in self.products if channels is None else channels:
            result[channel.key] = await self._read(channel)
        return result

    async def _async_update_data(self) -> dict[str, ShadeInfo]:
        """Fetch the latest state of all actors."""
        try:
            data = await self._read_all()
        except WmsError as err:
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
            self._track_unreachable(err)
            raise UpdateFailed(f"Error communicating with WebControl: {err}") from err
        self._poll_failures = 0
        self._track_reachable()

        # Once a shade has settled, forget its movement target.
        for key, info in data.items():
            if not info.is_moving:
                self.targets.pop(key, None)

        self._adjust_interval(any(info.is_moving for info in data.values()))
        return data

    def _track_unreachable(self, err: Exception) -> None:
        """Raise a repair issue once the box has been unreachable for a while."""
        now = dt_util.utcnow()
        if self._unreachable_since is None:
            self._unreachable_since = now
            return
        if (now - self._unreachable_since).total_seconds() < ISSUE_UNREACHABLE_AFTER:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_UNREACHABLE}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNREACHABLE,
            translation_placeholders={
                "url": self.url,
                "since": dt_util.as_local(self._unreachable_since).strftime("%d.%m. %H:%M"),
                "error": str(err),
            },
        )

    def _track_reachable(self) -> None:
        if self._unreachable_since is None:
            return
        self._unreachable_since = None
        ir.async_delete_issue(
            self.hass, DOMAIN, f"{ISSUE_UNREACHABLE}_{self.config_entry.entry_id}"
        )

    # -- timers --------------------------------------------------------------

    async def async_read_timers(self) -> None:
        """Read the built-in timer of every actor (slow: radio round trips)."""
        for channel in self.products:
            for attempt in range(1 + TIMER_READ_RETRIES):
                try:
                    plan = await self.client.read_timer(channel.room_id, channel.channel_id)
                except WmsPollError as err:
                    # The actor did not answer by radio; this happens now and then.
                    LOGGER.debug(
                        "Timer read of %s failed (attempt %d): %s",
                        channel.name,
                        attempt + 1,
                        err,
                    )
                    self.timer_errors[channel.key] = str(err)
                    if attempt < TIMER_READ_RETRIES:
                        await asyncio.sleep(TIMER_RETRY_WAIT)
                    continue
                except WmsError as err:
                    LOGGER.warning("Timer read of %s failed: %s", channel.name, err)
                    self.timer_errors[channel.key] = str(err)
                    break
                self.timers[channel.key] = plan
                self.timer_errors.pop(channel.key, None)
                LOGGER.debug(
                    "Timer of %s: %s, %d switching time(s)",
                    channel.name,
                    "on" if plan.enabled else "off",
                    len(plan.entries),
                )
                break
            else:
                LOGGER.warning(
                    "Timer of %s could not be read: %s",
                    channel.name,
                    self.timer_errors.get(channel.key),
                )
        self.timers_read_at = dt_util.utcnow()
        self.async_update_listeners()

    # -- clock ---------------------------------------------------------------

    async def async_check_clock(self, *, sync: bool, force: bool = False) -> None:
        """Read the box clock; set it to HA's local time if it drifted.

        ``sync`` sets the clock when it is off by more than CLOCK_MAX_DRIFT,
        ``force`` sets it regardless. The box's time-master flag is kept.
        """
        clock = await self.client.read_clock()
        offset = self._offset(clock)
        LOGGER.debug("Box clock %s, offset %.0f s", clock.time, offset)
        if force or (sync and abs(offset) > CLOCK_MAX_DRIFT):
            now = dt_util.now().replace(tzinfo=None, microsecond=0)
            clock = await self.client.set_clock(
                now, system_time_master=clock.system_time_master
            )
            LOGGER.info(
                "Box clock set to %s (was off by %.0f s)", now, offset
            )
            self.clock_set_at = dt_util.utcnow()
            offset = self._offset(clock)
        self.clock = clock
        self.clock_offset = offset
        self.clock_checked_at = dt_util.utcnow()
        self.async_update_listeners()

    @staticmethod
    def _offset(clock: BoxClock) -> float:
        local_now = dt_util.now().replace(tzinfo=None)
        return round((clock.time - local_now).total_seconds())

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

    def set_target(self, key: str, ha_position: int | None) -> None:
        """Record the last commanded HA target position for a shade."""
        self.targets[key] = ha_position

    # -- cover operations ----------------------------------------------------

    async def async_move(
        self,
        key: str,
        position: float | None = None,
        *,
        volant1: float | None = None,
        volant2: float | None = None,
    ) -> None:
        """Move an actor (positions 0..100, library semantics).

        Failures are logged, not raised: callers such as the wind/rain safety
        script check the final state themselves and must not abort on a single
        unconfirmed attempt.
        """
        channel = self.product(key)

        def raw(value: float | None) -> int | None:
            return None if value is None else int(round(value * 2))

        for attempt in range(1, MOVE_ATTEMPTS + 1):
            try:
                result = await self.client.move(
                    channel.room_id,
                    channel.channel_id,
                    raw(position),
                    volant1=raw(volant1),
                    volant2=raw(volant2),
                )
            except WmsError as err:
                LOGGER.warning(
                    "Move of %s failed (attempt %d): %s", channel.name, attempt, err
                )
                continue
            if result.confirmed is not False:
                break
            LOGGER.debug("Move of %s not confirmed (attempt %d)", channel.name, attempt)
        else:
            LOGGER.warning(
                "Move of %s not confirmed by the box after %d attempt(s)",
                channel.name,
                MOVE_ATTEMPTS,
            )
        self.trigger_fast_poll()
        await self.async_request_refresh()

    async def async_stop(self, key: str) -> None:
        """Stop an actor."""
        channel = self.product(key)
        try:
            result = await self.client.stop(channel.room_id, channel.channel_id)
            if result.confirmed is False:
                await self.client.stop(channel.room_id, channel.channel_id)
        except WmsError as err:
            raise HomeAssistantError(f"Stop of {channel.name} failed: {err}") from err
        finally:
            self.targets.pop(key, None)
            self.trigger_fast_poll()
            await self.async_request_refresh()

    async def async_wink(self, key: str) -> None:
        """Let an actor move briefly to identify it."""
        channel = self.product(key)
        try:
            await self.client.wink(channel.room_id, channel.channel_id)
        except WmsError as err:
            raise HomeAssistantError(f"Wink of {channel.name} failed: {err}") from err

    # -- scenes --------------------------------------------------------------

    async def _snapshot(self, room_id: int) -> dict[str, tuple[float | None, bool]]:
        """Best-effort state of the actors in a room, for movement checks."""
        channels = [c for c in self.products if c.room_id == room_id]
        try:
            data = await self._read_all(channels)
        except WmsError as err:
            LOGGER.debug("State snapshot failed: %s", err)
            return {}
        return {key: (info.position, info.is_moving) for key, info in data.items()}

    async def _moved_since(self, room_id: int, before: dict) -> bool | None:
        """Return True if an actor moved, False if not, None if unknown."""
        after: dict = {}
        for _ in range(VERIFY_READS):
            await asyncio.sleep(POST_COMMAND_SETTLE)
            after = await self._snapshot(room_id)
            if any(
                state[0] is not None
                and helpers.movement_detected(before.get(key), state)
                for key, state in after.items()
            ):
                return True
        if not before or not after:
            return None
        return False

    async def async_run_scene(self, room_id: int, channel_id: int, label: str) -> None:
        """Recall a scene and make sure the box executed it.

        Primary check: the box's own confirmation (poll of the channel
        operation). If the box gives none, fall back to checking whether an
        actor in the room moved. Resends only when nothing happened, so a
        running motor is never interrupted.

        Raises HomeAssistantError if the box rejects the scene on every attempt
        or is unreachable, so a failed press is visible in the UI.
        """
        attempts = 1 + PRESET_RESENDS
        before = await self._snapshot(room_id)
        try:
            for attempt in range(1, attempts + 1):
                result = await self.client.run_scene(room_id, channel_id)
                if result.confirmed:
                    LOGGER.debug("Scene %s confirmed by box (attempt %d)", label, attempt)
                    return
                if result.confirmed is None:
                    moved = await self._moved_since(room_id, before)
                    if moved is not False:
                        return
                LOGGER.debug("Scene %s not executed (attempt %d)", label, attempt)
            if result.confirmed is False:
                raise HomeAssistantError(
                    f"WebControl did not execute scene {label} after {attempts} attempt(s)"
                )
            LOGGER.warning(
                "Scene %s sent, but no movement detected (actor may already be "
                "in position)",
                label,
            )
        except WmsError as err:
            raise HomeAssistantError(f"Scene {label} failed: {err}") from err
        finally:
            self.trigger_fast_poll()
            await self.async_request_refresh()

    async def async_send_payload(self, payload_hex: str, label: str) -> None:
        """Send a manually configured (0.3.x style) preset payload."""
        try:
            payload = parse_legacy_payload(payload_hex)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        if (
            len(payload) >= 4
            and payload[0] == TEL_KANALBEDIENUNG
            and payload[3] == FC_SZENE_AUSFUEHREN
        ):
            await self.async_run_scene(payload[1], payload[2], label)
            return
        try:
            await self.client.send_payload(payload)
        except WmsError as err:
            raise HomeAssistantError(f"Preset {label} failed: {err}") from err
        finally:
            self.trigger_fast_poll()
            await self.async_request_refresh()
