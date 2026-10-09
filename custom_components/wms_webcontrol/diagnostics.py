"""Diagnostics for WAREMA WMS WebControl."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from .coordinator import WmsConfigEntry

TO_REDACT = {CONF_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WmsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "products": [asdict(channel) for channel in coordinator.products],
        "scenes": [asdict(channel) for channel in coordinator.scenes],
        "state": {
            key: asdict(info) for key, info in (coordinator.data or {}).items()
        },
        "last_update_success": coordinator.last_update_success,
        "timers": {
            key: {
                "enabled": plan.enabled,
                "entries": [asdict(e) for e in plan.entries],
                "raw": list(plan.raw),
            }
            for key, plan in coordinator.timers.items()
        },
        "timer_errors": coordinator.timer_errors,
        "timers_read_at": coordinator.timers_read_at,
        "clock": None if coordinator.clock is None else asdict(coordinator.clock),
        "clock_offset": coordinator.clock_offset,
        "clock_set_at": coordinator.clock_set_at,
    }
