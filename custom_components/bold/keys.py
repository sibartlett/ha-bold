"""Keys for talking to Bold locks over Bluetooth.

Bold's cloud issues each lock a handshake (valid for about a week) and signed
commands (valid for about a year). They're stored, so locks can be unlocked
over Bluetooth while Bold's cloud is unreachable.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .boldsmartlock import (
    COMMAND_ACTIVATE,
    COMMAND_DEACTIVATE,
    BoldClient,
    BoldError,
    parse_datetime,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


@dataclass(frozen=True)
class BoldSecret:
    """A secret from Bold's cloud, and when it expires."""

    value: bytes
    expires: datetime

    def valid(self, now: datetime) -> bool:
        """Return whether the secret can still be used."""
        return now < self.expires


@dataclass(frozen=True)
class BoldLockKeys:
    """The Bluetooth keys of a lock."""

    handshake_key: BoldSecret
    handshake_payload: BoldSecret
    commands: dict[str, BoldSecret]

    def command(self, command_type: str, now: datetime) -> bytes | None:
        """Return a usable command, if the handshake and command are valid."""
        command = self.commands.get(command_type)
        if (
            command is None
            or not command.valid(now)
            or not self.handshake_payload.valid(now)
        ):
            return None
        return command.value


def _secret(value: Any, expires: Any) -> BoldSecret | None:
    """Decode a base64 secret and its expiry."""
    if not isinstance(value, str) or (expiry := parse_datetime(expires)) is None:
        return None
    try:
        return BoldSecret(base64.b64decode(value, validate=True), expiry)
    except binascii.Error:
        return None


def _storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.bluetooth_keys"


def _encode(secret: BoldSecret) -> dict[str, str]:
    return {
        "value": base64.b64encode(secret.value).decode(),
        "expires": secret.expires.isoformat(),
    }


class BoldBluetoothKeys:
    """Fetches, stores and hands out the Bluetooth keys of locks."""

    def __init__(self, hass: HomeAssistant, entry_id: str, client: BoldClient) -> None:
        """Initialize the keys."""
        self._client = client
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            _storage_key(entry_id),
            private=True,
        )
        self._keys: dict[int, BoldLockKeys] = {}
        self._listeners: list[CALLBACK_TYPE] = []
        self._failing = False

    def get(self, device_id: int) -> BoldLockKeys | None:
        """Return the keys of a lock."""
        return self._keys.get(device_id)

    def command(self, device_id: int, command_type: str) -> bytes | None:
        """Return a usable command for a lock, if there is one."""
        keys = self._keys.get(device_id)
        return keys.command(command_type, dt_util.utcnow()) if keys else None

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> Callable[[], None]:
        """Call a listener when the keys change."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_load(self) -> None:
        """Load stored keys."""
        stored = await self._store.async_load() or {}
        for device_id, keys in stored.get("locks", {}).items():
            try:
                self._keys[int(device_id)] = BoldLockKeys(
                    handshake_key=BoldSecret(
                        base64.b64decode(keys["handshake_key"]["value"]),
                        datetime.fromisoformat(keys["handshake_key"]["expires"]),
                    ),
                    handshake_payload=BoldSecret(
                        base64.b64decode(keys["handshake_payload"]["value"]),
                        datetime.fromisoformat(keys["handshake_payload"]["expires"]),
                    ),
                    commands={
                        command_type: BoldSecret(
                            base64.b64decode(command["value"]),
                            datetime.fromisoformat(command["expires"]),
                        )
                        for command_type, command in keys["commands"].items()
                    },
                )
            except KeyError, TypeError, ValueError, binascii.Error:
                _LOGGER.debug("Ignoring invalid stored keys for %s", device_id)

    async def async_refresh(self, device_ids: list[int]) -> None:
        """Fetch fresh keys for locks from Bold's cloud, keeping old ones on errors."""
        if not device_ids:
            return
        try:
            handshakes = await self._client.get_bluetooth_handshakes(device_ids)
            commands = await self._client.get_bluetooth_commands(
                device_ids, [COMMAND_ACTIVATE, COMMAND_DEACTIVATE]
            )
        except BoldError as err:
            level = logging.DEBUG if self._failing else logging.WARNING
            self._failing = True
            _LOGGER.log(
                level, "Couldn't refresh the Bluetooth keys of Bold locks: %s", err
            )
            return
        if self._failing:
            _LOGGER.info("Refreshed the Bluetooth keys of Bold locks again")
        self._failing = False

        lock_commands: dict[int, dict[str, BoldSecret]] = {}
        for command in commands:
            if (
                isinstance(device_id := command.get("deviceId"), int)
                and isinstance(command_type := command.get("commandType"), str)
                and (
                    secret := _secret(command.get("payload"), command.get("expiration"))
                )
            ):
                lock_commands.setdefault(device_id, {})[command_type] = secret

        for handshake in handshakes:
            device_id = handshake.get("deviceId")
            key = _secret(handshake.get("handshakeKey"), handshake.get("expiration"))
            payload = _secret(handshake.get("payload"), handshake.get("expiration"))
            if isinstance(device_id, int) and key and payload:
                self._keys[device_id] = BoldLockKeys(
                    key, payload, lock_commands.get(device_id, {})
                )

        await self._store.async_save(
            {
                "locks": {
                    str(device_id): {
                        "handshake_key": _encode(keys.handshake_key),
                        "handshake_payload": _encode(keys.handshake_payload),
                        "commands": {
                            command_type: _encode(command)
                            for command_type, command in keys.commands.items()
                        },
                    }
                    for device_id, keys in self._keys.items()
                }
            }
        )
        for listener in list(self._listeners):
            listener()

    @staticmethod
    async def async_remove_stored(hass: HomeAssistant, entry_id: str) -> None:
        """Delete the stored keys of a config entry."""
        await Store[dict[str, Any]](
            hass, STORAGE_VERSION, _storage_key(entry_id), private=True
        ).async_remove()
