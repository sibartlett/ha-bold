"""Tracks which Bold locks Home Assistant can reach over Bluetooth."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.service_info.bluetooth import BluetoothServiceInfo

from .ble import MANUFACTURER_ID, parse_advertisement

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice

_LOGGER = logging.getLogger(__name__)


class BoldBluetoothTracker:
    """Follows Bold advertisements through Home Assistant's Bluetooth stack.

    Does nothing when Home Assistant's Bluetooth integration isn't set up.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the tracker."""
        self._hass = hass
        self._addresses: dict[int, str] = {}
        self._reachable: set[int] = set()
        self._rssi: dict[int, int] = {}
        self._listeners: dict[int, list[CALLBACK_TYPE]] = {}
        self._unsubscribes: list[Callable[[], None]] = []

    @property
    def enabled(self) -> bool:
        """Return whether Home Assistant has Bluetooth."""
        return "bluetooth" in self._hass.config.components

    @callback
    def async_start(self, entry: ConfigEntry) -> None:
        """Start following Bold advertisements."""
        if not self.enabled:
            return
        from homeassistant.components import bluetooth  # noqa: PLC0415

        entry.async_on_unload(self._async_stop)
        self._unsubscribes.append(
            bluetooth.async_register_callback(
                self._hass,
                lambda info, _change: self.async_process_advertisement(info),
                bluetooth.BluetoothCallbackMatcher(
                    manufacturer_id=MANUFACTURER_ID, connectable=True
                ),
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        for info in bluetooth.async_discovered_service_info(
            self._hass, connectable=True
        ):
            if MANUFACTURER_ID in info.manufacturer_data:
                self.async_process_advertisement(info)

    @callback
    def _async_stop(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    @callback
    def async_process_advertisement(self, info: BluetoothServiceInfo) -> None:
        """Handle an advertisement of a Bold device."""
        data = info.manufacturer_data.get(MANUFACTURER_ID)
        if data is None or (advertisement := parse_advertisement(data)) is None:
            return
        device_id = advertisement.device_id
        self._rssi[device_id] = info.rssi
        if self._addresses.get(device_id) != info.address:
            _LOGGER.debug("Bold device %s is at %s", device_id, info.address)
            self._addresses[device_id] = info.address
            self._async_track_unavailable(device_id, info.address)
        if device_id not in self._reachable:
            self._reachable.add(device_id)
            self._async_notify(device_id)

    @callback
    def _async_track_unavailable(self, device_id: int, address: str) -> None:
        if not self.enabled:
            return
        from homeassistant.components import bluetooth  # noqa: PLC0415

        @callback
        def unavailable(_info: BluetoothServiceInfo) -> None:
            self.async_mark_unreachable(device_id)

        self._unsubscribes.append(
            bluetooth.async_track_unavailable(
                self._hass, unavailable, address, connectable=True
            )
        )

    @callback
    def async_mark_unreachable(self, device_id: int) -> None:
        """Handle a device that stopped advertising."""
        if device_id in self._reachable:
            self._reachable.discard(device_id)
            self._async_notify(device_id)

    def is_reachable(self, device_id: int, min_rssi: int | None = None) -> bool:
        """Return whether a device can currently be reached over Bluetooth.

        With min_rssi, only when its last advertisement was at least that strong.
        """
        if device_id not in self._reachable:
            return False
        return min_rssi is None or self._rssi.get(device_id, min_rssi) >= min_rssi

    def ble_device(self, device_id: int) -> BLEDevice | None:
        """Return the Bluetooth device to connect to, if reachable."""
        if not self.enabled or (address := self._addresses.get(device_id)) is None:
            return None
        from homeassistant.components import bluetooth  # noqa: PLC0415

        return bluetooth.async_ble_device_from_address(
            self._hass, address, connectable=True
        )

    @callback
    def async_add_listener(
        self, device_id: int, listener: CALLBACK_TYPE
    ) -> Callable[[], None]:
        """Call a listener when a device becomes reachable or unreachable."""
        listeners = self._listeners.setdefault(device_id, [])
        listeners.append(listener)
        return lambda: listeners.remove(listener)

    @callback
    def _async_notify(self, device_id: int) -> None:
        for listener in list(self._listeners.get(device_id, [])):
            listener()
