"""Constants for the WAREMA WMS WebControl integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "wms_webcontrol"

LOGGER: Final = logging.getLogger(__package__)

# Config / options keys
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_PRESETS: Final = "presets"
CONF_DEVICE_CLASSES: Final = "device_classes"

# Preset dict keys
PRESET_NAME: Final = "name"
PRESET_PAYLOAD: Final = "payload_hex"

# Defaults
DEFAULT_URL: Final = "http://webcontrol.local"
DEFAULT_UPDATE_INTERVAL: Final = 600  # seconds
MIN_UPDATE_INTERVAL: Final = 30  # seconds

# The WebControl server rejects commands that arrive too quickly after each
# other, so the library needs a wait time between the "check ready" request and
# the actual command. 0.5s has proven reliable over the local network.
TIME_BETWEEN_CMDS: Final = 0.5
NUM_RETRIES: Final = 3

# After a move the box keeps reporting "not moving" for a short while, so poll
# more often for a couple of seconds to catch the shade settling on its target.
FAST_UPDATE_INTERVAL: Final = 5  # seconds
FAST_UPDATE_DURATION: Final = 15  # seconds

# Prefilled scene recalls captured by the user. These are verbatim protocol
# payloads (format ``0821 + 00 + <idx> + 08ffffffff``) WITHOUT the variable
# ``90<counter>`` prefix, which the library prepends automatically.
DEFAULT_PRESETS: Final[list[dict[str, str]]] = [
    {PRESET_NAME: "Markise einfahren", PRESET_PAYLOAD: "0821000308ffffffff"},
    {PRESET_NAME: "Markise 60 %", PRESET_PAYLOAD: "0821000108ffffffff"},
    {PRESET_NAME: "Markise 100 %", PRESET_PAYLOAD: "0821000208ffffffff"},
]
