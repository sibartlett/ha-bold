"""Tests for Bold repair issues."""

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_OPTION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import DEVICE_SCAN_INTERVAL, DOMAIN

from .conftest import (
    GATEWAY,
    GATEWAY_ID,
    LOCK,
    LOCK_ID,
    FakeBluetooth,
    advance,
    mock_bluetooth_keys,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("frozen_time")

CONNECT_ISSUE = f"connect_offline_{GATEWAY_ID}"
OUT_OF_RANGE_ISSUE = f"lock_out_of_range_{LOCK_ID}"
NO_ROUTE_ISSUE = f"lock_no_route_{LOCK_ID}"


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
    mock_bluetooth_keys(aioclient_mock)
    await setup_integration(hass, mock_config_entry, aioclient_mock, devices)


def _local(time: str) -> str:
    """Format a time as issues show it, in Home Assistant's time zone."""
    return dt_util.as_local(datetime.fromisoformat(time)).strftime("%Y-%m-%d %H:%M")


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
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    issue = _issue(issue_registry, CONNECT_ISSUE)
    assert issue.translation_key == "connect_offline"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert issue.translation_placeholders == {
        "name": "Bold Connect",
        "locks": "Front Door",
        "last_seen": _local("2026-09-24T10:30:00+00:00"),
    }

    _mock_devices(aioclient_mock, [LOCK, _connect("2026-09-24T12:09:00Z")])
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
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
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
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
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert _issue(issue_registry, CONNECT_ISSUE) is not None


async def test_lock_without_bluetooth_or_connect(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Test an issue for a lock without a Connect, with no Bluetooth in Home Assistant."""
    await _setup(
        hass,
        mock_config_entry,
        aioclient_mock,
        [
            # A lock reachable through its Connect doesn't stop the others
            # being checked.
            LOCK,
            GATEWAY,
            {**LOCK, "id": 5, "name": "Garage", "gateway": None},
            {**LOCK, "id": 6, "name": "Shed", "gateway": None},
        ],
    )
    assert _issue(issue_registry, NO_ROUTE_ISSUE) is None
    for lock_id, name in ((5, "Garage"), (6, "Shed")):
        issue = _issue(issue_registry, f"lock_no_route_{lock_id}")
        assert issue.translation_key == "lock_no_route"
        assert issue.translation_placeholders == {"name": name}


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
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    assert _issue(issue_registry, OUT_OF_RANGE_ISSUE) is None

    for _ in range(6):
        await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
    issue = _issue(issue_registry, OUT_OF_RANGE_ISSUE)
    assert issue.translation_key == "lock_out_of_range"
    assert set(issue.translation_placeholders) == {"name", "since"}
    assert issue.translation_placeholders["name"] == "Front Door"

    # Heard again, it's cleared.
    tracker._reachable.add(LOCK_ID)  # noqa: SLF001
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
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
        await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
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
    await advance(hass, frozen_time, DEVICE_SCAN_INTERVAL)
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
