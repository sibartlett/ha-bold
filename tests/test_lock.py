"""Tests for the Bold lock platform."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import SERVICE_LOCK, SERVICE_UNLOCK, LockState
from homeassistant.const import ATTR_ASSUMED_STATE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import DEVICE_SCAN_INTERVAL, EVENT_SCAN_INTERVAL

from .conftest import (
    GATEWAY,
    LOCK,
    LOCK_ENTITY,
    LOCK_ID,
    advance,
    call_lock,
    count_calls,
    event_payload,
    set_events,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time")


@pytest.fixture
def platforms() -> list[str]:
    """Only set up locks."""
    return ["lock"]


async def test_initial_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the lock starts locked, as an assumed state."""
    state = hass.states.get(LOCK_ENTITY)
    assert state.state == LockState.LOCKED
    assert state.attributes[ATTR_ASSUMED_STATE] is True


async def test_unlock_until_activation_ends(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test unlocking activates the lock for the activation time."""
    await call_lock(hass, SERVICE_UNLOCK)
    assert count_calls(mock_api, "remote-activation") == 1
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    await advance(hass, frozen_time, timedelta(seconds=4))
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    await advance(hass, frozen_time, timedelta(seconds=1))
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_lock_ends_activation(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locking an activated lock deactivates it."""
    await call_lock(hass, SERVICE_UNLOCK)
    await call_lock(hass, SERVICE_LOCK)
    assert count_calls(mock_api, "remote-deactivation") == 1
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_lock_when_not_activated_is_noop(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locking a lock that isn't activated doesn't call the API."""
    await call_lock(hass, SERVICE_LOCK)
    assert count_calls(mock_api, "remote-deactivation") == 0
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("gatewayNotFoundError", "No Bold Connect"),
        ("TooManyRequests", "Too many requests"),
        ("DeviceFirmwareOutdated", "Update the lock's firmware"),
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
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": code},
    )
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])

    with pytest.raises(HomeAssistantError, match=message):
        await call_lock(hass, SERVICE_UNLOCK)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_unlock_auth_error(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test Bold rejecting the credentials for a command."""
    aioclient_mock.post(f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation", status=401)
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])

    with pytest.raises(HomeAssistantError, match="rejected the credentials"):
        await call_lock(hass, SERVICE_UNLOCK)


async def test_unavailable_without_gateway(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a lock without a Bold Connect is unavailable."""
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [{**LOCK, "gateway": None}]
    )

    assert hass.states.get(LOCK_ENTITY).state == STATE_UNAVAILABLE


async def test_no_lock_without_remote_access(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test locks without remote access get no lock entity."""
    lock = {**LOCK, "features": {**LOCK["features"], "remoteAccess": False}}
    await setup_integration(hass, mock_config_entry, aioclient_mock, [lock])

    assert hass.states.get(LOCK_ENTITY) is None


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
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    mock_api.clear_requests()
    mock_api.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    mock_api.get(f"{API_URL}/v2/events", json=[])
    await advance(hass, frozen_time, timedelta(minutes=50))
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_activation_events(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test activations and deactivations from the event log."""
    await advance(hass, frozen_time, timedelta(seconds=1))
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
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get(LOCK_ENTITY)
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
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get(LOCK_ENTITY)
    assert state.state == LockState.LOCKED
    assert state.attributes["changed_by"] == "Grace"


async def test_activation_event_lasts_its_activation_time(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an activation stays unlocked for its activation time, from when it happened.

    A deactivation from before it doesn't end it.
    """
    set_events(
        mock_api,
        [
            event_payload(
                100,
                "DeviceActivation",
                "2026-09-24T12:00:20+00:00",
                result="Success",
                activationTime=60,
            ),
        ],
    )
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    # A deactivation uploaded late, from before the activation.
    set_events(
        mock_api,
        [event_payload(99, "DeviceDeactivation", "2026-09-24T12:00:10+00:00")],
    )
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    await advance(hass, frozen_time, timedelta(seconds=15))
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
    await advance(hass, frozen_time, timedelta(seconds=10))
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_older_deactivation_after_unlock(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a deactivation from before an unlock doesn't end it."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "OK", "activationTime": 60},
    )
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
    await call_lock(hass, SERVICE_UNLOCK)
    set_events(
        aioclient_mock,
        [event_payload(99, "DeviceDeactivation", "2026-09-24T11:59:50+00:00")],
    )
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


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
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get(LOCK_ENTITY)
    assert state.state == LockState.LOCKED
    assert state.attributes.get("changed_by") is None
