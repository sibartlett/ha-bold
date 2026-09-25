"""Diagnostics for the Bold integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

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
        "event_log_enabled": data.events is not None,
        "recent_events": (
            async_redact_data(
                [event.raw for event in data.events.recent_events], TO_REDACT
            )
            if data.events is not None
            else []
        ),
    }
