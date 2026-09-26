"""Base entity for the Bold integration."""

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .boldsmartlock import BoldDevice
from .const import DOMAIN, MANUFACTURER
from .coordinator import BoldConfigEntry, BoldDeviceCoordinator


@callback
def async_add_device_entities(
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    create_entities: Callable[[BoldDevice], Iterable[Entity]],
) -> None:
    """Add entities for each device, including devices added to Bold later."""
    coordinator = entry.runtime_data.devices
    known: set[int] = set()

    @callback
    def add_new_devices() -> None:
        # Forget removed devices, so they get entities again if they return.
        known.intersection_update(coordinator.data)
        new_devices = [
            device for device in coordinator.data.values() if device.id not in known
        ]
        known.update(device.id for device in new_devices)
        if entities := [
            entity for device in new_devices for entity in create_entities(device)
        ]:
            async_add_entities(entities)

    add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(add_new_devices))


def device_info(device: BoldDevice, via_device_id: str | None = None) -> DeviceInfo:
    """Return the device registry info for a Bold device."""
    info = DeviceInfo(
        identifiers={(DOMAIN, str(device.id))},
        name=device.name,
        manufacturer=MANUFACTURER,
        model=device.model_name,
        sw_version=(
            str(device.actual_firmware_version)
            if device.actual_firmware_version is not None
            else None
        ),
    )
    if via_device_id is not None:
        info["via_device_id"] = via_device_id
    return info


class BoldEntity(CoordinatorEntity[BoldDeviceCoordinator]):
    """An entity of a Bold device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BoldDeviceCoordinator, device: BoldDevice, key: str | None
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device_id = device.id
        self._attr_unique_id = f"{device.id}_{key}" if key else str(device.id)
        # A Connect reports itself as its own gateway.
        via_device_id = (
            coordinator.connect_device_ids.get(device.gateway_id)
            if device.gateway_id != device.id
            else None
        )
        self._attr_device_info = device_info(device, via_device_id)

    @property
    def device(self) -> BoldDevice:
        """Return the latest data for this entity's device."""
        return self.coordinator.data[self.device_id]

    @property
    def available(self) -> bool:
        """Return whether the device is still known to the account."""
        return super().available and self.device_id in self.coordinator.data
