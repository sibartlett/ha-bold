"""Tests for Bold diagnostics."""

from __future__ import annotations

import base64
import json

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bold.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    ACTIVATE_COMMAND,
    DEACTIVATE_COMMAND,
    HANDSHAKE_KEY,
    HANDSHAKE_PAYLOAD,
    LOCK_ID,
    FakeBluetooth,
)


async def test_diagnostics(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test diagnostics include devices and redact the token."""
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    assert diagnostics["entry"]["token"] == REDACTED
    assert [device["name"] for device in diagnostics["devices"]] == [
        "Front Door",
        "Bold Connect",
    ]
    assert diagnostics["event_log_devices"] == [LOCK_ID]
    assert diagnostics["recent_events"] == []
    assert diagnostics["push"] == {
        "active": False,
        "last_push": None,
        "bold_webhooks": 0,
        "cloudhook": False,
    }
    # The webhook's ID and secret let anyone push events, so aren't included.
    assert diagnostics["entry"]["webhook_id"] == REDACTED
    assert diagnostics["entry"]["webhook_secret"] == REDACTED
    assert diagnostics["bluetooth"] == {
        "enabled": False,
        "locks": {
            str(LOCK_ID): {
                "reachable": False,
                "unlock_method": "prefer_connect",
                "handshake_expires": None,
                "commands": {},
            }
        },
    }


async def test_diagnostics_bluetooth(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
) -> None:
    """Test diagnostics describe Bluetooth keys without including them."""
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    expires = "2099-01-01T00:00:00+00:00"
    assert diagnostics["bluetooth"]["locks"][str(LOCK_ID)] == {
        "reachable": True,
        "unlock_method": "prefer_connect",
        "handshake_expires": expires,
        "commands": {"Activate": expires, "Deactivate": expires},
    }

    # The keys unlock the door, so must never be included, in any encoding.
    output = json.dumps(diagnostics)
    for secret in (
        HANDSHAKE_KEY,
        HANDSHAKE_PAYLOAD,
        ACTIVATE_COMMAND,
        DEACTIVATE_COMMAND,
    ):
        assert base64.b64encode(secret).decode() not in output
        assert secret.hex() not in output
