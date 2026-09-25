"""Client for Bold Smart Locks: Bold's cloud API, and Bluetooth.

Kept free of Home Assistant imports, so it can become a standalone library.
"""

from .ble import (
    MANUFACTURER_ID,
    SERVICE_UUID,
    BoldAdvertisement,
    BoldBluetoothError,
    BoldBluetoothUnavailableError,
    async_send_command,
    parse_advertisement,
)
from .client import BoldClient
from .const import (
    API_URL,
    COMMAND_ACTIVATE,
    COMMAND_DEACTIVATE,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
    WEBHOOK_SECRET_HEADER,
)
from .exceptions import (
    BoldAuthError,
    BoldCommandError,
    BoldConnectionError,
    BoldError,
    BoldFirmwareOutdatedError,
    BoldForbiddenError,
    BoldGatewayNotFoundError,
    BoldRateLimitError,
)
from .models import (
    BoldDevice,
    BoldEvent,
    BoldEventType,
    parse_datetime,
    parse_duration,
)

__all__ = [
    "API_URL",
    "COMMAND_ACTIVATE",
    "COMMAND_DEACTIVATE",
    "MANUFACTURER_ID",
    "OAUTH2_AUTHORIZE",
    "OAUTH2_TOKEN",
    "SERVICE_UUID",
    "WEBHOOK_SECRET_HEADER",
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
    "BoldEventType",
    "BoldFirmwareOutdatedError",
    "BoldForbiddenError",
    "BoldGatewayNotFoundError",
    "BoldRateLimitError",
    "async_send_command",
    "parse_advertisement",
    "parse_datetime",
    "parse_duration",
]
