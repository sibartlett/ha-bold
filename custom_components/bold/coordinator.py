"""Data update coordinators for the Bold integration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .boldsmartlock import (
    BoldAuthError,
    BoldClient,
    BoldDevice,
    BoldError,
    BoldEvent,
    BoldEventType,
    BoldForbiddenError,
)
from .const import (
    DEVICE_SCAN_INTERVAL,
    DOMAIN,
    EVENT_CATCH_UP_INTERVAL,
    EVENT_CATCH_UP_LOOKBACK,
    EVENT_POLL_OVERLAP,
    EVENT_PUSH_SCAN_INTERVAL,
    EVENT_SCAN_INTERVAL,
    PUSHED_EVENT_TYPES,
)
from .keys import BoldBluetoothKeys
from .tracker import BoldBluetoothTracker
from .unlock import BoldUnlockMethods

_LOGGER = logging.getLogger(__name__)

# Number of raw events kept for diagnostics.
RECENT_EVENTS = 25

type BoldConfigEntry = ConfigEntry[BoldRuntimeData]


@dataclass
class BoldRuntimeData:
    """Runtime data for a Bold config entry."""

    client: BoldClient
    devices: BoldDeviceCoordinator
    events: BoldEventCoordinator
    bluetooth_keys: BoldBluetoothKeys
    bluetooth: BoldBluetoothTracker
    unlock_methods: BoldUnlockMethods


class BoldDeviceCoordinator(DataUpdateCoordinator[dict[int, BoldDevice]]):
    """Polls the devices of a Bold account."""

    config_entry: BoldConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BoldConfigEntry, client: BoldClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} devices",
            update_interval=DEVICE_SCAN_INTERVAL,
        )
        self.client = client
        # Bold Connect device ID -> device registry ID, for linking locks.
        self.connect_device_ids: dict[int | None, str] = {}

    async def _async_update_data(self) -> dict[int, BoldDevice]:
        """Fetch all devices."""
        try:
            devices = await self.client.get_devices()
        except BoldAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except BoldError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return {device.id: device for device in devices}


class BoldEventCoordinator(DataUpdateCoordinator[list[BoldEvent]]):
    """Polls the event log of a set of Bold devices.

    The data is the list of events that are new since the previous poll,
    oldest first. A device's first poll only records which of its events
    already exist, so history is not replayed when Home Assistant starts or
    a lock is added. The device list is kept up to date by the integration.

    Polls look back a couple of minutes. Locks upload events when something
    next syncs with them, so every so often a catch-up poll looks back an hour
    to pick up events that arrived late.
    """

    config_entry: BoldConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BoldConfigEntry,
        client: BoldClient,
        device_ids: list[int],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} events",
            update_interval=EVENT_SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.device_ids = device_ids
        self.recent_events: deque[BoldEvent] = deque(maxlen=RECENT_EVENTS)
        # Status and debug events from before startup, which carry voltages.
        self.status_history: list[BoldEvent] = []
        self._cursor: datetime | None = None
        # Seen events, by BoldEvent.key.
        self._seen: dict[tuple[str, int | None, datetime, bool | None], datetime] = {}
        self._primed: set[int] = set()
        self._last_catch_up: datetime | None = None
        self.push_active = False
        self.last_push: datetime | None = None

    async def async_load_status_history(self, since: datetime) -> None:
        """Fetch recent status and debug events, e.g. for battery voltages."""
        if not self.device_ids:
            return
        try:
            events = await self.client.get_events(
                self.device_ids, since, [BoldEventType.STATUS, BoldEventType.DEBUG]
            )
        except BoldError as err:
            _LOGGER.debug("Couldn't fetch recent status events: %s", err)
            return
        self.status_history = sorted(events, key=lambda event: event.sort_key)

    async def _async_update_data(self) -> list[BoldEvent]:
        """Fetch events since the last poll."""
        now = dt_util.utcnow()
        cursor = self._cursor or now
        if not (device_ids := list(self.device_ids)):
            self._cursor = cursor
            return []
        # Catch up periodically, and when priming devices, so the hour they
        # record as already seen is the hour catch-ups look back over.
        catch_up = (
            self._last_catch_up is None
            or now - self._last_catch_up >= EVENT_CATCH_UP_INTERVAL
            or not self._primed.issuperset(device_ids)
        )
        since = cursor - EVENT_POLL_OVERLAP
        if catch_up:
            since = min(since, now - EVENT_CATCH_UP_LOOKBACK)
        try:
            events = await self.client.get_events(device_ids, since)
        except BoldAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except BoldForbiddenError:
            _LOGGER.warning(
                "This Bold account is not allowed to read the event log; "
                "activity will not be tracked"
            )
            self.update_interval = None
            return []
        except BoldError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        new_events = self._accept(events, now)
        if catch_up:
            self._last_catch_up = now
        primed, self._primed = self._primed, set(device_ids)
        delivered = [event for event in new_events if event.device_id in primed]

        # A poll finding an event the webhook should have pushed means pushes
        # stopped working: poll often again until the next one arrives.
        if self.push_active and any(
            event.type in PUSHED_EVENT_TYPES for event in delivered
        ):
            _LOGGER.info(
                "Bold's webhook missed an event; polling every %s until it "
                "delivers again",
                EVENT_SCAN_INTERVAL,
            )
            self.async_set_push_active(active=False)
        return delivered

    def _accept(self, events: list[BoldEvent], now: datetime) -> list[BoldEvent]:
        """Record events, returning those not seen before, oldest first."""
        cursor = self._cursor or now
        new_events = sorted(
            (event for event in events if event.key not in self._seen),
            key=lambda event: event.sort_key,
        )
        for event in new_events:
            self._seen[event.key] = event.time
            self.recent_events.append(event)
            cursor = max(cursor, event.time)
        self._cursor = cursor
        # Forget events older than any poll can return again.
        horizon = (
            min(cursor - EVENT_POLL_OVERLAP, now - EVENT_CATCH_UP_LOOKBACK)
            - EVENT_POLL_OVERLAP
        )
        self._seen = {key: time for key, time in self._seen.items() if time >= horizon}
        return new_events

    @callback
    def async_handle_push(self, events: list[BoldEvent]) -> None:
        """Handle events Bold pushed to the webhook."""
        self.last_push = dt_util.utcnow()
        if not self.push_active:
            _LOGGER.info("Bold's webhook is delivering events again")
            self.async_set_push_active(active=True)
        if new_events := [
            event
            for event in self._accept(events, self.last_push)
            if event.device_id in self._primed
        ]:
            self.async_set_updated_data(new_events)

    @callback
    def async_set_push_active(self, *, active: bool) -> None:
        """Poll less often while Bold pushes events to the webhook."""
        self.push_active = active
        self.update_interval = (
            EVENT_PUSH_SCAN_INTERVAL if active else EVENT_SCAN_INTERVAL
        )
