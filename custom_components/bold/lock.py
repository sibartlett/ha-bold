"""Lock platform for the Bold integration.

A Bold lock is not motorised: activating it lets someone turn the cylinder by
hand for a short time.

Upgraded locks report their bolt position: the lock shows that, and shows as
unlocking while it's activated with the bolt still thrown. Other locks show as
unlocked while activated and locked otherwise, as an assumed state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .boldsmartlock import (
    COMMAND_ACTIVATE,
    COMMAND_DEACTIVATE,
    BoldAuthError,
    BoldBluetoothError,
    BoldBluetoothUnavailableError,
    BoldDevice,
    BoldError,
    BoldEvent,
    BoldEventType,
    BoldFirmwareOutdatedError,
    BoldGatewayNotFoundError,
    BoldRateLimitError,
    async_send_command,
)
from .const import (
    BLUETOOTH_FALLBACK_TIMEOUT,
    BLUETOOTH_MIN_RSSI,
    BLUETOOTH_TIMEOUT,
    DEFAULT_ACTIVATION_TIME,
    DOMAIN,
)
from .coordinator import BoldConfigEntry, BoldRuntimeData
from .entity import BoldEntity, async_add_device_entities
from .unlock import ROUTES, Route, UnlockMethod

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold locks."""
    data = entry.runtime_data
    async_add_device_entities(
        entry,
        async_add_entities,
        lambda device: (
            [BoldLock(data, device)]
            if device.is_lock and (device.remote_access or data.bluetooth.enabled)
            else []
        ),
    )


def _command_error(err: BoldError) -> HomeAssistantError:
    """Translate an API error from a lock command."""
    if isinstance(err, BoldBluetoothUnavailableError):
        key = "bluetooth_unavailable"
    elif isinstance(err, BoldBluetoothError):
        key = "bluetooth_failed"
    elif isinstance(err, BoldRateLimitError):
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

    def __init__(self, data: BoldRuntimeData, device: BoldDevice) -> None:
        """Initialize the lock."""
        super().__init__(data.devices, device, None)
        self._data = data
        self._events = data.events
        self._bluetooth_lock = asyncio.Lock()
        self._disconnecting: asyncio.Task[None] | None = None
        self._activated_at: datetime | None = None
        self._active_until: datetime | None = None
        self._unsub_expiry: CALLBACK_TYPE | None = None
        self._bolt_locked: bool | None = None
        self._bolt_changed: datetime | None = None
        self._update_from_device()

    async def async_added_to_hass(self) -> None:
        """Subscribe to events and schedule the end of any activation."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._events.async_add_listener(self._handle_events_update)
        )
        # Routes to the lock can open up or close.
        self.async_on_remove(
            self._data.bluetooth.async_add_listener(
                self.device_id, self.async_write_ha_state
            )
        )
        self.async_on_remove(
            self._data.bluetooth_keys.async_add_listener(self.async_write_ha_state)
        )
        self.async_on_remove(
            self._data.unlock_methods.async_add_listener(
                self.device_id, self.async_write_ha_state
            )
        )
        self.async_on_remove(self._cancel_expiry)
        self._schedule_expiry()

    @property
    def available(self) -> bool:
        """Return whether the lock can be reached at all.

        A lock in Bluetooth range stays available when Bold's cloud is down.
        """
        return self.device_id in self.coordinator.data and bool(
            self._routes(COMMAND_ACTIVATE)
        )

    def _routes(self, command_type: str) -> list[Route]:
        """Return the usable routes to the lock, in order of preference."""
        method = self._data.unlock_methods.get(self.device_id)
        connect = self._connect_usable()
        # Only try Bluetooth ahead of a usable Connect with a strong signal. As a
        # fallback, or the only way, any signal is worth a try.
        min_rssi = (
            BLUETOOTH_MIN_RSSI
            if connect and method is UnlockMethod.PREFER_BLUETOOTH
            else None
        )
        bluetooth = (
            self._data.bluetooth.is_reachable(self.device_id, min_rssi)
            and self._data.bluetooth_keys.command(self.device_id, command_type)
            is not None
        )
        usable = {Route.CONNECT: connect, Route.BLUETOOTH: bluetooth}
        return [route for route in ROUTES[method] if usable[route]]

    def _connect_usable(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.device.gateway_id is not None
            and self.device.remote_access
        )

    @property
    def _reports_bolt(self) -> bool:
        """Return whether the lock's bolt position is known."""
        return self.device.reports_bolt and self._bolt_locked is not None

    @property
    def assumed_state(self) -> bool:
        """Return whether the state is assumed, without a bolt position."""
        return not self._reports_bolt

    @property
    def is_locked(self) -> bool:
        """Return whether the bolt is thrown, or else the lock isn't activated."""
        if self._reports_bolt:
            return bool(self._bolt_locked)
        return not self._is_active

    @property
    def is_unlocking(self) -> bool:
        """Return whether the lock is being activated, or ready to be turned."""
        return bool(self._attr_is_unlocking) or (
            self._reports_bolt and bool(self._bolt_locked) and self._is_active
        )

    @property
    def _is_active(self) -> bool:
        return self._active_until is not None and dt_util.utcnow() < self._active_until

    @property
    def _activation_time(self) -> timedelta:
        return self.device.activation_time or DEFAULT_ACTIVATION_TIME

    async def async_unlock(self, **kwargs: Any) -> None:
        """Activate the lock, so it can be turned by hand."""
        duration = await self._async_send_showing_progress(COMMAND_ACTIVATE)
        now = dt_util.utcnow()
        self._set_active(now, now + (duration or self._activation_time))
        self.async_write_ha_state()

    async def async_lock(self, **kwargs: Any) -> None:
        """End an activation early. Bold locks can't throw the bolt themselves."""
        if not self._is_active:
            if self._reports_bolt and not self._bolt_locked:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="bolt_open",
                    translation_placeholders={"name": self.device.name},
                )
            return
        await self._async_send_showing_progress(COMMAND_DEACTIVATE)
        self._set_inactive(dt_util.utcnow())
        self.async_write_ha_state()

    async def _async_send_showing_progress(self, command_type: str) -> timedelta | None:
        """Send a command, showing the lock as unlocking or locking meanwhile."""
        unlocking = command_type == COMMAND_ACTIVATE
        self._attr_is_unlocking = unlocking
        self._attr_is_locking = not unlocking
        self.async_write_ha_state()
        try:
            return await self._async_send(command_type)
        except HomeAssistantError:
            self._attr_is_unlocking = self._attr_is_locking = False
            self.async_write_ha_state()
            raise
        finally:
            # On success, the caller writes the new state.
            self._attr_is_unlocking = self._attr_is_locking = False

    async def _async_send(self, command_type: str) -> timedelta | None:
        """Send a command over the preferred route, falling back to others."""
        routes = self._routes(command_type)
        if not routes:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unreachable",
                translation_placeholders={"name": self.device.name},
            )
        error: BoldError | None = None
        for index, route in enumerate(routes):
            fallback = index + 1 < len(routes)
            try:
                if route is Route.BLUETOOTH:
                    return await self._async_send_bluetooth(
                        command_type,
                        BLUETOOTH_FALLBACK_TIMEOUT if fallback else BLUETOOTH_TIMEOUT,
                    )
                return await self._async_send_connect(command_type)
            except BoldError as err:
                error = err
                if fallback:
                    _LOGGER.warning(
                        "Couldn't reach %s over %s (%s), trying %s",
                        self.device.name,
                        route,
                        err,
                        routes[index + 1],
                    )
        assert error is not None
        raise _command_error(error) from error

    async def _async_send_connect(self, command_type: str) -> timedelta | None:
        """Send a command through the Bold Connect, via Bold's cloud."""
        client = self.coordinator.client
        if command_type == COMMAND_ACTIVATE:
            return await client.remote_activation(self.device_id)
        await client.remote_deactivation(self.device_id)
        return None

    async def _async_send_bluetooth(
        self, command_type: str, timeout: float
    ) -> timedelta | None:
        """Send a command to the lock over Bluetooth."""
        keys = self._data.bluetooth_keys.get(self.device_id)
        command = self._data.bluetooth_keys.command(self.device_id, command_type)
        ble_device = self._data.bluetooth.ble_device(self.device_id)
        if keys is None or command is None or ble_device is None:
            raise BoldBluetoothUnavailableError("Not reachable over Bluetooth")
        async with self._bluetooth_lock:
            # Don't connect while still disconnecting from the last command.
            if self._disconnecting is not None:
                await self._disconnecting
                self._disconnecting = None
            seconds = await async_send_command(
                ble_device,
                keys.handshake_key.value,
                keys.handshake_payload.value,
                command,
                timeout=timeout,
                disconnect_later=self._disconnect_later,
            )
        return timedelta(seconds=seconds) if seconds else None

    @callback
    def _disconnect_later(self, disconnect: Coroutine[Any, Any, None]) -> None:
        """Disconnect in the background, so the result shows straight away."""
        self._disconnecting = (
            self.coordinator.config_entry.async_create_background_task(
                self.hass, disconnect, f"Disconnect from {self.device.name}"
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated device data."""
        self._update_from_device()
        super()._handle_coordinator_update()

    def _update_from_device(self) -> None:
        """Pick up activations reported by the device, e.g. keep-active."""
        if self.device_id not in self.coordinator.data:
            return
        self._update_bolt(self.device.bolt_locked, self.device.bolt_changed)
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
        changed = False
        for event in self._events.data or []:
            if event.device_id == self.device_id:
                changed = self._apply_event(event) or changed
        if changed:
            self.async_write_ha_state()

    def _apply_event(self, event: BoldEvent) -> bool:
        """Apply an event from the event log, returning whether it applied."""
        if event.type == BoldEventType.LOCKED:
            self._update_bolt(event.bolt_locked, event.time)
            return True
        if event.type == BoldEventType.ACTIVATION and event.successful:
            until = event.time + (event.activation_time or self._activation_time)
            if event.keep_active_until:
                until = max(until, event.keep_active_until)
            if self._active_until is None or until > self._active_until:
                self._set_active(event.time, until)
        elif event.type == BoldEventType.DEACTIVATION:
            if self._activated_at is None or event.time >= self._activated_at:
                self._set_inactive(event.time)
        else:
            return False
        if event.user_name:
            self._attr_changed_by = event.user_name
        return True

    def _update_bolt(self, locked: bool | None, changed: datetime | None) -> None:
        """Take a bolt position, unless an already known one is newer."""
        if locked is None:
            return
        if (
            changed is not None
            and self._bolt_changed is not None
            and changed < self._bolt_changed
        ):
            return
        self._bolt_locked = locked
        self._bolt_changed = changed or self._bolt_changed

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
