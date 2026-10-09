"""End-to-end tests of the integration inside a Home Assistant test instance."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.wms_webcontrol.const import DOMAIN
from custom_components.wms_webcontrol.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .fakebox import FakeBox, timer_block

# The options of the real 0.3.x installation (presets, exclusions).
OPTIONS_03X = {
    "update_interval": 600,
    "presets": [
        {"name": "Markise einfahren", "payload_hex": "0821000308ffffffff"},
        {"name": "Markise 60 %", "payload_hex": "0821000108ffffffff"},
        {"name": "Markise 100 %", "payload_hex": "0821000208ffffffff"},
    ],
    "device_classes": {},
    "invert": {},
    "exclude_channels": ["60% raus", "100 % raus", "Markise einfahren"],
}


async def _setup(hass: HomeAssistant, box: FakeBox, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="http://10.1.5.17",
        data={CONF_URL: "http://10.1.5.17"},
        options=OPTIONS_03X if options is None else options,
        entry_id="01TESTENTRY",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.wms_webcontrol.make_fetch", return_value=box.fetch
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    return entry


@pytest.fixture
def no_sleep():
    async def _sleep(_s):
        return None

    with patch("custom_components.wms_webcontrol.client.asyncio.sleep", _sleep), patch(
        "custom_components.wms_webcontrol.coordinator.asyncio.sleep", _sleep
    ):
        yield


async def test_setup_keeps_03x_unique_ids(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    unique_ids = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    # Same unique ids as 0.3.x -> existing entity ids survive the update.
    assert "01TESTENTRY_0_0" in unique_ids  # cover
    assert "01TESTENTRY_0_0_status" in unique_ids  # status sensor
    for payload in ("0821000108ffffffff", "0821000208ffffffff", "0821000308ffffffff"):
        assert f"01TESTENTRY_preset_{payload}" in unique_ids
    assert "01TESTENTRY_0_0_wink" in unique_ids
    # Scenes are not created as covers (the old exclusion list is not needed).
    assert not any(uid.startswith("01TESTENTRY_0_1") for uid in unique_ids)

    wink = hass.states.get(unique_ids["01TESTENTRY_0_0_wink"])
    assert wink.attributes["friendly_name"] == "WAREMA WMS WebControl Winken"

    cover = hass.states.get(unique_ids["01TESTENTRY_0_0"])
    assert cover.state == "closed"
    assert cover.attributes["device_class"] == "awning"
    # Preset names from the options win over the box's scene names.
    names = {
        hass.states.get(eid).attributes["friendly_name"]
        for uid, eid in unique_ids.items()
        if "_preset_" in uid
    }
    assert names == {
        "WAREMA WMS WebControl Markise einfahren",
        "WAREMA WMS WebControl Markise 60 %",
        "WAREMA WMS WebControl Markise 100 %",
    }


async def test_scene_without_preset_uses_box_name(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    await _setup(hass, box, options={"update_interval": 600})
    state = hass.states.get("button.warema_wms_webcontrol_60_raus")
    assert state is not None
    assert state.attributes["scene_index"] == 2


async def test_scene_button_confirmed(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_preset_0821000108ffffffff"
    )
    box.payloads.clear()
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    assert box.operations() == ["21000108ffffffff"]
    await hass.async_block_till_done()
    cover = hass.states.get("cover.warema_wms_webcontrol_markise")
    assert cover.attributes["current_position"] == 60


async def test_scene_rejected_once_is_resent(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_preset_0821000208ffffffff"
    )
    box.payloads.clear()
    box.reject_next_operations = 1  # like 2026-10-09 07:31:39
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    assert box.operations() == ["21000208ffffffff", "21000208ffffffff"]


async def test_scene_rejected_always_raises(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_preset_0821000308ffffffff"
    )
    box.reject_next_operations = 100
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )


async def test_cover_close_open_stop(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(position=120)
    await _setup(hass, box)
    box.payloads.clear()
    await hass.services.async_call(
        "cover", "close_cover", {"entity_id": "cover.warema_wms_webcontrol_markise"}, blocking=True
    )
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": "cover.warema_wms_webcontrol_markise", "position": 60},
        blocking=True,
    )
    await hass.services.async_call(
        "cover", "stop_cover", {"entity_id": "cover.warema_wms_webcontrol_markise"}, blocking=True
    )
    assert box.operations() == [
        "2100000300ffffff",  # close = HA 0 = raw 0 (awning not inverted)
        "2100000378ffffff",  # 60 % = raw 120
        "21000001ffffffff",  # stop
    ]


async def test_cover_move_never_raises_when_box_rejects(hass: HomeAssistant, no_sleep) -> None:
    """The wind/rain script must not abort because of a rejected move."""
    box = FakeBox(position=120)
    await _setup(hass, box)
    box.reject_next_operations = 100
    await hass.services.async_call(
        "cover", "close_cover", {"entity_id": "cover.warema_wms_webcontrol_markise"}, blocking=True
    )


async def test_unreachable_box_retries_setup(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(reachable=False)
    entry = await _setup(hass, box)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_poll_tolerance_then_unavailable(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    coordinator = entry.runtime_data
    box.reachable = False
    for _ in range(2):
        await coordinator.async_refresh()
        assert hass.states.get("cover.warema_wms_webcontrol_markise").state == "closed"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("cover.warema_wms_webcontrol_markise").state == "unavailable"
    box.reachable = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("cover.warema_wms_webcontrol_markise").state == "closed"


# --- 0.5.0: timer, clock, repair issue, diagnostics ---------------------------


def _entity(hass, entry, suffix):
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{suffix}")


async def test_timer_read_at_startup(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    state = hass.states.get(_entity(hass, entry, "0_0_next_switch"))
    assert state is not None
    when = dt_util.parse_datetime(state.state)
    local = dt_util.as_local(when)
    assert (local.hour, local.minute) == (18, 30)
    assert local > dt_util.now()
    assert (local - dt_util.now()) <= timedelta(days=1)
    assert state.attributes["timer_enabled"] is True
    assert state.attributes["next_position"] == 0
    assert state.attributes["plan"][0] == "Mo 18:30 → 0 %"
    assert len(state.attributes["plan"]) == 7


async def test_timer_disabled_has_no_value(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(timer=timer_block(enabled=0, entries=[(0, 0, 7, 0, 200, 1)]))
    entry = await _setup(hass, box)
    state = hass.states.get(_entity(hass, entry, "0_0_next_switch"))
    assert state.state == "unknown"
    assert state.attributes["timer_enabled"] is False


async def test_timer_read_retries_once(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(timer_failures=1)
    entry = await _setup(hass, box)
    state = hass.states.get(_entity(hass, entry, "0_0_next_switch"))
    assert state.state not in ("unknown", "unavailable")
    assert "last_error" not in state.attributes


async def test_timer_read_fails_twice_unavailable(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(timer_failures=2)
    entry = await _setup(hass, box)
    assert entry.state is ConfigEntryState.LOADED  # never blocks the setup
    assert hass.states.get(_entity(hass, entry, "0_0_next_switch")).state == "unavailable"
    box.timer_failures = 0
    button = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_read_timers")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert hass.states.get(_entity(hass, entry, "0_0_next_switch")).state != "unavailable"


async def test_clock_in_sync_is_not_written(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(clock_drift=20)
    entry = await _setup(hass, box)
    assert box.clock_writes() == []
    state = hass.states.get(_entity(hass, entry, "clock_offset"))
    assert 15 <= float(state.state) <= 25
    assert state.attributes["system_time_master"] is True


async def test_clock_drift_is_corrected_keeping_master_flag(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(clock_drift=-3600, time_master=0)  # e.g. DST not applied
    entry = await _setup(hass, box)
    writes = box.clock_writes()
    assert len(writes) == 1
    assert writes[0][2] == 0  # time-master flag passed through unchanged
    assert abs(box.clock_drift) < 5
    assert abs(float(hass.states.get(_entity(hass, entry, "clock_offset")).state)) < 5


async def test_clock_sync_option_off(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox(clock_drift=-3600)
    options = dict(OPTIONS_03X, clock_sync=False)
    entry = await _setup(hass, box, options=options)
    assert box.clock_writes() == []
    assert float(hass.states.get(_entity(hass, entry, "clock_offset")).state) < -3500
    button = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_set_clock")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert len(box.clock_writes()) == 1


async def test_daily_clock_check(hass: HomeAssistant, no_sleep, freezer) -> None:
    box = FakeBox()
    await _setup(hass, box)
    box.clock_drift = 300
    freezer.move_to(dt_util.now().replace(hour=3, minute=29, second=59) + timedelta(days=1))
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(box.clock_writes()) == 1


async def test_repair_issue_when_unreachable(hass: HomeAssistant, no_sleep, freezer) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    coordinator = entry.runtime_data
    issue_id = f"box_unreachable_{entry.entry_id}"
    box.reachable = False
    for _ in range(3):
        await coordinator.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    freezer.tick(timedelta(minutes=16))
    await coordinator.async_refresh()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_key == "box_unreachable"
    box.reachable = True
    await coordinator.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_diagnostics(hass: HomeAssistant, no_sleep) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["url"] == "**REDACTED**"
    assert diag["products"][0]["name"] == "Markise"
    assert len(diag["scenes"]) == 3
    assert diag["timers"]["0_0"]["enabled"] is True
    assert len(diag["timers"]["0_0"]["raw"]) == 199
    assert diag["clock"]["system_time_master"] is True
