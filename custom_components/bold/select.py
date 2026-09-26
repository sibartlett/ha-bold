"""Select platform for the Bold integration."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .boldsmartlock import BoldDevice
from .coordinator import BoldConfigEntry, BoldRuntimeData
from .entity import BoldEntity, async_add_device_entities
from .unlock import UnlockMethod

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Bold selects."""
    data = entry.runtime_data

    def create_entities(device: BoldDevice) -> list[SelectEntity]:
        # There's only a choice with both Bluetooth and a Bold Connect.
        if (
            device.is_lock
            and data.bluetooth.enabled
            and device.remote_access
            and device.gateway_id is not None
        ):
            return [BoldUnlockMethodSelect(data, device)]
        return []

    async_add_device_entities(entry, async_add_entities, create_entities)


class BoldUnlockMethodSelect(BoldEntity, SelectEntity, RestoreEntity):
    """Whether a lock is unlocked over Bluetooth or through its Bold Connect."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [method.value for method in UnlockMethod]
    _attr_translation_key = "unlock_method"

    def __init__(self, data: BoldRuntimeData, device: BoldDevice) -> None:
        """Initialize the select."""
        super().__init__(data.devices, device, "unlock_method")
        self._unlock_methods = data.unlock_methods

    async def async_added_to_hass(self) -> None:
        """Restore the chosen unlock method."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) and state.state in (
            self.options
        ):
            self._unlock_methods.async_set(self.device_id, UnlockMethod(state.state))

    @property
    def current_option(self) -> str:
        """Return the unlock method."""
        return self._unlock_methods.get(self.device_id).value

    async def async_select_option(self, option: str) -> None:
        """Change the unlock method."""
        self._unlock_methods.async_set(self.device_id, UnlockMethod(option))
        self.async_write_ha_state()
