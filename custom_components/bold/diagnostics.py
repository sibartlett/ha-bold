"""Diagnostics for the Bold integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import BoldConfigEntry, BoldRuntimeData

TO_REDACT = {
    "webhook_id",
    "webhook_secret",
    "cloudhook_url",
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
# Objects naming a person or organization, e.g. a device's owner. Their
# "name" is redacted; other names, such as a device's, are kept.
NAMED_PARTIES = {"owner", "user", "account", "triggeredBy", "organization"}


def _redact(data: Any) -> Any:
    """Redact secrets and personal details from Bold's API data."""
    return _redact_party_names(async_redact_data(data, TO_REDACT))


def _redact_party_names(data: Any) -> Any:
    if isinstance(data, list):
        return [_redact_party_names(item) for item in data]
    if not isinstance(data, dict):
        return data
    redacted = {key: _redact_party_names(value) for key, value in data.items()}
    for key in NAMED_PARTIES & redacted.keys():
        if isinstance(party := redacted[key], dict) and party.get("name"):
            redacted[key] = {**party, "name": REDACTED}
    return redacted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BoldConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": _redact([device.raw for device in data.devices.data.values()]),
        "event_log_devices": data.events.device_ids,
        "recent_events": _redact([event.raw for event in data.events.recent_events]),
        "bluetooth": _bluetooth(data),
        "push": {
            "active": data.events.push_active,
            "last_push": (
                data.events.last_push.isoformat() if data.events.last_push else None
            ),
            "bold_webhooks": len(entry.data.get("bold_webhooks", {})),
            "cloudhook": "cloudhook_url" in entry.data,
        },
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
