"""A lock's door sensor, for the Bold integration.

A door can't open with the bolt thrown, so a lock linked to its door's contact
sensor can tell when it missed being unlocked: the door opened after it last
reported the bolt locked.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

ATTR_DOOR_SENSOR = "door_sensor"
ATTR_DOOR_OPENED_AT = "door_opened_at"
ATTR_DOOR_OPEN = "door_open"
ATTR_DOOR_SEEN_AT = "door_seen_at"


class DoorSensor:
    """Follows a door's contact sensor, remembering when the door last opened."""

    def __init__(self, entity_id: str, link_id: str) -> None:
        """Initialize the door sensor.

        link_id identifies the sensor as the link stores it, which stays the
        same when its entity ID changes.
        """
        self.entity_id = entity_id
        self._link_id = link_id
        # When the door last opened, by Home Assistant's clock.
        self.opened_at: datetime | None = None
        # Whether the door was last seen open, ignoring an unavailable sensor.
        self._was_open: bool | None = None

    @callback
    def async_start(
        self,
        hass: HomeAssistant,
        stored: Mapping[str, Any] | None,
        on_change: Callable[[], None],
    ) -> CALLBACK_TYPE:
        """Follow the sensor, from what was stored before a restart.

        Calls on_change when the sensor changes, and returns how to stop.
        """
        seen_at: datetime | None = None
        # What was stored for another sensor, before the link was changed,
        # says nothing about this door.
        if stored is not None and stored.get(ATTR_DOOR_SENSOR) == self._link_id:
            self.opened_at = _stored_time(stored.get(ATTR_DOOR_OPENED_AT))
            seen_at = _stored_time(stored.get(ATTR_DOOR_SEEN_AT))
            if isinstance(open_ := stored.get(ATTR_DOOR_OPEN), bool):
                self._was_open = open_
        if state := hass.states.get(self.entity_id):
            # Opened while Home Assistant wasn't watching: at the earliest, when
            # it last saw the door closed.
            self._seen(state, seen_at or state.last_changed)

        @callback
        def changed(event: Event[EventStateChangedData]) -> None:
            if (new := event.data["new_state"]) is not None:
                old = event.data["old_state"]
                # Back from unavailable: opened, at the earliest, when it went.
                unseen_since = (
                    old.last_changed
                    if old is not None and old.state not in (STATE_ON, STATE_OFF)
                    else new.last_changed
                )
                self._seen(new, unseen_since)
            on_change()

        return async_track_state_change_event(hass, self.entity_id, changed)

    def as_dict(self) -> dict[str, Any]:
        """Return what to remember across restarts: when it last opened, and how it was."""
        return {
            ATTR_DOOR_SENSOR: self._link_id,
            ATTR_DOOR_OPENED_AT: self.opened_at.isoformat() if self.opened_at else None,
            ATTR_DOOR_OPEN: self._was_open,
            ATTR_DOOR_SEEN_AT: dt_util.utcnow().isoformat(),
        }

    def _seen(self, state: State, opened_at: datetime) -> None:
        """Take the door's state, if the sensor knows it."""
        if state.state not in (STATE_ON, STATE_OFF):
            return
        is_open = state.state == STATE_ON
        if is_open and self._was_open is not True:
            self._opened(opened_at)
        self._was_open = is_open

    def _opened(self, at: datetime) -> None:
        if self.opened_at is None or at > self.opened_at:
            self.opened_at = at


def _stored_time(value: Any) -> datetime | None:
    """Return a time stored across restarts, if it's one."""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None
