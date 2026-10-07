"""Base entity for the Bold integration."""

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .boldsmartlock import (
    BoldAuthError,
    BoldBluetoothError,
    BoldBluetoothUnavailableError,
    BoldDevice,
    BoldError,
    BoldFirmwareOutdatedError,
    BoldGatewayNotFoundError,
    BoldRateLimitError,
)
from .const import DOMAIN, MANUFACTURER
from .coordinator import BoldConfigEntry, BoldDeviceCoordinator


@callback
def async_add_device_entities(
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    create_entities: Callable[[BoldDevice], Iterable[Entity]],
) -> None:
    """Add entities for each device, including devices added to Bold later.

    A device can gain entities later too, e.g. a Connect with its Controller
    setting turned on in the Bold app. Entities aren't removed when it loses
    what they need, keeping their history and whether they're enabled.
    """
    coordinator = entry.runtime_data.devices
    # The unique IDs of the entities added for each device.
    added: dict[int, set[str | None]] = {}

    @callback
    def add_new_entities() -> None:
        # Forget removed devices, so they get entities again if they return.
        for device_id in added.keys() - coordinator.data.keys():
            del added[device_id]
        new_entities: list[Entity] = []
        for device in coordinator.data.values():
            unique_ids = added.setdefault(device.id, set())
            for entity in create_entities(device):
                if entity.unique_id not in unique_ids:
                    unique_ids.add(entity.unique_id)
                    new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


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


def command_error(err: BoldError) -> HomeAssistantError:
    """Translate an API error from a command to a lock or Bold Connect."""
    if isinstance(err, BoldBluetoothUnavailableError):
        key = "bluetooth_unavailable"
    elif isinstance(err, BoldBluetoothError):
        key = "bluetooth_failed"
    elif isinstance(err, BoldRateLimitError):
        key = "rate_limited"
    elif isinstance(err, BoldGatewayNotFoundError):
        key = "gateway_not_found"
    elif isinstance(err, BoldFirmwareOutdatedError):
        key = "firmware_outdated"
    elif isinstance(err, BoldAuthError):
        key = "auth_failed"
    else:
        key = "command_failed"
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"error": str(err)},
    )
