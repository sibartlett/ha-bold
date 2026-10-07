"""Tests for a Bold Connect that opens a door itself."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.event import ATTR_EVENT_TYPE
from homeassistant.components.lock import SERVICE_LOCK, SERVICE_UNLOCK, LockState
from homeassistant.const import ATTR_ASSUMED_STATE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import (
    DEFAULT_ACTIVATION_TIME,
    DEVICE_SCAN_INTERVAL,
    EVENT_SCAN_INTERVAL,
)

from .conftest import (
    GATEWAY,
    GATEWAY_ID,
    LOCK,
    advance,
    call_lock,
    count_calls,
    event_payload,
    set_events,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time")

# A Connect with its relay wired to a door, e.g. a building's entrance.
DOOR_CONNECT = {
    **GATEWAY,
    "settings": {"activationTime": 30, "controllerFunctionality": True},
    "features": {
        "activatable": True,
        "remoteAccess": True,
        "eventLog": True,
        "controller": True,
    },
}
# The same, when Bold doesn't allow it to be activated remotely.
NO_REMOTE_ACCESS = {
    **DOOR_CONNECT,
    "features": {**DOOR_CONNECT["features"], "remoteAccess": False},
}
# A Connect that doesn't, as Bold reports one without its Controller setting.
PLAIN_CONNECT = {
    **GATEWAY,
    "settings": {"activationTime": 5, "controllerFunctionality": False},
    "features": {
        "activatable": False,
        "remoteAccess": True,
        "eventLog": True,
        "controller": True,
    },
}
CONNECT_LOCK = "lock.bold_connect"
CONNECT_ACTIVITY = "event.bold_connect_activity"


@pytest.fixture
def platforms() -> list[str]:
    """Only set up locks and events."""
    return ["event", "lock"]


@pytest.fixture
def devices() -> list[dict]:
    """Return a lock served by a Connect that opens a door itself."""
    return [LOCK, DOOR_CONNECT]


@pytest.fixture
def mock_api(mock_api: AiohttpClientMocker) -> AiohttpClientMocker:
    """Also accept commands for the Connect."""
    mock_api.post(
        f"{API_URL}/v1/devices/{GATEWAY_ID}/remote-activation",
        json={"deviceId": GATEWAY_ID, "errorCode": "OK", "activationTime": 30},
    )
    mock_api.post(
        f"{API_URL}/v1/devices/{GATEWAY_ID}/remote-deactivation",
        json={"deviceId": GATEWAY_ID, "errorCode": "OK"},
    )
    return mock_api


async def test_door_connect_is_a_lock(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the Connect gets a lock, starting locked as an assumed state."""
    state = hass.states.get(CONNECT_LOCK)
    assert state.state == LockState.LOCKED
    assert state.attributes[ATTR_ASSUMED_STATE] is True
    # The lock it serves is unaffected.
    assert hass.states.get("lock.front_door").state == LockState.LOCKED


async def test_unlock_until_activation_ends(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test unlocking activates the Connect for its activation time."""
    await call_lock(hass, SERVICE_UNLOCK, CONNECT_LOCK)
    assert count_calls(mock_api, f"/v1/devices/{GATEWAY_ID}/remote-activation") == 1
    assert hass.states.get(CONNECT_LOCK).state == LockState.UNLOCKED

    await advance(hass, frozen_time, timedelta(seconds=29))
    assert hass.states.get(CONNECT_LOCK).state == LockState.UNLOCKED

    await advance(hass, frozen_time, timedelta(seconds=1))
    assert hass.states.get(CONNECT_LOCK).state == LockState.LOCKED


async def test_lock_ends_activation(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locking an activated Connect deactivates it."""
    await call_lock(hass, SERVICE_UNLOCK, CONNECT_LOCK)
    await call_lock(hass, SERVICE_LOCK, CONNECT_LOCK)
    assert count_calls(mock_api, f"/v1/devices/{GATEWAY_ID}/remote-deactivation") == 1
    assert hass.states.get(CONNECT_LOCK).state == LockState.LOCKED


async def test_lock_when_not_activated_is_noop(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locking a Connect that isn't activated doesn't call the API."""
    await call_lock(hass, SERVICE_LOCK, CONNECT_LOCK)
    assert count_calls(mock_api, "remote-deactivation") == 0


async def test_unlock_without_activation_time(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the default activation time applies when Bold gives none."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{GATEWAY_ID}/remote-activation",
        json={"deviceId": GATEWAY_ID, "errorCode": "OK"},
    )
    await setup_integration(
        hass,
        mock_config_entry,
        aioclient_mock,
        [LOCK, {**DOOR_CONNECT, "settings": {"controllerFunctionality": True}}],
    )

    await call_lock(hass, SERVICE_UNLOCK, CONNECT_LOCK)
    assert hass.states.get(CONNECT_LOCK).state == LockState.UNLOCKED

    await advance(hass, frozen_time, DEFAULT_ACTIVATION_TIME)
    assert hass.states.get(CONNECT_LOCK).state == LockState.LOCKED


async def test_unlock_error(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a command error is raised to the user and leaves the Connect locked."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{GATEWAY_ID}/remote-activation",
        json={"deviceId": GATEWAY_ID, "errorCode": "GatewayNotFound"},
    )
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [LOCK, DOOR_CONNECT]
    )

    with pytest.raises(HomeAssistantError):
        await call_lock(hass, SERVICE_UNLOCK, CONNECT_LOCK)
    assert hass.states.get(CONNECT_LOCK).state == LockState.LOCKED


async def test_lock_error(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a failure to end an activation is raised, leaving it unlocked."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{GATEWAY_ID}/remote-activation",
        json={"deviceId": GATEWAY_ID, "errorCode": "OK", "activationTime": 30},
    )
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{GATEWAY_ID}/remote-deactivation",
        json={"deviceId": GATEWAY_ID, "errorCode": "GatewayNotFound"},
    )
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [LOCK, DOOR_CONNECT]
    )
    await call_lock(hass, SERVICE_UNLOCK, CONNECT_LOCK)

    with pytest.raises(HomeAssistantError):
        await call_lock(hass, SERVICE_LOCK, CONNECT_LOCK)
    assert hass.states.get(CONNECT_LOCK).state == LockState.UNLOCKED


async def test_activation_reported_by_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an activation in Bold's device data shows on the lock."""
    mock_api.clear_requests()
    mock_api.get(
        f"{API_URL}/v2/devices",
        json=[LOCK, {**DOOR_CONNECT, "isActiveUntil": "2026-09-24T13:00:00Z"}],
    )
    mock_api.get(f"{API_URL}/v2/events", json=[])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get(CONNECT_LOCK).state == LockState.UNLOCKED


async def test_remote_access_lost(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test losing remote access makes the lock unavailable, but not the activity."""
    mock_api.clear_requests()
    mock_api.get(f"{API_URL}/v2/devices", json=[LOCK, NO_REMOTE_ACCESS])
    mock_api.get(f"{API_URL}/v2/events", json=[])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get(CONNECT_LOCK).state == STATE_UNAVAILABLE

    # Openings by the button or a PIN are still in the Connect's event log.
    set_events(mock_api, [_activation("2026-09-24T12:10:10+00:00")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(CONNECT_ACTIVITY).attributes[ATTR_EVENT_TYPE] == "activated"


async def test_no_remote_access_at_setup(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a Connect without remote access at setup gets its lock once it has it."""
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [LOCK, NO_REMOTE_ACCESS]
    )
    assert hass.states.get(CONNECT_LOCK).state == STATE_UNAVAILABLE
    assert hass.states.get(CONNECT_ACTIVITY) is not None

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, DOOR_CONNECT])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get(CONNECT_LOCK).state == LockState.LOCKED


async def test_activity(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test activations from elsewhere show on the Connect's lock and activity."""
    set_events(mock_api, [_activation("2026-09-24T12:00:10+00:00")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)

    state = hass.states.get(CONNECT_ACTIVITY)
    assert state.attributes[ATTR_EVENT_TYPE] == "activated"
    assert state.attributes["user"] == "Ada Lovelace"
    lock = hass.states.get(CONNECT_LOCK)
    assert lock.state == LockState.UNLOCKED
    assert lock.attributes["changed_by"] == "Ada Lovelace"
    assert any(
        call[1].query.get("deviceId") == f"{LOCK['id']} {GATEWAY_ID}"
        for call in mock_api.mock_calls
        if "/v2/events" in str(call[1])
    )


def _activation(time: str) -> dict:
    """Return an activation of the Connect, as Bold's event log has it."""
    return event_payload(
        10,
        "DeviceActivation",
        time,
        device={"id": GATEWAY_ID, "name": "Bold Connect"},
        user={"id": 3, "firstName": "Ada", "lastName": "Lovelace"},
        method="Ble",
        result="Success",
    )


async def test_plain_connect_is_not_a_lock(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a Connect that doesn't open a door gets no lock or activity."""
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [LOCK, PLAIN_CONNECT]
    )
    assert hass.states.get(CONNECT_LOCK) is None
    assert hass.states.get(CONNECT_ACTIVITY) is None
