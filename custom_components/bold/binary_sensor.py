"""Binary sensor platform for the Bold integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONNECT_OFFLINE_AFTER
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
    entities: list[BinarySensorEntity] = []
    for device in coordinator.data.values():
        if device.is_lock:
            entities.append(BoldBatteryLowSensor(coordinator, device, "battery"))
        elif device.is_gateway:
            entities.append(BoldConnectOnlineSensor(coordinator, device, "online"))
    async_add_entities(entities)


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


class BoldConnectOnlineSensor(BoldEntity, BinarySensorEntity):
    """Whether a Bold Connect has checked in with Bold recently."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        """Return whether the Connect was seen recently."""
        if (last_seen := self.device.gateway_last_seen) is None:
            return None
        return dt_util.utcnow() - last_seen < CONNECT_OFFLINE_AFTER
