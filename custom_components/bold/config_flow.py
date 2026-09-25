"""Config flow for the Bold integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import BoldClient, BoldError
from .const import DOMAIN


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle Bold OAuth2 authentication."""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the tokens stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm reauthentication."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=vol.Schema({})
            )
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create an entry for the account, or update it when reauthenticating."""
        access_token: str = data["token"]["access_token"]

        async def get_access_token() -> str:
            return access_token

        client = BoldClient(async_get_clientsession(self.hass), get_access_token)
        try:
            account = await client.get_account()
        except BoldError:
            self.logger.exception("Failed to fetch the Bold account")
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(str(account["id"]))
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )

        self._abort_if_unique_id_configured()
        name = " ".join(
            part for part in (account.get("firstName"), account.get("lastName")) if part
        )
        return self.async_create_entry(
            title=name or account.get("email") or "Bold", data=data
        )
