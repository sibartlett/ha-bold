"""The Bold Smart Lock integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
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

    events: BoldEventCoordinator | None = None
    if event_device_ids := [
        device.id
        for device in devices.data.values()
        if device.is_lock and device.event_log
    ]:
        events = BoldEventCoordinator(hass, entry, client, event_device_ids)
        await events.async_config_entry_first_refresh()

    entry.runtime_data = BoldRuntimeData(client=client, devices=devices, events=events)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BoldConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
