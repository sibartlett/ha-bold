"""Tests for the Bold API client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.api import (
    PAGE_SIZE,
    BoldAuthError,
    BoldClient,
    BoldCommandError,
    BoldDevice,
    BoldEvent,
    BoldFirmwareOutdatedError,
    BoldForbiddenError,
    BoldGatewayNotFoundError,
    BoldRateLimitError,
    parse_datetime,
    parse_duration,
)
from custom_components.bold.const import API_URL

from .conftest import LOCK, LOCK_ID, event_payload


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, timedelta(seconds=5)),
        (2.5, timedelta(seconds=2.5)),
        ("5", timedelta(seconds=5)),
        ("5 seconds", timedelta(seconds=5)),
        ("5s", timedelta(seconds=5)),
        ("1 minute", timedelta(minutes=1)),
        ("1500 milliseconds", timedelta(seconds=1.5)),
        ("PT5S", timedelta(seconds=5)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("forever", None),
        ("5 fortnights", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_duration(value, expected) -> None:
    """Test parsing the duration formats the API may use."""
    assert parse_duration(value) == expected


def test_parse_datetime() -> None:
    """Test timestamps are always timezone aware."""
    assert parse_datetime("2026-09-24T12:00:00Z") == datetime(
        2026, 9, 24, 12, tzinfo=UTC
    )
    assert parse_datetime("2026-09-24T12:00:00").tzinfo is UTC
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None


def test_device_from_api() -> None:
    """Test parsing a device."""
    device = BoldDevice.from_api(LOCK)
    assert device.id == LOCK_ID
    assert device.name == "Front Door"
    assert device.is_lock
    assert device.model_name == "Smart Cylinder SX"
    assert device.battery_level == 87
    assert device.activation_time == timedelta(seconds=5)
    assert device.remote_access
    assert device.event_log
    assert device.gateway_id == 2
    assert device.is_active_until is None
    assert not device.update_available


def test_device_from_api_minimal() -> None:
    """Test parsing a device with most fields missing."""
    device = BoldDevice.from_api({"id": 9, "batteryLevel": "LOW"})
    assert device.name == "Bold 9"
    assert not device.is_lock
    assert device.battery_level is None
    assert not device.remote_access
    assert device.gateway_id is None


def test_event_from_api() -> None:
    """Test parsing an activation event."""
    event = BoldEvent.from_api(
        event_payload(
            10,
            "DeviceActivation",
            "2026-09-24T12:00:00Z",
            user={"id": 3, "firstName": "Ada", "lastName": "Lovelace"},
            method="Ble",
            result="Success",
            activationTime="5 seconds",
        )
    )
    assert event is not None
    assert event.device_id == LOCK_ID
    assert event.user_name == "Ada Lovelace"
    assert event.method == "Ble"
    assert event.result == "Success"
    assert event.activation_time == timedelta(seconds=5)
    assert not event.remote_activation


def test_event_user_fallbacks() -> None:
    """Test the user name falls back to the account and triggeredBy."""
    payload = event_payload(10, "DeviceDeactivation", "2026-09-24T12:00:00Z")
    assert BoldEvent.from_api(payload).user_name is None
    payload["triggeredBy"]["emailAddress"] = "ada@example.com"
    assert BoldEvent.from_api(payload).user_name == "ada@example.com"
    payload["account"] = {"id": 1, "firstName": "Ada"}
    assert BoldEvent.from_api(payload).user_name == "Ada"


def test_event_from_api_malformed() -> None:
    """Test malformed events are skipped."""
    assert BoldEvent.from_api({"id": 1, "type": "DeviceActivation"}) is None
    assert (
        BoldEvent.from_api({"type": "DeviceActivation", "time": "2026-09-24T12:00:00Z"})
        is None
    )


def _client(hass: HomeAssistant) -> BoldClient:
    async def get_token() -> str:
        return "token"

    return BoldClient(async_get_clientsession(hass), get_token)


async def test_get_devices_paginates(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test all pages of devices are fetched."""
    first_page = [{**LOCK, "id": i} for i in range(PAGE_SIZE)]
    aioclient_mock.get(f"{API_URL}/v2/devices", params={"offset": 0}, json=first_page)
    aioclient_mock.get(
        f"{API_URL}/v2/devices", params={"offset": PAGE_SIZE}, json=[LOCK]
    )
    devices = await _client(hass).get_devices()
    assert len(devices) == PAGE_SIZE + 1
    assert aioclient_mock.mock_calls[0][3] == {"Authorization": "Bearer token"}


async def test_get_events_filters(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test events are requested for the given devices and time."""
    aioclient_mock.get(
        f"{API_URL}/v2/events",
        json=[
            event_payload(1, "DeviceBoot", "2026-09-24T12:00:00Z"),
            {"id": "broken"},
        ],
    )
    since = datetime(2026, 9, 24, 11, tzinfo=UTC)
    events = await _client(hass).get_events([1, 5], since)
    assert [event.id for event in events] == [1]
    url = aioclient_mock.mock_calls[0][1]
    assert url.query["deviceId"] == "1 5"
    assert url.query["from"] == since.isoformat()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, BoldAuthError),
        (403, BoldForbiddenError),
        (429, BoldRateLimitError),
    ],
)
async def test_http_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status, error
) -> None:
    """Test HTTP errors are translated."""
    aioclient_mock.get(f"{API_URL}/v2/devices", status=status)
    with pytest.raises(error):
        await _client(hass).get_devices()


async def test_remote_activation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test activation returns the activation time."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "OK", "activationTime": 7},
    )
    assert await _client(hass).remote_activation(LOCK_ID) == timedelta(seconds=7)


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("TooManyRequests", BoldRateLimitError),
        ("gatewayNotFoundError", BoldGatewayNotFoundError),
        ("DeviceFirmwareOutdated", BoldFirmwareOutdatedError),
        ("SomethingElse", BoldCommandError),
    ],
)
async def test_command_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, code, error
) -> None:
    """Test command error codes are translated."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-deactivation",
        json={"deviceId": LOCK_ID, "errorCode": code, "errorMessage": "nope"},
    )
    with pytest.raises(error):
        await _client(hass).remote_deactivation(LOCK_ID)
