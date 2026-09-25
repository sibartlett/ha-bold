"""Data update coordinators for the Bold integration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BoldAuthError,
    BoldClient,
    BoldDevice,
    BoldError,
    BoldEvent,
    BoldForbiddenError,
)
from .const import DEVICE_SCAN_INTERVAL, DOMAIN, EVENT_POLL_OVERLAP, EVENT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Number of raw events kept for diagnostics.
RECENT_EVENTS = 25

type BoldConfigEntry = ConfigEntry[BoldRuntimeData]


@dataclass
class BoldRuntimeData:
    """Runtime data for a Bold config entry."""

    client: BoldClient
    devices: BoldDeviceCoordinator
    events: BoldEventCoordinator | None


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
    oldest first. The first poll only records which events already exist,
    so history is not replayed when Home Assistant starts.
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
        self._cursor: datetime | None = None
        self._seen: dict[int, datetime] = {}

    async def _async_update_data(self) -> list[BoldEvent]:
        """Fetch events since the last poll."""
        first_poll = self._cursor is None
        cursor = self._cursor or dt_util.utcnow()
        try:
            events = await self.client.get_events(
                self.device_ids, cursor - EVENT_POLL_OVERLAP
            )
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

        new_events = sorted(
            (event for event in events if event.id not in self._seen),
            key=lambda event: (event.time, event.id),
        )
        for event in new_events:
            self._seen[event.id] = event.time
            self.recent_events.append(event)
            cursor = max(cursor, event.time)

        # Events older than the overlap window can't be returned again.
        self._cursor = cursor
        horizon = cursor - 2 * EVENT_POLL_OVERLAP
        self._seen = {
            event_id: time for event_id, time in self._seen.items() if time >= horizon
        }

        if first_poll:
            return []
        return new_events
