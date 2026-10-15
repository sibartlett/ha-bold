"""Tests for the Bold sensor and binary sensor platforms."""

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL

from .conftest import GATEWAY, LOCK


@pytest.fixture
def platforms() -> list[str]:
    """Only set up sensors."""
    return ["binary_sensor", "sensor"]


async def test_battery(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the battery level and low battery sensors."""
    state = hass.states.get("sensor.front_door_battery_level")
    assert state.state == "excellent"
    assert state.attributes["options"] == ["excellent", "good", "low", "critical"]
    entry = entity_registry.async_get("sensor.front_door_battery_level")
    assert entry.unique_id == "1_battery_level"

    state = hass.states.get("binary_sensor.front_door_battery")
    assert state.state == STATE_OFF
    assert state.attributes["device_class"] == "battery"

    # Gateways have no battery entities.
    assert not hass.states.get("sensor.bold_connect_battery_level")
    assert not hass.states.get("binary_sensor.bold_connect_battery")


@pytest.mark.parametrize(
    ("battery_level", "level_state", "low_state"),
    [
        ("Good", "good", STATE_OFF),
        ("Low", "low", STATE_ON),
        ("Critical", "critical", STATE_ON),
        # Shown as Bold sent it, but not known to be low or not.
        ("Medium", "medium", STATE_UNKNOWN),
        ("Something new", "something new", STATE_UNKNOWN),
        (None, STATE_UNKNOWN, STATE_UNKNOWN),
    ],
)
async def test_battery_levels(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    battery_level: str | None,
    level_state: str,
    low_state: str,
) -> None:
    """Test each battery level."""
    aioclient_mock.get(
        f"{API_URL}/v2/devices",
        json=[{**LOCK, "batteryLevel": battery_level}, GATEWAY],
    )
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.front_door_battery_level")
    assert state.state == level_state
    # A level we don't know is added to the options, so it can be shown.
    known = ["excellent", "good", "low", "critical"]
    assert state.attributes["options"] == (
        known
        if battery_level is None or level_state in known
        else [*known, level_state]
    )
    assert hass.states.get("binary_sensor.front_door_battery").state == low_state


async def test_unknown_signal_level(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a signal level Bold isn't known to send is shown as it sent it."""
    aioclient_mock.get(
        f"{API_URL}/v2/devices",
        json=[{**LOCK, "gateway": {**LOCK["gateway"], "rssiLevel": "Good"}}, GATEWAY],
    )
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.front_door_bold_connect_signal")
    assert state.state == "good"
    assert state.attributes["options"] == [
        "excellent",
        "high",
        "medium",
        "low",
        "critical",
        "good",
    ]
