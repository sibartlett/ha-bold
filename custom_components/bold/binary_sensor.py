"""Binary sensor platform for the Bold integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoldConfigEntry
from .entity import BoldEntity

PARALLEL_UPDATES = 0

LOW_BATTERY_LEVELS = {"low", "critical"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold binary sensors."""
    coordinator = entry.runtime_data.devices
    async_add_entities(
        BoldBatteryLowSensor(coordinator, device, "battery")
        for device in coordinator.data.values()
        if device.is_lock
    )


class BoldBatteryLowSensor(BoldEntity, BinarySensorEntity):
    """Whether the battery of a Bold lock is low."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return whether the battery is low."""
        if (level := self.device.battery_level) is None:
            return None
        return level in LOW_BATTERY_LEVELS
