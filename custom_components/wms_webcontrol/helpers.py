"""Pure, framework-free helpers for the WAREMA WMS WebControl integration.

This module deliberately imports nothing from Home Assistant so the core logic
(position inversion, movement derivation, preset parsing, raw sending) can be
unit-tested on a plain Python interpreter with a mocked controller.
"""

from __future__ import annotations

import time
from typing import Callable, Optional


def invert_position(lib_position: float) -> int:
    """Convert a library position to a Home Assistant cover position.

    The library uses ``0 = open`` / ``100 = closed`` while Home Assistant uses
    ``0 = closed`` / ``100 = open``. Hence the value is inverted.
    """
    return 100 - int(round(lib_position))


def to_lib_position(ha_position: int) -> int:
    """Convert a Home Assistant cover position back to a library position."""
    return 100 - int(round(ha_position))


def derive_movement(
    is_moving: bool,
    target_ha: Optional[int],
    current_ha: Optional[int],
) -> tuple[bool, bool]:
    """Return ``(is_opening, is_closing)`` from movement state and positions.

    Home Assistant has no dedicated "is moving" flag for covers; it infers
    motion from ``is_opening`` / ``is_closing``. Direction is derived by
    comparing the last commanded target with the current position. When the
    shade moves without a known target (e.g. triggered by a physical remote)
    the direction is unknown and both flags stay ``False``.
    """
    if not is_moving or target_ha is None or current_ha is None:
        return False, False
    if target_ha > current_ha:
        return True, False
    if target_ha < current_ha:
        return False, True
    return False, False


def guess_device_class(name: str) -> str:
    """Guess a cover device class from the channel name."""
    lowered = (name or "").lower()
    if any(token in lowered for token in ("marki", "awning", "sonnenschutz")):
        return "awning"
    return "shutter"


def is_valid_payload(payload_hex: str) -> bool:
    """Return whether ``payload_hex`` is a non-empty, even-length hex string."""
    payload = (payload_hex or "").strip().lower()
    if not payload or len(payload) % 2 != 0:
        return False
    try:
        int(payload, 16)
    except ValueError:
        return False
    return True


def parse_presets_text(text: str) -> list[dict[str, str]]:
    """Parse the multiline options text into a list of preset dicts.

    Each non-empty line has the form ``Name | payload_hex``. Lines without a
    ``|`` separator are treated as ``name`` only with an empty payload so the
    options flow can flag them as invalid.
    """
    presets: list[dict[str, str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name, sep, payload = line.partition("|")
        if not sep:
            presets.append({"name": name.strip(), "payload_hex": ""})
            continue
        presets.append(
            {"name": name.strip(), "payload_hex": payload.strip().lower().replace(" ", "")}
        )
    return presets


def format_presets_text(presets: list[dict[str, str]]) -> str:
    """Render a list of preset dicts back into the multiline options text."""
    return "\n".join(
        f"{preset.get('name', '')} | {preset.get('payload_hex', '')}" for preset in presets
    )


def parse_device_classes_text(text: str) -> dict[str, str]:
    """Parse ``channel name = device_class`` lines into a lookup dict.

    Keys are lower-cased channel names so overrides match case-insensitively.
    """
    result: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip().lower()
        if key and value:
            result[key] = value
    return result


def format_device_classes_text(mapping: dict[str, str]) -> str:
    """Render a device-class override mapping back into the options text."""
    return "\n".join(f"{key} = {value}" for key, value in mapping.items())


def send_raw(
    controller,
    payload_hex: str,
    *,
    retries: int = 3,
    wait: float = 0.5,
    check_ready: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> None:
    """Replay a raw protocol payload via the controller.

    Mirrors the ordering used for moves: an optional check-ready request, a
    short wait, then the command. ``controller._send_command`` prepends the
    ``90<counter>`` prefix and the ``_`` timestamp automatically, so the payload
    is sent verbatim otherwise. Retries the whole sequence on transport errors.
    """
    last_exc: Optional[BaseException] = None
    for _ in range(max(1, retries)):
        try:
            if check_ready:
                controller.send_rx_check_ready()
                sleep(wait)
            controller._send_command(payload_hex)  # noqa: SLF001 - intended raw path
            return
        except exceptions as exc:  # noqa: BLE001 - re-raised after retries
            last_exc = exc
            sleep(wait)
    if last_exc is not None:
        raise last_exc
