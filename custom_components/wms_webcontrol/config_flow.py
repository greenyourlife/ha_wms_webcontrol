"""Config and options flow for WAREMA WMS WebControl."""

from __future__ import annotations

from typing import Any

import requests
import voluptuous as vol
from warema_wms import WmsController

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import helpers
from .const import (
    CONF_DEVICE_CLASSES,
    CONF_PRESETS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PRESETS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
)
from .coordinator import WmsConfigEntry

_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=MIN_UPDATE_INTERVAL, max=86400, step=1, mode=NumberSelectorMode.BOX)
)
_MULTILINE_TEXT = TextSelector(
    TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
)


def _validate_connection(url: str) -> None:
    """Blocking connection test via auto-discovery. Runs in the executor."""
    WmsController(url)


class WmsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial UI-based setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step: URL + update interval, with a connection test."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            try:
                await self.hass.async_add_executor_job(_validate_connection, url)
            except (requests.RequestException, OSError, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface unexpected failures gently
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=url,
                    data={CONF_URL: url},
                    options={
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                        CONF_PRESETS: DEFAULT_PRESETS,
                        CONF_DEVICE_CLASSES: {},
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_URL,
                    default=(user_input or {}).get(CONF_URL, DEFAULT_URL),
                ): str,
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=(user_input or {}).get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): _INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: WmsConfigEntry) -> WmsOptionsFlow:
        """Return the options flow handler."""
        return WmsOptionsFlow()


class WmsOptionsFlow(OptionsFlow):
    """Edit update interval, presets and device-class overrides."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            presets = helpers.parse_presets_text(user_input.get(CONF_PRESETS, ""))
            invalid = [
                preset
                for preset in presets
                if not preset["name"] or not helpers.is_valid_payload(preset["payload_hex"])
            ]
            if invalid:
                errors[CONF_PRESETS] = "invalid_preset"
            else:
                return self.async_create_entry(
                    data={
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                        CONF_PRESETS: presets,
                        CONF_DEVICE_CLASSES: helpers.parse_device_classes_text(
                            user_input.get(CONF_DEVICE_CLASSES, "")
                        ),
                    },
                )

        presets_default = helpers.format_presets_text(
            options.get(CONF_PRESETS, DEFAULT_PRESETS)
        )
        device_classes_default = helpers.format_device_classes_text(
            options.get(CONF_DEVICE_CLASSES, {})
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): _INTERVAL_SELECTOR,
                vol.Optional(
                    CONF_PRESETS, default=presets_default
                ): _MULTILINE_TEXT,
                vol.Optional(
                    CONF_DEVICE_CLASSES, default=device_classes_default
                ): _MULTILINE_TEXT,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
