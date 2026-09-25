"""Tests for the Bold Bluetooth protocol."""

from __future__ import annotations

import os

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
    ) -> None:
        self.session: BoldBleSession | None = None
        self.result = result
        self.activation_time = activation_time
        self.chunk_size = chunk_size
        self.event_first = event_first
        self.reject_handshake = reject_handshake
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
            self._send(
                encode_packet(
                    PACKET_HANDSHAKE_FINISHED,
                    self._cryptor.process(b"\x00" + client_response[8:]),
                )
            )
        elif packet_type == PACKET_COMMAND:
            assert self._cryptor is not None
            self.commands.append(self._cryptor.process(payload))
            ack = bytes([self.result]) + self.activation_time.to_bytes(2, "little")
            self._send(encode_packet(PACKET_COMMAND_ACK, self._cryptor.process(ack)))
        else:
            pytest.fail(f"Unexpected packet {packet_type:#x}")


def _session(lock: FakeLock) -> BoldBleSession:
    session = BoldBleSession(lock.write)
    lock.session = session
    return session


@pytest.mark.parametrize(
    "lock",
    [FakeLock(), FakeLock(chunk_size=20), FakeLock(chunk_size=1, event_first=True)],
    ids=["whole", "20-byte chunks", "bytewise with events"],
)
async def test_activate(lock: FakeLock) -> None:
    """Test a handshake and command against a simulated lock."""
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
