"""Client for the Bold Smart Lock API.

Only depends on aiohttp, so it can be split out into a library later.
API reference: https://apidoc.boldsmartlock.com/
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_URL
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
from .models import BoldDevice, BoldEvent, parse_duration

PAGE_SIZE = 100


class BoldClient:
    """Client for the Bold Smart Lock API."""

    def __init__(
        self,
        session: ClientSession,
        get_access_token: Callable[[], Awaitable[str]],
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._get_access_token = get_access_token

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated request and return the decoded JSON body."""
        try:
            token = await self._get_access_token()
        except ClientResponseError as err:
            if HTTPStatus.BAD_REQUEST <= err.status < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise BoldAuthError("Refreshing the access token failed") from err
            raise BoldConnectionError("Refreshing the access token failed") from err
        except ClientError as err:
            raise BoldConnectionError("Refreshing the access token failed") from err

        try:
            async with self._session.request(
                method,
                f"{API_URL}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                if response.status == HTTPStatus.UNAUTHORIZED:
                    raise BoldAuthError("Access token rejected")
                if response.status == HTTPStatus.FORBIDDEN:
                    raise BoldForbiddenError(f"{method} {path} is not allowed")
                if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                    raise BoldRateLimitError("Too many requests")
                if response.status >= HTTPStatus.BAD_REQUEST:
                    raise BoldError(f"{method} {path} failed: HTTP {response.status}")
                return await response.json(content_type=None)
        except ClientError as err:
            raise BoldConnectionError(f"{method} {path} failed: {err}") from err

    async def get_account(self) -> dict[str, Any]:
        """Return the account of the current session."""
        account = await self._request("GET", "/v1/account")
        if not isinstance(account, dict):
            raise BoldError("Unexpected response from GET /v1/account")
        return account

    async def get_devices(self) -> list[BoldDevice]:
        """Return all devices the account has access to."""
        devices: list[BoldDevice] = []
        offset = 0
        while True:
            page = await self._request(
                "GET", "/v2/devices", {"offset": offset, "size": PAGE_SIZE}
            )
            if not isinstance(page, list):
                raise BoldError("Unexpected response from GET /v2/devices")
            devices.extend(BoldDevice.from_api(item) for item in page)
            if len(page) < PAGE_SIZE:
                return devices
            offset += PAGE_SIZE

    async def get_events(
        self,
        device_ids: list[int],
        since: datetime,
        event_types: list[str] | None = None,
    ) -> list[BoldEvent]:
        """Return events for the given devices since a point in time."""
        events: list[BoldEvent] = []
        offset = 0
        params: dict[str, Any] = {
            "deviceId": " ".join(str(device_id) for device_id in device_ids),
            "from": since.isoformat(),
            "size": PAGE_SIZE,
        }
        if event_types:
            params["type"] = " ".join(event_types)
        while True:
            page = await self._request(
                "GET", "/v2/events", {**params, "offset": offset}
            )
            if not isinstance(page, list):
                raise BoldError("Unexpected response from GET /v2/events")
            events.extend(
                event
                for item in page
                if isinstance(item, dict) and (event := BoldEvent.from_api(item))
            )
            if len(page) < PAGE_SIZE:
                return events
            offset += PAGE_SIZE

    async def get_bluetooth_handshakes(
        self, device_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Return Bluetooth handshakes for devices.

        Not part of Bold's public API: this is what the Bold app uses to talk
        to locks over Bluetooth.
        """
        return await self._get_list(
            "/v2/controller/handshakes",
            {"deviceIds": ",".join(str(device_id) for device_id in device_ids)},
        )

    async def get_bluetooth_commands(
        self, device_ids: list[int], command_types: list[str]
    ) -> list[dict[str, Any]]:
        """Return signed Bluetooth commands, e.g. "Activate", for devices.

        Not part of Bold's public API: this is what the Bold app uses to talk
        to locks over Bluetooth.
        """
        return await self._get_list(
            "/v2/controller/commands",
            {
                "deviceIds": ",".join(str(device_id) for device_id in device_ids),
                "commandTypes": ",".join(command_types),
            },
        )

    async def _get_list(
        self, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get a list of objects."""
        response = await self._request("GET", path, params)
        if not isinstance(response, list) or not all(
            isinstance(item, dict) for item in response
        ):
            raise BoldError(f"Unexpected response from GET {path}")
        return response

    async def get_webhooks(self, organization_id: int) -> list[dict[str, Any]]:
        """Return an organization's webhooks: id, webhookUrl and types."""
        return await self._get_list("/v3/webhooks", {"organizationId": organization_id})

    async def create_webhook(
        self,
        organization_id: int,
        url: str,
        event_types: list[str],
        secret: str,
    ) -> int:
        """Create a webhook, returning its ID.

        Bold sends events to the URL as a JSON list, in the format of the
        event log, with the secret in the X-Bold-Secret header.
        """
        response = await self._request(
            "POST",
            "/v3/webhooks",
            json={
                "organizationId": organization_id,
                "webhookUrl": url,
                "types": event_types,
                "secretHttp": secret,
            },
        )
        webhook_id = response.get("id") if isinstance(response, dict) else None
        if not isinstance(webhook_id, int):
            raise BoldError("Unexpected response from POST /v3/webhooks")
        return webhook_id

    async def update_webhook(
        self, webhook_id: int, url: str, event_types: list[str], secret: str
    ) -> None:
        """Update a webhook in place."""
        await self._request(
            "PUT",
            f"/v3/webhooks/{webhook_id}",
            json={"webhookUrl": url, "types": event_types, "secretHttp": secret},
        )

    async def delete_webhook(self, webhook_id: int) -> None:
        """Delete a webhook."""
        await self._request("DELETE", f"/v3/webhooks/{webhook_id}")

    async def remote_activation(self, device_id: int) -> timedelta | None:
        """Activate a device, returning how long it will stay active."""
        response = await self._command(device_id, "remote-activation")
        return parse_duration(response.get("activationTime"))

    async def remote_deactivation(self, device_id: int) -> None:
        """End an activation of a device."""
        await self._command(device_id, "remote-deactivation")

    async def _command(self, device_id: int, command: str) -> dict[str, Any]:
        """Send a remote command and check its result."""
        response = await self._request("POST", f"/v1/devices/{device_id}/{command}")
        if not isinstance(response, dict):
            raise BoldError(f"Unexpected response from {command}")
        code = response.get("errorCode")
        message = response.get("errorMessage")
        if code in (None, "OK"):
            return response
        if code == "TooManyRequests":
            raise BoldRateLimitError(message or code)
        if code == "gatewayNotFoundError":
            raise BoldGatewayNotFoundError(code, message)
        if code == "DeviceFirmwareOutdated":
            raise BoldFirmwareOutdatedError(code, message)
        raise BoldCommandError(code, message)
