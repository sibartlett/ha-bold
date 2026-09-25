"""Tests for the Bold update platform."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.update import (
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_RELEASE_SUMMARY,
)
from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import DEVICE_SCAN_INTERVAL, DOMAIN

from .conftest import (
    GATEWAY,
    LOCK,
    LOCK_ID,
    setup_integration,
)

ENTITY_ID = "update.front_door_firmware"


@pytest.fixture
def platforms() -> list[str]:
    """Only set up updates."""
    return ["update"]


async def test_up_to_date(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a device on the required firmware."""
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_INSTALLED_VERSION] == "90"
    assert state.attributes[ATTR_LATEST_VERSION] == "90"
    assert state.attributes[ATTR_RELEASE_SUMMARY] is None
    # Firmware is installed from the Bold app, not Home Assistant.
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == 0
    # Bold Connects have firmware too.
    assert hass.states.get("update.bold_connect_firmware") is not None


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [(89, 90, STATE_ON), (91, 90, STATE_OFF), (None, 90, STATE_UNKNOWN)],
)
async def test_versions(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    actual: int | None,
    required: int,
    expected: str,
) -> None:
    """Test comparing installed and required firmware."""
    lock = {
        **LOCK,
        "actualFirmwareVersion": actual,
        "requiredFirmwareVersion": required,
    }
    await setup_integration(hass, mock_config_entry, aioclient_mock, [lock, GATEWAY])
    state = hass.states.get(ENTITY_ID)
    assert state.state == expected
    if expected == STATE_ON:
        assert "Bold app" in state.attributes[ATTR_RELEASE_SUMMARY]


async def test_firmware_updated(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test updating firmware in the Bold app updates the entity and device."""
    lock = {**LOCK, "actualFirmwareVersion": 89, "requiredFirmwareVersion": 90}
    await setup_integration(hass, mock_config_entry, aioclient_mock, [lock, GATEWAY])
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    freezer.tick(DEVICE_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_OFF
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(LOCK_ID)), mock_config_entry.entry_id
    )
    assert device.sw_version == "90"
