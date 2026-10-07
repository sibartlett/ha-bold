"""Button platform for the Bold integration.

A Bold Connect with its Controller setting on switches its relay when
activated. Bold doesn't say what the relay opens: a door, a gate or a garage
door. The button activates it whatever it opens, and is disabled by default,
like the Connect's lock, for the user to choose.
"""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .boldsmartlock import BoldDevice, BoldError
from .coordinator import BoldConfigEntry, BoldRuntimeData
from .entity import BoldEntity, async_add_device_entities, command_error

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold buttons."""
    data = entry.runtime_data
    async_add_device_entities(
        entry,
        async_add_entities,
        lambda device: (
            [BoldActivateButton(data, device)] if device.is_door_connect else []
        ),
    )


class BoldActivateButton(BoldEntity, ButtonEntity):
    """Activates a Bold Connect's relay, through Bold's cloud."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "activate"

    def __init__(self, data: BoldRuntimeData, device: BoldDevice) -> None:
        """Initialize the button."""
        super().__init__(data.devices, device, "activate")

    @property
    def available(self) -> bool:
        """Return whether Bold allows the Connect to be activated remotely."""
        return super().available and self.device.remote_access

    async def async_press(self) -> None:
        """Activate the Connect."""
        try:
            await self.coordinator.client.remote_activation(self.device_id)
        except BoldError as err:
            raise command_error(err) from err
