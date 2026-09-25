"""Sensor platform for the Bold integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .boldsmartlock import BoldDevice, BoldEvent
from .coordinator import BoldConfigEntry, BoldEventCoordinator, BoldRuntimeData
from .entity import BoldEntity, async_add_device_entities, device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Bluetooth signal sensors read the latest advertisement at most this often,
# rather than on each advertisement, which can be several times a second.
SCAN_INTERVAL = timedelta(seconds=30)

# Status reports this many seconds after a lock started are from its boot.
BOOT_STATUS_UPTIME = 60

# Bold reports battery and signal levels as words, on the same scale.
LEVELS = ["excellent", "high", "medium", "low", "critical"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold sensors."""
    data = entry.runtime_data
    coordinator = data.devices

    def create_entities(device: BoldDevice) -> list[SensorEntity]:
        entities: list[SensorEntity] = []
        if device.is_lock and data.bluetooth.enabled:
            entities.append(BoldBluetoothSignalSensor(data, device))
        if device.is_lock and device.event_log:
            entities.extend(
                BoldReportedSensor(data.events, device, description)
                for description in REPORTED_SENSORS
            )
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
        return entities

    async_add_device_entities(entry, async_add_entities, create_entities)


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


class BoldBluetoothSignalSensor(BoldEntity, SensorEntity):
    """How well Home Assistant hears a Bold lock over Bluetooth."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_should_poll = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "bluetooth_signal"

    def __init__(self, data: BoldRuntimeData, device: BoldDevice) -> None:
        """Initialize the sensor."""
        super().__init__(data.devices, device, "bluetooth_signal")
        self._tracker = data.bluetooth

    async def async_added_to_hass(self) -> None:
        """Update straight away when the lock comes into or goes out of range."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._tracker.async_add_listener(self.device_id, self._async_changed)
        )

    @callback
    def _async_changed(self) -> None:
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Re-read the latest advertisement, without refreshing from Bold."""

    @property
    def available(self) -> bool:
        """Return whether Home Assistant can hear the lock."""
        return self._tracker.is_reachable(self.device_id)

    @property
    def native_value(self) -> int | None:
        """Return the signal strength."""
        return self._tracker.rssi(self.device_id)


def voltage_under_load(event: BoldEvent) -> float | None:
    """Return the battery voltage under load, from the daily status.

    Debug events also sample the voltage while the motor runs, but those
    samples are lower than the lock's own measurement, so they aren't mixed in.
    A status sent right after the lock started has nothing run under load
    yet, so its voltage under load isn't one.
    """
    if event.uptime is not None and event.uptime < BOOT_STATUS_UPTIME:
        return None
    return event.voltage_under_load


@dataclass(frozen=True, kw_only=True)
class BoldReportedSensorDescription(SensorEntityDescription):
    """A value Bold locks report in their event log."""

    value_fn: Callable[[BoldEvent], float | None]


REPORTED_SENSORS: tuple[BoldReportedSensorDescription, ...] = (
    BoldReportedSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda event: event.voltage_idle,
    ),
    BoldReportedSensorDescription(
        key="battery_voltage_under_load",
        translation_key="battery_voltage_under_load",
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=voltage_under_load,
    ),
)


class BoldReportedSensor(CoordinatorEntity[BoldEventCoordinator], RestoreSensor):
    """A value a Bold lock reports in its event log, e.g. in its daily status.

    Readings are infrequent, so the last one is kept across restarts.
    """

    _attr_has_entity_name = True
    entity_description: BoldReportedSensorDescription

    def __init__(
        self,
        coordinator: BoldEventCoordinator,
        device: BoldDevice,
        description: BoldReportedSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device.id
        self._attr_unique_id = f"{device.id}_{description.key}"
        self._attr_device_info = device_info(device)

    async def async_added_to_hass(self) -> None:
        """Restore the last reading, and pick up any from recent events."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        self._update_from(
            sorted(
                [*self.coordinator.status_history, *self.coordinator.recent_events],
                key=lambda event: event.sort_key,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Pick up readings from new events."""
        self._update_from(self.coordinator.data or [])
        super()._handle_coordinator_update()

    def _update_from(self, events: Iterable[BoldEvent]) -> None:
        for event in events:
            if (
                event.device_id == self.device_id
                and (value := self.entity_description.value_fn(event)) is not None
            ):
                self._attr_native_value = value
