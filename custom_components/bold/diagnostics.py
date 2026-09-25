"""Diagnostics for the Bold integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import BoldConfigEntry, BoldRuntimeData

TO_REDACT = {
    "access_token",
    "refresh_token",
    "token",
    "email",
    "emailAddress",
    "firstName",
    "lastName",
    "phone",
    "externalId",
    "userExternalId",
    "webKey",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BoldConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": async_redact_data(
            [device.raw for device in data.devices.data.values()], TO_REDACT
        ),
        "event_log_devices": data.events.device_ids,
        "recent_events": async_redact_data(
            [event.raw for event in data.events.recent_events], TO_REDACT
        ),
        "bluetooth": _bluetooth(data),
    }


def _bluetooth(data: BoldRuntimeData) -> dict[str, Any]:
    """Describe Bluetooth support, without the keys, which unlock the door."""
    locks: dict[str, Any] = {}
    for device in data.devices.data.values():
        if not device.is_lock:
            continue
        keys = data.bluetooth_keys.get(device.id)
        locks[str(device.id)] = {
            "reachable": data.bluetooth.is_reachable(device.id),
            "unlock_method": data.unlock_methods.get(device.id).value,
            "handshake_expires": (
                keys.handshake_payload.expires.isoformat() if keys else None
            ),
            "commands": (
                {
                    command_type: command.expires.isoformat()
                    for command_type, command in keys.commands.items()
                }
                if keys
                else {}
            ),
        }
    return {"enabled": data.bluetooth.enabled, "locks": locks}
