"""Tests for a lock linked to its door's contact sensor."""

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import SERVICE_UNLOCK, LockState
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_restore_state_shutdown_restart,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import CONF_DOOR_SENSORS, EVENT_SCAN_INTERVAL

from .conftest import (
    GATEWAY,
    LOCK_ENTITY,
    LOCK_ID,
    advance,
    call_lock,
    set_events,
    setup_integration,
)
from .test_bolt import UPGRADED_LOCK, _bolt_event

pytestmark = pytest.mark.usefixtures("frozen_time")

DOOR = "binary_sensor.front_door_contact"


@pytest.fixture
def platforms() -> list[str]:
    """Only set up locks and events."""
    return ["event", "lock"]


@pytest.fixture
def devices() -> list[dict]:
    """Return a lock that reports its bolt, locked at 11:50."""
    return [UPGRADED_LOCK, GATEWAY]


@pytest.fixture
def mock_config_entry(mock_config_entry: MockConfigEntry) -> MockConfigEntry:
    """Link the lock to its door sensor, closed to begin with."""
    return MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data=mock_config_entry.data,
        options={CONF_DOOR_SENSORS: {str(LOCK_ID): DOOR}},
    )


@pytest.fixture(autouse=True)
def door_closed(hass: HomeAssistant) -> None:
    """Start with the door closed."""
    hass.states.async_set(DOOR, STATE_OFF)


async def _door(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set(DOOR, state)
    await hass.async_block_till_done()


async def test_open_then_unlocked(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test an opened door shows the lock open, then unlocked once closed."""
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED

    await _door(hass, STATE_ON)
    assert hass.states.get(LOCK_ENTITY).state == LockState.OPEN

    # The lock last reported locked at 11:50, before the door opened: it missed
    # being unlocked.
    await _door(hass, STATE_OFF)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_locked_after_opening(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the lock reporting locked after the door opened shows locked."""
    await _door(hass, STATE_ON)
    await _door(hass, STATE_OFF)
    set_events(mock_api, [_bolt_event(10, "2026-09-24T12:00:20+00:00", "Locked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_late_report_from_before_opening(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a locked report arriving late, from before the door opened, is old."""
    await _door(hass, STATE_ON)
    await _door(hass, STATE_OFF)
    set_events(mock_api, [_bolt_event(10, "2026-09-24T11:59:30+00:00", "Locked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_unlocking_with_the_door_open(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test an activation with the door open still shows the door open."""
    await _door(hass, STATE_ON)
    await call_lock(hass, SERVICE_UNLOCK)
    assert hass.states.get(LOCK_ENTITY).state == LockState.OPEN


async def test_sensor_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test an unavailable or removed sensor is ignored, and its return counts."""
    await _door(hass, STATE_UNAVAILABLE)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED
    hass.states.async_remove(DOOR)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED

    # Back, and open: the door opened while it was away.
    await _door(hass, STATE_ON)
    assert hass.states.get(LOCK_ENTITY).state == LockState.OPEN


async def test_opening_remembered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the last opening is stored for after a restart."""
    await _door(hass, STATE_ON)
    await _door(hass, STATE_OFF)
    data = await async_mock_restore_state_shutdown_restart(hass)
    extra = data.last_states[LOCK_ENTITY].extra_data
    assert extra is not None
    assert extra.as_dict() == {"door_opened_at": "2026-09-24T12:00:00+00:00"}


async def test_opening_restored(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test an opening from before a restart, after the last locked report."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(LOCK_ENTITY, LockState.LOCKED),
                {"door_opened_at": "2026-09-24T11:55:00+00:00"},
            )
        ],
    )
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [UPGRADED_LOCK, GATEWAY]
    )
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_open_at_startup(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a door already open at startup shows the lock open."""
    hass.states.async_set(DOOR, STATE_ON)
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [UPGRADED_LOCK, GATEWAY]
    )
    assert hass.states.get(LOCK_ENTITY).state == LockState.OPEN


async def test_options_link_and_unlink(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test linking a lock to a door sensor, and unlinking it."""
    entry = init_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"lock": str(LOCK_ID)}
    )
    assert result["step_id"] == "door_sensor"
    assert result["description_placeholders"] == {"lock": "Front Door"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"door_sensor": "binary_sensor.back_door_contact"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_DOOR_SENSORS] == {
        str(LOCK_ID): "binary_sensor.back_door_contact"
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"lock": str(LOCK_ID)}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_DOOR_SENSORS] == {}
    assert entry.state is ConfigEntryState.LOADED


async def test_options_not_loaded(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the options can't be changed while Bold isn't loaded."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_options_without_locks(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test there's nothing to link without locks."""
    await setup_integration(hass, mock_config_entry, aioclient_mock, [GATEWAY])
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_locks"


async def test_unlinked_lock_ignores_doors(
    hass: HomeAssistant,
    setup_credentials: None,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a lock without a door sensor is unaffected by one opening."""
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        unique_id=mock_config_entry.unique_id,
        data=mock_config_entry.data,
    )
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "OK"},
    )
    await setup_integration(hass, entry, aioclient_mock, [UPGRADED_LOCK, GATEWAY])
    await _door(hass, STATE_ON)
    await _door(hass, STATE_OFF)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED
