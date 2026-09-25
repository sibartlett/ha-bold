"""Client for Bold Smart Locks: Bold's cloud API, and Bluetooth.

Kept free of Home Assistant imports, so it can become a standalone library.
"""

from .api import (
    BoldAuthError,
    BoldClient,
    BoldCommandError,
    BoldConnectionError,
    BoldDevice,
    BoldError,
    BoldEvent,
    BoldFirmwareOutdatedError,
    BoldForbiddenError,
    BoldGatewayNotFoundError,
    BoldRateLimitError,
    parse_datetime,
    parse_duration,
)
from .ble import (
    MANUFACTURER_ID,
    SERVICE_UUID,
    BoldAdvertisement,
    BoldBluetoothError,
    BoldBluetoothUnavailableError,
    async_send_command,
    parse_advertisement,
)
from .const import (
    API_URL,
    COMMAND_ACTIVATE,
    COMMAND_DEACTIVATE,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
)

__all__ = [
    "API_URL",
    "COMMAND_ACTIVATE",
    "COMMAND_DEACTIVATE",
    "MANUFACTURER_ID",
    "OAUTH2_AUTHORIZE",
    "OAUTH2_TOKEN",
    "SERVICE_UUID",
    "BoldAdvertisement",
    "BoldAuthError",
    "BoldBluetoothError",
    "BoldBluetoothUnavailableError",
    "BoldClient",
    "BoldCommandError",
    "BoldConnectionError",
    "BoldDevice",
    "BoldError",
    "BoldEvent",
    "BoldFirmwareOutdatedError",
    "BoldForbiddenError",
    "BoldGatewayNotFoundError",
    "BoldRateLimitError",
    "async_send_command",
    "parse_advertisement",
    "parse_datetime",
    "parse_duration",
]
