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
CONF_INVERT: Final = "invert"
CONF_EXCLUDE_CHANNELS: Final = "exclude_channels"
CONF_CLOCK_SYNC: Final = "clock_sync"

# Awning status sensor option keys (translated in strings.json).
AWNING_STATE_RETRACTED: Final = "retracted"
AWNING_STATE_EXTENDED: Final = "extended"
AWNING_STATE_RETRACTING: Final = "retracting"
AWNING_STATE_EXTENDING: Final = "extending"
AWNING_STATE_PARTIAL: Final = "partial"
AWNING_STATES: Final = [
    AWNING_STATE_RETRACTED,
    AWNING_STATE_EXTENDED,
    AWNING_STATE_RETRACTING,
    AWNING_STATE_EXTENDING,
    AWNING_STATE_PARTIAL,
]

# Preset dict keys
PRESET_NAME: Final = "name"
PRESET_PAYLOAD: Final = "payload_hex"

# Defaults
DEFAULT_URL: Final = "http://webcontrol.local"
DEFAULT_UPDATE_INTERVAL: Final = 600  # seconds
MIN_UPDATE_INTERVAL: Final = 30  # seconds

# How often a cover move is re-sent when the box does not confirm it.
MOVE_ATTEMPTS: Final = 2
# HTTP timeout per request to the box.
REQUEST_TIMEOUT: Final = 10  # seconds

# After a preset (scene) command, how long to wait before checking whether a
# shade reacted, how many checks to make, and how often to resend the scene if
# nothing moved. A resend only happens when the shade neither reports movement
# nor changed position, so a running motor is never interrupted.
POST_COMMAND_SETTLE: Final = 1.5  # seconds
VERIFY_READS: Final = 2
PRESET_RESENDS: Final = 1

# The box answers state reads with "busy" (befehl=1 feedback=0) for several
# seconds while a motor is running (observed 2026-10-09 08:37:59-08:38:03).
# Up to this many consecutive failed polls keep the last known state (and
# re-poll after FAST_UPDATE_INTERVAL) before the entities go unavailable.
POLL_FAILURE_TOLERANCE: Final = 2

# After a move the box keeps reporting "not moving" for a short while, so poll
# more often for a couple of seconds to catch the shade settling on its target.
FAST_UPDATE_INTERVAL: Final = 5  # seconds
FAST_UPDATE_DURATION: Final = 15  # seconds

# 0.3.x shipped the author's scene payloads as defaults. Since 0.4 scenes are
# discovered from the box; manual presets are only an optional extra.
DEFAULT_PRESETS: Final[list[dict[str, str]]] = []

# Box clock: the box distributes its (local, DST-unaware) time to the actors,
# whose built-in timers depend on it. When the option is on, HA sets the clock
# at startup and daily if it is off by more than CLOCK_MAX_DRIFT seconds.
DEFAULT_CLOCK_SYNC: Final = True
CLOCK_MAX_DRIFT: Final = 60  # seconds
CLOCK_SYNC_TIME: Final = (3, 30, 0)  # daily check, after the DST switch at 2/3 am

# Reading an actor's timer is a radio round trip that occasionally fails on the
# first attempt (observed 2026-10-09); retry this many times.
TIMER_READ_RETRIES: Final = 1
TIMER_RETRY_WAIT: Final = 2.0  # seconds

# Repair issue when the box stays unreachable this long.
ISSUE_UNREACHABLE: Final = "box_unreachable"
ISSUE_UNREACHABLE_AFTER: Final = 15 * 60  # seconds
