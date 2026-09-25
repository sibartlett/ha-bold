"""The Bold Smart Lock integration."""

from __future__ import annotations

from functools import partial

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
    OAuth2Session,
    async_get_config_entry_implementation,
)

from .api import BoldClient
from .const import DOMAIN
from .coordinator import (
    BoldConfigEntry,
    BoldDeviceCoordinator,
    BoldEventCoordinator,
    BoldRuntimeData,
)
from .entity import device_info

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.LOCK,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: BoldConfigEntry) -> bool:
    """Set up Bold from a config entry."""
    try:
        implementation = await async_get_config_entry_implementation(hass, entry)
    except ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="oauth2_implementation_unavailable",
        ) from err

    session = OAuth2Session(hass, entry, implementation)

    async def get_access_token() -> str:
        await session.async_ensure_token_valid()
        return session.token["access_token"]

    client = BoldClient(async_get_clientsession(hass), get_access_token)

    devices = BoldDeviceCoordinator(hass, entry, client)
    await devices.async_config_entry_first_refresh()
    events = BoldEventCoordinator(hass, entry, client, [])
    entry.runtime_data = BoldRuntimeData(client=client, devices=devices, events=events)

    # Registered before the platforms, so it runs before they add entities for
    # new devices.
    _async_sync_devices(hass, entry)
    entry.async_on_unload(
        devices.async_add_listener(partial(_async_sync_devices, hass, entry))
    )

    await events.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


@callback
def _async_sync_devices(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Follow devices being added to or removed from the Bold account."""
    devices = entry.runtime_data.devices
    if not devices.last_update_success:
        return
    device_registry = dr.async_get(hass)

    # Register Bold Connects first, so locks can be linked to them.
    for device in devices.data.values():
        if device.is_gateway and device.id not in devices.connect_device_ids:
            devices.connect_device_ids[device.id] = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id, **device_info(device)
            ).id

    entry.runtime_data.events.device_ids = [
        device.id
        for device in devices.data.values()
        if device.is_lock and device.event_log
    ]

    for device_entry in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        if (device_id := _bold_device_id(device_entry)) not in devices.data:
            devices.connect_device_ids.pop(device_id, None)
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )


def _bold_device_id(device_entry: dr.DeviceEntry) -> int | None:
    """Return the Bold device ID of a device registry entry."""
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN and identifier.isdigit():
            return int(identifier)
    return None


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: BoldConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device that is no longer in the Bold account."""
    return _bold_device_id(device_entry) not in entry.runtime_data.devices.data


async def async_unload_entry(hass: HomeAssistant, entry: BoldConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
