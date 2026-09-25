"""Sensor platform for the Bold integration."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoldConfigEntry
from .entity import BoldEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Bold reports battery levels as words, on the same scale as signal strength.
BATTERY_LEVELS = ["excellent", "high", "medium", "low", "critical"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold sensors."""
    coordinator = entry.runtime_data.devices
    async_add_entities(
        BoldBatteryLevelSensor(coordinator, device, "battery_level")
        for device in coordinator.data.values()
        if device.is_lock
    )


class BoldBatteryLevelSensor(BoldEntity, SensorEntity):
    """Battery level of a Bold lock."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = BATTERY_LEVELS
    _attr_translation_key = "battery_level"

    @property
    def native_value(self) -> str | None:
        """Return the battery level."""
        level = self.device.battery_level
        if level is not None and level not in BATTERY_LEVELS:
            _LOGGER.debug("Unknown battery level %r for %s", level, self.device.name)
            return None
        return level
