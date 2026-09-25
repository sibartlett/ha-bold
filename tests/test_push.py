"""Tests for Bold pushing events to a webhook."""

from __future__ import annotations

from datetime import timedelta
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.const import (
    EVENT_PUSH_SCAN_INTERVAL,
    EVENT_SCAN_INTERVAL,
    PUSHED_EVENT_TYPES,
)
from custom_components.bold.push import (
    CONF_BOLD_WEBHOOKS,
    CONF_CLOUDHOOK_URL,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
)

from .conftest import GATEWAY, LOCK, event_payload, set_events

ORGANIZATION_ID = 7  # The test lock's organization.
WEBHOOKS = f"{API_URL}/v3/webhooks"
ACTIVITY = "event.front_door_activity"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time."""
    freezer.move_to("2026-09-24T12:00:00+00:00")
    return freezer


@pytest.fixture
def platforms() -> list[str]:
    """Only set up events."""
    return ["event"]


@pytest.fixture
async def external_url(hass: HomeAssistant) -> str:
    """Give Home Assistant an external URL."""
    await async_process_ha_core_config(hass, {"external_url": "https://ha.example.com"})
    return "https://ha.example.com"


def _mock_bold(
    aioclient_mock: AiohttpClientMocker, existing: list[dict] | None = None
) -> None:
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    aioclient_mock.get(WEBHOOKS, json=existing or [])
    aioclient_mock.post(WEBHOOKS, json={"id": 99, "secretHmac": "hmac"})
    aioclient_mock.put(f"{WEBHOOKS}/99", json={})
    aioclient_mock.delete(f"{WEBHOOKS}/100", json={})
    aioclient_mock.delete(f"{WEBHOOKS}/99", json={})


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    with patch("custom_components.bold.PLATFORMS", ["event"]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _calls(aioclient_mock: AiohttpClientMocker, method: str, url: str) -> list:
    return [
        call
        for call in aioclient_mock.mock_calls
        if call[0] == method and str(call[1]).startswith(url)
    ]


async def test_webhook_registered(
    hass: HomeAssistant,
    external_url: str,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test a Bold webhook is created, pointing at Home Assistant."""
    _mock_bold(aioclient_mock)
    await _setup(hass, mock_config_entry)

    (create,) = _calls(aioclient_mock, "POST", WEBHOOKS)
    webhook_id = mock_config_entry.data[CONF_WEBHOOK_ID]
    assert create[2] == {
        "organizationId": ORGANIZATION_ID,
        "webhookUrl": f"{external_url}/api/webhook/{webhook_id}",
        "types": PUSHED_EVENT_TYPES,
        "secretHttp": mock_config_entry.data[CONF_WEBHOOK_SECRET],
    }
    assert mock_config_entry.data[CONF_BOLD_WEBHOOKS] == {str(ORGANIZATION_ID): 99}
    events = mock_config_entry.runtime_data.events
    assert events.push_active
    assert events.update_interval == EVENT_PUSH_SCAN_INTERVAL


async def test_webhook_reused_after_restart(
    hass: HomeAssistant,
    external_url: str,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test an existing webhook is updated, and duplicates removed."""
    url = f"{external_url}/api/webhook/abc"
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            CONF_WEBHOOK_ID: "abc",
            CONF_WEBHOOK_SECRET: "secret",
            CONF_BOLD_WEBHOOKS: {str(ORGANIZATION_ID): 99},
        },
    )
    _mock_bold(
        aioclient_mock,
        existing=[
            {"id": 99, "webhookUrl": url, "types": ["DeviceBoot"]},
            {"id": 100, "webhookUrl": url, "types": ["DeviceBoot"]},
            {"id": 101, "webhookUrl": "https://other.example.com/hook", "types": []},
        ],
    )
    await _setup(hass, mock_config_entry)

    assert not _calls(aioclient_mock, "POST", WEBHOOKS)
    (update,) = _calls(aioclient_mock, "PUT", f"{WEBHOOKS}/99")
    assert update[2] == {
        "webhookUrl": url,
        "types": PUSHED_EVENT_TYPES,
        "secretHttp": "secret",
    }
    assert len(_calls(aioclient_mock, "DELETE", f"{WEBHOOKS}/100")) == 1
    # Someone else's webhook is left alone.
    assert not _calls(aioclient_mock, "DELETE", f"{WEBHOOKS}/101")


async def test_webhook_refused(
    hass: HomeAssistant,
    external_url: str,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test polling carries on when Bold refuses the webhook."""
    aioclient_mock.get(f"{API_URL}/v2/devices", json=[LOCK, GATEWAY])
    aioclient_mock.get(f"{API_URL}/v2/events", json=[])
    aioclient_mock.get(WEBHOOKS, json=[])
    aioclient_mock.post(WEBHOOKS, status=403)
    await _setup(hass, mock_config_entry)

    events = mock_config_entry.runtime_data.events
    assert not events.push_active
    assert events.update_interval == EVENT_SCAN_INTERVAL


async def test_no_public_url(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test no webhook is set up without a URL Bold can reach."""
    _mock_bold(aioclient_mock)
    await _setup(hass, mock_config_entry)
    assert not _calls(aioclient_mock, "GET", WEBHOOKS)
    assert not mock_config_entry.runtime_data.events.push_active


async def test_cloudhook(
    hass: HomeAssistant,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test Home Assistant Cloud provides the URL without an external URL."""
    cloud = MagicMock()
    cloud.async_active_subscription.return_value = True
    cloud.async_create_cloudhook = AsyncMock(
        return_value="https://hooks.nabu.casa/hook"
    )
    cloud.async_delete_cloudhook = AsyncMock()
    cloud.CloudNotAvailable = type("CloudNotAvailable", (Exception,), {})
    # Remote access is off, so Home Assistant Cloud has no remote URL.
    cloud.async_remote_ui_url.side_effect = cloud.CloudNotAvailable
    hass.config.components.add("cloud")
    _mock_bold(aioclient_mock)
    with (
        patch.dict(sys.modules, {"homeassistant.components.cloud": cloud}),
        patch("homeassistant.components.cloud", cloud, create=True),
    ):
        await _setup(hass, mock_config_entry)
        (create,) = _calls(aioclient_mock, "POST", WEBHOOKS)
        assert create[2]["webhookUrl"] == "https://hooks.nabu.casa/hook"
        assert mock_config_entry.data[CONF_CLOUDHOOK_URL] == (
            "https://hooks.nabu.casa/hook"
        )

        # Removing the integration removes the cloudhook and the webhook.
        await hass.config_entries.async_remove(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    cloud.async_delete_cloudhook.assert_awaited_once()
    assert len(_calls(aioclient_mock, "DELETE", f"{WEBHOOKS}/99")) == 1


async def test_pushed_events(
    hass: HomeAssistant,
    external_url: str,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    """Test events pushed with Bold's secret are handled, others rejected."""
    _mock_bold(aioclient_mock)
    await _setup(hass, mock_config_entry)
    client = await hass_client_no_auth()
    path = f"/api/webhook/{mock_config_entry.data[CONF_WEBHOOK_ID]}"
    secret = mock_config_entry.data[CONF_WEBHOOK_SECRET]
    # Bold sends a list of events, in the event log's format.
    payload = [
        event_payload(
            10,
            "DeviceActivation",
            "2026-09-24T12:00:01Z",
            method="Button",
            result="Success",
        )
    ]

    response = await client.post(path, json=payload, headers={"X-Bold-Secret": "wrong"})
    assert response.status == 401
    response = await client.post(path, json=payload)
    assert response.status == 401
    response = await client.post(
        path, data="not json", headers={"X-Bold-Secret": secret}
    )
    assert response.status == 400
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVITY).state == "unknown"

    response = await client.post(path, json=payload, headers={"X-Bold-Secret": secret})
    assert response.status == 200
    await hass.async_block_till_done()
    state = hass.states.get(ACTIVITY)
    assert state.attributes["event_type"] == "activated"
    assert state.attributes["bold_event_id"] == 10

    # The same event, polled or pushed again, doesn't fire twice.
    fired_at = state.state
    response = await client.post(path, json=payload, headers={"X-Bold-Secret": secret})
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVITY).state == fired_at


async def test_missed_push_polls_faster(
    hass: HomeAssistant,
    external_url: str,
    setup_credentials: None,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test polling speeds up when a poll finds an event the webhook missed."""
    _mock_bold(aioclient_mock)
    await _setup(hass, mock_config_entry)
    events = mock_config_entry.runtime_data.events
    assert events.update_interval == EVENT_PUSH_SCAN_INTERVAL

    missed = event_payload(11, "DeviceLocked", "2026-09-24T12:03:00Z", status="Locked")
    set_events(aioclient_mock, [missed])
    frozen_time.tick(EVENT_PUSH_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not events.push_active
    assert events.update_interval == EVENT_SCAN_INTERVAL

    # The next delivery restores slow polling.
    client = await hass_client_no_auth()
    await client.post(
        f"/api/webhook/{mock_config_entry.data[CONF_WEBHOOK_ID]}",
        json=[],
        headers={"X-Bold-Secret": mock_config_entry.data[CONF_WEBHOOK_SECRET]},
    )
    assert events.push_active
    assert events.update_interval == EVENT_PUSH_SCAN_INTERVAL
    assert timedelta(minutes=5) == EVENT_PUSH_SCAN_INTERVAL
