"""Tests for the Bold event platform."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.event import ATTR_EVENT_TYPE
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.const import API_URL, EVENT_SCAN_INTERVAL

from .conftest import GATEWAY, LOCK, event_payload, set_events

ENTITY_ID = "event.front_door_activity"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time."""
    freezer.move_to("2026-09-24T12:00:00+00:00")
    return freezer


@pytest.fixture
def platforms() -> list[str]:
    """Only set up events."""
    return ["event"]


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(EVENT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_history_is_not_replayed(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test events that exist at startup don't fire, and aren't refired."""
    existing = event_payload(
        1, "DeviceActivation", "2026-09-24T11:59:30+00:00", result="Success"
    )
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[existing])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN

    await _poll(hass, frozen_time)
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN


async def test_activation_event(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an activation fires an event with its details."""
    event = event_payload(
        10,
        "DeviceActivation",
        "2026-09-24T12:00:10+00:00",
        user={"id": 3, "firstName": "Ada", "lastName": "Lovelace"},
        method="Pin",
        result="Success",
    )
    set_events(mock_api, [event])
    await _poll(hass, frozen_time)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "2026-09-24T12:00:30.000+00:00"
    assert state.attributes[ATTR_EVENT_TYPE] == "activated"
    assert state.attributes["user"] == "Ada Lovelace"
    assert state.attributes["method"] == "Pin"
    assert state.attributes["result"] == "Success"
    assert state.attributes["remote"] is False
    assert state.attributes["bold_event_id"] == 10

    # The same event is returned by the next poll, but must not fire again.
    await _poll(hass, frozen_time)
    assert hass.states.get(ENTITY_ID).state == "2026-09-24T12:00:30.000+00:00"


@pytest.mark.parametrize(
    ("event", "event_type", "attributes"),
    [
        (
            event_payload(
                10, "DeviceActivation", "2026-09-24T12:00:10Z", result="PinInvalid"
            ),
            "activation_failed",
            {"result": "PinInvalid"},
        ),
        (
            event_payload(
                10, "DeviceDeactivation", "2026-09-24T12:00:10Z", method="Button"
            ),
            "deactivated",
            {"method": "Button"},
        ),
        (
            event_payload(
                10, "DeviceTamperVibration", "2026-09-24T12:00:10Z", duration=3
            ),
            "tamper",
            {"tamper_type": "vibration"},
        ),
    ],
)
async def test_event_types(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    event: dict,
    event_type: str,
    attributes: dict,
) -> None:
    """Test Bold events map to event types."""
    set_events(mock_api, [event])
    await _poll(hass, frozen_time)

    state = hass.states.get(ENTITY_ID)
    assert state.attributes[ATTR_EVENT_TYPE] == event_type
    for key, value in attributes.items():
        assert state.attributes[key] == value


async def test_other_events_ignored(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test events that aren't activity, or are for other devices, are ignored."""
    other_device = event_payload(
        11, "DeviceActivation", "2026-09-24T12:00:10Z", result="Success"
    )
    other_device["device"] = {"id": 999}
    set_events(
        mock_api,
        [
            event_payload(10, "DeviceStatus", "2026-09-24T12:00:10Z", uptime=5),
            other_device,
        ],
    )
    await _poll(hass, frozen_time)
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN
