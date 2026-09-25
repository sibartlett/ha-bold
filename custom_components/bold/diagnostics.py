"""Diagnostics for the Bold integration."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Coroutine
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .api import BoldClient, BoldError
from .coordinator import BoldConfigEntry

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

# Bluetooth handshakes and commands unlock the door, so only these fields are
# included as they are. Secrets are reduced to their size, and anything else to
# its name.
BLUETOOTH_KEY_FIELDS = {"deviceId", "expiration", "commandType"}
BLUETOOTH_SECRET_FIELDS = {"handshakeKey", "payload"}


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
        "bluetooth_keys": await _async_check_bluetooth_keys(
            data.client,
            [device.id for device in data.devices.data.values() if device.is_lock],
        ),
    }


async def _async_check_bluetooth_keys(
    client: BoldClient, device_ids: list[int]
) -> dict[str, Any]:
    """Check whether Bold provides Bluetooth keys for the locks, without them."""
    if not device_ids:
        return {}
    checks: dict[str, Coroutine[Any, Any, list[dict[str, Any]]]] = {
        "handshakes": client.get_bluetooth_handshakes(device_ids),
        "activate_commands": client.get_bluetooth_commands(device_ids, ["Activate"]),
        "deactivate_commands": client.get_bluetooth_commands(
            device_ids, ["Deactivate"]
        ),
    }
    result: dict[str, Any] = {}
    for name, check in checks.items():
        try:
            result[name] = [_describe_bluetooth_key(item) for item in await check]
        except BoldError as err:
            result[name] = {"error": f"{type(err).__name__}: {err}"}
    return result


def _describe_bluetooth_key(item: dict[str, Any]) -> dict[str, Any]:
    """Describe a Bluetooth handshake or command without its secrets."""
    description: dict[str, Any] = {}
    for field, value in item.items():
        if field in BLUETOOTH_KEY_FIELDS:
            description[field] = value
        elif field in BLUETOOTH_SECRET_FIELDS:
            description[field] = f"<{_secret_size(value)}>"
        else:
            description[field] = "<not shown>"
    return description


def _secret_size(value: Any) -> str:
    """Return the size of a base64 encoded secret."""
    if not isinstance(value, str):
        return type(value).__name__
    try:
        return f"{len(base64.b64decode(value, validate=True))} bytes"
    except binascii.Error:
        return f"{len(value)} characters"
