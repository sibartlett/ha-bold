"""Repair issues for problems users can fix themselves."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ISSUE_AFTER, TROUBLESHOOTING_URL
from .coordinator import BoldConfigEntry
from .keys import COMMAND_ACTIVATE
from .unlock import UnlockMethod

ISSUE_PREFIXES = ("connect_offline_", "lock_out_of_range_", "lock_no_route_")


def _local(time: datetime) -> str:
    return dt_util.as_local(time).strftime("%Y-%m-%d %H:%M")


@callback
def async_check_issues(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Raise issues for problems that have lasted a while, and clear fixed ones.

    Nothing is raised while Bold's cloud can't be reached: entities already
    show that, and there's nothing to fix locally.
    """
    data = entry.runtime_data
    devices = data.devices
    if not devices.last_update_success:
        return
    now = dt_util.utcnow()
    active: set[str] = set()
    locks = [device for device in devices.data.values() if device.is_lock]

    def create(issue_id: str, key: str, placeholders: dict[str, str]) -> None:
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

    for connect in devices.data.values():
        if not connect.is_gateway or (last_seen := connect.gateway_last_seen) is None:
            continue
        served = [lock.name for lock in locks if lock.gateway_id == connect.id]
        if served and now - last_seen > ISSUE_AFTER:
            create(
                f"connect_offline_{connect.id}",
                "connect_offline",
                {
                    "name": connect.name,
                    "last_seen": _local(last_seen),
                    "locks": ", ".join(served),
                },
            )

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
            create(f"lock_no_route_{lock.id}", "lock_no_route", {"name": lock.name})
            continue
        since = data.bluetooth.unreachable_since(lock.id)
        no_keys = data.bluetooth_keys.command(lock.id, COMMAND_ACTIVATE) is None
        if since is not None and now - since > ISSUE_AFTER and not no_keys:
            create(
                f"lock_out_of_range_{lock.id}",
                "lock_out_of_range",
                {"name": lock.name, "since": _local(since)},
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
