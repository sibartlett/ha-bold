"""Tests for Bold devices being added and removed."""

from __future__ import annotations

import copy

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import (
    DEVICE_SCAN_INTERVAL,
    DOMAIN,
    EVENT_SCAN_INTERVAL,
)

from .conftest import (
    GATEWAY,
    GATEWAY_ID,
    LOCK,
    LOCK_ID,
    advance,
    event_payload,
)

pytestmark = pytest.mark.usefixtures("frozen_time")

NEW_LOCK_ID = 5
NEW_LOCK = {**copy.deepcopy(LOCK), "id": NEW_LOCK_ID, "name": "Garage"}


def _mock_api(
    aioclient_mock: AiohttpClientMocker, devices: list[dict], events: list[dict]
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", json=devices)
    aioclient_mock.get(f"{API_URL}/v2/events", json=events)


def _device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, device_id: int
) -> dr.DeviceEntry | None:
    return device_registry.async_get_device_by_identifier(
        (DOMAIN, str(device_id)), entry.entry_id
    )


async def test_lock_added(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a lock added to Bold gets entities without a reload."""
    assert hass.states.get("lock.garage") is None

    # Its existing history must not be replayed.
    old_event = event_payload(
        50, "DeviceActivation", "2026-09-24T12:05:00Z", result="Success"
    )
    old_event["device"] = {"id": NEW_LOCK_ID}
    _mock_api(aioclient_mock, [LOCK, NEW_LOCK, GATEWAY], [old_event])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)

    for entity_id in (
        "lock.garage",
        "event.garage_activity",
        "sensor.garage_battery_level",
        "binary_sensor.garage_battery",
        "sensor.garage_bold_connect_signal",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    connect = _device(device_registry, init_integration, GATEWAY_ID)
    assert _device(device_registry, init_integration, NEW_LOCK_ID).via_device_id == (
        connect.id
    )
    assert init_integration.runtime_data.events.device_ids == [LOCK_ID, NEW_LOCK_ID]

    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get("event.garage_activity").state == "unknown"

    # New activity does fire.
    new_event = event_payload(
        51, "DeviceActivation", "2026-09-24T12:10:20Z", result="Success"
    )
    new_event["device"] = {"id": NEW_LOCK_ID}
    _mock_api(aioclient_mock, [LOCK, NEW_LOCK, GATEWAY], [old_event, new_event])
    await advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    state = hass.states.get("event.garage_activity")
    assert state.attributes["event_type"] == "activated"
    assert state.attributes["bold_event_id"] == 51


async def test_lock_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a lock removed from Bold is removed, and returns if re-added."""
    _mock_api(aioclient_mock, [GATEWAY], [])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)

    assert _device(device_registry, init_integration, LOCK_ID) is None
    assert entity_registry.async_get("lock.front_door") is None
    assert hass.states.get("lock.front_door") is None
    assert _device(device_registry, init_integration, GATEWAY_ID) is not None
    assert init_integration.runtime_data.events.device_ids == []

    _mock_api(aioclient_mock, [LOCK, GATEWAY], [])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert hass.states.get("lock.front_door") is not None


async def test_failed_poll_keeps_devices(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a failed poll doesn't remove devices."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", status=500)
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)

    assert _device(device_registry, init_integration, LOCK_ID) is not None
    assert hass.states.get("lock.front_door").state == "unavailable"


async def test_remove_stale_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test only devices that are no longer in Bold can be removed manually."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)

    async def remove(device: dr.DeviceEntry) -> bool:
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove_config_entry",
                "config_entry_id": init_integration.entry_id,
                "device_id": device.id,
            }
        )
        return (await client.receive_json())["success"]

    assert not await remove(_device(device_registry, init_integration, LOCK_ID))

    stale = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id, identifiers={(DOMAIN, "999")}
    )
    assert await remove(stale)
    assert device_registry.async_get(stale.id) is None


async def test_clicker_ignored(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test devices other than locks and Bold Connects get no entities."""
    clicker = {
        **copy.deepcopy(GATEWAY),
        "id": 9,
        "name": "Key fob",
        "model": {
            "id": 7,
            "name": "CLICKER",
            "type": {"id": 3, "name": "Clicker", "description": "Clicker"},
        },
    }
    _mock_api(aioclient_mock, [LOCK, GATEWAY, clicker], [])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _device(device_registry, mock_config_entry, 9) is None
    assert not [
        entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
        if entry.unique_id.startswith("9_") or entry.unique_id == "9"
    ]
    assert _device(device_registry, mock_config_entry, LOCK_ID) is not None
