"""Lock platform for the Bold integration.

A Bold lock is not motorised: activating it lets someone turn the cylinder by
hand for a short time. Without bolt position reporting, the lock is shown as
unlocked while it is activated and locked otherwise, as an assumed state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .api import (
    BoldAuthError,
    BoldDevice,
    BoldError,
    BoldFirmwareOutdatedError,
    BoldGatewayNotFoundError,
    BoldRateLimitError,
)
from .const import DEFAULT_ACTIVATION_TIME, DOMAIN
from .coordinator import BoldConfigEntry, BoldDeviceCoordinator, BoldEventCoordinator
from .entity import BoldEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold locks."""
    data = entry.runtime_data
    async_add_entities(
        BoldLock(data.devices, data.events, device)
        for device in data.devices.data.values()
        if device.is_lock and device.remote_access
    )


def _command_error(err: BoldError) -> HomeAssistantError:
    """Translate an API error from a lock command."""
    if isinstance(err, BoldRateLimitError):
        key = "rate_limited"
    elif isinstance(err, BoldGatewayNotFoundError):
        key = "gateway_not_found"
    elif isinstance(err, BoldFirmwareOutdatedError):
        key = "firmware_outdated"
    elif isinstance(err, BoldAuthError):
        key = "auth_failed"
    else:
        key = "command_failed"
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"error": str(err)},
    )


class BoldLock(BoldEntity, LockEntity):
    """A Bold Smart Lock."""

    _attr_name = None
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: BoldDeviceCoordinator,
        events: BoldEventCoordinator | None,
        device: BoldDevice,
    ) -> None:
        """Initialize the lock."""
        super().__init__(coordinator, device, None)
        self._events = events
        self._activated_at: datetime | None = None
        self._active_until: datetime | None = None
        self._unsub_expiry: CALLBACK_TYPE | None = None
        self._update_from_device()

    async def async_added_to_hass(self) -> None:
        """Subscribe to events and schedule the end of any activation."""
        await super().async_added_to_hass()
        if self._events is not None:
            self.async_on_remove(
                self._events.async_add_listener(self._handle_events_update)
            )
        self.async_on_remove(self._cancel_expiry)
        self._schedule_expiry()

    @property
    def available(self) -> bool:
        """Return whether the lock can be reached through a Bold Connect."""
        return super().available and self.device.gateway_id is not None

    @property
    def is_locked(self) -> bool:
        """Return whether the lock is not activated."""
        return not self._is_active

    @property
    def _is_active(self) -> bool:
        return self._active_until is not None and dt_util.utcnow() < self._active_until

    @property
    def _activation_time(self) -> timedelta:
        return self.device.activation_time or DEFAULT_ACTIVATION_TIME

    async def async_unlock(self, **kwargs: Any) -> None:
        """Activate the lock, so it can be turned by hand."""
        try:
            duration = await self.coordinator.client.remote_activation(self.device_id)
        except BoldError as err:
            raise _command_error(err) from err
        now = dt_util.utcnow()
        self._set_active(now, now + (duration or self._activation_time))
        self.async_write_ha_state()

    async def async_lock(self, **kwargs: Any) -> None:
        """End an activation early. Bold locks can't throw the bolt themselves."""
        if not self._is_active:
            return
        try:
            await self.coordinator.client.remote_deactivation(self.device_id)
        except BoldError as err:
            raise _command_error(err) from err
        self._set_inactive(dt_util.utcnow())
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated device data."""
        self._update_from_device()
        super()._handle_coordinator_update()

    def _update_from_device(self) -> None:
        """Pick up activations reported by the device, e.g. keep-active."""
        if self.device_id not in self.coordinator.data:
            return
        until = self.device.is_active_until
        now = dt_util.utcnow()
        if (
            until
            and until > now
            and (self._active_until is None or until > self._active_until)
        ):
            self._set_active(now, until)

    @callback
    def _handle_events_update(self) -> None:
        """Apply activation events from the event log."""
        assert self._events is not None
        changed = False
        for event in self._events.data or []:
            if event.device_id != self.device_id:
                continue
            if event.type == "DeviceActivation" and event.result == "Success":
                until = event.time + (event.activation_time or self._activation_time)
                if event.keep_active_until:
                    until = max(until, event.keep_active_until)
                if self._active_until is None or until > self._active_until:
                    self._set_active(event.time, until)
            elif event.type == "DeviceDeactivation":
                if self._activated_at is None or event.time >= self._activated_at:
                    self._set_inactive(event.time)
            else:
                continue
            changed = True
            if event.user_name:
                self._attr_changed_by = event.user_name
        if changed:
            self.async_write_ha_state()

    def _set_active(self, start: datetime, until: datetime) -> None:
        self._activated_at = start
        self._active_until = until
        self._schedule_expiry()

    def _set_inactive(self, at: datetime) -> None:
        self._active_until = at
        self._cancel_expiry()

    def _schedule_expiry(self) -> None:
        """Update the state when the activation ends."""
        self._cancel_expiry()
        if self.hass is None or not self._is_active:
            return
        assert self._active_until is not None
        self._unsub_expiry = async_track_point_in_utc_time(
            self.hass, self._expired, self._active_until
        )

    @callback
    def _cancel_expiry(self) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None

    @callback
    def _expired(self, _now: datetime) -> None:
        self._unsub_expiry = None
        self.async_write_ha_state()
