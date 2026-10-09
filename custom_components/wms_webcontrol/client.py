"""Async client for the WAREMA WMS WebControl (Basic) ``protocol.xml`` protocol.

The protocol was taken from the JavaScript of the box's own web interface
(see ``docs/PROTOCOL.md``). This module imports nothing from Home Assistant so
it can be unit-tested on a plain interpreter with a fake transport.

Safety: the client only ever sends telegrams from ``ALLOWED_TELEGRAMS`` and,
for channel operation, only function codes from ``ALLOWED_FUNCTIONS``. Anything
that deletes, renames or reloads the box configuration is rejected before it
reaches the network.
"""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ElemTree
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

# --- Framing -----------------------------------------------------------------

HEADER_BYTE = 0x90
COUNTER_MAX = 254  # official UI: 0, 1, ..., 254, 1, 2, ... (255 is never sent)
PAYLOAD_MAX = 32
INVALID = 0xFF  # "ignore" / "unknown" in arguments and positions

MAX_ROOMS = 20
MAX_CHANNELS = 10
PRODUCT = 255  # szeneindex value marking a product (actor) instead of a scene

# --- Telegram ids (request; the response id is request + 1) --------------------

TEL_RAUM_ABFRAGEN = 0x03
TEL_KANAL_ABFRAGEN = 0x0D
TEL_KANALBEDIENUNG = 0x21
TEL_POS_RUECKMELDUNG = 0x23
TEL_WINKEN = 0x25
TEL_GRENZWERTE = 0x2D
TEL_POLLING = 0x31
TEL_KANAL_SZENE_ABFRAGEN = 0x47

RES_RAUM_ABFRAGEN = 4
RES_KANALBEDIENUNG = 34
RES_POS_RUECKMELDUNG = 36
RES_WINKEN = 38
RES_POLLING = 50
RES_WMS_STACK_BUSY = 51
RES_ERROR_MESSAGE = 52
RES_KANAL_SZENE_ABFRAGEN = 72

# Function codes for TEL_KANALBEDIENUNG.
FC_STOP = 1
FC_SOLL_SICHER = 3
FC_SZENE_AUSFUEHREN = 8
FC_SZENE_LERNEN = 9  # NOT allowed in 0.4 (would overwrite stored scene positions)

# Polling types for TEL_POLLING.
POLL_KANALBEDIENUNG = 0
POLL_POSITION = 1
POLL_WINKEN = 5

# Error codes (RES_ERROR_MESSAGE).
ERROR_POLLING_BEFEHL = 32  # poll without a matching pending request

ALLOWED_TELEGRAMS = frozenset(
    {
        TEL_RAUM_ABFRAGEN,
        TEL_KANAL_ABFRAGEN,
        TEL_KANALBEDIENUNG,
        TEL_POS_RUECKMELDUNG,
        TEL_WINKEN,
        TEL_GRENZWERTE,
        TEL_POLLING,
        TEL_KANAL_SZENE_ABFRAGEN,
    }
)
ALLOWED_FUNCTIONS = frozenset({FC_STOP, FC_SOLL_SICHER, FC_SZENE_AUSFUEHREN})


# --- Errors ------------------------------------------------------------------


class WmsError(Exception):
    """Base error of the WebControl client."""


class WmsConnectionError(WmsError):
    """The box could not be reached or answered with garbage."""


class WmsForbiddenTelegram(WmsError):
    """A telegram outside the allow-list was requested (never sent)."""


class WmsBusyError(WmsError):
    """The box kept answering "WMS stack busy" (feedback 0)."""


class WmsErrorResponse(WmsError):
    """The box answered with an error message (responseID 52)."""

    def __init__(self, errorcode: int | None, requestid: int | None) -> None:
        super().__init__(f"box error {errorcode} for telegram {requestid}")
        self.errorcode = errorcode
        self.requestid = requestid


class WmsPollError(WmsError):
    """A poll finished with an error feedback (e.g. actor did not answer)."""

    def __init__(self, befehl: int, feedback: int | None) -> None:
        super().__init__(f"poll {befehl} failed with feedback {feedback}")
        self.befehl = befehl
        self.feedback = feedback


class WmsTimeout(WmsError):
    """A poll did not produce a result in time."""


# --- Data --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    """One configured channel of the box: a product (actor) or a scene."""

    room_id: int
    channel_id: int
    room_name: str
    name: str
    scene_index: int  # PRODUCT (255) for actors, 0..31 for scenes
    product_type: int | None
    operation_type: int | None

    @property
    def is_scene(self) -> bool:
        """Return whether this channel is a scene."""
        return self.scene_index != PRODUCT

    @property
    def key(self) -> str:
        """Stable key ``<room>_<channel>`` (matches 0.3.x unique ids)."""
        return f"{self.room_id}_{self.channel_id}"


@dataclass(frozen=True, slots=True)
class ShadeState:
    """Position feedback of one actor (raw protocol values, 0..200 or None)."""

    position: int | None
    moving: bool
    angle: int | None
    volant1: int | None
    volant2: int | None


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Outcome of a channel operation.

    ``confirmed`` is True when the box reported the operation as executed,
    False when it reported an error, and None when the box gave no usable
    confirmation (callers may then fall back to checking movement).
    """

    confirmed: bool | None
    feedback: int | None = None


# --- Helpers -----------------------------------------------------------------


def _text(resp: ElemTree.Element, tag: str) -> str | None:
    element = resp.find(tag)
    return None if element is None else element.text


def _int(resp: ElemTree.Element, tag: str) -> int | None:
    value = _text(resp, tag)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def response_id(resp: ElemTree.Element) -> int | None:
    """Return the responseID of a box answer."""
    return _int(resp, "responseID")


def raw_or_none(value: int | None) -> int | None:
    """Map the protocol's 255 ("unknown") to None."""
    if value is None or value == INVALID:
        return None
    return value


def parse_legacy_payload(payload_hex: str) -> bytes:
    """Parse a 0.3.x preset payload (``<len><telegram>...``) into raw payload bytes.

    0.3.x stored presets the way the old library expected them: the length byte
    followed by the telegram, e.g. ``0821000308ffffffff``. The length byte is
    validated and stripped; the counter/header are added by the client.
    """
    data = bytes.fromhex((payload_hex or "").strip())
    if len(data) < 2 or data[0] != len(data) - 1:
        raise ValueError(f"invalid preset payload {payload_hex!r}")
    return data[1:]


def legacy_scene_payload(room_id: int, channel_id: int) -> str:
    """Return the 0.3.x preset payload that recalls the scene on a channel."""
    return f"0821{room_id:02x}{channel_id:02x}08ffffffff"


# --- Client ------------------------------------------------------------------

Fetch = Callable[[str], Awaitable[str]]


class WmsClient:
    """Talks to one WebControl box.

    ``fetch`` receives the query string (``protocol=...&_=...``) and returns the
    raw XML text; it raises ``WmsConnectionError`` on transport problems.
    """

    def __init__(
        self,
        fetch: Fetch,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        busy_retries: int = 5,
        busy_wait: float = 1.0,
        poll_interval: float = 0.5,
        poll_timeout: float = 10.0,
    ) -> None:
        """Initialise the client."""
        self._fetch = fetch
        self._sleep = sleep
        self._busy_retries = busy_retries
        self._busy_wait = busy_wait
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._counter = 0
        self._ts = int(time.time() * 1000)
        # One logical operation (command + its polls) at a time.
        self.lock = asyncio.Lock()

    # -- framing --------------------------------------------------------------

    def _next_counter(self) -> int:
        """Return the next command counter exactly like the official UI."""
        if self._counter >= COUNTER_MAX:
            self._counter = 1
            return COUNTER_MAX
        value = self._counter
        self._counter += 1
        return value

    @staticmethod
    def check_allowed(payload: bytes) -> None:
        """Raise unless the payload is on the allow-list."""
        if not payload:
            raise WmsForbiddenTelegram("empty payload")
        telegram = payload[0]
        if telegram not in ALLOWED_TELEGRAMS:
            raise WmsForbiddenTelegram(f"telegram 0x{telegram:02x} is not allowed")
        if telegram == TEL_KANALBEDIENUNG:
            if len(payload) < 4 or payload[3] not in ALLOWED_FUNCTIONS:
                function = payload[3] if len(payload) >= 4 else None
                raise WmsForbiddenTelegram(f"function code {function} is not allowed")
        if len(payload) > PAYLOAD_MAX:
            raise WmsForbiddenTelegram("payload too long")

    def frame(self, payload: bytes) -> str:
        """Build the hex string for one request (consumes a counter value)."""
        self.check_allowed(payload)
        header = bytes((HEADER_BYTE, self._next_counter(), len(payload)))
        return (header + payload).hex()

    # -- transport ------------------------------------------------------------

    async def request(self, payload: bytes) -> ElemTree.Element:
        """Send one telegram and return the parsed XML answer."""
        hex_string = self.frame(payload)
        self._ts += 1
        query = f"protocol={hex_string}&_={self._ts}"
        text = await self._fetch(query)
        _LOGGER.debug("TX %s RX %s", hex_string, text)
        try:
            return ElemTree.fromstring(text)
        except ElemTree.ParseError as err:
            raise WmsConnectionError(f"invalid XML from box: {err}") from err

    async def command(self, payload: bytes) -> ElemTree.Element:
        """Send a telegram, resending while the WMS stack is busy.

        Mirrors the official UI: a ``WMS stack busy`` answer with feedback 0
        means the command was dropped, so it is repeated after a pause.
        """
        for attempt in range(self._busy_retries):
            resp = await self.request(payload)
            rid = response_id(resp)
            if rid == RES_ERROR_MESSAGE:
                raise WmsErrorResponse(_int(resp, "errorcode"), _int(resp, "requestid"))
            if rid == RES_WMS_STACK_BUSY and _int(resp, "feedback") == 0:
                _LOGGER.debug(
                    "Box busy for telegram 0x%02x (attempt %d)", payload[0], attempt + 1
                )
                await self._sleep(self._busy_wait)
                continue
            return resp
        raise WmsBusyError(f"box stayed busy for telegram 0x{payload[0]:02x}")

    async def poll(
        self, room_id: int, channel_id: int, befehl: int, expect: int
    ) -> ElemTree.Element:
        """Poll until the box delivers the result ``expect`` for ``befehl``."""
        deadline = self._poll_timeout
        waited = 0.0
        payload = bytes((TEL_POLLING, room_id, channel_id, befehl))
        while True:
            resp = await self.request(payload)
            rid = response_id(resp)
            if rid == expect:
                return resp
            if rid == RES_ERROR_MESSAGE:
                raise WmsErrorResponse(_int(resp, "errorcode"), _int(resp, "requestid"))
            if rid == RES_POLLING:
                feedback = _int(resp, "feedback")
                if feedback not in (0, None):
                    raise WmsPollError(befehl, feedback)
            # feedback 0 (pending) or stack busy: wait and poll again
            if waited >= deadline:
                raise WmsTimeout(f"no result for poll {befehl}")
            await self._sleep(self._poll_interval)
            waited += self._poll_interval

    # -- read operations ------------------------------------------------------

    async def read_room(self, room_id: int) -> str | None:
        """Return the room name, or None for an unused room slot."""
        async with self.lock:
            resp = await self.command(bytes((TEL_RAUM_ABFRAGEN, room_id)))
        if response_id(resp) != RES_RAUM_ABFRAGEN:
            raise WmsConnectionError("unexpected answer to room query")
        return _text(resp, "raumname") or None

    async def read_channel(self, room_id: int, channel_id: int, room_name: str) -> ChannelInfo | None:
        """Return channel/scene info, or None for an unused channel slot."""
        async with self.lock:
            resp = await self.command(
                bytes((TEL_KANAL_SZENE_ABFRAGEN, room_id, channel_id))
            )
        if response_id(resp) != RES_KANAL_SZENE_ABFRAGEN:
            raise WmsConnectionError("unexpected answer to channel query")
        name = _text(resp, "kanalname")
        if not name:
            return None
        scene_index = _int(resp, "szeneindex")
        return ChannelInfo(
            room_id=room_id,
            channel_id=channel_id,
            room_name=room_name,
            name=name,
            scene_index=PRODUCT if scene_index is None else scene_index,
            product_type=raw_or_none(_int(resp, "produkttyp")),
            operation_type=raw_or_none(_int(resp, "bedientyp")),
        )

    async def discover(self) -> list[ChannelInfo]:
        """Return all configured channels and scenes of the box.

        All room slots are checked (rooms can have gaps after deletions); within
        a used room all channel slots are checked for the same reason.
        """
        channels: list[ChannelInfo] = []
        for room_id in range(MAX_ROOMS):
            room_name = await self.read_room(room_id)
            if room_name is None:
                continue
            for channel_id in range(MAX_CHANNELS):
                info = await self.read_channel(room_id, channel_id, room_name)
                if info is not None:
                    channels.append(info)
        return channels

    async def read_state(self, room_id: int, channel_id: int) -> ShadeState:
        """Request fresh position feedback from an actor and return it."""
        async with self.lock:
            await self.command(bytes((TEL_POS_RUECKMELDUNG, room_id, channel_id)))
            resp = await self.poll(
                room_id, channel_id, POLL_POSITION, RES_POS_RUECKMELDUNG
            )
        fahrt = _int(resp, "fahrt")
        return ShadeState(
            position=raw_or_none(_int(resp, "position")),
            moving=bool(fahrt),
            angle=raw_or_none(_int(resp, "winkel")),
            volant1=raw_or_none(_int(resp, "positionvolant1")),
            volant2=raw_or_none(_int(resp, "positionvolant2")),
        )

    # -- operations -----------------------------------------------------------

    async def operate(
        self,
        room_id: int,
        channel_id: int,
        function: int,
        args: tuple[int, int, int, int] = (INVALID, INVALID, INVALID, INVALID),
    ) -> OperationResult:
        """Run a channel operation and wait for the box's confirmation."""
        payload = bytes((TEL_KANALBEDIENUNG, room_id, channel_id, function, *args))
        async with self.lock:
            resp = await self.command(payload)
            if response_id(resp) == RES_WMS_STACK_BUSY and _int(resp, "feedback") != 1:
                return OperationResult(confirmed=False)
            try:
                result = await self.poll(
                    room_id, channel_id, POLL_KANALBEDIENUNG, RES_KANALBEDIENUNG
                )
            except WmsPollError as err:
                _LOGGER.debug("Operation %s on %s/%s failed: %s", function, room_id, channel_id, err)
                return OperationResult(confirmed=False, feedback=err.feedback)
            except WmsErrorResponse as err:
                if err.errorcode == ERROR_POLLING_BEFEHL:
                    return OperationResult(confirmed=None)
                raise
            except WmsTimeout:
                return OperationResult(confirmed=None)
        return OperationResult(confirmed=True, feedback=_int(result, "feedback"))

    async def move(
        self,
        room_id: int,
        channel_id: int,
        position: int | None = None,
        *,
        angle: int | None = None,
        volant1: int | None = None,
        volant2: int | None = None,
    ) -> OperationResult:
        """Move an actor; positions are raw protocol values (0..200)."""

        def arg(value: int | None, low: int, high: int) -> int:
            if value is None:
                return INVALID
            if not low <= value <= high:
                raise ValueError(f"value {value} outside {low}..{high}")
            return value

        return await self.operate(
            room_id,
            channel_id,
            FC_SOLL_SICHER,
            (
                arg(position, 0, 200),
                arg(angle, 0, 254),
                arg(volant1, 0, 200),
                arg(volant2, 0, 200),
            ),
        )

    async def stop(self, room_id: int, channel_id: int) -> OperationResult:
        """Stop an actor."""
        return await self.operate(room_id, channel_id, FC_STOP)

    async def run_scene(self, room_id: int, channel_id: int) -> OperationResult:
        """Recall the scene stored on a scene channel."""
        return await self.operate(room_id, channel_id, FC_SZENE_AUSFUEHREN)

    async def wink(self, room_id: int, channel_id: int) -> None:
        """Let an actor move briefly to identify it."""
        async with self.lock:
            await self.command(bytes((TEL_WINKEN, room_id, channel_id)))

    async def send_payload(self, payload: bytes) -> ElemTree.Element:
        """Send an allow-listed raw payload (legacy presets)."""
        async with self.lock:
            return await self.command(payload)
