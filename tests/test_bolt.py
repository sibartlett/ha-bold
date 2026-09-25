"""Tests for locks that report their bolt position (upgraded locks)."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import (
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    LockState,
)
from homeassistant.const import ATTR_ASSUMED_STATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import DEVICE_SCAN_INTERVAL, EVENT_SCAN_INTERVAL

from .conftest import (
    GATEWAY,
    LOCK,
    LOCK_ENTITY,
    LOCK_ID,
    advance,
    call_lock,
    event_payload,
    set_events,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time")

ACTIVITY = "event.front_door_activity"

# Shaped like a Bold Classic with the upgrade, and locked status turned on.
UPGRADED_LOCK = {
    **LOCK,
    "features": {**LOCK["features"], "lockedStatus": True},
    "settings": {**LOCK["settings"], "lockedStatus": True},
    "actualFirmwareVersion": 192,
    "requiredFirmwareVersion": 192,
    "locked": "LOCKED",
    "lastLocked": "2026-09-24T11:50:00Z",
    "addons": [{"id": 840, "type": "CLASSIC_UPGRADE"}],
}


def _bolt_event(event_id: int, time: str, status: str) -> dict:
    """A DeviceLocked event, shaped like a real one."""
    return event_payload(
        event_id,
        "DeviceLocked",
        time,
        status=status,
        innerKnobRotation=-752 if status == "Unlocked" else 696,
        innerKnobAngle=-126,
    )


@pytest.fixture
def platforms() -> list[str]:
    """Only set up locks and events."""
    return ["event", "lock"]


async def _setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    lock: dict,
) -> None:
    """Set up with this lock, whose activations last 15 seconds."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "OK", "activationTime": 15},
    )
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-deactivation",
        json={"deviceId": LOCK_ID, "errorCode": "OK"},
    )
    await setup_integration(hass, mock_config_entry, aioclient_mock, [lock, GATEWAY])


@pytest.fixture
async def upgraded(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    platforms: list[str],
) -> MockConfigEntry:
    """Set up with an upgraded lock."""
    from unittest.mock import patch  # noqa: PLC0415

    with patch("custom_components.bold.PLATFORMS", platforms):
        await _setup(hass, mock_config_entry, aioclient_mock, UPGRADED_LOCK)
    return mock_config_entry


async def test_bolt_state(hass: HomeAssistant, upgraded: MockConfigEntry) -> None:
    """Test the lock shows its real bolt position, not an assumed state."""
    state = hass.states.get(LOCK_ENTITY)
    assert state.state == LockState.LOCKED
    assert not state.attributes.get(ATTR_ASSUMED_STATE)


async def test_bolt_events(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test bolt changes from the event log, which also fire activity events."""
    set_events(aioclient_mock, [_bolt_event(10, "2026-09-24T12:00:20Z", "Unlocked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
    assert hass.states.get(ACTIVITY).attributes["event_type"] == "unlocked"

    set_events(aioclient_mock, [_bolt_event(11, "2026-09-24T12:00:40Z", "Locked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED
    assert hass.states.get(ACTIVITY).attributes["event_type"] == "locked"


async def test_older_bolt_event_ignored(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an event older than the known bolt position doesn't override it."""
    set_events(aioclient_mock, [_bolt_event(10, "2026-09-24T11:40:00Z", "Unlocked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_bolt_from_device_poll(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the bolt position from the device data."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{API_URL}/v2/devices",
        json=[
            {
                **UPGRADED_LOCK,
                "locked": "UNLOCKED",
                "lastLocked": "2026-09-24T12:05:00Z",
            },
            GATEWAY,
        ],
    )
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_unlock_shows_unlocking_until_turned(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an activated lock is unlocking until someone turns it."""
    await call_lock(hass, SERVICE_UNLOCK)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKING

    # Someone turns it within the activation window; the lock shows it as soon
    # as the event is polled.
    set_events(aioclient_mock, [_bolt_event(10, "2026-09-24T12:00:08Z", "Unlocked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_unlock_not_turned(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an activation nobody uses ends back at locked."""
    await call_lock(hass, SERVICE_UNLOCK)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKING
    await advance(hass, frozen_time, timedelta(seconds=15))
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_lock_open_bolt(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test locking an open bolt explains it has to be turned by hand."""
    set_events(aioclient_mock, [_bolt_event(10, "2026-09-24T12:00:20Z", "Unlocked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    with pytest.raises(ServiceValidationError, match="turn the knob"):
        await call_lock(hass, SERVICE_LOCK)


async def test_lock_ends_activation(
    hass: HomeAssistant,
    upgraded: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test locking an activated lock ends the activation."""
    await call_lock(hass, SERVICE_UNLOCK)
    await call_lock(hass, SERVICE_LOCK)
    assert any(
        "remote-deactivation" in str(call[1]) for call in aioclient_mock.mock_calls
    )
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


@pytest.mark.parametrize(
    "lock",
    [
        {**UPGRADED_LOCK, "locked": "UNKNOWN"},
        {**UPGRADED_LOCK, "settings": {**LOCK["settings"], "lockedStatus": False}},
    ],
    ids=["unknown position", "turned off"],
)
async def test_without_bolt_position(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    lock: dict,
) -> None:
    """Test locks without a known bolt position keep the assumed state."""
    await _setup(hass, mock_config_entry, aioclient_mock, lock)
    assert hass.states.get(LOCK_ENTITY).attributes[ATTR_ASSUMED_STATE] is True
    await call_lock(hass, SERVICE_UNLOCK)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
