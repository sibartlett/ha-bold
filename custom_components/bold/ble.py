"""Bluetooth protocol of Bold locks.

Bold locks accept commands over a Nordic UART service. A session starts with a
handshake, using a handshake key and payload from Bold's cloud, after which
commands (also from Bold's cloud) are sent encrypted with AES-128-CTR.

The protocol is ported from homebridge-bold-ble
(https://github.com/robbertkl/homebridge-bold-ble), under its MIT license:

    Copyright (c) 2023 Robbert Klarenbeek

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to permit
    persons to whom the Software is furnished to do so, subject to the
    following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import os
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .api import BoldError

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice

MANUFACTURER_ID = 0x065B  # Sesam Solutions BV
SERVICE_UUID = "0000fd30-0000-1000-8000-00805f9b34fb"
UART_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # We write to this.
UART_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # The lock notifies on this.

PACKET_START_HANDSHAKE = 0xA0
PACKET_HANDSHAKE_RESPONSE = 0xA1
PACKET_HANDSHAKE_CLIENT_RESPONSE = 0xA2
PACKET_HANDSHAKE_FINISHED = 0xA3
PACKET_COMMAND = 0xA4
PACKET_COMMAND_ACK = 0xA5
PACKET_EVENT = 0xD0
PACKET_CLIENT_BLOCKED = 0xFD
PACKET_HANDSHAKE_EXPIRED = 0xFE
PACKET_ENCRYPTION_ERROR = 0xFF

COMMAND_RESULT_OK = 0x00
COMMAND_RESULT_ACCESS_DENIED = 0xF0

NONCE_SIZE = 13
CHALLENGE_SIZE = 8


class BoldBluetoothError(BoldError):
    """A Bluetooth conversation with a lock failed."""


class BoldBluetoothUnavailableError(BoldBluetoothError):
    """The lock can't be reached over Bluetooth, or there are no keys."""


@dataclass(frozen=True)
class BoldAdvertisement:
    """What a Bold device advertises over Bluetooth."""

    protocol_version: int
    device_type: int
    model: int
    device_id: int
    installable: bool
    events_available: bool
    should_time_sync: bool
    in_dfu_mode: bool


def parse_advertisement(manufacturer_data: bytes) -> BoldAdvertisement | None:
    """Parse the manufacturer data of a Bold advertisement."""
    if len(manufacturer_data) != 12:
        return None
    flags = manufacturer_data[11]
    return BoldAdvertisement(
        protocol_version=manufacturer_data[0],
        device_type=manufacturer_data[1],
        model=manufacturer_data[2],
        device_id=int.from_bytes(manufacturer_data[3:11], "little"),
        installable=bool(flags & 1),
        events_available=bool(flags & 2),
        should_time_sync=bool(flags & 4),
        in_dfu_mode=bool(flags & 8),
    )


class BoldCryptor:
    """AES-128-CTR as Bold uses it: a 13-byte nonce and a block counter."""

    def __init__(self, key: bytes, nonce: bytes) -> None:
        """Initialize the cryptor."""
        self._key = key
        self._nonce = nonce
        self._counter = 0

    def process(self, data: bytes) -> bytes:
        """Encrypt or decrypt data (CTR mode is symmetric)."""
        iv = self._nonce + bytes([0, 0, self._counter & 0xFF])
        encryptor = Cipher(algorithms.AES(self._key), modes.CTR(iv)).encryptor()
        self._counter += -(-len(data) // 16)
        return encryptor.update(data) + encryptor.finalize()


def encode_packet(packet_type: int, payload: bytes) -> bytes:
    """Frame a packet: type, little-endian payload length, payload."""
    return bytes([packet_type]) + len(payload).to_bytes(2, "little") + payload


class BoldBleSession:
    """A conversation with a Bold lock over an established connection.

    Feed notifications from the lock to data_received(); packets are written
    with the write callback.
    """

    def __init__(self, write: Callable[[bytes], Awaitable[None]]) -> None:
        """Initialize the session."""
        self._write = write
        self._buffer = b""
        self._packets: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue()
        self._cryptor: BoldCryptor | None = None

    def data_received(self, data: bytes) -> None:
        """Handle bytes notified by the lock, which may split or join packets."""
        self._buffer += data
        while self._buffer:
            packet_type = self._buffer[0]
            if packet_type >= 0xF0:
                # Error packets are a single byte.
                self._buffer = self._buffer[1:]
                self._packets.put_nowait((packet_type, b""))
                continue
            if len(self._buffer) < 3:
                return
            size = int.from_bytes(self._buffer[1:3], "little")
            if len(self._buffer) < size + 3:
                return
            payload = self._buffer[3 : size + 3]
            self._buffer = self._buffer[size + 3 :]
            if packet_type != PACKET_EVENT:
                # Events can arrive in the middle of a conversation.
                self._packets.put_nowait((packet_type, payload))

    async def _call(self, packet_type: int, payload: bytes, reply_type: int) -> bytes:
        """Send a packet and wait for its reply."""
        await self._write(encode_packet(packet_type, payload))
        received_type, reply = await self._packets.get()
        if received_type == reply_type:
            return reply
        if received_type == PACKET_CLIENT_BLOCKED:
            raise BoldBluetoothError("The lock blocked this client")
        if received_type == PACKET_HANDSHAKE_EXPIRED:
            raise BoldBluetoothError("The handshake has expired")
        if received_type == PACKET_ENCRYPTION_ERROR:
            raise BoldBluetoothError("The lock reported an encryption error")
        raise BoldBluetoothError(
            f"Unexpected reply {received_type:#x}, expected {reply_type:#x}"
        )

    async def handshake(self, handshake_key: bytes, handshake_payload: bytes) -> None:
        """Authenticate with the lock and set up encryption."""
        response = await self._call(
            PACKET_START_HANDSHAKE, handshake_payload, PACKET_HANDSHAKE_RESPONSE
        )
        if len(response) < NONCE_SIZE + CHALLENGE_SIZE:
            raise BoldBluetoothError("Handshake response is too short")
        nonce = response[:NONCE_SIZE]
        server_challenge = response[NONCE_SIZE : NONCE_SIZE + CHALLENGE_SIZE]

        handshake_cryptor = BoldCryptor(handshake_key, nonce)
        client_challenge = os.urandom(CHALLENGE_SIZE)
        client_response = handshake_cryptor.process(server_challenge) + client_challenge
        finished = await self._call(
            PACKET_HANDSHAKE_CLIENT_RESPONSE,
            handshake_cryptor.process(client_response),
            PACKET_HANDSHAKE_FINISHED,
        )

        self._cryptor = BoldCryptor(client_response, nonce)
        server_response = self._cryptor.process(finished)
        if server_response[:1] != b"\x00" or server_response[1:] != client_challenge:
            raise BoldBluetoothError("The lock failed the handshake")

    async def command(self, command_payload: bytes) -> int:
        """Send a command, returning the activation time in seconds."""
        if self._cryptor is None:
            raise BoldBluetoothError("Commands need a handshake first")
        ack = self._cryptor.process(
            await self._call(
                PACKET_COMMAND,
                self._cryptor.process(command_payload),
                PACKET_COMMAND_ACK,
            )
        )
        if not ack:
            raise BoldBluetoothError("Empty command acknowledgement")
        if ack[0] == COMMAND_RESULT_ACCESS_DENIED:
            raise BoldBluetoothError("The lock denied access")
        if ack[0] != COMMAND_RESULT_OK:
            raise BoldBluetoothError(f"The lock returned result {ack[0]:#x}")
        return int.from_bytes(ack[1:3], "little") if len(ack) >= 3 else 0


async def async_send_command(
    ble_device: BLEDevice,
    handshake_key: bytes,
    handshake_payload: bytes,
    command_payload: bytes,
    timeout: float,
) -> int:
    """Connect to a lock, and send it a command.

    Returns the activation time in seconds. Uses Home Assistant's Bluetooth
    stack, so this works through ESPHome Bluetooth proxies too.
    """
    # Only available when Home Assistant's Bluetooth integration is set up.
    from bleak.exc import BleakError  # noqa: PLC0415
    from bleak_retry_connector import (  # noqa: PLC0415
        BleakClientWithServiceCache,
        establish_connection,
    )

    try:
        async with asyncio.timeout(timeout):
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                ble_device.name or ble_device.address,
                max_attempts=2,
            )
            try:

                async def write(data: bytes) -> None:
                    await client.write_gatt_char(UART_RX_UUID, data, response=True)

                session = BoldBleSession(write)
                await client.start_notify(
                    UART_TX_UUID,
                    lambda _characteristic, data: session.data_received(bytes(data)),
                )
                await session.handshake(handshake_key, handshake_payload)
                return await session.command(command_payload)
            finally:
                await client.disconnect()
    except TimeoutError as err:
        raise BoldBluetoothError("Timed out talking to the lock") from err
    except BleakError as err:
        raise BoldBluetoothError(f"Bluetooth error: {err}") from err
