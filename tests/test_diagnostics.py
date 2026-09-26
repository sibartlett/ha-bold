"""Tests for Bold diagnostics."""

import base64
import json

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.diagnostics import REDACTED
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_OPTION
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.bold.const import EVENT_SCAN_INTERVAL
from custom_components.bold.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    ACTIVATE_COMMAND,
    DEACTIVATE_COMMAND,
    HANDSHAKE_KEY,
    HANDSHAKE_PAYLOAD,
    LOCK_ID,
    FakeBluetooth,
    advance,
    event_payload,
    set_events,
)


async def test_diagnostics(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test diagnostics, with secrets and personal details redacted.

    Update the snapshot with `pytest --snapshot-update`, and check the diff
    for anything that should be redacted.
    """
    set_events(
        mock_api,
        [
            event_payload(
                10,
                "DeviceActivation",
                "2026-09-24T12:00:10Z",
                result="Success",
                user={
                    "id": 3,
                    "firstName": "Ada",
                    "lastName": "Lovelace",
                    "emailAddress": "ada@example.com",
                },
                organization={"id": 7, "name": "The Lovelaces"},
            )
        ],
    )
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)

    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    assert diagnostics == snapshot
    # Nobody's name or email address is included, in devices or events.
    output = json.dumps(diagnostics)
    for personal in ("Ada", "Lovelace", "ada@example.com"):
        assert personal not in output
    # The token, and the webhook's ID and secret, which let anyone push
    # events, are never included.
    assert diagnostics["entry"]["token"] == REDACTED
    assert diagnostics["entry"]["webhook_id"] == REDACTED
    assert diagnostics["entry"]["webhook_secret"] == REDACTED


async def test_diagnostics_bluetooth(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
) -> None:
    """Test diagnostics describe Bluetooth keys without including them."""
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: "select.front_door_unlock_method",
            ATTR_OPTION: "prefer_bluetooth",
        },
        blocking=True,
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    expires = "2099-01-01T00:00:00+00:00"
    assert diagnostics["bluetooth"]["locks"][str(LOCK_ID)] == {
        "reachable": True,
        "unlock_method": "prefer_bluetooth",
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
