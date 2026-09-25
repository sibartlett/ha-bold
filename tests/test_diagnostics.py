"""Tests for Bold diagnostics."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bold.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test diagnostics include devices and redact the token."""
    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    assert diagnostics["entry"]["token"] == REDACTED
    assert [device["name"] for device in diagnostics["devices"]] == [
        "Front Door",
        "Bold Connect",
    ]
    assert diagnostics["event_log_devices"] == [1]
    assert diagnostics["recent_events"] == []
