"""Tests for setting up the Bold integration."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL, OAUTH2_TOKEN
from custom_components.bold.const import (
    DEVICE_SCAN_INTERVAL,
    DOMAIN,
    EVENT_SCAN_INTERVAL,
)

from .conftest import GATEWAY, LOCK


async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Test the integration sets up and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    # Bold is called with the account's token.
    assert mock_api.mock_calls
    assert all(
        call[3] == {"Authorization": "Bearer access-token"}
        for call in mock_api.mock_calls
    )
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


async def test_setup_implementation_unavailable(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test setup retries when the OAuth implementation is unavailable.

    For example when Home Assistant Cloud is not connected yet.
    """
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.bold.async_get_config_entry_implementation",
        side_effect=ImplementationUnavailableError,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_foreign_device_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a device of the entry that isn't a Bold device is removed."""
    foreign = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id, identifiers={(DOMAIN, "not-bold")}
    )
    freezer.tick(DEVICE_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert device_registry.async_get(foreign.id) is None


async def test_event_poll_auth_error_starts_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test Bold rejecting the credentials while polling events."""
    mock_api.clear_requests()
    mock_api.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    mock_api.get(f"{API_URL}/v2/events", status=401)
    freezer.tick(EVENT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    error = init_integration.runtime_data.events.last_exception
    assert (error.translation_domain, error.translation_key) == (DOMAIN, "auth_failed")
