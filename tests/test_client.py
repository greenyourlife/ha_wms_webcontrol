"""Tests for the async protocol client against a scripted fake box."""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys

import pytest

_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "wms_webcontrol"
    / "client.py"
)
_spec = importlib.util.spec_from_file_location("wms_client", _PATH)
client_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["wms_client"] = client_mod
_spec.loader.exec_module(client_mod)

WmsClient = client_mod.WmsClient


def run(coro):
    return asyncio.run(coro)


def xml(body: str) -> str:
    return f"<?xml version='1.0' encoding='utf-8'?><response>{body}</response>"


BUSY_OK = xml("<responseID>51</responseID><requestid>33</requestid><feedback>1</feedback>")
BUSY_NO = xml("<responseID>51</responseID><requestid>33</requestid><feedback>0</feedback>")
PENDING = xml("<responseID>50</responseID><befehl>0</befehl><feedback>0</feedback>")
DONE = xml("<responseID>34</responseID><raumindex>0</raumindex><kanalindex>0</kanalindex><feedback>0</feedback>")


class FakeBox:
    """Answers from a queue (or a callable) and records every frame sent."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.frames: list[str] = []

    async def fetch(self, query: str) -> str:
        frame = query.split("protocol=", 1)[1].split("&", 1)[0]
        self.frames.append(frame)
        answer = self.answers.pop(0)
        return answer(frame) if callable(answer) else answer


async def no_sleep(_s):
    return None


def make(box, **kwargs):
    return WmsClient(box.fetch, sleep=no_sleep, **kwargs)


# --- framing / counter ------------------------------------------------------


def test_counter_matches_official_ui():
    c = make(FakeBox([]))
    values = [c._next_counter() for _ in range(258)]
    assert values[:3] == [0, 1, 2]
    assert values[254] == 254
    assert values[255:] == [1, 2, 3]
    assert 255 not in values


def test_frame_has_header_counter_and_length():
    c = make(FakeBox([]))
    assert c.frame(bytes((0x23, 0, 0))) == "9000032300" + "00"
    assert c.frame(bytes((0x47, 0, 1))) == "9001034700" + "01"


@pytest.mark.parametrize(
    "payload",
    [
        bytes((0x13, 0, 1)),  # KANAL_LOESCHEN
        bytes((0x09, 0)),  # RAUM_LOESCHEN
        bytes((0x1D, 0)),  # INFRASTRUKTUR_LADEN
        bytes((0x0F, 0, 1, 65)),  # KANALNAMEN_AENDERN
        bytes((0x45, 0, 4, 3, 65)),  # SZENE_ANLEGEN (not in 0.4)
        bytes((0x21, 0, 1, 9, 255, 255, 255, 255)),  # FC 9 = scene learn
        bytes((0x21, 0, 1, 7, 0, 0, 0, 0)),  # FC 7 not allow-listed
    ],
)
def test_forbidden_telegrams_are_never_sent(payload):
    box = FakeBox([BUSY_OK])
    c = make(box)
    with pytest.raises(client_mod.WmsForbiddenTelegram):
        run(c.send_payload(payload))
    assert box.frames == []


def test_legacy_payload_parsing():
    assert client_mod.parse_legacy_payload("0821000308ffffffff") == bytes.fromhex(
        "21000308ffffffff"
    )
    assert client_mod.legacy_scene_payload(0, 3) == "0821000308ffffffff"
    with pytest.raises(ValueError):
        client_mod.parse_legacy_payload("0921000308ffffffff")


# --- command / busy ---------------------------------------------------------


def test_busy_answer_is_resent():
    box = FakeBox([BUSY_NO, BUSY_NO, BUSY_OK])
    c = make(box)
    resp = run(c.send_payload(bytes((0x21, 0, 3, 8, 255, 255, 255, 255))))
    assert client_mod.response_id(resp) == 51
    assert len(box.frames) == 3
    # same telegram, fresh counter each time
    assert [f[4:] for f in box.frames] == [box.frames[0][4:]] * 3
    assert len({f[2:4] for f in box.frames}) == 3


def test_busy_forever_raises():
    box = FakeBox([BUSY_NO] * 5)
    with pytest.raises(client_mod.WmsBusyError):
        run(make(box).send_payload(bytes((0x23, 0, 0))))


def test_error_message_raises():
    err = xml("<responseID>52</responseID><requestid>49</requestid><errorcode>8</errorcode>")
    with pytest.raises(client_mod.WmsErrorResponse) as info:
        run(make(FakeBox([err])).send_payload(bytes((0x23, 0, 0))))
    assert info.value.errorcode == 8


def test_invalid_xml_is_connection_error():
    with pytest.raises(client_mod.WmsConnectionError):
        run(make(FakeBox(["<html>nope"])).send_payload(bytes((0x23, 0, 0))))


# --- operations -------------------------------------------------------------


def test_operate_confirmed_after_pending_polls():
    box = FakeBox([BUSY_OK, PENDING, PENDING, DONE])
    result = run(make(box).run_scene(0, 1))
    assert result.confirmed is True
    assert box.frames[0][6:] == "21000108ffffffff"
    assert all(f[6:] == "31000100" for f in box.frames[1:])


def test_operate_poll_error_is_not_confirmed():
    failed = xml("<responseID>50</responseID><befehl>0</befehl><feedback>2</feedback>")
    result = run(make(FakeBox([BUSY_OK, PENDING, failed])).stop(0, 0))
    assert result.confirmed is False
    assert result.feedback == 2


def test_operate_unknown_when_poll_not_supported():
    err32 = xml("<responseID>52</responseID><requestid>49</requestid><errorcode>32</errorcode>")
    result = run(make(FakeBox([BUSY_OK, err32])).run_scene(0, 1))
    assert result.confirmed is None


def test_operate_timeout_is_unknown():
    box = FakeBox([BUSY_OK] + [PENDING] * 30)
    result = run(make(box, poll_timeout=2.0, poll_interval=0.5).run_scene(0, 1))
    assert result.confirmed is None


def test_move_encodes_raw_position():
    box = FakeBox([BUSY_OK, DONE])
    run(make(box).move(0, 0, 120))
    assert box.frames[0][6:] == "2100000378ffffff"
    with pytest.raises(ValueError):
        run(make(FakeBox([])).move(0, 0, 201))


def test_read_state():
    state_xml = xml(
        "<responseID>36</responseID><fahrt>1</fahrt><position>113</position>"
        "<winkel>255</winkel><positionvolant1>255</positionvolant1>"
        "<positionvolant2>255</positionvolant2>"
    )
    busy_poll = xml("<responseID>50</responseID><befehl>1</befehl><feedback>0</feedback>")
    box = FakeBox([BUSY_OK, busy_poll, state_xml])
    state = run(make(box).read_state(0, 0))
    assert state.position == 113 and state.moving is True
    assert state.angle is None and state.volant1 is None
    assert box.frames[0][6:] == "230000"
    assert box.frames[1][6:] == "31000001"


# --- discovery --------------------------------------------------------------


def _discovery_answer(rooms, channels):
    def answer(frame: str) -> str:
        payload = bytes.fromhex(frame[6:])
        if payload[0] == 0x03:
            name = rooms.get(payload[1], "")
            return xml(f"<responseID>4</responseID><raumname>{name}</raumname>")
        info = channels.get((payload[1], payload[2]))
        if info is None:
            return xml("<responseID>72</responseID><kanalname></kanalname>")
        name, scene, ptype, otype = info
        return xml(
            f"<responseID>72</responseID><kanalname>{name}</kanalname>"
            f"<szeneindex>{scene}</szeneindex><produkttyp>{ptype}</produkttyp>"
            f"<bedientyp>{otype}</bedientyp>"
        )

    return answer


def test_discover_products_scenes_and_gaps():
    rooms = {0: "Balkon", 2: "Garten"}  # room 1 is a gap
    channels = {
        (0, 0): ("Markise", 255, 3, 4),
        (0, 1): ("60% raus", 2, 255, 255),
        (0, 3): ("Markise einfahren", 1, 255, 255),  # channel 2 is a gap
        (2, 0): ("Rollo", 255, 2, 3),
    }
    answer = _discovery_answer(rooms, channels)
    box = FakeBox([answer] * 200)
    found = run(make(box).discover())
    assert [(c.key, c.name, c.is_scene) for c in found] == [
        ("0_0", "Markise", False),
        ("0_1", "60% raus", True),
        ("0_3", "Markise einfahren", True),
        ("2_0", "Rollo", False),
    ]
    markise = found[0]
    assert markise.product_type == 3 and markise.operation_type == 4
    assert found[1].product_type is None  # 255 -> None
    assert found[1].scene_index == 2
