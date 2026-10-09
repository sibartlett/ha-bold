"""Repair issues for problems users can fix themselves."""

from collections.abc import Iterator
from datetime import datetime
from itertools import chain

from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import dt as dt_util

from .boldsmartlock import COMMAND_ACTIVATE, BoldDevice
from .const import (
    CONF_DOOR_SENSOR,
    CONF_LOCK,
    DOMAIN,
    DOOR_SENSORS_URL,
    ISSUE_AFTER,
    SUBENTRY_DOOR_SENSOR,
    TROUBLESHOOTING_URL,
)
from .coordinator import BoldConfigEntry, BoldRuntimeData
from .links import title_lock_name
from .unlock import UnlockMethod

ISSUE_PREFIXES = (
    "connect_offline_",
    "lock_out_of_range_",
    "lock_no_route_",
    "door_sensor_missing_",
    "door_sensor_no_locked_status_",
)

# Where to learn more, if not troubleshooting, by translation key.
LEARN_MORE_URLS = {
    "door_sensor_missing": DOOR_SENSORS_URL,
    "door_sensor_no_locked_status": DOOR_SENSORS_URL,
}


def _local(time: datetime) -> str:
    return dt_util.as_local(time).strftime("%Y-%m-%d %H:%M")


# An issue to raise: its ID, translation key and placeholders.
type Issue = tuple[str, str, dict[str, str]]


def _connect_issues(
    devices: list[BoldDevice], locks: list[BoldDevice], now: datetime
) -> Iterator[Issue]:
    """Bold Connects that serve locks, and Bold hasn't heard from."""
    for connect in devices:
        if not connect.is_gateway or (last_seen := connect.gateway_last_seen) is None:
            continue
        served = [lock.name for lock in locks if lock.gateway_id == connect.id]
        if served and now - last_seen > ISSUE_AFTER:
            yield (
                f"connect_offline_{connect.id}",
                "connect_offline",
                {
                    "name": connect.name,
                    "last_seen": _local(last_seen),
                    "locks": ", ".join(served),
                },
            )


def _lock_issues(
    data: BoldRuntimeData, locks: list[BoldDevice], now: datetime
) -> Iterator[Issue]:
    """Locks that can only be unlocked over Bluetooth, and aren't in range."""
    for lock in locks:
        method = data.unlock_methods.get(lock.id)
        if (
            lock.gateway_id is not None
            and lock.remote_access
            and method is not UnlockMethod.BLUETOOTH_ONLY
        ):
            # Reachable through the Connect; if that's offline, it has an issue.
            continue
        if not data.bluetooth.enabled:
            yield (f"lock_no_route_{lock.id}", "lock_no_route", {"name": lock.name})
            continue
        since = data.bluetooth.unreachable_since(lock.id)
        has_keys = data.bluetooth_keys.command(lock.id, COMMAND_ACTIVATE) is not None
        if since is not None and now - since > ISSUE_AFTER and has_keys:
            yield (
                f"lock_out_of_range_{lock.id}",
                "lock_out_of_range",
                {"name": lock.name, "since": _local(since)},
            )


def _link_issues(hass: HomeAssistant, entry: BoldConfigEntry) -> Iterator[Issue]:
    """Door sensor links that no longer do anything."""
    registry = er.async_get(hass)
    devices = entry.runtime_data.devices.data
    for subentry in entry.get_subentries_of_type(SUBENTRY_DOOR_SENSOR):
        lock_id = subentry.data[CONF_LOCK]
        placeholders = {"lock": title_lock_name(subentry.title)}
        door = er.async_resolve_entity_id(registry, subentry.data[CONF_DOOR_SENSOR])
        if door is None or (
            # A sensor outside the registry has no state until its integration
            # has set it up, which may be after Bold, until Home Assistant is
            # running.
            hass.state is CoreState.running
            and registry.async_get(door) is None
            and hass.states.get(door) is None
        ):
            yield (
                f"door_sensor_missing_{lock_id}",
                "door_sensor_missing",
                placeholders,
            )
        elif (lock := devices.get(lock_id)) is not None and not lock.reports_bolt:
            yield (
                f"door_sensor_no_locked_status_{lock_id}",
                "door_sensor_no_locked_status",
                placeholders,
            )


@callback
def async_check_issues(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Raise issues for problems that have lasted a while, and clear fixed ones.

    Only called after a successful device poll, so nothing is raised or
    cleared from stale data while Bold's cloud can't be reached: entities
    already show that, and there's nothing to fix locally.
    """
    data = entry.runtime_data
    now = dt_util.utcnow()
    devices = list(data.devices.data.values())
    locks = [device for device in devices if device.is_lock]
    active: set[str] = set()
    for issue_id, key, placeholders in chain(
        _connect_issues(devices, locks, now),
        _lock_issues(data, locks, now),
        _link_issues(hass, entry),
    ):
        active.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
            learn_more_url=LEARN_MORE_URLS.get(key, TROUBLESHOOTING_URL),
        )

    for domain, issue_id in list(ir.async_get(hass).issues):
        if (
            domain == DOMAIN
            and issue_id.startswith(ISSUE_PREFIXES)
            and issue_id not in active
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_delete_issues(hass: HomeAssistant) -> None:
    """Delete all of the integration's issues."""
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
