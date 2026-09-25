"""Tests for catching up on events that locks upload late."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bold.boldsmartlock import BoldEvent, parse_datetime
from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import EVENT_SCAN_INTERVAL

from .conftest import GATEWAY, LOCK, event_payload

ENTITY_ID = "event.front_door_activity"
START = datetime(2026, 9, 24, 12, 0, tzinfo=dt_util.UTC)


class FakeEventLog:
    """Bold's event log: events show up once uploaded, filtered by when they happened."""

    def __init__(self) -> None:
        self.events: list[tuple[datetime, dict[str, Any]]] = []
        self.requested_since: list[tuple[datetime, datetime]] = []

    def add(self, event_id: int, happened: datetime, uploaded: datetime) -> None:
        self.events.append(
            (
                uploaded,
                event_payload(
                    event_id,
                    "DeviceActivation",
                    happened.isoformat(),
                    result="Success",
                ),
            )
        )

    async def get_events(
        self,
        _client: object,
        device_ids: list[int],
        since: datetime,
        event_types: list[str] | None = None,
    ) -> list[BoldEvent]:
        now = dt_util.utcnow()
        if event_types is None:
            self.requested_since.append((now, since))
        return [
            event
            for uploaded, payload in self.events
            if uploaded <= now
            and parse_datetime(payload["time"]) >= since
            and (event := BoldEvent.from_api(payload))
        ]


@pytest.fixture
def platforms() -> list[str]:
    """Only set up events."""
    return ["event"]


@pytest.fixture
async def event_log(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    platforms: list[str],
) -> FakeEventLog:
    """Set up the integration against a fake event log."""
    freezer.move_to(START)
    log = FakeEventLog()
    # Already in the log before startup.
    log.add(1, START - timedelta(minutes=30), START - timedelta(minutes=29))
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    with (
        patch("custom_components.bold.PLATFORMS", platforms),
        patch(
            "custom_components.bold.boldsmartlock.client.BoldClient.get_events",
            autospec=True,
            side_effect=log.get_events,
        ),
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        yield log


async def _run_until(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, until: datetime
) -> None:
    while dt_util.utcnow() < until:
        freezer.tick(EVENT_SCAN_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_late_event_caught_up(
    hass: HomeAssistant, event_log: FakeEventLog, freezer: FrozenDateTimeFactory
) -> None:
    """Test an event uploaded late is picked up by the next catch-up."""
    # An unlock at 12:04, uploaded straight away, moves the polls on.
    event_log.add(2, START + timedelta(minutes=4), START + timedelta(minutes=4))
    # The lock was turned at 12:01, but that's only uploaded at 12:05, too late
    # for the regular polls, which by then only look back to 12:02.
    event_log.add(3, START + timedelta(minutes=1), START + timedelta(minutes=5))

    await _run_until(hass, freezer, START + timedelta(minutes=9))
    assert hass.states.get(ENTITY_ID).attributes["bold_event_id"] == 2

    await _run_until(hass, freezer, START + timedelta(minutes=10, seconds=30))
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["bold_event_id"] == 3
    # It still says when it actually happened.
    assert state.attributes["time"] == (START + timedelta(minutes=1)).isoformat()


async def test_history_not_replayed(
    hass: HomeAssistant, event_log: FakeEventLog, freezer: FrozenDateTimeFactory
) -> None:
    """Test catch-ups don't fire events from before startup."""
    await _run_until(hass, freezer, START + timedelta(minutes=25))
    assert hass.states.get(ENTITY_ID).state == STATE_UNKNOWN


async def test_catch_up_every_ten_minutes(
    hass: HomeAssistant, event_log: FakeEventLog, freezer: FrozenDateTimeFactory
) -> None:
    """Test only a poll every 10 minutes looks back an hour."""
    await _run_until(hass, freezer, START + timedelta(minutes=25))
    catch_ups = [
        now - START
        for now, since in event_log.requested_since
        if now - since >= timedelta(hours=1)
    ]
    assert catch_ups == [
        timedelta(0),
        timedelta(minutes=10),
        timedelta(minutes=20),
    ]
    # The rest look back a couple of minutes from the latest event.
    assert all(
        now - since < timedelta(minutes=30)
        for now, since in event_log.requested_since
        if now - START not in catch_ups
    )
