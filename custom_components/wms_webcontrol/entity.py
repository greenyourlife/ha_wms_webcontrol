"""Shared entity helpers for WAREMA WMS WebControl."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def hub_device_info(entry: ConfigEntry, url: str) -> DeviceInfo:
    """Device info of the WebControl box (same identifiers as 0.3.x)."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="WAREMA WMS WebControl",
        manufacturer="WAREMA",
        model="WMS WebControl",
        configuration_url=url,
    )
