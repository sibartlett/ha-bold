"""Tests for Bold diagnostics."""

from __future__ import annotations

import base64
import json

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.const import API_URL
from custom_components.bold.diagnostics import async_get_config_entry_diagnostics

from .conftest import LOCK_ID

HANDSHAKE_KEY = base64.b64encode(b"k" * 16).decode()
HANDSHAKE_PAYLOAD = base64.b64encode(b"h" * 57).decode()
COMMAND_PAYLOAD = base64.b64encode(b"c" * 46).decode()


def _mock_bluetooth_keys(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"{API_URL}/v2/controller/handshakes",
        json=[
            {
                "deviceId": LOCK_ID,
                "expiration": "2026-09-28T12:00:00Z",
                "handshakeKey": HANDSHAKE_KEY,
                "payload": HANDSHAKE_PAYLOAD,
                "somethingNew": "secret?",
            }
        ],
    )
    aioclient_mock.get(
        f"{API_URL}/v2/controller/commands",
        json=[
            {
                "deviceId": LOCK_ID,
                "commandType": "Activate",
                "expiration": "2026-09-28T12:00:00Z",
                "payload": COMMAND_PAYLOAD,
            }
        ],
    )


async def test_diagnostics(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test diagnostics include devices and redact the token."""
    _mock_bluetooth_keys(aioclient_mock)
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    assert diagnostics["entry"]["token"] == REDACTED
    assert [device["name"] for device in diagnostics["devices"]] == [
        "Front Door",
        "Bold Connect",
    ]
    assert diagnostics["event_log_devices"] == [LOCK_ID]
    assert diagnostics["recent_events"] == []
    assert diagnostics["bluetooth_keys"]["handshakes"] == [
        {
            "deviceId": LOCK_ID,
            "expiration": "2026-09-28T12:00:00Z",
            "handshakeKey": "<16 bytes>",
            "payload": "<57 bytes>",
            "somethingNew": "<not shown>",
        }
    ]
    assert diagnostics["bluetooth_keys"]["activate_commands"] == [
        {
            "deviceId": LOCK_ID,
            "commandType": "Activate",
            "expiration": "2026-09-28T12:00:00Z",
            "payload": "<46 bytes>",
        }
    ]


async def test_diagnostics_never_include_bluetooth_secrets(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test the Bluetooth keys, which unlock the door, never leak."""
    _mock_bluetooth_keys(aioclient_mock)
    output = json.dumps(
        await async_get_config_entry_diagnostics(hass, init_integration)
    )
    for secret in (HANDSHAKE_KEY, HANDSHAKE_PAYLOAD, COMMAND_PAYLOAD, "secret?"):
        assert secret not in output


async def test_diagnostics_bluetooth_keys_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test diagnostics report when Bold refuses the Bluetooth keys."""
    aioclient_mock.get(f"{API_URL}/v2/controller/handshakes", status=403)
    aioclient_mock.get(f"{API_URL}/v2/controller/commands", status=403)
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    assert diagnostics["bluetooth_keys"]["handshakes"] == {
        "error": "BoldForbiddenError: GET /v2/controller/handshakes is not allowed"
    }
