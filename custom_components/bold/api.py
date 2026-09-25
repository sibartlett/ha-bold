"""Client for the Bold Smart Lock API.

Only depends on aiohttp, so it can be split out into a library later.
API reference: https://apidoc.boldsmartlock.com/
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
import re
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_URL

DEVICE_TYPE_LOCK = 1
DEVICE_TYPE_GATEWAY = 2

PAGE_SIZE = 100


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


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp from the API."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


_DURATION_UNITS = {
    "": 1,
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "ms": 0.001,
    "milli": 0.001,
    "millis": 0.001,
    "millisecond": 0.001,
    "milliseconds": 0.001,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")
_ISO_DURATION_RE = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


def parse_duration(value: Any) -> timedelta | None:
    """Parse a duration from the API.

    Durations are sometimes integers (seconds), and sometimes Scala
    FiniteDuration strings, whose exact format is undocumented; accept the
    common spellings ("5 seconds", "5s", "PT5S").
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if not isinstance(value, str):
        return None
    if match := _ISO_DURATION_RE.match(value.strip().upper()):
        days, hours, minutes, seconds = (float(g) if g else 0 for g in match.groups())
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if (match := _DURATION_RE.match(value)) and (
        unit := _DURATION_UNITS.get(match.group(2).lower())
    ) is not None:
        return timedelta(seconds=float(match.group(1)) * unit)
    return None


def _person_name(person: Any) -> str | None:
    """Return the display name of a user, account or triggeredBy object."""
    if not isinstance(person, dict):
        return None
    name = " ".join(
        part for part in (person.get("firstName"), person.get("lastName")) if part
    )
    return name or person.get("emailAddress") or None


@dataclass(frozen=True)
class BoldDevice:
    """A Bold device, from GET /v2/devices."""

    id: int
    name: str
    type_id: int | None
    model_name: str | None
    organization_id: int | None
    actual_firmware_version: int | None
    required_firmware_version: int | None
    battery_level: str | None
    battery_last_measurement: datetime | None
    activation_time: timedelta | None
    is_active_until: datetime | None
    remote_access: bool
    event_log: bool
    gateway_id: int | None
    gateway_rssi: int | None
    gateway_rssi_level: str | None
    gateway_last_seen: datetime | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BoldDevice:
        """Create a device from an API response."""
        model = data.get("model") or {}
        features = data.get("features") or {}
        settings = data.get("settings") or {}
        gateway = data.get("gateway") or {}
        battery_level = data.get("batteryLevel")
        return cls(
            id=data["id"],
            name=data.get("name") or f"Bold {data['id']}",
            type_id=(model.get("type") or {}).get("id"),
            model_name=model.get("description") or model.get("name"),
            organization_id=(data.get("owner") or {}).get("organizationId"),
            actual_firmware_version=data.get("actualFirmwareVersion"),
            required_firmware_version=data.get("requiredFirmwareVersion"),
            battery_level=(
                battery_level.lower() if isinstance(battery_level, str) else None
            ),
            battery_last_measurement=parse_datetime(data.get("batteryLastMeasurement")),
            activation_time=parse_duration(settings.get("activationTime")),
            is_active_until=parse_datetime(data.get("isActiveUntil")),
            remote_access=bool(features.get("remoteAccess")),
            event_log=bool(features.get("eventLog")),
            gateway_id=gateway.get("id"),
            gateway_rssi=gateway.get("rssi"),
            gateway_rssi_level=(
                rssi_level.lower()
                if isinstance(rssi_level := gateway.get("rssiLevel"), str)
                else None
            ),
            gateway_last_seen=parse_datetime(gateway.get("lastSeen")),
            raw=data,
        )

    @property
    def is_lock(self) -> bool:
        """Return whether the device is a lock."""
        return self.type_id == DEVICE_TYPE_LOCK

    @property
    def is_gateway(self) -> bool:
        """Return whether the device is a Bold Connect."""
        return self.type_id == DEVICE_TYPE_GATEWAY

    @property
    def update_available(self) -> bool:
        """Return whether the device firmware needs an update."""
        if (
            self.actual_firmware_version is None
            or self.required_firmware_version is None
        ):
            return False
        return self.actual_firmware_version < self.required_firmware_version


@dataclass(frozen=True)
class BoldEvent:
    """An event, from GET /v2/events."""

    id: int
    type: str
    time: datetime
    device_id: int | None
    result: str | None
    method: str | None
    user_name: str | None
    remote_activation: bool
    activation_time: timedelta | None
    keep_active_until: datetime | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BoldEvent | None:
        """Create an event from an API response, if it is well formed."""
        time = parse_datetime(data.get("time"))
        if not isinstance(data.get("id"), int) or not data.get("type") or time is None:
            return None
        return cls(
            id=data["id"],
            type=data["type"],
            time=time,
            device_id=(data.get("device") or {}).get("id"),
            result=data.get("result"),
            method=data.get("method"),
            user_name=(
                _person_name(data.get("user"))
                or _person_name(data.get("account"))
                or _person_name(data.get("triggeredBy"))
            ),
            # Remote activations name the Bold Connect they went through;
            # "remoteActivation" is documented but not always sent.
            remote_activation=bool(data.get("remoteActivation") or data.get("connect")),
            activation_time=parse_duration(data.get("activationTime")),
            keep_active_until=parse_datetime(data.get("keepActiveUntil")),
            raw=data,
        )


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
        self, method: str, path: str, params: dict[str, Any] | None = None
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
        self, device_ids: list[int], since: datetime
    ) -> list[BoldEvent]:
        """Return events for the given devices since a point in time."""
        events: list[BoldEvent] = []
        offset = 0
        while True:
            page = await self._request(
                "GET",
                "/v2/events",
                {
                    "deviceId": " ".join(str(device_id) for device_id in device_ids),
                    "from": since.isoformat(),
                    "offset": offset,
                    "size": PAGE_SIZE,
                },
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
