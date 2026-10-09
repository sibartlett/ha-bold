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
    ConfigSubentryFlow,
    SubentryFlowResult,
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
from .const import CONF_DOOR_SENSOR, CONF_LOCK, DOMAIN, SUBENTRY_DOOR_SENSOR

# A link's title: the lock, then its door sensor.
TITLE_LOCK = "🔒 "
TITLE_ARROW = " → "
TITLE_DOOR = "🚪 "

# The contact sensors a door can have.
DOOR_SENSOR_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        domain="binary_sensor",
        device_class=[
            BinarySensorDeviceClass.DOOR,
            BinarySensorDeviceClass.OPENING,
        ],
    )
)

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle Bold OAuth2 authentication."""

    DOMAIN = DOMAIN

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentries: a lock linked to its door sensor."""
        return {SUBENTRY_DOOR_SENSOR: DoorSensorSubentryFlow}

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


class DoorSensorSubentryFlow(ConfigSubentryFlow):
    """Link a lock to its door sensor, which shows when the lock missed an unlock."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose a lock that isn't linked yet, and its door sensor."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        linked = {
            subentry.unique_id
            for subentry in entry.get_subentries_of_type(SUBENTRY_DOOR_SENSOR)
        }
        locks = {
            str(device.id): device.name
            for device in entry.runtime_data.devices.data.values()
            # Only a lock reporting its bolt has a status a door can correct.
            if device.is_lock and device.reports_bolt and str(device.id) not in linked
        }
        if not locks:
            return self.async_abort(reason="no_locks")
        if user_input is not None:
            lock = user_input[CONF_LOCK]
            return self.async_create_entry(
                title=self._title(locks[lock], user_input[CONF_DOOR_SENSOR]),
                data={
                    CONF_LOCK: int(lock),
                    CONF_DOOR_SENSOR: user_input[CONF_DOOR_SENSOR],
                },
                unique_id=lock,
            )
        return self.async_show_form(
            step_id="user",
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
                    ),
                    vol.Required(CONF_DOOR_SENSOR): DOOR_SENSOR_SELECTOR,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose a different door sensor for the lock."""
        subentry = self._get_reconfigure_subentry()
        lock_name = subentry.title.partition(TITLE_ARROW)[0].removeprefix(TITLE_LOCK)
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=self._title(lock_name, user_input[CONF_DOOR_SENSOR]),
                data_updates={CONF_DOOR_SENSOR: user_input[CONF_DOOR_SENSOR]},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_DOOR_SENSOR): DOOR_SENSOR_SELECTOR}),
                {CONF_DOOR_SENSOR: subentry.data[CONF_DOOR_SENSOR]},
            ),
            description_placeholders={"lock": lock_name},
        )

    def _title(self, lock_name: str, door_sensor: str) -> str:
        """Return a link's title, showing the lock and its door sensor's name."""
        state = self.hass.states.get(door_sensor)
        door_name = state.name if state else door_sensor
        return f"{TITLE_LOCK}{lock_name}{TITLE_ARROW}{TITLE_DOOR}{door_name}"
