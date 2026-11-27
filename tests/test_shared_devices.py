"""Tests for devices shared with the account, which it doesn't administer."""

from datetime import timedelta
from http import HTTPStatus
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import DEVICE_SCAN_INTERVAL, DOMAIN
from custom_components.bold.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    GATEWAY,
    LOCK,
    LOCK_ID,
    FakeBluetooth,
    advance,
    count_calls,
    permission,
    set_permissions,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time", "setup_credentials")

SHARED_ID = 20
# A Connect with its Controller setting on, as Bold returns a shared one.
SHARED = {
    **GATEWAY,
    "id": SHARED_ID,
    "name": "Shared Gate",
    "owner": {"organizationId": 8, "accountId": 43},
    "settings": {"activationTime": 10, "controllerFunctionality": True},
    "features": {
        "activatable": True,
        "remoteAccess": True,
        "eventLog": True,
        "controller": True,
    },
    "gateway": {**GATEWAY["gateway"], "id": SHARED_ID},
}
SHARED_LOCK_ID = 21
SHARED_LOCK = {**LOCK, "id": SHARED_LOCK_ID, "name": "Shared Door"}
BUTTON = "button.shared_gate_activate"
LOCK_AND_CONNECT = [LOCK, GATEWAY]


def _registered(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, device_id: int
) -> bool:
    return (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, str(device_id)), entry.entry_id
        )
        is not None
    )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_only_shared_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a shared Connect works in an account with no devices of its own."""
    await async_process_ha_core_config(hass, {"external_url": "https://ha.example.com"})
    set_permissions(aioclient_mock, [permission(SHARED)])
    await setup_integration(hass, mock_config_entry, aioclient_mock, [])

    assert hass.states.get("lock.shared_gate").state == "locked"
    aioclient_mock.post(
        f"{API_URL}/v1/devices/{SHARED_ID}/remote-activation",
        json={"deviceId": SHARED_ID, "errorCode": "OK", "activationTime": 10},
    )
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
    )
    assert count_calls(aioclient_mock, f"/v1/devices/{SHARED_ID}/remote-activ") == 1

    # Bold doesn't allow reading its events, or a webhook in its organization.
    assert hass.states.get("event.shared_gate_activity") is None
    assert count_calls(aioclient_mock, "/v2/events") == 0
    assert count_calls(aioclient_mock, "/v3/webhooks") == 0
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["shared_devices"] == [SHARED_ID]


async def test_events_not_requested(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test events are only requested for the account's own devices."""
    set_permissions(aioclient_mock, [permission(SHARED)])
    await setup_integration(hass, mock_config_entry, aioclient_mock, LOCK_AND_CONNECT)
    assert mock_config_entry.runtime_data.events.device_ids == [LOCK_ID]


async def test_own_devices_win(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a device in both lists is one of the account's own."""
    set_permissions(aioclient_mock, [permission({**LOCK, "name": "Other"})])
    await setup_integration(hass, mock_config_entry, aioclient_mock, LOCK_AND_CONNECT)
    devices = mock_config_entry.runtime_data.devices
    assert devices.data[LOCK_ID].name == "Front Door"
    assert devices.data[LOCK_ID].event_log
    assert devices.shared_ids == set()


async def test_shared_and_unshared(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a device appears when shared, stays on errors, and goes when unshared."""
    await setup_integration(hass, mock_config_entry, aioclient_mock, LOCK_AND_CONNECT)
    assert not _registered(device_registry, mock_config_entry, SHARED_ID)

    set_permissions(aioclient_mock, [permission(SHARED)])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert _registered(device_registry, mock_config_entry, SHARED_ID)

    set_permissions(aioclient_mock, status=HTTPStatus.INTERNAL_SERVER_ERROR)
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert _registered(device_registry, mock_config_entry, SHARED_ID)
    assert SHARED_ID in mock_config_entry.runtime_data.devices.data

    set_permissions(aioclient_mock)
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL + timedelta(seconds=1))
    assert not _registered(device_registry, mock_config_entry, SHARED_ID)


@pytest.mark.parametrize(
    "status",
    [
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.INTERNAL_SERVER_ERROR,
    ],
)
async def test_error_at_startup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    frozen_time: FrozenDateTimeFactory,
    status: HTTPStatus,
) -> None:
    """Test own devices work without the shared ones, which aren't forgotten."""
    mock_config_entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, str(SHARED_ID))},
    )
    set_permissions(aioclient_mock, status=status)
    aioclient_mock.get(f"{API_URL}/v2/devices", json=LOCK_AND_CONNECT)
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("lock.front_door").state == "locked"
    assert _registered(device_registry, mock_config_entry, SHARED_ID)
    assert not any(mock_config_entry.async_get_active_flows(hass, {SOURCE_REAUTH}))

    # Once known not to be shared any more, it's removed.
    set_permissions(aioclient_mock)
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert not _registered(device_registry, mock_config_entry, SHARED_ID)


async def test_bluetooth_keys_separate(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test keys of own and shared locks are requested separately."""
    set_permissions(aioclient_mock, [permission(SHARED_LOCK)])
    with patch(
        "custom_components.bold.keys.BoldBluetoothKeys.async_refresh"
    ) as refresh:
        await setup_integration(
            hass, mock_config_entry, aioclient_mock, LOCK_AND_CONNECT
        )
    refresh.assert_called_once_with([LOCK_ID], [SHARED_LOCK_ID])


async def test_bluetooth_keys_refused(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a shared lock being refused keys doesn't affect the account's own."""
    set_permissions(aioclient_mock, [permission(SHARED_LOCK)])
    # Matched before the mock for any other locks.
    aioclient_mock.get(
        f"{API_URL}/v2/controller/handshakes",
        params={"deviceIds": str(SHARED_LOCK_ID)},
        status=HTTPStatus.FORBIDDEN,
    )
    aioclient_mock._mocks.insert(0, aioclient_mock._mocks.pop())  # noqa: SLF001
    await setup_integration(hass, mock_config_entry, aioclient_mock, LOCK_AND_CONNECT)
    await hass.async_block_till_done(wait_background_tasks=True)

    keys = mock_config_entry.runtime_data.bluetooth_keys
    assert keys.get(LOCK_ID) is not None
    assert keys.get(SHARED_LOCK_ID) is None
    assert "Couldn't refresh the Bluetooth keys" in caplog.text
