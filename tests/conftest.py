"""Fixtures for the Bold integration tests."""

from __future__ import annotations

from collections.abc import Generator
import copy
import time
from typing import Any
from unittest.mock import patch

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.const import API_URL, DOMAIN

CLIENT_ID = "client-id"
CLIENT_SECRET = "client-secret"
ACCOUNT_ID = 42

LOCK_ID = 1
GATEWAY_ID = 2

# Based on the examples in https://apidoc.boldsmartlock.com/openapi.yaml
LOCK = {
    "id": LOCK_ID,
    "name": "Front Door",
    "owner": {"organizationId": 7, "accountId": ACCOUNT_ID, "name": ""},
    "model": {
        "id": 1,
        "name": "SX33",
        "type": {"id": 1, "name": "Lock", "description": "Lock"},
        "description": "Smart Cylinder SX",
    },
    "settings": {"activationTime": 5},
    "features": {"remoteAccess": True, "eventLog": True, "lockedStatus": False},
    "gateway": {
        "id": GATEWAY_ID,
        "rssi": -60,
        "rssiLevel": "High",
        "lastSeen": "2026-09-24T10:00:00Z",
    },
    "actualFirmwareVersion": 90,
    "requiredFirmwareVersion": 90,
    "timeZone": "Europe/Amsterdam",
    "batteryLevel": "Excellent",
    "batteryLastMeasurement": "2026-09-24T09:00:00Z",
    "locked": "UNKNOWN",
    "entryTags": [],
    "matter": {},
    "relatedDeviceGroups": [],
    "reachableGateways": [],
    "reachableDevices": [],
    "addons": [],
}
GATEWAY = {
    "id": GATEWAY_ID,
    "name": "Bold Connect",
    "owner": {"organizationId": 7},
    "model": {
        "id": 4,
        "name": "CONNECT",
        "type": {"id": 2, "name": "Gateway", "description": "Connect"},
        "description": "Bold Connect",
    },
    # A Connect reports itself as its own gateway, with when Bold last heard
    # from it.
    "gateway": {
        "id": GATEWAY_ID,
        "rssi": 0,
        "rssiLevel": "Excellent",
        "lastSeen": "2026-09-24T11:55:00Z",
    },
    "settings": {},
    "features": {"remoteAccess": False, "eventLog": False},
    "locked": "UNKNOWN",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom_components."""


@pytest.fixture
def devices() -> list[dict[str, Any]]:
    """Return the devices the mocked API returns."""
    return [copy.deepcopy(LOCK), copy.deepcopy(GATEWAY)]


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a Bold config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test User",
        unique_id=str(ACCOUNT_ID),
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_at": time.time() + 365 * 86400,
                "token_type": "Bearer",
            },
        },
    )


@pytest.fixture
async def setup_credentials(hass: HomeAssistant) -> None:
    """Set up application credentials."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), DOMAIN
    )


@pytest.fixture
def mock_api(
    aioclient_mock: AiohttpClientMocker, devices: list[dict[str, Any]]
) -> AiohttpClientMocker:
    """Mock the Bold API with one lock and no events."""
    aioclient_mock.get(f"{API_URL}/v2/devices", json=devices)
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "OK", "activationTime": 5},
    )
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-deactivation",
        json={"deviceId": LOCK_ID, "errorCode": "OK"},
    )
    return aioclient_mock


@pytest.fixture
def platforms() -> list[str]:
    """Platforms to set up; override in a test module to limit them."""
    return ["binary_sensor", "event", "lock", "sensor", "update"]


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    platforms: list[str],
) -> MockConfigEntry:
    """Set up the integration."""
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.bold.PLATFORMS", platforms):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return mock_config_entry


def event_payload(event_id: int, event_type: str, time: str, **extra: Any) -> dict:
    """Return an event as GET /v2/events returns it."""
    return {
        "id": event_id,
        "type": event_type,
        "category": "AccessEvent",
        "time": time,
        "triggeredBy": {"userId": 3, "accountId": ACCOUNT_ID},
        "organization": {"id": 7, "name": "Home"},
        "device": {"id": LOCK_ID, "name": "Front Door"},
        **extra,
    }


def set_events(aioclient_mock: AiohttpClientMocker, events: list[dict]) -> None:
    """Replace the mocked /v2/events response."""
    aioclient_mock.mock_calls.clear()
    aioclient_mock._mocks = [  # noqa: SLF001
        mock
        for mock in aioclient_mock._mocks
        if "/v2/events" not in str(mock.url)  # noqa: SLF001
    ]
    aioclient_mock.get(f"{API_URL}/v2/events", json=events)


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Prevent the integration from being set up during config flow tests."""
    with patch("custom_components.bold.async_setup_entry", return_value=True):
        yield
