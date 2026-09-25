"""Constants for the Bold integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "bold"
MANUFACTURER: Final = "Bold"


DEVICE_SCAN_INTERVAL: Final = timedelta(minutes=10)
EVENT_SCAN_INTERVAL: Final = timedelta(seconds=30)

# How far back the event poll looks, to tolerate clock skew and events that
# arrive at the API late. Events are de-duplicated by ID.
EVENT_POLL_OVERLAP: Final = timedelta(minutes=2)
# Locks upload their events when a Bold Connect or phone next syncs with them,
# which can be minutes later. Every so often, a poll looks further back to
# catch those.
EVENT_CATCH_UP_INTERVAL: Final = timedelta(minutes=10)
EVENT_CATCH_UP_LOOKBACK: Final = timedelta(hours=1)

# A Bold Connect is considered offline when Bold last heard from it this long
# ago. It checks in every few minutes, and devices are polled every 10.
CONNECT_OFFLINE_AFTER: Final = timedelta(minutes=30)

# Locks only report their battery voltage when they're turned, so at startup
# the latest reading from this far back is used.
BATTERY_VOLTAGE_HISTORY: Final = timedelta(days=7)

# Bluetooth keys: handshakes last about a week, and are refreshed well before.
BLUETOOTH_KEYS_REFRESH_INTERVAL: Final = timedelta(hours=12)
# How long to try Bluetooth before falling back to the Bold Connect, and how
# long when there's nothing to fall back to.
BLUETOOTH_FALLBACK_TIMEOUT: Final = 15
# With a fallback, only try Bluetooth when the lock is heard at least this well.
BLUETOOTH_MIN_RSSI: Final = -85
BLUETOOTH_TIMEOUT: Final = 30

# Repair issues are only raised once a problem has lasted this long.
ISSUE_AFTER: Final = timedelta(hours=1)
TROUBLESHOOTING_URL: Final = "https://github.com/sibartlett/ha-bold#troubleshooting"

# Used when Bold does not tell us how long an activation lasts.
DEFAULT_ACTIVATION_TIME: Final = timedelta(seconds=5)
