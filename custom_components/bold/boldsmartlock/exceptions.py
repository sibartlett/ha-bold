"""Errors raised by the Bold Smart Lock client."""


class BoldError(Exception):
    """Base error for the Bold API."""


class BoldConnectionError(BoldError):
    """The Bold API could not be reached."""


class BoldAuthError(BoldError):
    """The Bold API rejected our credentials."""


class BoldForbiddenError(BoldError):
    """The account is not allowed to use this API."""


class BoldRateLimitError(BoldError):
    """Too many requests were sent to the Bold API."""


class BoldCommandError(BoldError):
    """A device command was rejected."""

    def __init__(self, code: str | None, message: str | None = None) -> None:
        """Initialize the error."""
        super().__init__(message or code)
        self.code = code


class BoldGatewayNotFoundError(BoldCommandError):
    """No Bold Connect is available to reach the device."""


class BoldFirmwareOutdatedError(BoldCommandError):
    """The device firmware does not support this command."""
