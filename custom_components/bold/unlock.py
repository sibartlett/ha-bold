"""How each Bold lock is unlocked: over Bluetooth or through a Bold Connect."""

from collections.abc import Callable
from enum import StrEnum

from homeassistant.core import CALLBACK_TYPE, callback


class UnlockMethod(StrEnum):
    """Which route a lock is unlocked through."""

    PREFER_BLUETOOTH = "prefer_bluetooth"
    PREFER_CONNECT = "prefer_connect"
    BLUETOOTH_ONLY = "bluetooth_only"
    CONNECT_ONLY = "connect_only"


# The Bold Connect is the dependable default; Bluetooth depends on range.
DEFAULT_UNLOCK_METHOD = UnlockMethod.PREFER_CONNECT


class Route(StrEnum):
    """A way to reach a lock."""

    BLUETOOTH = "bluetooth"
    CONNECT = "connect"


ROUTES: dict[UnlockMethod, tuple[Route, ...]] = {
    UnlockMethod.PREFER_BLUETOOTH: (Route.BLUETOOTH, Route.CONNECT),
    UnlockMethod.PREFER_CONNECT: (Route.CONNECT, Route.BLUETOOTH),
    UnlockMethod.BLUETOOTH_ONLY: (Route.BLUETOOTH,),
    UnlockMethod.CONNECT_ONLY: (Route.CONNECT,),
}


class BoldUnlockMethods:
    """The unlock method chosen for each lock."""

    def __init__(self) -> None:
        """Initialize the unlock methods."""
        self._methods: dict[int, UnlockMethod] = {}
        self._listeners: dict[int, list[CALLBACK_TYPE]] = {}

    def get(self, device_id: int) -> UnlockMethod:
        """Return a lock's unlock method."""
        return self._methods.get(device_id, DEFAULT_UNLOCK_METHOD)

    @callback
    def async_set(self, device_id: int, method: UnlockMethod) -> None:
        """Change a lock's unlock method."""
        self._methods[device_id] = method
        for listener in list(self._listeners.get(device_id, [])):
            listener()

    @callback
    def async_add_listener(
        self, device_id: int, listener: CALLBACK_TYPE
    ) -> Callable[[], None]:
        """Call a listener when a lock's unlock method changes."""
        listeners = self._listeners.setdefault(device_id, [])
        listeners.append(listener)
        return lambda: listeners.remove(listener)
