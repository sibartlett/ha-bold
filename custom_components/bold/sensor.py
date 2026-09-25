"""Sensor platform for the Bold integration."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BoldConfigEntry
from .entity import BoldEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Bold reports battery and signal levels as words, on the same scale.
LEVELS = ["excellent", "high", "medium", "low", "critical"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold sensors."""
    coordinator = entry.runtime_data.devices
    entities: list[SensorEntity] = []
    for device in coordinator.data.values():
        if device.is_lock:
            entities.append(
                BoldBatteryLevelSensor(coordinator, device, "battery_level")
            )
            if device.gateway_id is not None:
                entities.append(
                    BoldConnectSignalSensor(coordinator, device, "connect_signal")
                )
                entities.append(
                    BoldConnectSignalStrengthSensor(
                        coordinator, device, "connect_signal_strength"
                    )
                )
        elif device.is_gateway:
            entities.append(BoldLastSeenSensor(coordinator, device, "last_seen"))
    async_add_entities(entities)


def _level(level: str | None, what: str, device_name: str) -> str | None:
    """Return a level if it is one we know."""
    if level is not None and level not in LEVELS:
        _LOGGER.debug("Unknown %s %r for %s", what, level, device_name)
        return None
    return level


class BoldBatteryLevelSensor(BoldEntity, SensorEntity):
    """Battery level of a Bold lock."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = LEVELS
    _attr_translation_key = "battery_level"

    @property
    def native_value(self) -> str | None:
        """Return the battery level."""
        return _level(self.device.battery_level, "battery level", self.device.name)


class BoldConnectSignalSensor(BoldEntity, SensorEntity):
    """How well a Bold lock reaches its Bold Connect."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = LEVELS
    _attr_translation_key = "connect_signal"

    @property
    def native_value(self) -> str | None:
        """Return the signal level."""
        return _level(self.device.gateway_rssi_level, "signal level", self.device.name)


class BoldConnectSignalStrengthSensor(BoldEntity, SensorEntity):
    """Signal strength between a Bold lock and its Bold Connect."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "connect_signal_strength"

    @property
    def native_value(self) -> int | None:
        """Return the signal strength."""
        return self.device.gateway_rssi


class BoldLastSeenSensor(BoldEntity, SensorEntity):
    """When Bold last heard from a Bold Connect."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_seen"

    @property
    def native_value(self) -> datetime | None:
        """Return when the Connect was last seen."""
        return self.device.gateway_last_seen
