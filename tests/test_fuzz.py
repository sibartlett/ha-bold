"""Property-based tests of parsing input Home Assistant doesn't control.

Bluetooth advertisements and packets come from anything nearby, and Bold's
API and webhook send JSON whose exact shape isn't guaranteed. Whatever they
contain, parsing must either succeed or be rejected cleanly, never crash.
"""

import asyncio
import os
from typing import Any

from hypothesis import given, settings, strategies as st

from custom_components.bold.boldsmartlock import (
    BoldBluetoothError,
    BoldDevice,
    BoldEvent,
    parse_advertisement,
    parse_datetime,
    parse_duration,
)
from custom_components.bold.boldsmartlock.ble import (
    PACKET_EVENT,
    BoldBleSession,
    encode_packet,
)

from .test_ble import ACTIVATE_COMMAND, HANDSHAKE_KEY, HANDSHAKE_PAYLOAD, FakeLock

# Hypothesis runs each test many times; don't fail on a slow CI machine.
# HYPOTHESIS_PROFILE=thorough tries many more inputs.
settings.register_profile("bold", deadline=None)
settings.register_profile("thorough", deadline=None, max_examples=5000)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "bold"))

# Keys Bold's device and event payloads use, so generated objects hit the
# parsing code rather than only unknown keys.
KEYS = [
    "id",
    "name",
    "type",
    "time",
    "result",
    "method",
    "status",
    "device",
    "user",
    "account",
    "triggeredBy",
    "firstName",
    "lastName",
    "emailAddress",
    "remoteActivation",
    "connect",
    "activationTime",
    "keepActiveUntil",
    "voltageIdle",
    "voltageUnderLoad",
    "uptime",
    "body",
    "model",
    "features",
    "settings",
    "gateway",
    "owner",
    "organizationId",
    "actualFirmwareVersion",
    "requiredFirmwareVersion",
    "batteryLevel",
    "batteryLastMeasurement",
    "isActiveUntil",
    "lockedStatus",
    "locked",
    "lastLocked",
    "remoteAccess",
    "eventLog",
    "rssi",
    "rssiLevel",
    "lastSeen",
]
# Values Bold sends, mixed in so generated payloads take the parsing branches.
REALISTIC = st.sampled_from(
    [
        "DeviceActivation",
        "DeviceDeactivation",
        "DeviceLocked",
        "DeviceStatus",
        "DeviceDebug",
        "Success",
        "Locked",
        "UNLOCKED",
        "High",
        "2026-09-24T12:00:00Z",
        "2026-09-24T12:00:00",
        "PT5S",
        "5 seconds",
        "9999999999 days",
        "",
    ]
)
SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text(max_size=20)
    | REALISTIC
)
JSON: st.SearchStrategy[Any] = st.recursive(
    SCALARS,
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.sampled_from(KEYS), children, max_size=6)
    ),
    max_leaves=30,
)
PAYLOADS = st.dictionaries(st.sampled_from(KEYS) | st.text(max_size=5), JSON)


@given(PAYLOADS)
def test_event_from_any_payload(payload: dict[str, Any]) -> None:
    """Test any event payload is parsed or rejected, without raising."""
    event = BoldEvent.from_api(payload)
    if event is not None:
        assert isinstance(event.type, str)
        assert event.user_name is None or isinstance(event.user_name, str)
        assert event.device_id is None or isinstance(event.device_id, int)
        # Keys and ordering work on whatever was parsed.
        assert event.key == event.key
        assert event.sort_key <= event.sort_key


@given(PAYLOADS)
def test_device_from_any_payload(payload: dict[str, Any]) -> None:
    """Test any device payload is parsed or rejected, without raising."""
    device = BoldDevice.from_api(payload)
    if device is not None:
        assert isinstance(device.id, int)
        assert isinstance(device.name, str)
        assert isinstance(device.update_available, bool)
        assert device.gateway_id is None or isinstance(device.gateway_id, int)


@given(JSON)
def test_parse_any_value(value: Any) -> None:
    """Test durations and timestamps are parsed or rejected, without raising."""
    parse_duration(value)
    parse_datetime(value)


@given(st.binary(max_size=32))
def test_advertisement_from_any_bytes(data: bytes) -> None:
    """Test any manufacturer data is parsed or rejected, without raising."""
    advertisement = parse_advertisement(data)
    if advertisement is not None:
        assert advertisement.device_id == int.from_bytes(data[3:11], "little")


PACKETS = st.lists(
    st.tuples(
        st.integers(0, 0xEF).filter(lambda packet_type: packet_type != PACKET_EVENT),
        st.binary(max_size=40),
    ),
    max_size=5,
)


@given(PACKETS, st.lists(st.integers(1, 20), min_size=1))
def test_packets_reassembled(
    packets: list[tuple[int, bytes]], chunk_sizes: list[int]
) -> None:
    """Test packets split into notifications at any points are reassembled."""
    session = BoldBleSession(_ignore_write)
    stream = b"".join(encode_packet(type_, payload) for type_, payload in packets)
    position = 0
    for size in chunk_sizes * (len(stream) + 1):
        if position >= len(stream):
            break
        session.data_received(stream[position : position + size])
        position += size
    received = []
    while not session._packets.empty():  # noqa: SLF001
        received.append(session._packets.get_nowait())  # noqa: SLF001
    assert received == packets


@given(st.lists(st.binary(max_size=40), max_size=10))
def test_any_notifications(chunks: list[bytes]) -> None:
    """Test any bytes the lock notifies are buffered or queued, without raising."""
    session = BoldBleSession(_ignore_write)
    for chunk in chunks:
        session.data_received(chunk)


@given(
    st.lists(
        # Events aren't replies: waiting past one is left to the timeout that
        # async_send_command puts around the whole conversation.
        st.tuples(
            st.integers(0, 0xFF).filter(lambda type_: type_ != PACKET_EVENT),
            st.binary(max_size=40),
        ),
        min_size=3,
        max_size=3,
    )
)
def test_conversation_with_any_replies(replies: list[tuple[int, bytes]]) -> None:
    """Test a lock replying with anything fails with a Bluetooth error, or works."""

    async def converse() -> None:
        session: BoldBleSession
        answers = iter(replies)

        async def write(packet: bytes) -> None:
            type_, payload = next(answers)
            # Error packets are a single byte; others are framed.
            session.data_received(
                bytes([type_]) if type_ >= 0xF0 else encode_packet(type_, payload)
            )

        session = BoldBleSession(write)
        try:
            await session.handshake(bytes(16), bytes(32))
            await session.command(bytes(16))
        except BoldBluetoothError:
            pass

    asyncio.run(asyncio.wait_for(converse(), timeout=5))


@given(st.binary(max_size=10))
def test_any_command_acknowledgement(ack: bytes) -> None:
    """Test any acknowledgement after a real handshake is understood or rejected."""

    async def converse() -> None:
        lock = FakeLock(ack=ack)
        session = BoldBleSession(lock.write)
        lock.session = session
        await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)
        try:
            activation_time = await session.command(ACTIVATE_COMMAND)
        except BoldBluetoothError:
            assert not ack or ack[0] != 0x00
        else:
            assert ack[0] == 0x00
            # Too short to carry an activation time means none was given.
            expected = int.from_bytes(ack[1:3], "little") if len(ack) >= 3 else 0
            assert activation_time == expected

    asyncio.run(asyncio.wait_for(converse(), timeout=5))


async def _ignore_write(packet: bytes) -> None:
    """Write nowhere."""
