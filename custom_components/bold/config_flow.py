"""Config flow for the Bold integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .boldsmartlock import BoldClient, BoldError
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle Bold OAuth2 authentication."""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Bold device discovered over Bluetooth."""
        return await self._async_step_discovered()

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a Bold Connect discovered on the network."""
        return await self._async_step_discovered()

    async def _async_step_discovered(self) -> ConfigFlowResult:
        """Offer to set up Bold when a Bold device is discovered.

        A discovered device can't be tied to a Bold account without signing
        in, so all discoveries share one flow, and none is offered once Bold
        is set up (or the discovery was ignored).
        """
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm setting up a discovered Bold device."""
        if user_input is None:
            self._set_confirm_only()
            return self.async_show_form(step_id="discovery_confirm")
        return await self.async_step_user()

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
