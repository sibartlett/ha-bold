"""Update platform for the Bold integration.

Bold firmware is installed from the Bold app, over Bluetooth, so these entities
only report whether a device is on the firmware version Bold requires.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BoldDevice
from .coordinator import BoldConfigEntry
from .entity import BoldEntity, async_add_device_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold firmware updates."""
    coordinator = entry.runtime_data.devices

    def create_entities(device: BoldDevice) -> list[UpdateEntity]:
        if device.is_lock or device.is_gateway:
            return [BoldFirmwareUpdate(coordinator, device, "firmware")]
        return []

    async_add_device_entities(entry, async_add_entities, create_entities)


class BoldFirmwareUpdate(BoldEntity, UpdateEntity):
    """Whether a Bold device is on the firmware version Bold requires."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE

    @property
    def installed_version(self) -> str | None:
        """Return the firmware version on the device."""
        if (version := self.device.actual_firmware_version) is None:
            return None
        return str(version)

    @property
    def latest_version(self) -> str | None:
        """Return the firmware version Bold requires.

        Bold only reports the required version, which may not be the newest
        release.
        """
        if (version := self.device.required_firmware_version) is None:
            return None
        return str(version)

    @property
    def release_summary(self) -> str | None:
        """Explain where to install the update."""
        if not self.device.update_available:
            return None
        return (
            f"Bold requires firmware version {self.latest_version}. "
            "Update the device from the Bold app."
        )
