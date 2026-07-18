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


class _FakeController:
    """Records the calls a preset press makes on the controller."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def send_rx_check_ready(self):
        self.calls.append(("check_ready", None))

    def _send_command(self, cmd, additional_str=""):
        self.calls.append(("send_command", cmd))


def test_send_raw_replays_payload_verbatim():
    controller = _FakeController()
    helpers.send_raw(controller, "0821000308ffffffff", sleep=lambda _s: None)
    # check-ready precedes the raw command, and the payload is sent verbatim.
    assert controller.calls == [
        ("check_ready", None),
        ("send_command", "0821000308ffffffff"),
    ]


def test_send_raw_retries_then_raises():
    class _Boom:
        def __init__(self):
            self.attempts = 0

        def send_rx_check_ready(self):
            pass

        def _send_command(self, cmd, additional_str=""):
            self.attempts += 1
            raise ConnectionError("boom")

    boom = _Boom()
    with pytest.raises(ConnectionError):
        helpers.send_raw(
            boom,
            "0821000308ffffffff",
            retries=3,
            sleep=lambda _s: None,
            exceptions=(ConnectionError,),
        )
    assert boom.attempts == 3
