"""Tests for discovering Bold devices."""

from __future__ import annotations

from fnmatch import fnmatch
import json
from pathlib import Path

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_DHCP, SOURCE_IGNORE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.bluetooth import BluetoothServiceInfo
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bold.const import DOMAIN

MANIFEST = json.loads(
    (
        Path(__file__).parent.parent / "custom_components" / "bold" / "manifest.json"
    ).read_text()
)

BOLD_SERVICE_UUID = "0000fd30-0000-1000-8000-00805f9b34fb"

# Advertisement and DHCP data shaped like real Bold devices'.
LOCK_ADVERTISEMENT = BluetoothServiceInfo(
    name="AA-BB-CC-00-00-01",
    address="AA:BB:CC:00:00:01",
    rssi=-92,
    manufacturer_data={1627: bytes.fromhex("020103010000000000000000")},
    service_data={},
    service_uuids=[BOLD_SERVICE_UUID],
    source="local",
)
CONNECT_DHCP = DhcpServiceInfo(
    ip="192.168.1.20", hostname="Bold-Connect", macaddress="7cdfa1000001"
)


def _bluetooth_matches(info: BluetoothServiceInfo) -> bool:
    return any(
        matcher["manufacturer_id"] in info.manufacturer_data
        and matcher["service_uuid"] in info.service_uuids
        for matcher in MANIFEST["bluetooth"]
    )


def _dhcp_matches(hostname: str) -> bool:
    # Home Assistant matches lowercased hostnames with fnmatch.
    return any(
        fnmatch(hostname.lower(), matcher["hostname"]) for matcher in MANIFEST["dhcp"]
    )


def test_matchers() -> None:
    """Test the manifest matches Bold devices, and not other devices."""
    assert _bluetooth_matches(LOCK_ADVERTISEMENT)
    assert not _bluetooth_matches(
        BluetoothServiceInfo(
            "other", "AA:BB:CC:DD:EE:FF", -50, {1627: b""}, {}, [], "local"
        )
    )
    assert _dhcp_matches("Bold-Connect")
    assert _dhcp_matches("bold-connect-2")
    assert not _dhcp_matches("espressif")


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
@pytest.mark.parametrize(
    ("source", "discovery_info"),
    [(SOURCE_BLUETOOTH, LOCK_ADVERTISEMENT), (SOURCE_DHCP, CONNECT_DHCP)],
)
async def test_discovery(
    hass: HomeAssistant, source: str, discovery_info: object
) -> None:
    """Test a discovered device offers to set up Bold, then signs in."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": source}, data=discovery_info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith("https://auth.boldsmartlock.com/authorize")


@pytest.mark.usefixtures("setup_credentials")
async def test_discovery_only_once(hass: HomeAssistant) -> None:
    """Test several discovered devices only offer to set up Bold once."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=LOCK_ADVERTISEMENT
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=CONNECT_DHCP
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"


@pytest.mark.parametrize(
    "entry",
    [
        MockConfigEntry(domain=DOMAIN, unique_id="42"),
        MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, source=SOURCE_IGNORE),
    ],
    ids=["configured", "ignored"],
)
async def test_discovery_when_set_up_or_ignored(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Test discovery doesn't offer setup once Bold is set up or ignored."""
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=CONNECT_DHCP
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
