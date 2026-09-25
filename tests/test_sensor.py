"""Tests for the Bold sensor platform."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def platforms() -> list[str]:
    """Only set up sensors."""
    return ["sensor"]


async def test_battery(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the battery sensor."""
    state = hass.states.get("sensor.front_door_battery")
    assert state.state == "87"
    assert state.attributes["unit_of_measurement"] == "%"
    assert (
        entity_registry.async_get("sensor.front_door_battery").unique_id == "1_battery"
    )
    # Gateways have no battery sensor.
    assert len(hass.states.async_entity_ids("sensor")) == 1
