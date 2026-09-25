"""Tests for the Bold config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from yarl import URL

from custom_components.bold.boldsmartlock.const import (
    API_URL,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
)
from custom_components.bold.const import DOMAIN

from .conftest import ACCOUNT_ID, CLIENT_ID

REDIRECT_URI = "https://example.com/auth/external/callback"


async def _authorize(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    result: dict,
    account_id: int = ACCOUNT_ID,
) -> dict:
    """Complete the OAuth dance and return the final flow result."""
    state = config_entry_oauth2_flow._encode_jwt(  # noqa: SLF001
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT_URI}
    )
    url = URL(result["url"])
    assert str(url.with_query(None)) == OAUTH2_AUTHORIZE
    assert url.query["client_id"] == CLIENT_ID
    # Bold rejects scopes a client doesn't support; without one, it grants
    # everything the client (e.g. the Home Assistant Cloud one) allows.
    assert "scope" not in url.query
    assert url.query["state"] == state

    client = await hass_client_no_auth()
    response = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert response.status == 200

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    aioclient_mock.get(
        f"{API_URL}/v1/account",
        json={"id": account_id, "firstName": "Ada", "lastName": "Lovelace"},
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"])


@pytest.mark.usefixtures(
    "current_request_with_host", "setup_credentials", "mock_setup_entry"
)
async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test setting up an account."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await _authorize(hass, hass_client_no_auth, aioclient_mock, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ada Lovelace"
    assert result["result"].unique_id == str(ACCOUNT_ID)
    assert result["data"]["token"]["access_token"] == "new-access-token"


@pytest.mark.usefixtures(
    "current_request_with_host", "setup_credentials", "mock_setup_entry"
)
async def test_already_configured(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test adding the same account twice is aborted."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await _authorize(hass, hass_client_no_auth, aioclient_mock, result)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures(
    "current_request_with_host", "setup_credentials", "mock_setup_entry"
)
async def test_cannot_fetch_account(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test the flow aborts if the account can't be fetched."""
    aioclient_mock.get(f"{API_URL}/v1/account", status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await _authorize(hass, hass_client_no_auth, aioclient_mock, result)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures(
    "current_request_with_host", "setup_credentials", "mock_setup_entry"
)
@pytest.mark.parametrize(
    ("account_id", "reason"),
    [(ACCOUNT_ID, "reauth_successful"), (ACCOUNT_ID + 1, "wrong_account")],
)
async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    account_id: int,
    reason: str,
) -> None:
    """Test reauthentication only accepts the same account."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _authorize(
        hass, hass_client_no_auth, aioclient_mock, result, account_id
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    expected = "new-access-token" if reason == "reauth_successful" else "access-token"
    assert mock_config_entry.data["token"]["access_token"] == expected
