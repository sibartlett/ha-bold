"""Tests for unlocking Bold locks over Bluetooth."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.lock import (
    DOMAIN as LOCK_DOMAIN,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    LockState,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_OPTION, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.ble import BoldBluetoothError
from custom_components.bold.const import API_URL, DEVICE_SCAN_INTERVAL

from .conftest import (
    ACTIVATE_COMMAND,
    DEACTIVATE_COMMAND,
    GATEWAY,
    LOCK,
    LOCK_ID,
    FakeBluetooth,
    mock_bluetooth_keys,
)

LOCK_ENTITY = "lock.front_door"
SELECT_ENTITY = "select.front_door_unlock_method"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time."""
    freezer.move_to("2026-09-24T12:00:00+00:00")
    return freezer


def _remote_calls(aioclient_mock: AiohttpClientMocker, command: str) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if command in str(call[1]))


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        LOCK_DOMAIN, service, {ATTR_ENTITY_ID: LOCK_ENTITY}, blocking=True
    )


async def _set_method(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: SELECT_ENTITY, ATTR_OPTION: option},
        blocking=True,
    )


async def _setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    devices: list[dict],
) -> None:
    aioclient_mock.get(f"{API_URL}/v2/devices", json=devices)
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_unlock_prefers_bluetooth(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a lock in range is unlocked over Bluetooth by default."""
    assert hass.states.get(SELECT_ENTITY).state == "prefer_bluetooth"

    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]
    assert _remote_calls(mock_api, "remote-activation") == 0
    assert hass.states.get(LOCK_ENTITY).state == LockState.UNLOCKED

    await _call(hass, SERVICE_LOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND, DEACTIVATE_COMMAND]
    assert hass.states.get(LOCK_ENTITY).state == LockState.LOCKED


async def test_bluetooth_activation_time(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the lock stays unlocked for the time the lock reports."""
    fake_bluetooth.activation_time = 20
    await _call(hass, SERVICE_UNLOCK)
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
    fake_bluetooth.error = BoldBluetoothError("Timed out talking to the lock")
    await _call(hass, SERVICE_UNLOCK)
    assert _remote_calls(mock_api, "remote-activation") == 1
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
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert _remote_calls(mock_api, "remote-activation") == 1


async def test_connect_only(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test never using Bluetooth."""
    await _set_method(hass, "connect_only")
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert _remote_calls(mock_api, "remote-activation") == 1


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
        await _call(hass, SERVICE_UNLOCK)
    assert _remote_calls(mock_api, "remote-activation") == 0

    # Out of range, there's no way to reach the lock.
    init_integration.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == STATE_UNAVAILABLE


async def test_out_of_range_uses_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test a lock out of Bluetooth range is unlocked through the Connect."""
    init_integration.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert _remote_calls(mock_api, "remote-activation") == 1


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
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]


async def test_lock_without_connect(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a lock without a Bold Connect works over Bluetooth only."""
    await _setup(hass, mock_config_entry, aioclient_mock, [{**LOCK, "gateway": None}])
    # With nothing to choose between, there's no unlock method setting.
    assert hass.states.get(SELECT_ENTITY) is None
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]

    mock_config_entry.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    await hass.async_block_till_done()
    assert hass.states.get(LOCK_ENTITY).state == STATE_UNAVAILABLE
    # Home Assistant doesn't act on unavailable entities.
    await _call(hass, SERVICE_UNLOCK)
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
    await _setup(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
    await _call(hass, SERVICE_UNLOCK)
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
    await _setup(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
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
    tracker = init_integration.runtime_data.bluetooth
    tracker._rssi[LOCK_ID] = -92  # noqa: SLF001
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == []
    assert _remote_calls(mock_api, "remote-activation") == 1

    # With Bluetooth only, a weak signal is still worth trying.
    await _set_method(hass, "bluetooth_only")
    await _call(hass, SERVICE_UNLOCK)
    assert fake_bluetooth.sent == [ACTIVATE_COMMAND]
