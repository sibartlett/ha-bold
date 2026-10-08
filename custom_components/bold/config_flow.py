"""Config flow for the Bold integration."""

from collections.abc import Mapping
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
import voluptuous as vol

from .boldsmartlock import BoldClient, BoldError
from .const import CONF_DOOR_SENSORS, DOMAIN

CONF_LOCK = "lock"
CONF_DOOR_SENSOR = "door_sensor"

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle Bold OAuth2 authentication."""

    DOMAIN = DOMAIN

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BoldOptionsFlow:
        """Return the options flow, for linking locks to door sensors."""
        return BoldOptionsFlow()

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
        first_name: str | None = account.get("firstName")
        last_name: str | None = account.get("lastName")
        email: str | None = account.get("email")
        name = " ".join(
            part for part in (first_name, last_name) if isinstance(part, str) and part
        )
        return self.async_create_entry(
            title=name or (email if isinstance(email, str) else "") or "Bold",
            data=data,
        )


class BoldOptionsFlow(OptionsFlowWithReload):
    """Link a lock to a door sensor, which shows when the lock missed an unlock."""

    _lock: str
    _lock_name: str

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the lock."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        locks = {
            str(device.id): device.name
            for device in self.config_entry.runtime_data.devices.data.values()
            if device.is_lock or device.is_door_connect
        }
        if not locks:
            return self.async_abort(reason="no_locks")
        if user_input is not None:
            self._lock = user_input[CONF_LOCK]
            self._lock_name = locks[self._lock]
            return await self.async_step_door_sensor()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCK): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=device_id, label=name)
                                for device_id, name in sorted(
                                    locks.items(), key=lambda item: item[1]
                                )
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_door_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the lock's door sensor, or none."""
        sensors: dict[str, str] = dict(
            self.config_entry.options.get(CONF_DOOR_SENSORS, {})
        )
        if user_input is not None:
            if sensor := user_input.get(CONF_DOOR_SENSOR):
                sensors[self._lock] = sensor
            else:
                sensors.pop(self._lock, None)
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_DOOR_SENSORS: sensors}
            )
        return self.async_show_form(
            step_id="door_sensor",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DOOR_SENSOR,
                        description={"suggested_value": sensors.get(self._lock)},
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain="binary_sensor",
                            device_class=[
                                BinarySensorDeviceClass.DOOR,
                                BinarySensorDeviceClass.GARAGE_DOOR,
                                BinarySensorDeviceClass.OPENING,
                            ],
                        )
                    )
                }
            ),
            description_placeholders={"lock": self._lock_name},
        )
