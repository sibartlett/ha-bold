"""Constants of the Bold API."""

from typing import Final

API_URL: Final = "https://api.boldsmartlock.com"
OAUTH2_AUTHORIZE: Final = "https://auth.boldsmartlock.com/authorize"
OAUTH2_TOKEN: Final = "https://api.boldsmartlock.com/v2/oauth/token"

# Bluetooth command types Bold's cloud issues signed commands for.
COMMAND_ACTIVATE: Final = "Activate"
COMMAND_DEACTIVATE: Final = "Deactivate"

# Webhooks send the secret they were created with in this header.
WEBHOOK_SECRET_HEADER: Final = "X-Bold-Secret"
