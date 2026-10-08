"""Tests for a lock linked to its door's contact sensor."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import SERVICE_UNLOCK, LockState
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
    ConfigSubentryData,
)
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
from custom_components.bold.const import (
    CONF_DOOR_SENSOR,
    CONF_LOCK,
    EVENT_SCAN_INTERVAL,
    SUBENTRY_DOOR_SENSOR,
)

from .conftest import (
    GATEWAY,
    LOCK,
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
    """Link the lock to its door sensor."""
    return MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data=mock_config_entry.data,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_LOCK: LOCK_ID, CONF_DOOR_SENSOR: DOOR},
                subentry_type=SUBENTRY_DOOR_SENSOR,
                title="🔒 Front Door → 🚪 Front Door contact",
                unique_id=str(LOCK_ID),
            )
        ],
    )


@pytest.fixture(autouse=True)
def door_closed(hass: HomeAssistant) -> None:
    """Start with the door closed."""
    hass.states.async_set(DOOR, STATE_OFF, {"friendly_name": "Front Door contact"})


async def _door(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set(DOOR, state)
    await hass.async_block_till_done()


async def test_open_door_unlocked(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test an opened door shows the lock unlocked, and still once closed."""
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED

    await _door(hass, STATE_ON)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

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


async def test_locked_while_open(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the bolt thrown with the door open shows locked, as reported."""
    await _door(hass, STATE_ON)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
    set_events(mock_api, [_bolt_event(10, "2026-09-24T12:00:20+00:00", "Locked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED
    await _door(hass, STATE_OFF)
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
    """Test an activation with the door open is ready to be locked."""
    await _door(hass, STATE_ON)
    await call_lock(hass, SERVICE_UNLOCK)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKING


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
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_opening_remembered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the last opening is stored for after a restart."""
    await _door(hass, STATE_ON)
    await _door(hass, STATE_OFF)
    data = await async_mock_restore_state_shutdown_restart(hass)
    extra = data.last_states[LOCK_ENTITY].extra_data
    assert extra is not None
    assert extra.as_dict() == {
        "door_opened_at": "2026-09-24T12:00:00+00:00",
        "door_open": False,
        "door_seen_at": "2026-09-24T12:00:00+00:00",
    }


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


async def _restart_with(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    stored: dict,
    door: str,
) -> None:
    """Set up as after a restart, with what the lock stored and the door now."""
    mock_restore_cache_with_extra_data(
        hass, [(State(LOCK_ENTITY, LockState.LOCKED), stored)]
    )
    hass.states.async_set(DOOR, door)
    await setup_integration(hass, entry, aioclient_mock, [UPGRADED_LOCK, GATEWAY])


async def test_restart_with_the_door_still_open(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a door open before and after a restart hasn't opened again."""
    # Opened at 11:45, then locked at 11:50 with the door still open.
    await _restart_with(
        hass,
        mock_config_entry,
        aioclient_mock,
        {
            "door_opened_at": "2026-09-24T11:45:00+00:00",
            "door_open": True,
            "door_seen_at": "2026-09-24T11:58:00+00:00",
        },
        STATE_ON,
    )
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_opened_while_restarting(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a door closed before a restart and open after it has opened."""
    await _restart_with(
        hass,
        mock_config_entry,
        aioclient_mock,
        {
            "door_opened_at": "2026-09-24T11:40:00+00:00",
            "door_open": False,
            "door_seen_at": "2026-09-24T11:58:00+00:00",
        },
        STATE_ON,
    )
    # Opened after 11:58, when last seen closed: after the 11:50 locked report.
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_sensor_back_with_the_door_still_open(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a sensor coming back with the door still open isn't an opening."""
    await _door(hass, STATE_ON)
    set_events(mock_api, [_bolt_event(10, "2026-09-24T12:00:20+00:00", "Locked")])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED

    await _door(hass, STATE_UNAVAILABLE)
    await _door(hass, STATE_ON)
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_open_at_startup(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a door already open at startup shows the lock unlocked."""
    hass.states.async_set(DOOR, STATE_ON)
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [UPGRADED_LOCK, GATEWAY]
    )
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_link_reconfigure_and_unlink(
    hass: HomeAssistant,
    setup_credentials: None,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test linking a lock to a door sensor, changing it, and unlinking it."""
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        unique_id=mock_config_entry.unique_id,
        data=mock_config_entry.data,
    )
    await setup_integration(hass, entry, aioclient_mock, [UPGRADED_LOCK, GATEWAY])

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR_SENSOR), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LOCK: str(LOCK_ID), CONF_DOOR_SENSOR: DOOR}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "🔒 Front Door → 🚪 Front Door contact"
    await hass.async_block_till_done()
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data == {CONF_LOCK: LOCK_ID, CONF_DOOR_SENSOR: DOOR}
    assert subentry.unique_id == str(LOCK_ID)
    # Reloaded with the link.
    assert entry.runtime_data.door_sensors == {LOCK_ID: DOOR}
    await _door(hass, STATE_ON)
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
    await _door(hass, STATE_OFF)

    # Every lock is linked now.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR_SENSOR), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_locks"

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR_SENSOR),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"lock": "Front Door"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_DOOR_SENSOR: "binary_sensor.other_door"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.runtime_data.door_sensors == {LOCK_ID: "binary_sensor.other_door"}
    # Without a state, the sensor is named by its entity ID.
    assert entry.subentries[subentry.subentry_id].title == (
        "🔒 Front Door → 🚪 binary_sensor.other_door"
    )

    assert hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.door_sensors == {}
    assert entry.state is ConfigEntryState.LOADED


async def test_lock_without_locked_status_not_offered(
    hass: HomeAssistant,
    setup_credentials: None,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test only locks reporting their bolt can be linked to a door sensor."""
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        unique_id=mock_config_entry.unique_id,
        data=mock_config_entry.data,
    )
    await setup_integration(hass, entry, aioclient_mock, [LOCK, GATEWAY])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DOOR_SENSOR), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_locks"


async def test_entry_update_without_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test other changes to the entry, e.g. refreshed tokens, don't reload it."""
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        hass.config_entries.async_update_entry(
            init_integration, data={**init_integration.data, "refreshed": True}
        )
        await hass.async_block_till_done()
    reload.assert_not_called()


async def test_link_not_loaded(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a door sensor can't be linked while Bold isn't loaded."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, SUBENTRY_DOOR_SENSOR),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


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
