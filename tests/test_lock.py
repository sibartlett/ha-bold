"""Tests for the Bold lock platform."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import (
    DOMAIN as LOCK_DOMAIN,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    LockState,
)
from homeassistant.const import ATTR_ASSUMED_STATE, ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.const import (
    API_URL,
    DEVICE_SCAN_INTERVAL,
    EVENT_SCAN_INTERVAL,
)

from .conftest import GATEWAY, LOCK, LOCK_ID, event_payload, set_events

ENTITY_ID = "lock.front_door"
NOW = "2026-09-24T12:00:00+00:00"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def platforms() -> list[str]:
    """Only set up locks."""
    return ["lock"]


def _calls(aioclient_mock: AiohttpClientMocker, command: str) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if command in str(call[1]))


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        LOCK_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )


async def test_initial_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the lock starts locked, as an assumed state."""
    state = hass.states.get(ENTITY_ID)
    assert state.state == LockState.LOCKED
    assert state.attributes[ATTR_ASSUMED_STATE] is True


async def test_unlock_until_activation_ends(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test unlocking activates the lock for the activation time."""
    await _call(hass, SERVICE_UNLOCK)
    assert _calls(mock_api, "remote-activation") == 1
    assert hass.states.get(ENTITY_ID).state == LockState.UNLOCKED

    await _advance(hass, frozen_time, timedelta(seconds=4))
    assert hass.states.get(ENTITY_ID).state == LockState.UNLOCKED

    await _advance(hass, frozen_time, timedelta(seconds=1))
    assert hass.states.get(ENTITY_ID).state == LockState.LOCKED


async def test_lock_ends_activation(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locking an activated lock deactivates it."""
    await _call(hass, SERVICE_UNLOCK)
    await _call(hass, SERVICE_LOCK)
    assert _calls(mock_api, "remote-deactivation") == 1
    assert hass.states.get(ENTITY_ID).state == LockState.LOCKED


async def test_lock_when_not_activated_is_noop(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locking a lock that isn't activated doesn't call the API."""
    await _call(hass, SERVICE_LOCK)
    assert _calls(mock_api, "remote-deactivation") == 0
    assert hass.states.get(ENTITY_ID).state == LockState.LOCKED


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("gatewayNotFoundError", "No Bold Connect"),
        ("TooManyRequests", "Too many requests"),
        ("Unknown", "command failed"),
    ],
)
async def test_unlock_errors(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    code: str,
    message: str,
) -> None:
    """Test command errors are raised to the user and leave the lock locked."""
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": code},
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match=message):
        await _call(hass, SERVICE_UNLOCK)
    assert hass.states.get(ENTITY_ID).state == LockState.LOCKED


async def test_unavailable_without_gateway(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a lock without a Bold Connect is unavailable."""
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[{**LOCK, "gateway": None}])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_no_lock_without_remote_access(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test locks without remote access get no lock entity."""
    lock = {**LOCK, "features": {**LOCK["features"], "remoteAccess": False}}
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[lock])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID) is None


async def test_keep_active_from_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an activation reported by the device, e.g. keep-active mode."""
    mock_api.clear_requests()
    mock_api.get(
        f"{API_URL}/v2/devices",
        json=[{**LOCK, "isActiveUntil": "2026-09-24T13:00:00Z"}, GATEWAY],
    )
    mock_api.get(f"{API_URL}/v2/events", json=[])
    await _advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get(ENTITY_ID).state == LockState.UNLOCKED

    mock_api.clear_requests()
    mock_api.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    mock_api.get(f"{API_URL}/v2/events", json=[])
    await _advance(hass, frozen_time, timedelta(minutes=50))
    assert hass.states.get(ENTITY_ID).state == LockState.LOCKED


async def test_activation_events(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test activations and deactivations from the event log."""
    await _advance(hass, frozen_time, timedelta(seconds=1))
    set_events(
        mock_api,
        [
            event_payload(
                100,
                "DeviceActivation",
                "2026-09-24T12:00:01+00:00",
                user={"id": 3, "firstName": "Ada", "lastName": "Lovelace"},
                method="Ble",
                result="Success",
                keepActiveUntil="2026-09-24T12:10:00+00:00",
            )
        ],
    )
    await _advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get(ENTITY_ID)
    assert state.state == LockState.UNLOCKED
    assert state.attributes["changed_by"] == "Ada Lovelace"

    set_events(
        mock_api,
        [
            event_payload(
                101,
                "DeviceDeactivation",
                "2026-09-24T12:00:40+00:00",
                user={"id": 4, "firstName": "Grace"},
                method="Button",
            )
        ],
    )
    await _advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get(ENTITY_ID)
    assert state.state == LockState.LOCKED
    assert state.attributes["changed_by"] == "Grace"


async def test_failed_activation_event_stays_locked(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a failed activation, e.g. a wrong PIN, doesn't unlock."""
    set_events(
        mock_api,
        [
            event_payload(
                100,
                "DeviceActivation",
                "2026-09-24T12:00:20+00:00",
                method="Pin",
                result="PinInvalid",
                keepActiveUntil="2026-09-24T12:10:00+00:00",
            )
        ],
    )
    await _advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get(ENTITY_ID)
    assert state.state == LockState.LOCKED
    assert state.attributes.get("changed_by") is None
