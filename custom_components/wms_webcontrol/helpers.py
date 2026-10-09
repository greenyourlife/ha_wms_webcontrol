"""Pure, framework-free helpers for the WAREMA WMS WebControl integration.

This module deliberately imports nothing from Home Assistant so the core logic
(position inversion, movement derivation, preset parsing, raw sending) can be
unit-tested on a plain Python interpreter with a mocked controller.
"""

from __future__ import annotations

from typing import Optional


def invert_position(lib_position: float) -> int:
    """Convert a library position to a Home Assistant cover position.

    The library uses ``0 = open`` / ``100 = closed`` while Home Assistant uses
    ``0 = closed`` / ``100 = open``. Hence the value is inverted.
    """
    return 100 - int(round(lib_position))


def to_lib_position(ha_position: int) -> int:
    """Convert a Home Assistant cover position back to a library position."""
    return 100 - int(round(ha_position))


def ha_from_lib(lib_position: float, invert: bool) -> int:
    """Map a library position to a Home Assistant position.

    ``invert=True`` (shutters/blinds): HA ``100 = open`` = library ``0``.
    ``invert=False`` (awnings): HA follows the library value directly, so
    HA ``0 = closed`` corresponds to a retracted awning (library ``0``).
    """
    if invert:
        return 100 - int(round(lib_position))
    return int(round(lib_position))


def lib_from_ha(ha_position: int, invert: bool) -> int:
    """Map a Home Assistant position back to a library position."""
    if invert:
        return 100 - int(round(ha_position))
    return int(round(ha_position))


def resolved_device_class(
    channel_name: str,
    override: dict[str, str],
    valid: Optional[set] = None,
) -> str:
    """Resolve a channel's device class string (override or name heuristic)."""
    value = (override or {}).get((channel_name or "").lower())
    if value and (valid is None or value in valid):
        return value
    return guess_device_class(channel_name)


def resolve_invert(channel_name: str, device_class: str, override: dict[str, bool]) -> bool:
    """Decide whether a channel's position should be inverted.

    Shutters/blinds are inverted (library ``0 = open`` vs HA ``100 = open``).
    Awnings are NOT inverted: the box reports a retracted awning as library ``0``,
    which we map straight through to HA ``0 %`` = „eingefahren" = closed (and
    HA ``100 %`` = fully extended). Per-channel overrides win for the rare device
    that reports the other way round.
    """
    key = (channel_name or "").lower()
    if key in (override or {}):
        return override[key]
    return device_class != "awning"


def awning_state(
    ha_position: Optional[int],
    is_moving: bool,
    target_ha: Optional[int],
) -> Optional[str]:
    """Map an awning's HA position/movement to a status option key.

    In HA space (as anchored by the cover): ``extended`` = ausgefahren (HA 100),
    ``retracted`` = eingefahren (HA 0). Since the sensor and the cover share the
    same inversion, the wording stays consistent with the cover state.
    """
    if is_moving and target_ha is not None and ha_position is not None:
        if target_ha > ha_position:
            return "extending"
        if target_ha < ha_position:
            return "retracting"
    if ha_position is None:
        return None
    if ha_position >= 100:
        return "extended"
    if ha_position <= 0:
        return "retracted"
    return "partial"


def _parse_bool(value: str) -> Optional[bool]:
    """Parse a human-written boolean; returns None if unrecognised."""
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes", "ja", "on", "invert"):
        return True
    if lowered in ("false", "0", "no", "nein", "off"):
        return False
    return None


def parse_bool_map(text: str) -> dict[str, bool]:
    """Parse ``channel name = true/false`` lines into a lookup dict."""
    result: dict[str, bool] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        parsed = _parse_bool(value)
        if key and parsed is not None:
            result[key] = parsed
    return result


def format_bool_map(mapping: dict[str, bool]) -> str:
    """Render a boolean override mapping back into the options text."""
    return "\n".join(f"{key} = {str(value).lower()}" for key, value in mapping.items())


def parse_lines(text: str) -> list[str]:
    """Parse a multiline text into a list of trimmed, non-empty lines."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _normalize_channel(name: str) -> str:
    """Normalise a channel name for matching: drop all whitespace, lower-case."""
    return "".join((name or "").split()).lower()


def is_excluded(channel_name: str, excluded: list[str]) -> bool:
    """Return whether a channel name is in the exclude list.

    Matching ignores case and whitespace, so ``60% raus`` and ``60 % raus`` are
    treated the same.
    """
    target = _normalize_channel(channel_name)
    return target in {_normalize_channel(entry) for entry in (excluded or [])}


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


# --- Product types (``produkttyp`` reported by the box) ---------------------

# Mapping from the box's product type to a Home Assistant cover device class
# string. Taken from the box's web interface (TYPE_* constants).
PRODUCT_DEVICE_CLASS: dict[int, str] = {
    0: "blind",  # Raffstore
    1: "blind",  # Jalousie innen
    2: "shutter",  # Rollladen
    3: "awning",  # Markise
    4: "awning",  # Markise 1 Volant
    5: "awning",  # Markise int. Wind
    6: "awning",  # Markise 1 Volant int. Wind
    7: "awning",  # Wintergarten-Markise
    8: "awning",  # Fassadenmarkise
    9: "awning",  # Fallarmmarkise
    10: "awning",  # Senkrechtmarkise
    11: "awning",  # Markisolette
    12: "shade",  # Faltstore innen
    13: "shade",  # Rollo innen
    14: "blind",  # Vertikal-Jalousie innen
    15: "window",  # Fenster
    21: "shade",  # Volant
    22: "awning",  # Markise 2 Volant
    23: "awning",  # Markise 2 Volant int. Wind
    24: "shade",  # Sonnensegel
    25: "awning",  # Pergolamarkise
}

# Product types with one or two separately movable valances (Volant).
VOLANT_PARTS: dict[int, tuple[str, ...]] = {
    4: ("volant1",),
    6: ("volant1",),
    22: ("volant1", "volant2"),
    23: ("volant1", "volant2"),
}

# Product types with tiltable slats.
TILT_TYPES = frozenset({0, 1, 14})


def is_cover_type(product_type: int | None) -> bool:
    """Return whether a product type is a cover (lights/loads are not, yet)."""
    return product_type is None or product_type in PRODUCT_DEVICE_CLASS


def device_class_for(
    channel_name: str,
    product_type: int | None,
    override: dict[str, str],
    valid: Optional[set] = None,
) -> str:
    """Resolve a cover device class: option override, box type, then name guess."""
    value = (override or {}).get((channel_name or "").lower())
    if value and (valid is None or value in valid):
        return value
    if product_type in PRODUCT_DEVICE_CLASS:
        return PRODUCT_DEVICE_CLASS[product_type]
    return guess_device_class(channel_name)


def movement_detected(
    before: Optional[tuple[float, bool]],
    after: tuple[float, bool],
    min_delta: float = 1.0,
) -> bool:
    """Return whether a shade reacted to a command.

    True if the shade reports movement, or its position changed by at least
    ``min_delta`` percent compared to the snapshot taken before the command.
    """
    _, moving = after
    if moving:
        return True
    if before is None:
        return False
    return abs(after[0] - before[0]) >= min_delta
