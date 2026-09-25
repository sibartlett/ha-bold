"""Repair issues for problems users can fix themselves."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from itertools import chain

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .boldsmartlock import COMMAND_ACTIVATE, BoldDevice
from .const import DOMAIN, ISSUE_AFTER, TROUBLESHOOTING_URL
from .coordinator import BoldConfigEntry, BoldRuntimeData
from .unlock import UnlockMethod

ISSUE_PREFIXES = ("connect_offline_", "lock_out_of_range_", "lock_no_route_")


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
        _connect_issues(devices, locks, now), _lock_issues(data, locks, now)
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
            learn_more_url=TROUBLESHOOTING_URL,
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
