"""Tests for Bold repair issues."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_OPTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.const import API_URL, DEVICE_SCAN_INTERVAL, DOMAIN

from .conftest import (
    GATEWAY,
    GATEWAY_ID,
    LOCK,
    LOCK_ID,
    FakeBluetooth,
    mock_bluetooth_keys,
)

CONNECT_ISSUE = f"connect_offline_{GATEWAY_ID}"
OUT_OF_RANGE_ISSUE = f"lock_out_of_range_{LOCK_ID}"
NO_ROUTE_ISSUE = f"lock_no_route_{LOCK_ID}"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time, 5 minutes after the Connect was last seen."""
    freezer.move_to("2026-09-24T12:00:00+00:00")
    return freezer


def _connect(last_seen: str) -> dict:
    return {**GATEWAY, "gateway": {**GATEWAY["gateway"], "lastSeen": last_seen}}


def _mock_devices(aioclient_mock: AiohttpClientMocker, devices: list[dict]) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", json=devices)
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    mock_bluetooth_keys(aioclient_mock)


async def _setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    devices: list[dict],
) -> None:
    _mock_devices(aioclient_mock, devices)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def _poll_devices(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(DEVICE_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _issue(issue_registry: ir.IssueRegistry, issue_id: str) -> ir.IssueEntry | None:
    return issue_registry.async_get_issue(DOMAIN, issue_id)


async def test_connect_offline(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an issue for a Connect not seen for over an hour, until it's back."""
    await _setup(hass, mock_config_entry, aioclient_mock, [LOCK, GATEWAY])
    assert _issue(issue_registry, CONNECT_ISSUE) is None

    _mock_devices(aioclient_mock, [LOCK, _connect("2026-09-24T10:30:00Z")])
    await _poll_devices(hass, frozen_time)
    issue = _issue(issue_registry, CONNECT_ISSUE)
    assert issue.translation_key == "connect_offline"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert issue.translation_placeholders["name"] == "Bold Connect"
    assert issue.translation_placeholders["locks"] == "Front Door"

    _mock_devices(aioclient_mock, [LOCK, _connect("2026-09-24T12:09:00Z")])
    await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, CONNECT_ISSUE) is None


async def test_ignored_issue_stays_ignored(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an ignored issue stays ignored while the problem lasts."""
    await _setup(
        hass,
        mock_config_entry,
        aioclient_mock,
        [LOCK, _connect("2026-09-24T10:30:00Z")],
    )
    ir.async_ignore_issue(hass, DOMAIN, CONNECT_ISSUE, True)
    await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, CONNECT_ISSUE).dismissed_version is not None


async def test_unused_connect_offline(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test no issue for an offline Connect that no lock uses."""
    await _setup(
        hass,
        mock_config_entry,
        aioclient_mock,
        [{**LOCK, "gateway": None}, _connect("2026-09-24T08:00:00Z")],
    )
    assert _issue(issue_registry, CONNECT_ISSUE) is None


async def test_no_issues_while_bold_is_unreachable(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test issues aren't raised or cleared from stale data."""
    await _setup(
        hass,
        mock_config_entry,
        aioclient_mock,
        [LOCK, _connect("2026-09-24T10:30:00Z")],
    )
    assert _issue(issue_registry, CONNECT_ISSUE) is not None
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/v2/devices", status=500)
    aioclient_mock.get(f"{API_URL}/v2/events", status=500)
    await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, CONNECT_ISSUE) is not None


async def test_lock_without_bluetooth_or_connect(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test an issue for a lock without a Connect, with no Bluetooth in Home Assistant."""
    await _setup(hass, mock_config_entry, aioclient_mock, [{**LOCK, "gateway": None}])
    assert _issue(issue_registry, NO_ROUTE_ISSUE).translation_placeholders == {
        "name": "Front Door"
    }


async def test_lock_out_of_bluetooth_range(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test an issue for a Bluetooth-only lock out of range for over an hour."""
    fake_bluetooth.reachable.clear()
    await _setup(hass, mock_config_entry, aioclient_mock, [{**LOCK, "gateway": None}])
    tracker = mock_config_entry.runtime_data.bluetooth

    # Not raised straight away.
    await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, OUT_OF_RANGE_ISSUE) is None

    for _ in range(6):
        await _poll_devices(hass, frozen_time)
    issue = _issue(issue_registry, OUT_OF_RANGE_ISSUE)
    assert issue.translation_placeholders["name"] == "Front Door"

    # Heard again, it's cleared.
    tracker._reachable.add(LOCK_ID)  # noqa: SLF001
    await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, OUT_OF_RANGE_ISSUE) is None
    assert _issue(issue_registry, NO_ROUTE_ISSUE) is None


async def test_bluetooth_only_lock_out_of_range(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test a lock with a Connect only gets an issue when set to Bluetooth only."""
    init_integration.runtime_data.bluetooth.async_mark_unreachable(LOCK_ID)
    _mock_devices(aioclient_mock, [LOCK, _connect("2026-09-24T13:10:00Z")])
    for _ in range(7):
        await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, OUT_OF_RANGE_ISSUE) is None

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: "select.front_door_unlock_method",
            ATTR_OPTION: "bluetooth_only",
        },
        blocking=True,
    )
    await _poll_devices(hass, frozen_time)
    assert _issue(issue_registry, OUT_OF_RANGE_ISSUE) is not None


async def test_issues_removed_with_integration(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test removing the integration removes its issues."""
    await _setup(
        hass,
        mock_config_entry,
        aioclient_mock,
        [LOCK, _connect("2026-09-24T10:30:00Z")],
    )
    assert _issue(issue_registry, CONNECT_ISSUE) is not None
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(issue_registry, CONNECT_ISSUE) is None


def test_issue_after_is_an_hour() -> None:
    """Keep the documented threshold in sync."""
    from custom_components.bold.const import ISSUE_AFTER  # noqa: PLC0415

    assert timedelta(hours=1) == ISSUE_AFTER
