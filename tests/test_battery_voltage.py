"""Tests for the Bold battery voltage sensors."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.const import API_URL, EVENT_SCAN_INTERVAL

from .conftest import GATEWAY, LOCK, event_payload, set_events

IDLE = "sensor.front_door_battery_voltage"
UNDER_LOAD = "sensor.front_door_battery_voltage_under_load"

# Shaped like the debug event a Bold Classic sends when it's activated.
DEBUG_EVENT = event_payload(
    20,
    "DeviceDebug",
    "2026-09-24T12:00:10Z",
    category="DeviceEvent",
    debugType="DebugClutchEvent",
    body={
        "uptime": 30384003,
        "voltage0": 3060,
        "voltage1": 3060,
        "voltage2": 2790,
        "voltage3": 2682,
        "voltage4": 2688,
        "voltage5": 2694,
        "voltage6": 2706,
        "temperature": 17,
        "voltageIdle": 3063,
        "activationTime": 15,
    },
)


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time."""
    freezer.move_to("2026-09-24T12:00:00+00:00")
    return freezer


@pytest.fixture
def platforms() -> list[str]:
    """Only set up sensors."""
    return ["sensor"]


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(EVENT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_voltage_from_activation(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the voltages reported with an activation."""
    assert hass.states.get(IDLE).state == STATE_UNKNOWN
    set_events(mock_api, [DEBUG_EVENT])
    await _poll(hass, frozen_time)

    state = hass.states.get(IDLE)
    assert state.state == "3.063"
    assert state.attributes["unit_of_measurement"] == "V"
    assert state.attributes["device_class"] == "voltage"
    assert hass.states.get(UNDER_LOAD).state == "2.682"


async def test_voltage_from_status(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test the voltages from a status event."""
    set_events(
        mock_api,
        [
            event_payload(
                21,
                "DeviceStatus",
                "2026-09-24T12:00:10Z",
                category="DeviceEvent",
                uptime=5,
                voltageIdle=2950,
                voltageUnderLoad=2600,
            )
        ],
    )
    await _poll(hass, frozen_time)
    assert hass.states.get(IDLE).state == "2.95"
    assert hass.states.get(UNDER_LOAD).state == "2.6"


async def test_other_events_ignored(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test other devices' events, and events without voltages, are ignored."""
    other_device = {**DEBUG_EVENT, "id": 22, "device": {"id": 999}}
    no_body = event_payload(
        23, "DeviceDebug", "2026-09-24T12:00:10Z", body="unexpected"
    )
    activation = event_payload(
        24, "DeviceActivation", "2026-09-24T12:00:10Z", result="Success"
    )
    set_events(mock_api, [other_device, no_body, activation])
    await _poll(hass, frozen_time)
    assert hass.states.get(IDLE).state == STATE_UNKNOWN
    assert hass.states.get(UNDER_LOAD).state == STATE_UNKNOWN


async def test_voltage_at_startup(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a reading from just before startup is picked up."""
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[DEBUG_EVENT])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(IDLE).state == "3.063"


async def test_voltage_restored(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test the last reading is kept across restarts."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(IDLE, "3.01"),
                {"native_value": 3.01, "native_unit_of_measurement": "V"},
            )
        ],
    )
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(IDLE).state == "3.01"


async def test_no_voltage_without_event_log(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test locks without the event log get no voltage sensors."""
    lock = {**LOCK, "features": {**LOCK["features"], "eventLog": False}}
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[lock, GATEWAY])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(IDLE) is None
