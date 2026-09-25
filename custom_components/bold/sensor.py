"""Sensor platform for the Bold integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoldConfigEntry
from .entity import BoldEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold sensors."""
    coordinator = entry.runtime_data.devices
    async_add_entities(
        BoldBatterySensor(coordinator, device, "battery")
        for device in coordinator.data.values()
        if device.is_lock
    )


class BoldBatterySensor(BoldEntity, SensorEntity):
    """Battery level of a Bold lock."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the battery level."""
        return self.device.battery_level
