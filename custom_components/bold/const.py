"""Constants for the Bold integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "bold"
MANUFACTURER: Final = "Bold"

API_URL: Final = "https://api.boldsmartlock.com"
OAUTH2_AUTHORIZE: Final = "https://auth.boldsmartlock.com/authorize"
OAUTH2_TOKEN: Final = "https://api.boldsmartlock.com/v2/oauth/token"

DEVICE_SCAN_INTERVAL: Final = timedelta(minutes=10)
EVENT_SCAN_INTERVAL: Final = timedelta(seconds=30)

# How far back the event poll looks, to tolerate clock skew and events that
# arrive at the API late. Events are de-duplicated by ID.
EVENT_POLL_OVERLAP: Final = timedelta(minutes=2)

# Used when Bold does not tell us how long an activation lasts.
DEFAULT_ACTIVATION_TIME: Final = timedelta(seconds=5)
