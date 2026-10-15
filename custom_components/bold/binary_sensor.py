"""Binary sensor platform for the Bold integration."""

# Home Assistant 2026.10 moved it to binary_sensor.const, which 2026.8 lacks.
from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined]
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .boldsmartlock import BoldDevice
from .const import BATTERY_LEVELS, CONNECT_OFFLINE_AFTER, LOW_BATTERY_LEVELS
from .coordinator import BoldConfigEntry
from .entity import BoldEntity, async_add_device_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold binary sensors."""
    coordinator = entry.runtime_data.devices

    def create_entities(device: BoldDevice) -> list[BinarySensorEntity]:
        if device.is_lock:
            return [BoldBatteryLowSensor(coordinator, device, "battery")]
        if device.is_gateway:
            return [BoldConnectOnlineSensor(coordinator, device, "online")]
        return []

    async_add_device_entities(entry, async_add_entities, create_entities)


class BoldBatteryLowSensor(BoldEntity, BinarySensorEntity):
    """Whether the battery of a Bold lock is low."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return whether the battery is low, unless it's a level we don't know."""
        if (level := self.device.battery_level) not in BATTERY_LEVELS:
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
