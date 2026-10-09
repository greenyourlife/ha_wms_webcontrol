"""Unit tests for the framework-free helpers.

These tests import ``helpers.py`` directly (not through the Home Assistant
package) so they run on a plain Python interpreter without Home Assistant
installed. The library ``warema-wms`` is not needed either; a lightweight fake
controller stands in for the raw-send test.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_HELPERS_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "wms_webcontrol"
    / "helpers.py"
)
_spec = importlib.util.spec_from_file_location("wms_helpers", _HELPERS_PATH)
helpers = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(helpers)


# --- Position inversion -----------------------------------------------------


@pytest.mark.parametrize(
    ("lib_position", "expected_ha"),
    [
        (0, 100),  # library open  -> HA fully open
        (100, 0),  # library closed -> HA closed
        (30, 70),
        (75, 25),
        (50.0, 50),  # library returns floats (raw/2)
    ],
)
def test_invert_position(lib_position, expected_ha):
    assert helpers.invert_position(lib_position) == expected_ha


@pytest.mark.parametrize("ha_position", [0, 25, 50, 100])
def test_inversion_round_trips(ha_position):
    lib = helpers.to_lib_position(ha_position)
    assert helpers.invert_position(lib) == ha_position


# --- Configurable inversion (shutters vs awnings) --------------------------


@pytest.mark.parametrize(
    ("lib", "invert", "expected_ha"),
    [
        (0, True, 100),   # shutter: library open -> HA open
        (100, True, 0),   # shutter: library closed -> HA closed
        (0, False, 0),    # awning: library 0 (retracted) -> HA 0 (closed)
        (100, False, 100),  # awning: library 100 (extended) -> HA 100 (open)
    ],
)
def test_ha_from_lib(lib, invert, expected_ha):
    assert helpers.ha_from_lib(lib, invert) == expected_ha


@pytest.mark.parametrize(
    ("ha", "invert", "expected_lib"),
    [
        (100, True, 0),   # shutter open -> library 0
        (0, True, 100),   # shutter closed -> library 100
        (100, False, 100),  # awning open/extended -> library 100
        (0, False, 0),    # awning closed/retracted -> library 0
    ],
)
def test_lib_from_ha(ha, invert, expected_lib):
    assert helpers.lib_from_ha(ha, invert) == expected_lib


def test_resolve_invert_defaults():
    # Awnings are NOT inverted (HA 0 % = eingefahren = library 0); others are.
    assert helpers.resolve_invert("Markise", "awning", {}) is False
    assert helpers.resolve_invert("Rollo", "shutter", {}) is True


def test_resolve_invert_override_wins():
    assert helpers.resolve_invert("Markise", "awning", {"markise": True}) is True
    assert helpers.resolve_invert("Rollo", "shutter", {"rollo": False}) is False


def test_resolved_device_class():
    assert helpers.resolved_device_class("Markise Terrasse", {}) == "awning"
    assert helpers.resolved_device_class("Rollo", {}) == "shutter"
    # Valid override wins; invalid override falls back to the heuristic.
    valid = {"awning", "shutter", "blind"}
    assert helpers.resolved_device_class("Rollo", {"rollo": "awning"}, valid) == "awning"
    assert helpers.resolved_device_class("Rollo", {"rollo": "bogus"}, valid) == "shutter"


# --- Awning status wording --------------------------------------------------


# awning_state works in HA space (shared with the cover): HA 0 = eingefahren,
# HA 100 = ausgefahren.
@pytest.mark.parametrize(
    ("ha_position", "is_moving", "target_ha", "expected"),
    [
        (0, False, None, "retracted"),      # HA 0 -> eingefahren
        (100, False, None, "extended"),     # HA 100 -> ausgefahren
        (40, False, None, "partial"),       # in between
        (30, True, 100, "extending"),       # moving towards HA 100 -> fährt aus
        (80, True, 0, "retracting"),        # moving towards HA 0 -> fährt ein
        (None, False, None, None),          # unknown position
    ],
)
def test_awning_state(ha_position, is_moving, target_ha, expected):
    assert helpers.awning_state(ha_position, is_moving, target_ha) == expected


# --- Boolean override parsing ----------------------------------------------


def test_parse_bool_map():
    text = "Markise = false\nRollo = true\nGarage = ja\nJunk line"
    assert helpers.parse_bool_map(text) == {
        "markise": False,
        "rollo": True,
        "garage": True,
    }


def test_format_bool_map_roundtrips():
    mapping = {"markise": False, "rollo": True}
    assert helpers.parse_bool_map(helpers.format_bool_map(mapping)) == mapping


# --- Channel exclusion ------------------------------------------------------


def test_parse_lines():
    text = "60% raus\n  100 % raus  \n\nMarkise einfahren\n"
    assert helpers.parse_lines(text) == ["60% raus", "100 % raus", "Markise einfahren"]


@pytest.mark.parametrize(
    ("channel", "excluded", "expected"),
    [
        ("60% raus", ["60% raus", "100 % raus"], True),
        ("100 % raus", ["60% raus", "100 % raus"], True),
        ("Markise", ["60% raus", "100 % raus"], False),
        ("markise", ["Markise"], True),  # case-insensitive
        ("60% raus", ["60 % raus"], True),  # whitespace-insensitive
        ("Markise", [], False),
    ],
)
def test_is_excluded(channel, excluded, expected):
    assert helpers.is_excluded(channel, excluded) is expected


# --- Movement / state derivation -------------------------------------------


def test_not_moving_yields_no_direction():
    assert helpers.derive_movement(False, 100, 30) == (False, False)


def test_moving_towards_open_is_opening():
    # target HA 100 (open) is above current HA 30 -> opening
    assert helpers.derive_movement(True, 100, 30) == (True, False)


def test_moving_towards_closed_is_closing():
    # target HA 0 (closed) is below current HA 80 -> closing
    assert helpers.derive_movement(True, 0, 80) == (False, True)


def test_moving_without_target_is_unknown():
    assert helpers.derive_movement(True, None, 40) == (False, False)


def test_is_closed_derived_from_inverted_position():
    # Library position 100 (closed) inverts to HA 0 -> closed
    assert helpers.invert_position(100) == 0
    # Library position 0 (open) inverts to HA 100 -> not closed
    assert helpers.invert_position(0) == 100


# --- Device class heuristic -------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Markise Terrasse", "awning"),
        ("Awning South", "awning"),
        ("Sonnenschutz", "awning"),
        ("Rollo Küche", "shutter"),
        ("Wohnzimmer", "shutter"),
    ],
)
def test_guess_device_class(name, expected):
    assert helpers.guess_device_class(name) == expected


# --- Preset parsing ---------------------------------------------------------


def test_parse_presets_text_roundtrip():
    text = "Markise einfahren | 0821000308ffffffff\nMarkise 60 % | 0821000108ffffffff"
    presets = helpers.parse_presets_text(text)
    assert presets == [
        {"name": "Markise einfahren", "payload_hex": "0821000308ffffffff"},
        {"name": "Markise 60 %", "payload_hex": "0821000108ffffffff"},
    ]
    assert all(helpers.is_valid_payload(p["payload_hex"]) for p in presets)


def test_parse_presets_missing_separator_is_invalid():
    presets = helpers.parse_presets_text("Just a name without payload")
    assert presets == [{"name": "Just a name without payload", "payload_hex": ""}]
    assert not helpers.is_valid_payload(presets[0]["payload_hex"])


@pytest.mark.parametrize(
    ("payload", "valid"),
    [
        ("0821000308ffffffff", True),
        ("", False),
        ("821", False),  # odd length
        ("zz21", False),  # non-hex
    ],
)
def test_is_valid_payload(payload, valid):
    assert helpers.is_valid_payload(payload) is valid


def test_parse_device_classes_text():
    text = "Markise Terrasse = awning\nRollo Küche = shutter"
    assert helpers.parse_device_classes_text(text) == {
        "markise terrasse": "awning",
        "rollo küche": "shutter",
    }


# --- Raw preset send --------------------------------------------------------

import xml.etree.ElementTree as ET  # noqa: E402


def _xml(body: str):
    return ET.fromstring(f"<response>{body}</response>")


READY = "<feedback>1</feedback>"
BUSY = "<feedback>0</feedback>"
ACK = "<requestid>33</requestid><feedback>1</feedback>"
NACK = "<requestid>33</requestid><feedback>0</feedback>"
ERR32 = "<requestid>49</requestid><errorcode>32</errorcode>"


class _ScriptedController:
    """Fake box answering check-ready / command / state from scripted queues."""

    def __init__(self, ready=(), command=(), state=()):
        self._ready = list(ready)
        self._command = list(command)
        self._state = list(state)
        self.calls: list[str] = []

    def send_rx_check_ready(self, room_id=0, channel_id=0):
        self.calls.append("check_ready")
        return _xml(self._ready.pop(0) if self._ready else READY)

    def _send_command(self, cmd, additional_str=""):
        self.calls.append(f"cmd:{cmd}")
        return _xml(self._command.pop(0) if self._command else ACK)

    def send_rx_shade_state(self, room_id, channel_id):
        self.calls.append("state")
        return _xml(self._state.pop(0))


def _no_sleep(_s):
    return None


def test_send_raw_replays_payload_verbatim():
    controller = _ScriptedController()
    helpers.send_raw(controller, "0821000308ffffffff", sleep=_no_sleep)
    assert controller.calls == ["check_ready", "cmd:0821000308ffffffff"]


def test_send_raw_waits_until_box_is_ready():
    """The command must not be sent while the box reports feedback=0 (busy)."""
    controller = _ScriptedController(ready=[BUSY, BUSY, READY])
    helpers.send_raw(controller, "0821000308ffffffff", sleep=_no_sleep)
    assert controller.calls == [
        "check_ready",
        "check_ready",
        "check_ready",
        "cmd:0821000308ffffffff",
    ]


def test_send_raw_does_not_send_while_box_stays_busy():
    """Regression: 0.3.1 sent the command anyway after the ready polls ran out."""
    controller = _ScriptedController(ready=[BUSY] * 9)
    with pytest.raises(helpers.WmsCommandError, match="busy"):
        helpers.send_raw(controller, "0821000308ffffffff", retries=3, sleep=_no_sleep)
    assert not any(call.startswith("cmd:") for call in controller.calls)


def test_send_raw_resends_when_box_rejects_command():
    controller = _ScriptedController(command=[NACK, ACK])
    helpers.send_raw(controller, "0821000308ffffffff", sleep=_no_sleep)
    assert controller.calls.count("cmd:0821000308ffffffff") == 2


def test_send_raw_ready_then_rejected_is_resent():
    """Real trace 2026-10-09 07:31:39: ready=1, command feedback=0, box busy."""
    controller = _ScriptedController(
        ready=[READY, BUSY, BUSY, BUSY, READY],
        command=[NACK, ACK],
    )
    pauses: list[float] = []
    helpers.send_raw(
        controller,
        "0821000108ffffffff",
        retries=5,
        wait=0.5,
        retry_wait=1.0,
        sleep=pauses.append,
    )
    assert controller.calls.count("cmd:0821000108ffffffff") == 2
    assert 1.0 in pauses  # generous pause after the rejection


def test_send_raw_raises_when_box_always_rejects():
    controller = _ScriptedController(command=[ERR32] * 3)
    with pytest.raises(helpers.WmsCommandError, match="errorcode 32"):
        helpers.send_raw(controller, "0821000308ffffffff", retries=3, sleep=_no_sleep)


def test_send_raw_retries_then_raises_transport_error():
    class _Boom(_ScriptedController):
        def _send_command(self, cmd, additional_str=""):
            self.calls.append("cmd")
            raise ConnectionError("boom")

    boom = _Boom()
    with pytest.raises(ConnectionError):
        helpers.send_raw(
            boom,
            "0821000308ffffffff",
            retries=3,
            sleep=_no_sleep,
            exceptions=(ConnectionError,),
        )
    assert boom.calls.count("cmd") == 3


# --- Response / state parsing ----------------------------------------------


@pytest.mark.parametrize(
    ("body", "ok"),
    [(READY, True), (BUSY, False), (ACK, True), (NACK, False), (ERR32, False)],
)
def test_response_ok(body, ok):
    assert helpers.response_ok(_xml(body)) is ok


def test_response_ok_none_is_not_ok():
    assert helpers.response_ok(None) is False


def test_parse_shade_state():
    resp = _xml("<fahrt>1</fahrt><position>120</position>")
    assert helpers.parse_shade_state(resp) == (60.0, True)


@pytest.mark.parametrize("body", [ERR32, "<fahrt>0</fahrt>", "<position>x</position><fahrt>0</fahrt>"])
def test_parse_shade_state_invalid(body):
    assert helpers.parse_shade_state(_xml(body)) is None


def test_read_state_retries_errorcode_instead_of_keeping_stale_value():
    """Regression: the library logged 'Invalid response' and kept the old state."""
    controller = _ScriptedController(
        state=[ERR32, "<fahrt>0</fahrt><position>0</position>"]
    )
    assert helpers.read_state(controller, 0, 0, sleep=_no_sleep) == (0.0, False)
    assert controller.calls.count("state") == 2


def test_read_state_raises_after_tries():
    controller = _ScriptedController(state=[ERR32] * 3)
    with pytest.raises(helpers.WmsCommandError, match="errorcode 32"):
        helpers.read_state(controller, 0, 0, tries=3, sleep=_no_sleep)


# --- Movement verification --------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ((0.0, False), (0.0, True), True),  # reports moving
        ((0.0, False), (5.0, False), True),  # position changed
        ((0.0, False), (0.5, False), False),  # below threshold
        ((0.0, False), (0.0, False), False),  # nothing happened
        (None, (0.0, True), True),  # no snapshot, but moving
        (None, (30.0, False), False),  # no snapshot, no movement flag
    ],
)
def test_movement_detected(before, after, expected):
    assert helpers.movement_detected(before, after) is expected
