"""Tests for Bold Connect entities."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.const import DOMAIN

from .conftest import (
    GATEWAY,
    GATEWAY_ID,
    LOCK,
    LOCK_ID,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time")


async def test_connect_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the Connect is a device, with the lock linked to it."""
    connect = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(GATEWAY_ID)), init_integration.entry_id
    )
    assert connect.name == "Bold Connect"
    assert connect.model == "Bold Connect"
    assert connect.via_device_id is None

    lock = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(LOCK_ID)), init_integration.entry_id
    )
    assert lock.via_device_id == connect.id

    state = hass.states.get("binary_sensor.bold_connect_connectivity")
    assert state.state == STATE_ON
    assert state.attributes["device_class"] == "connectivity"
    assert (
        hass.states.get("sensor.bold_connect_last_seen").state
        == "2026-09-24T11:55:00+00:00"
    )

    # Connects only get connectivity and firmware entities.
    assert sorted(
        entry.entity_id
        for entry in er.async_entries_for_device(entity_registry, connect.id)
    ) == [
        "binary_sensor.bold_connect_connectivity",
        "sensor.bold_connect_last_seen",
        "update.bold_connect_firmware",
    ]


async def test_connect_offline(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a Connect not seen for 30 minutes is offline."""
    gateway = {
        **GATEWAY,
        "gateway": {**GATEWAY["gateway"], "lastSeen": "2026-09-24T11:30:00Z"},
    }
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, gateway])
    assert hass.states.get("binary_sensor.bold_connect_connectivity").state == STATE_OFF


async def test_connect_never_seen(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a Connect without a last seen time is unknown."""
    gateway = {key: value for key, value in GATEWAY.items() if key != "gateway"}
    await setup_integration(hass, mock_config_entry, aioclient_mock, [LOCK, gateway])
    assert (
        hass.states.get("binary_sensor.bold_connect_connectivity").state
        == STATE_UNKNOWN
    )


async def test_lock_signal(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the lock's signal to its Connect."""
    state = hass.states.get("sensor.front_door_bold_connect_signal")
    assert state.state == "high"
    assert state.attributes["options"] == [
        "excellent",
        "high",
        "medium",
        "low",
        "critical",
    ]

    # The raw signal strength is disabled by default.
    entry = entity_registry.async_get("sensor.front_door_bold_connect_signal_strength")
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.unique_id == f"{LOCK_ID}_connect_signal_strength"

    # Enabled, it shows the signal in dBm.
    entity_registry.async_update_entity(entry.entity_id, disabled_by=None)
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.front_door_bold_connect_signal_strength")
    assert state.state == "-60"
    assert state.attributes["unit_of_measurement"] == "dBm"


async def test_lock_without_connect(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test a lock without a Connect has no signal sensors or link."""
    await setup_integration(
        hass, mock_config_entry, aioclient_mock, [{**LOCK, "gateway": None}]
    )
    assert not hass.states.get("sensor.front_door_bold_connect_signal")
    lock = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(LOCK_ID)), mock_config_entry.entry_id
    )
    assert lock.via_device_id is None
