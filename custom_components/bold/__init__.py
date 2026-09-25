"""The Bold Smart Lock integration."""

from __future__ import annotations

from functools import partial
from typing import Any

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
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import BoldClient
from .const import BATTERY_VOLTAGE_HISTORY, BLUETOOTH_KEYS_REFRESH_INTERVAL, DOMAIN
from .coordinator import (
    BoldConfigEntry,
    BoldDeviceCoordinator,
    BoldEventCoordinator,
    BoldRuntimeData,
)
from .entity import device_info
from .issues import async_check_issues, async_delete_issues
from .keys import BoldBluetoothKeys
from .tracker import BoldBluetoothTracker
from .unlock import BoldUnlockMethods

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.LOCK,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.UPDATE,
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
        access_token: str = session.token["access_token"]
        return access_token

    client = BoldClient(async_get_clientsession(hass), get_access_token)

    devices = BoldDeviceCoordinator(hass, entry, client)
    await devices.async_config_entry_first_refresh()
    events = BoldEventCoordinator(hass, entry, client, [])
    bluetooth_keys = BoldBluetoothKeys(hass, entry.entry_id, client)
    await bluetooth_keys.async_load()
    entry.runtime_data = BoldRuntimeData(
        client=client,
        devices=devices,
        events=events,
        bluetooth_keys=bluetooth_keys,
        bluetooth=BoldBluetoothTracker(hass),
        unlock_methods=BoldUnlockMethods(),
    )

    # Registered before the platforms, so it runs before they add entities for
    # new devices.
    _async_sync_devices(hass, entry)
    entry.async_on_unload(
        devices.async_add_listener(partial(_async_sync_devices, hass, entry))
    )

    await events.async_config_entry_first_refresh()
    await events.async_load_status_history(dt_util.utcnow() - BATTERY_VOLTAGE_HISTORY)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_setup_bluetooth(hass, entry)
    return True


@callback
def _async_setup_bluetooth(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Follow locks over Bluetooth, and keep their Bluetooth keys fresh."""
    data = entry.runtime_data
    data.bluetooth.async_start(entry)
    if not data.bluetooth.enabled:
        return

    @callback
    def refresh_keys(*_: Any) -> None:
        entry.async_create_background_task(
            hass,
            data.bluetooth_keys.async_refresh(
                [device.id for device in data.devices.data.values() if device.is_lock]
            ),
            "Refresh Bold Bluetooth keys",
        )

    refresh_keys()
    entry.async_on_unload(
        async_track_time_interval(hass, refresh_keys, BLUETOOTH_KEYS_REFRESH_INTERVAL)
    )


async def async_remove_entry(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Delete the stored Bluetooth keys and issues when Bold is removed."""
    await BoldBluetoothKeys.async_remove_stored(hass, entry.entry_id)
    async_delete_issues(hass)


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
        device_id = _bold_device_id(device_entry)
        bold_device = devices.data.get(device_id) if device_id is not None else None
        if bold_device is None:
            devices.connect_device_ids.pop(device_id, None)
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )
        elif device_entry.sw_version != (
            sw_version := device_info(bold_device).get("sw_version")
        ):
            # Firmware was updated, e.g. from the Bold app.
            device_registry.async_update_device(device_entry.id, sw_version=sw_version)

    async_check_issues(hass, entry)


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
