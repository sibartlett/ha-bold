"""Tests for the Bold Bluetooth protocol."""

import os
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import pytest

from custom_components.bold.boldsmartlock.ble import (
    PACKET_COMMAND,
    PACKET_COMMAND_ACK,
    PACKET_EVENT,
    PACKET_HANDSHAKE_CLIENT_RESPONSE,
    PACKET_HANDSHAKE_EXPIRED,
    PACKET_HANDSHAKE_FINISHED,
    PACKET_HANDSHAKE_RESPONSE,
    PACKET_START_HANDSHAKE,
    BoldBleSession,
    BoldBluetoothError,
    BoldCryptor,
    encode_packet,
    parse_advertisement,
)

HANDSHAKE_KEY = os.urandom(16)
HANDSHAKE_PAYLOAD = os.urandom(62)
ACTIVATE_COMMAND = os.urandom(51)


class FakeLock:
    """The lock's side of the protocol, written independently of the client."""

    def __init__(
        self,
        *,
        result: int = 0x00,
        activation_time: int = 15,
        chunk_size: int = 0,
        event_first: bool = False,
        reject_handshake: bool = False,
        ack: bytes | None = None,
        finish_status: int = 0x00,
        echo_challenge: bool = True,
    ) -> None:
        """Set how the lock answers: its result code, and how it sends replies.

        With ack, the lock acknowledges commands with those bytes instead.
        finish_status and echo_challenge make it finish the handshake wrongly.
        """
        self.session: BoldBleSession | None = None
        self.result = result
        self.activation_time = activation_time
        self.chunk_size = chunk_size
        self.event_first = event_first
        self.reject_handshake = reject_handshake
        self.ack = ack
        self.finish_status = finish_status
        self.echo_challenge = echo_challenge
        self.commands: list[bytes] = []
        self._nonce = os.urandom(13)
        self._server_challenge = os.urandom(8)
        self._cryptor: BoldCryptor | None = None

    def _send(self, data: bytes) -> None:
        assert self.session is not None
        if self.event_first:
            self.session.data_received(encode_packet(PACKET_EVENT, b"event"))
        if not self.chunk_size:
            self.session.data_received(data)
            return
        for i in range(0, len(data), self.chunk_size):
            self.session.data_received(data[i : i + self.chunk_size])

    async def write(self, packet: bytes) -> None:
        """Receive a packet from the client, and reply as a lock would."""
        packet_type = packet[0]
        size = int.from_bytes(packet[1:3], "little")
        payload = packet[3:]
        assert len(payload) == size

        if packet_type == PACKET_START_HANDSHAKE:
            if self.reject_handshake:
                self._send(bytes([PACKET_HANDSHAKE_EXPIRED]))
                return
            assert payload == HANDSHAKE_PAYLOAD
            self._send(
                encode_packet(
                    PACKET_HANDSHAKE_RESPONSE, self._nonce + self._server_challenge
                )
            )
        elif packet_type == PACKET_HANDSHAKE_CLIENT_RESPONSE:
            cryptor = BoldCryptor(HANDSHAKE_KEY, self._nonce)
            expected_challenge = cryptor.process(self._server_challenge)
            client_response = cryptor.process(payload)
            assert client_response[:8] == expected_challenge, "bad handshake"
            self._cryptor = BoldCryptor(client_response, self._nonce)
            challenge = client_response[8:] if self.echo_challenge else bytes(8)
            self._send(
                encode_packet(
                    PACKET_HANDSHAKE_FINISHED,
                    self._cryptor.process(bytes([self.finish_status]) + challenge),
                )
            )
        elif packet_type == PACKET_COMMAND:
            assert self._cryptor is not None
            self.commands.append(self._cryptor.process(payload))
            ack = self.ack
            if ack is None:
                ack = bytes([self.result]) + self.activation_time.to_bytes(2, "little")
            self._send(encode_packet(PACKET_COMMAND_ACK, self._cryptor.process(ack)))
        else:
            pytest.fail(f"Unexpected packet {packet_type:#x}")


def _session(lock: FakeLock) -> BoldBleSession:
    session = BoldBleSession(lock.write)
    lock.session = session
    return session


@pytest.mark.parametrize(
    "options",
    [{}, {"chunk_size": 20}, {"chunk_size": 1, "event_first": True}],
    ids=["whole", "20-byte chunks", "bytewise with events"],
)
async def test_activate(options: dict[str, Any]) -> None:
    """Test a handshake and command against a simulated lock."""
    # A new lock each run: it records the commands it receives.
    lock = FakeLock(**options)
    session = _session(lock)
    await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)
    assert await session.command(ACTIVATE_COMMAND) == 15
    assert lock.commands == [ACTIVATE_COMMAND]


async def test_wrong_handshake_key() -> None:
    """Test a wrong handshake key is detected by the lock."""
    lock = FakeLock()
    session = _session(lock)
    with pytest.raises(AssertionError, match="bad handshake"):
        await session.handshake(os.urandom(16), HANDSHAKE_PAYLOAD)


async def test_handshake_expired() -> None:
    """Test the lock rejecting an expired handshake."""
    session = _session(FakeLock(reject_handshake=True))
    with pytest.raises(BoldBluetoothError, match="expired"):
        await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)


async def test_access_denied() -> None:
    """Test the lock denying a command."""
    session = _session(FakeLock(result=0xF0))
    await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)
    with pytest.raises(BoldBluetoothError, match="denied"):
        await session.command(ACTIVATE_COMMAND)


async def test_command_needs_handshake() -> None:
    """Test commands can't be sent before a handshake."""
    with pytest.raises(BoldBluetoothError, match="handshake first"):
        await _session(FakeLock()).command(ACTIVATE_COMMAND)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"finish_status": 0x01}, "failed the handshake"),
        ({"echo_challenge": False}, "failed the handshake"),
    ],
    ids=["bad status", "wrong challenge"],
)
async def test_lock_fails_handshake(options: dict[str, Any], message: str) -> None:
    """Test the lock must both report success and return our challenge."""
    with pytest.raises(BoldBluetoothError, match=message):
        await _session(FakeLock(**options)).handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)


async def test_longer_acknowledgement() -> None:
    """Test the activation time is the two bytes after the result."""
    session = _session(FakeLock(ack=b"\x00\x0f\x00\x07"))
    await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)
    assert await session.command(ACTIVATE_COMMAND) == 15


def test_cryptor_known_answer() -> None:
    """Test the IV is the nonce, two zero bytes and a block counter.

    The simulated lock uses BoldCryptor too, so check it against AES-CTR
    directly: that's what the real lock does.
    """
    key, nonce = bytes(range(16)), bytes(range(13))
    first, second = bytes(40), bytes(20)

    def aes_ctr(counter: int, data: bytes) -> bytes:
        iv = nonce + bytes([0, 0, counter])
        encryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
        return encryptor.update(data) + encryptor.finalize()

    cryptor = BoldCryptor(key, nonce)
    assert cryptor.process(first) == aes_ctr(0, first)
    # 40 bytes used three 16-byte blocks, so the next message starts at 3.
    assert cryptor.process(second) == aes_ctr(3, second)


def test_cryptor_is_symmetric() -> None:
    """Test decrypting with the same key and nonce restores the data."""
    key, nonce, data = os.urandom(16), os.urandom(13), os.urandom(40)
    assert (
        BoldCryptor(key, nonce).process(BoldCryptor(key, nonce).process(data)) == data
    )


def test_parse_advertisement() -> None:
    """Test parsing the manufacturer data of a Bold lock."""
    advertisement = parse_advertisement(bytes.fromhex("020103010000000000000002"))
    assert advertisement is not None
    assert advertisement.protocol_version == 2
    assert advertisement.device_type == 1
    assert advertisement.model == 3
    assert advertisement.device_id == 1
    assert advertisement.events_available
    assert not advertisement.installable
    assert parse_advertisement(b"\x02\x01") is None
    # The other flags, each a bit of the last byte.
    advertisement = parse_advertisement(bytes.fromhex("02010301000000000000000d"))
    assert advertisement is not None
    assert advertisement.installable
    assert not advertisement.events_available
    assert advertisement.should_time_sync
    assert advertisement.in_dfu_mode
