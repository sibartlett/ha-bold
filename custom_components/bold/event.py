"""Event platform for the Bold integration."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .boldsmartlock import BoldDevice, BoldEvent
from .coordinator import BoldConfigEntry, BoldEventCoordinator
from .entity import async_add_device_entities, device_info

PARALLEL_UPDATES = 0

EVENT_ACTIVATED = "activated"
EVENT_ACTIVATION_FAILED = "activation_failed"
EVENT_DEACTIVATED = "deactivated"
EVENT_TAMPER = "tamper"
EVENT_LOCKED = "locked"
EVENT_UNLOCKED = "unlocked"

TAMPER_EVENTS = {
    "DeviceTamperVibration": "vibration",
    "DeviceTamperRotations": "rotations",
    "DeviceTamperFaultyPin": "faulty_pin",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold activity events."""
    events = entry.runtime_data.events
    async_add_device_entities(
        entry,
        async_add_entities,
        lambda device: (
            [BoldActivityEvent(events, device)]
            if device.is_lock and device.event_log
            else []
        ),
    )


def _event_type(event: BoldEvent) -> str | None:
    """Map a Bold event to an event entity type."""
    if event.type == "DeviceActivation":
        return EVENT_ACTIVATED if event.result == "Success" else EVENT_ACTIVATION_FAILED
    if event.type == "DeviceDeactivation":
        return EVENT_DEACTIVATED
    if event.type in TAMPER_EVENTS:
        return EVENT_TAMPER
    if event.type == "DeviceLocked" and event.bolt_locked is not None:
        return EVENT_LOCKED if event.bolt_locked else EVENT_UNLOCKED
    return None


class BoldActivityEvent(CoordinatorEntity[BoldEventCoordinator], EventEntity):
    """Activity on a Bold lock, from its event log."""

    _attr_has_entity_name = True
    _attr_translation_key = "activity"
    _attr_event_types = [
        EVENT_ACTIVATED,
        EVENT_ACTIVATION_FAILED,
        EVENT_DEACTIVATED,
        EVENT_TAMPER,
        EVENT_LOCKED,
        EVENT_UNLOCKED,
    ]

    def __init__(self, coordinator: BoldEventCoordinator, device: BoldDevice) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device_id = device.id
        self._attr_unique_id = f"{device.id}_activity"
        self._attr_device_info = device_info(device)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire an event for each new event of this device."""
        for event in self.coordinator.data or []:
            if event.device_id != self.device_id or not (
                event_type := _event_type(event)
            ):
                continue
            attributes: dict[str, str | int | bool | None] = {
                "bold_event_id": event.id,
                "time": event.time.isoformat(),
                "user": event.user_name,
            }
            if event.type in ("DeviceActivation", "DeviceDeactivation"):
                attributes["method"] = event.method
                attributes["remote"] = event.remote_activation
            if event.type == "DeviceActivation":
                attributes["result"] = event.result
            if event.type in TAMPER_EVENTS:
                attributes["tamper_type"] = TAMPER_EVENTS[event.type]
            self._trigger_event(event_type, attributes)
        super()._handle_coordinator_update()
