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
    async_fire_time_changed,
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

from .conftest import GATEWAY, GATEWAY_ID, LOCK, LOCK_ID, event_payload

NEW_LOCK_ID = 5
NEW_LOCK = {**copy.deepcopy(LOCK), "id": NEW_LOCK_ID, "name": "Garage"}


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time."""
    freezer.move_to("2026-09-24T12:00:00+00:00")
    return freezer


def _mock_api(
    aioclient_mock: AiohttpClientMocker, devices: list[dict], events: list[dict]
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", json=devices)
    aioclient_mock.get(f"{API_URL}/v2/events", json=events)


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


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
    await _advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)

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

    await _advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
    assert hass.states.get("event.garage_activity").state == "unknown"

    # New activity does fire.
    new_event = event_payload(
        51, "DeviceActivation", "2026-09-24T12:10:20Z", result="Success"
    )
    new_event["device"] = {"id": NEW_LOCK_ID}
    _mock_api(aioclient_mock, [LOCK, NEW_LOCK, GATEWAY], [old_event, new_event])
    await _advance(hass, frozen_time, EVENT_SCAN_INTERVAL)
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
    await _advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)

    assert _device(device_registry, init_integration, LOCK_ID) is None
    assert entity_registry.async_get("lock.front_door") is None
    assert hass.states.get("lock.front_door") is None
    assert _device(device_registry, init_integration, GATEWAY_ID) is not None
    assert init_integration.runtime_data.events.device_ids == []

    _mock_api(aioclient_mock, [LOCK, GATEWAY], [])
    await _advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
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
    await _advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)

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
