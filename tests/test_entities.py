"""Snapshots of the entities and devices the integration creates.

Update them with `pytest --snapshot-update`, and review the diff.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from .conftest import FakeBluetooth

pytestmark = pytest.mark.usefixtures(
    "frozen_time", "entity_registry_enabled_by_default"
)


@pytest.mark.parametrize(
    "platforms",
    [["binary_sensor"], ["event"], ["lock"], ["select"], ["sensor"], ["update"]],
    ids=lambda platforms: platforms[0],
)
async def test_entities(
    hass: HomeAssistant,
    fake_bluetooth: FakeBluetooth,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test each platform's entities, with Bluetooth, and all entities enabled."""
    await snapshot_platform(hass, entity_registry, snapshot, init_integration.entry_id)


async def test_devices(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the lock and Bold Connect devices, and how they're linked."""
    devices = dr.async_entries_for_config_entry(
        device_registry, init_integration.entry_id
    )
    assert sorted(devices, key=lambda device: device.name or "") == snapshot
