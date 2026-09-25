"""Tests for setting up the Bold integration."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.const import API_URL, OAUTH2_TOKEN

from .conftest import GATEWAY, LOCK


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the integration sets up and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.events is not None
    assert init_integration.runtime_data.events.device_ids == [LOCK["id"]]

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_error_starts_reauth(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a rejected token starts reauthentication."""
    aioclient_mock.get(f"{API_URL}/v2/devices", status=401)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_setup_server_error_retries(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a server error retries setup later."""
    aioclient_mock.get(f"{API_URL}/v2/devices", status=500)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_without_event_log(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test locks without the event log feature don't poll events."""
    lock = {**LOCK, "features": {**LOCK["features"], "eventLog": False}}
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[lock, GATEWAY])
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.events.device_ids == []
    assert hass.states.get("lock.front_door") is not None
    assert hass.states.get("event.front_door_activity") is None
    assert not any("/v2/events" in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_setup_event_log_forbidden(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a forbidden event log doesn't break setup, and stops polling."""
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", status=403)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.events.update_interval is None


async def test_token_refresh_rejected_starts_reauth(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a rejected refresh token starts reauthentication."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            "token": {**mock_config_entry.data["token"], "expires_at": 0},
        },
    )
    aioclient_mock.post(OAUTH2_TOKEN, status=400)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
