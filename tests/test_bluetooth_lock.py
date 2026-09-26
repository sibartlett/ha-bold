"""Tests for unlocking Bold locks over Bluetooth."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import (
    DATA_COMPONENT as LOCK_COMPONENT,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    LockState,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_OPTION,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_component import async_update_entity
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock import COMMAND_ACTIVATE, COMMAND_DEACTIVATE
from custom_components.bold.boldsmartlock.ble import BoldBluetoothError
from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import (
    BLUETOOTH_FALLBACK_TIMEOUT,
    BLUETOOTH_TIMEOUT,
    DEVICE_SCAN_INTERVAL,
)
from custom_components.bold.keys import BoldLockKeys, BoldSecret

from .conftest import (
    ACTIVATE_COMMAND,
    DEACTIVATE_COMMAND,
    GATEWAY,
    LOCK,
    LOCK_ENTITY,
    LOCK_ID,
    FakeBluetooth,
    call_lock,
    count_calls,
    mock_bluetooth_keys,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time")

SELECT_ENTITY = "select.front_door_unlock_method"


async def _set_method(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: SELECT_ENTITY, ATTR_OPTION: option},
        blocking=True,
    )


async def test_default_prefers_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test locks use the Bold Connect by default, even in Bluetooth range."""
    assert hass.states.get(SELECT_ENTITY).state == "prefer_connect"
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert count_calls(mock_api, "remote-activation") == 1


async def test_prefer_connect_falls_back_to_bluetooth(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a failing Connect falls back to Bluetooth, even with a weak signal."""
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "gatewayNotFoundError"},
    )
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
    mock_config_entry.runtime_data.bluetooth._rssi[LOCK_ID] = -95  # noqa: SLF001
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED


async def test_unlock_prefers_bluetooth(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test preferring Bluetooth for a lock in range."""
    await _set_method(hass, "prefer_bluetooth")
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]
    assert count_calls(mock_api, "remote-activation") == 0
    # With the Connect to fall back to, Bluetooth gets less time.
    assert fake_bluetooth.timeouts == [BLUETOOTH_FALLBACK_TIMEOUT]
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    await call_lock(hass, SERVICE_LOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND, DEACTIVATE_COMMAND]
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_bluetooth_activation_time(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the lock stays unlocked for the time the lock reports."""
    await _set_method(hass, "prefer_bluetooth")
    fake_bluetooth.activation_time = 20
    await call_lock(hass, SERVICE_UNLOCK)
    frozen_time.tick(19)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
    frozen_time.tick(1)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_bluetooth_falls_back_to_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a failed Bluetooth unlock falls back to the Bold Connect."""
    await _set_method(hass, "prefer_bluetooth")
    fake_bluetooth.error = BoldBluetoothError("Timed out talking to the lock")
    await call_lock(hass, SERVICE_UNLOCK)
    assert count_calls(mock_api, "remote-activation") == 1
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED
    assert "over bluetooth (Timed out talking to the lock), trying connect" in (
        caplog.text
    )


async def test_prefer_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test preferring the Bold Connect."""
    await _set_method(hass, "prefer_connect")
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert count_calls(mock_api, "remote-activation") == 1


async def test_connect_only(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test never using Bluetooth."""
    await _set_method(hass, "connect_only")
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert count_calls(mock_api, "remote-activation") == 1


async def test_bluetooth_only(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test never using the Bold Connect, even when Bluetooth fails."""
    await _set_method(hass, "bluetooth_only")
    fake_bluetooth.error = BoldBluetoothError("The lock denied access")
    with pytest.raises(HomeAssistantError, match="over Bluetooth failed"):
        await call_lock(hass, SERVICE_UNLOCK)
    assert count_calls(mock_api, "remote-activation") == 0
    # As the only way, Bluetooth gets the full time.
    assert fake_bluetooth.timeouts == [BLUETOOTH_TIMEOUT]

    # Out of range, there's no way to reach the lock.
    init_integration.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == STATE_UNAVAILABLE


async def test_bluetooth_lost_before_sending(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
) -> None:
    """Test the lock going out of range just as a command is sent."""
    await _set_method(hass, "bluetooth_only")
    fake_bluetooth.ble_device = None
    with pytest.raises(HomeAssistantError, match="can't be reached over Bluetooth"):
        await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []


async def test_no_route_left(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
) -> None:
    """Test unlocking a lock that became unreachable since it was last shown."""
    await _set_method(hass, "bluetooth_only")
    entity = hass.data[LOCK_COMPONENT].get_entity(LOCK_ENTITY)
    init_integration.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    with pytest.raises(HomeAssistantError, match="can't be reached through"):
        await entity.async_unlock()


async def test_out_of_range_uses_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test a lock out of Bluetooth range is unlocked through the Connect."""
    await _set_method(hass, "prefer_bluetooth")
    init_integration.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert count_calls(mock_api, "remote-activation") == 1


async def test_bluetooth_when_cloud_is_down(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a lock in range still works while Bold's cloud is unreachable."""
    mock_api.clear_requests()
    mock_api.get(f"{API_URL}/v2/devices", status=500)
    mock_api.get(f"{API_URL}/v2/events", status=500)
    frozen_time.tick(DEVICE_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]


async def test_lock_without_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a lock without a Bold Connect works over Bluetooth only."""
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [{**LOCK, "gateway": None}]
    )
    # With nothing to choose between, there's no unlock method setting.
    assert hass.states.get(SELECT_ENTITY) is None
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]

    mock_config_entry.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == STATE_UNAVAILABLE
    # Home Assistant doesn't act on unavailable entities.
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]


async def test_no_keys_uses_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test without Bluetooth keys from Bold, the Connect is used."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/controller/handshakes", status=403)
    aioclient_mock.get(f"{API_URL}/v2/controller/commands", status=403)
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{LOCK_ID}/remote-activation",
        json={"deviceId": LOCK_ID, "errorCode": "OK", "activationTime": 5},
    )
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []


async def test_unlock_method_restored(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test the unlock method survives a restart."""
    mock_restore_cache(hass, [State(SELECT_ENTITY, "connect_only")])
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
    assert hass.states.get(SELECT_ENTITY).state == "connect_only"


async def test_no_bluetooth_no_setting(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test Home Assistant without Bluetooth gets no unlock method setting."""
    assert hass.states.get(SELECT_ENTITY) is None


async def test_keys_refresh_keeps_old_keys_on_errors(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a failed refresh keeps the stored keys, and only warns once."""
    keys = init_integration.runtime_data.bluetooth_keys
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/controller/handshakes", status=500)
    await keys.async_refresh([LOCK_ID])
    await keys.async_refresh([LOCK_ID])
    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and "Couldn't refresh the Bluetooth keys" in record.message
    ]
    assert len(warnings) == 1
    assert keys.command(LOCK_ID, "Activate") == ACTIVATE_COMMAND

    aioclient_mock.clear_requests()
    mock_bluetooth_keys(aioclient_mock)
    await keys.async_refresh([LOCK_ID])
    assert "Refreshed the Bluetooth keys of Bold locks again" in caplog.text


async def test_weak_signal_uses_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test a weak Bluetooth signal isn't tried when the Connect can be used."""
    await _set_method(hass, "prefer_bluetooth")
    tracker = init_integration.runtime_data.bluetooth
    tracker._rssi[LOCK_ID] = -92  # noqa: SLF001
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert count_calls(mock_api, "remote-activation") == 1

    # With Bluetooth only, a weak signal is still worth trying.
    await _set_method(hass, "bluetooth_only")
    await call_lock(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]


async def test_bluetooth_signal_sensor(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the Bluetooth signal sensor follows advertisements, without polling Bold."""
    entity_id = "sensor.front_door_bluetooth_signal"
    tracker = init_integration.runtime_data.bluetooth
    tracker._rssi[LOCK_ID] = -88  # noqa: SLF001
    # Home Assistant polls it every 30 seconds.
    await async_update_entity(hass, entity_id)
    state = hass.states.get(entity_id)
    assert state.state == "-88"
    assert state.attributes["unit_of_measurement"] == "dBm"

    # Reading the signal doesn't call Bold's API. Move past the cooldown on
    # refresh requests first, so a refresh would go through straight away.
    frozen_time.tick(60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_api.mock_calls.clear()
    await async_update_entity(hass, entity_id)
    await hass.async_block_till_done()
    assert mock_api.call_count == 0

    # Out of range, it's unavailable straight away.
    tracker.async_mark_unreachable(LOCK_ID)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_no_bluetooth_signal_sensor_without_bluetooth(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test Home Assistant without Bluetooth gets no Bluetooth signal sensor."""
    assert hass.states.get("sensor.front_door_bluetooth_signal") is None


def _record_states(hass: HomeAssistant) -> list[str]:
    """Record every state the front door lock goes through."""
    states: list[str] = []

    @callback
    def record(event: Event) -> None:
        if event.data["entity_id"] == LOCK_ENTITY and event.data["new_state"]:
            states.append(event.data["new_state"].state)

    hass.bus.async_listen(EVENT_STATE_CHANGED, record)
    return states


async def test_unlocking_shown_while_unlocking(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
) -> None:
    """Test the lock shows as unlocking straight away, over Bluetooth."""
    await _set_method(hass, "bluetooth_only")
    fake_bluetooth.started = asyncio.Event()
    unlock = hass.async_create_task(call_lock(hass, SERVICE_UNLOCK))
    await fake_bluetooth.started.wait()
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKING

    fake_bluetooth.release.set()
    await unlock
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    # The disconnect happens after the result, in the background.
    await hass.async_block_till_done()
    assert fake_bluetooth.disconnects == 1

    # Locking shows as locking.
    fake_bluetooth.started = asyncio.Event()
    fake_bluetooth.release = asyncio.Event()
    lock = hass.async_create_task(call_lock(hass, SERVICE_LOCK))
    await fake_bluetooth.started.wait()
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKING
    fake_bluetooth.release.set()
    await lock
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_unlocking_shown_through_connect(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the lock shows as unlocking through the Bold Connect too."""
    states = _record_states(hass)
    await call_lock(hass, SERVICE_UNLOCK)
    assert states == [LockState.UNLOCKING, LockState.UNLOCKED]


async def test_failed_unlock_stops_unlocking(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
) -> None:
    """Test a failed unlock returns the lock to its real state."""
    await _set_method(hass, "bluetooth_only")
    fake_bluetooth.error = BoldBluetoothError("The lock denied access")
    states = _record_states(hass)
    with pytest.raises(HomeAssistantError):
        await call_lock(hass, SERVICE_UNLOCK)
    assert states == [LockState.UNLOCKING, LockState.LOCKED]


def test_expired_keys_unused() -> None:
    """Test commands aren't used once they, or the handshake, expire."""
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    later = now + timedelta(hours=1)
    valid = BoldSecret(b"secret", later)
    expired = BoldSecret(b"secret", now)
    keys = BoldLockKeys(valid, valid, {COMMAND_ACTIVATE: valid})
    assert keys.command(COMMAND_ACTIVATE, now) == b"secret"
    assert keys.command(COMMAND_ACTIVATE, later) is None
    assert keys.command(COMMAND_DEACTIVATE, now) is None
    keys = BoldLockKeys(valid, expired, {COMMAND_ACTIVATE: valid})
    assert keys.command(COMMAND_ACTIVATE, now) is None


async def test_keys_removed_with_integration(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Test the stored Bluetooth keys, which unlock the door, go with the integration."""
    key = f"bold.{init_integration.entry_id}.bluetooth_keys"
    await hass.async_block_till_done()
    assert key in hass_storage
    await hass.config_entries.async_remove(init_integration.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
