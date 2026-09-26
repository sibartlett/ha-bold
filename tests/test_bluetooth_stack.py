"""Tests for the parts of Bluetooth support that touch the radio and storage."""

from datetime import UTC, datetime, timedelta
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.bluetooth import BluetoothServiceInfo
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
import pytest

from custom_components.bold.boldsmartlock import BoldClient
from custom_components.bold.boldsmartlock.ble import (
    PACKET_CLIENT_BLOCKED,
    PACKET_COMMAND_ACK,
    PACKET_ENCRYPTION_ERROR,
    PACKET_HANDSHAKE_RESPONSE,
    UART_RX_UUID,
    UART_TX_UUID,
    BoldBleSession,
    BoldBluetoothError,
    BoldCryptor,
    _async_disconnect,
    async_send_command,
    encode_packet,
)
from custom_components.bold.boldsmartlock.const import API_URL
from custom_components.bold.keys import BoldBluetoothKeys, decode_keys, parse_keys
from custom_components.bold.tracker import BoldBluetoothTracker

from .conftest import HANDSHAKE_KEY as CLOUD_HANDSHAKE_KEY, LOCK_ID, mock_bluetooth_keys
from .test_ble import ACTIVATE_COMMAND, HANDSHAKE_KEY, HANDSHAKE_PAYLOAD, FakeLock

ADDRESS = "AA:BB:CC:00:00:01"
LOCK_ADVERTISEMENT = BluetoothServiceInfo(
    "lock",
    ADDRESS,
    -70,
    {1627: bytes.fromhex("020101010000000000000000")},
    {},
    [],
    "hci0",
)


class FakeBleakClient:
    """A connected Bleak client, wired to a simulated lock."""

    def __init__(self, lock: FakeLock) -> None:
        """Connect to the simulated lock."""
        self.lock = lock
        self.disconnected = False

    async def start_notify(self, uuid: str, callback: Any) -> None:
        """Pass the lock's replies to the callback."""
        assert uuid == UART_TX_UUID
        # The simulated lock replies straight into the notification callback.
        session = BoldBleSession(self.lock.write)
        session.data_received = lambda data: callback(None, bytearray(data))  # type: ignore[method-assign]
        self.lock.session = session

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool) -> None:
        """Send a packet to the lock."""
        assert uuid == UART_RX_UUID
        assert response
        await self.lock.write(data)

    async def disconnect(self) -> None:
        """Disconnect from the lock."""
        self.disconnected = True


async def test_send_command_over_bleak() -> None:
    """Test a command end to end through a Bleak client."""
    lock = FakeLock()
    client = FakeBleakClient(lock)
    ble_device = SimpleNamespace(name=None, address=ADDRESS)
    with patch(
        "bleak_retry_connector.establish_connection", AsyncMock(return_value=client)
    ) as establish_connection:
        activation_time = await async_send_command(
            ble_device,  # type: ignore[arg-type]
            HANDSHAKE_KEY,
            HANDSHAKE_PAYLOAD,
            ACTIVATE_COMMAND,
            timeout=5,
        )
    assert activation_time == 15
    assert lock.commands == [ACTIVATE_COMMAND]
    assert client.disconnected
    # A device without a name is named by its address.
    establish_connection.assert_awaited_once_with(
        BleakClientWithServiceCache, ble_device, ADDRESS, max_attempts=2
    )


async def test_send_command_times_out() -> None:
    """Test a lock that never replies times out, and is disconnected."""
    lock = FakeLock()
    client = FakeBleakClient(lock)

    async def silent(_packet: bytes) -> None:
        """Never reply."""

    lock.write = silent  # type: ignore[method-assign]
    with (
        patch(
            "bleak_retry_connector.establish_connection", AsyncMock(return_value=client)
        ),
        pytest.raises(BoldBluetoothError, match="Timed out"),
    ):
        await async_send_command(
            SimpleNamespace(name="lock", address=ADDRESS),  # type: ignore[arg-type]
            HANDSHAKE_KEY,
            HANDSHAKE_PAYLOAD,
            ACTIVATE_COMMAND,
            timeout=0.05,
        )
    assert client.disconnected


async def test_send_command_disconnects_later() -> None:
    """Test the result comes before the disconnect, which ignores errors."""
    lock = FakeLock()
    client = FakeBleakClient(lock)
    disconnects: list = []
    with patch(
        "bleak_retry_connector.establish_connection", AsyncMock(return_value=client)
    ):
        activation_time = await async_send_command(
            SimpleNamespace(name="lock", address=ADDRESS),  # type: ignore[arg-type]
            HANDSHAKE_KEY,
            HANDSHAKE_PAYLOAD,
            ACTIVATE_COMMAND,
            timeout=5,
            disconnect_later=disconnects.append,
        )
    assert activation_time == 15
    assert not client.disconnected
    await disconnects[0]
    assert client.disconnected

    # A failing disconnect doesn't matter: the command already succeeded.
    client.disconnect = AsyncMock(side_effect=BleakError("gone"))  # type: ignore[method-assign]
    await _async_disconnect(client)


async def test_send_command_error_disconnects_first() -> None:
    """Test the lock is disconnected before an error is raised."""
    lock = FakeLock(result=0xF0)
    client = FakeBleakClient(lock)
    with (
        patch(
            "bleak_retry_connector.establish_connection", AsyncMock(return_value=client)
        ),
        pytest.raises(BoldBluetoothError, match="denied"),
    ):
        await async_send_command(
            SimpleNamespace(name="lock", address=ADDRESS),  # type: ignore[arg-type]
            HANDSHAKE_KEY,
            HANDSHAKE_PAYLOAD,
            ACTIVATE_COMMAND,
            timeout=5,
            disconnect_later=lambda _disconnect: pytest.fail("not on errors"),
        )
    assert client.disconnected


@pytest.mark.parametrize(
    ("error", "message"),
    [(BleakError("gone"), "Bluetooth error: gone"), (TimeoutError(), "Timed out")],
)
async def test_send_command_errors(error: Exception, message: str) -> None:
    """Test connection errors are translated."""
    with (
        patch(
            "bleak_retry_connector.establish_connection", AsyncMock(side_effect=error)
        ),
        pytest.raises(BoldBluetoothError, match=message),
    ):
        await async_send_command(
            SimpleNamespace(name=None, address=ADDRESS),  # type: ignore[arg-type]
            HANDSHAKE_KEY,
            HANDSHAKE_PAYLOAD,
            ACTIVATE_COMMAND,
            timeout=5,
        )


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (bytes([PACKET_CLIENT_BLOCKED]), "blocked"),
        (bytes([PACKET_ENCRYPTION_ERROR]), "encryption error"),
        (encode_packet(PACKET_COMMAND_ACK, b""), "Unexpected reply"),
        (encode_packet(PACKET_HANDSHAKE_RESPONSE, b"short"), "too short"),
    ],
)
async def test_handshake_errors(reply: bytes, message: str) -> None:
    """Test errors the lock can answer a handshake with."""

    async def write(_packet: bytes) -> None:
        session.data_received(reply)

    session = BoldBleSession(write)
    with pytest.raises(BoldBluetoothError, match=message):
        await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)


async def test_handshake_wrong_server_response() -> None:
    """Test a lock that fails to prove it knows the session key."""
    nonce = bytes(13)

    async def write(packet: bytes) -> None:
        if packet[0] == 0xA0:
            session.data_received(
                encode_packet(PACKET_HANDSHAKE_RESPONSE, nonce + bytes(8))
            )
        else:
            session.data_received(encode_packet(0xA3, bytes(9)))

    session = BoldBleSession(write)
    with pytest.raises(BoldBluetoothError, match="failed the handshake"):
        await session.handshake(HANDSHAKE_KEY, HANDSHAKE_PAYLOAD)


@pytest.mark.parametrize(
    ("ack", "message"), [(b"", "Empty"), (b"\x05", "returned result 0x5")]
)
async def test_command_errors(ack: bytes, message: str) -> None:
    """Test unexpected command acknowledgements."""
    lock_cryptor = BoldCryptor(bytes(16), bytes(13))

    async def write(packet: bytes) -> None:
        # Like the lock: decrypt the command, then encrypt the acknowledgement.
        lock_cryptor.process(packet[3:])
        session.data_received(
            encode_packet(PACKET_COMMAND_ACK, lock_cryptor.process(ack))
        )

    session = BoldBleSession(write)
    session._cryptor = BoldCryptor(bytes(16), bytes(13))  # noqa: SLF001
    with pytest.raises(BoldBluetoothError, match=message):
        await session.command(ACTIVATE_COMMAND)


@pytest.fixture
def fake_bluetooth_integration(hass: HomeAssistant) -> MagicMock:
    """Stand in for Home Assistant's Bluetooth integration."""
    hass.config.components.add("bluetooth")
    module = MagicMock()
    module.async_discovered_service_info.return_value = [LOCK_ADVERTISEMENT]
    module.async_register_callback.return_value = MagicMock()
    module.async_track_unavailable.return_value = MagicMock()
    module.async_ble_device_from_address.return_value = "ble device"
    # "from homeassistant.components import bluetooth" reads the attribute.
    with (
        patch.dict(sys.modules, {"homeassistant.components.bluetooth": module}),
        patch("homeassistant.components.bluetooth", module, create=True),
    ):
        yield module


async def test_tracker(
    hass: HomeAssistant,
    fake_bluetooth_integration: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test following a lock appearing, disappearing and moving."""
    entry = MagicMock()
    started = dt_util.utcnow()
    tracker = BoldBluetoothTracker(hass)
    freezer.tick(timedelta(minutes=1))
    changes: list[bool] = []
    tracker.async_add_listener(
        LOCK_ID, lambda: changes.append(tracker.is_reachable(LOCK_ID))
    )

    tracker.async_start(entry)
    assert tracker.is_reachable(LOCK_ID)
    assert tracker.is_reachable(LOCK_ID, min_rssi=-85)
    assert not tracker.is_reachable(LOCK_ID, min_rssi=-60)
    assert changes == [True]
    assert tracker.ble_device(LOCK_ID) == "ble device"
    fake_bluetooth_integration.async_ble_device_from_address.assert_called_with(
        hass, ADDRESS, connectable=True
    )

    assert tracker.rssi(LOCK_ID) == -70
    assert tracker.unreachable_since(LOCK_ID) is None

    # The lock stops advertising.
    freezer.tick(timedelta(minutes=5))
    unavailable = fake_bluetooth_integration.async_track_unavailable.call_args[0][1]
    unavailable(LOCK_ADVERTISEMENT)
    assert changes == [True, False]
    assert tracker.rssi(LOCK_ID) is None
    # Out of range since it was last heard; a lock never heard, since startup.
    assert tracker.unreachable_since(LOCK_ID) == started + timedelta(minutes=1)
    assert tracker.unreachable_since(999) == started

    # It comes back, via the advertisement callback.
    on_advertisement = fake_bluetooth_integration.async_register_callback.call_args[0][
        1
    ]
    on_advertisement(LOCK_ADVERTISEMENT, None)
    assert changes == [True, False, True]

    # Other manufacturers' data is ignored.
    tracker.async_process_advertisement(
        BluetoothServiceInfo("x", "11:22:33:44:55:66", -50, {76: b"x"}, {}, [], "hci0")
    )

    # Stopping unsubscribes.
    stop = entry.async_on_unload.call_args[0][0]
    stop()
    fake_bluetooth_integration.async_register_callback.return_value.assert_called_once()


async def test_tracker_without_bluetooth(hass: HomeAssistant) -> None:
    """Test the tracker does nothing without Home Assistant's Bluetooth."""
    tracker = BoldBluetoothTracker(hass)
    assert not tracker.enabled
    tracker.async_start(MagicMock())
    tracker.async_process_advertisement(LOCK_ADVERTISEMENT)
    assert tracker.is_reachable(LOCK_ID)
    assert tracker.ble_device(LOCK_ID) is None


async def test_keys_survive_restart(
    hass: HomeAssistant, aioclient_mock, hass_storage: dict[str, Any]
) -> None:
    """Test keys are stored, loaded again, and removed."""

    async def token() -> str:
        return "token"

    mock_bluetooth_keys(aioclient_mock)
    client = BoldClient(async_get_clientsession(hass), token)
    created: list[dict[str, Any]] = []

    class RecordingStore[T](Store[T]):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created.append(kwargs)
            super().__init__(*args, **kwargs)

    with patch("custom_components.bold.keys.Store", RecordingStore):
        keys = BoldBluetoothKeys(hass, "entry", client)
        await keys.async_refresh([LOCK_ID])
        stored = hass_storage["bold.entry.bluetooth_keys"]["data"]["locks"]
        assert set(stored[str(LOCK_ID)]["commands"]) == {"Activate", "Deactivate"}

        # All of the keys come back after a restart.
        restarted = BoldBluetoothKeys(hass, "entry", client)
        await restarted.async_load()
        assert restarted.get(LOCK_ID) == keys.get(LOCK_ID)
        assert restarted.get(LOCK_ID).handshake_key.value == CLOUD_HANDSHAKE_KEY

        await BoldBluetoothKeys.async_remove_stored(hass, "entry")
        assert "bold.entry.bluetooth_keys" not in hass_storage
    # The keys unlock the door, so they're stored privately.
    assert [kwargs["private"] for kwargs in created] == [True, True, True]


async def test_keys_ignore_invalid(
    hass: HomeAssistant, aioclient_mock, hass_storage: dict[str, Any]
) -> None:
    """Test invalid keys, stored or from Bold, are ignored."""

    async def token() -> str:
        return "token"

    hass_storage["bold.entry.bluetooth_keys"] = {
        "version": 1,
        "data": {"locks": {"1": {"handshake_key": "broken"}}},
    }
    aioclient_mock.get(
        f"{API_URL}/v2/controller/handshakes",
        json=[
            {
                "deviceId": 1,
                "expiration": "2099-01-01T00:00:00Z",
                "handshakeKey": "!!",
                "payload": "aGk=",
            },
            {
                "deviceId": 2,
                "expiration": None,
                "handshakeKey": "aGk=",
                "payload": "aGk=",
            },
            # A handshake, but no commands.
            {
                "deviceId": 3,
                "expiration": "2099-01-01T00:00:00Z",
                "handshakeKey": "aGk=",
                "payload": "aGk=",
            },
        ],
    )
    aioclient_mock.get(f"{API_URL}/v2/controller/commands", json=[])
    keys = BoldBluetoothKeys(
        hass, "entry", BoldClient(async_get_clientsession(hass), token)
    )
    await keys.async_load()
    assert keys.get(1) is None
    await keys.async_refresh([1, 2, 3])
    assert keys.get(1) is None
    assert keys.get(2) is None
    assert keys.get(3).commands == {}
    assert keys.command(3, "Activate") is None
    await keys.async_refresh([])


def test_decode_damaged_keys() -> None:
    """Test damaged stored keys are skipped, and times without a zone are UTC."""
    secret = {"value": "aGk=", "expires": "2099-01-01T00:00:00"}
    lock = {"handshake_key": secret, "handshake_payload": secret, "commands": {}}
    keys = decode_keys(
        {
            "locks": {
                "1": {**lock, "commands": {"Activate": secret}},
                # A damaged command, and a lock ID that isn't one.
                "2": {**lock, "commands": {"Activate": "broken"}},
                "lock": lock,
            }
        }
    )
    assert list(keys) == [1]
    assert keys[1].commands["Activate"].expires == datetime(2099, 1, 1, tzinfo=UTC)
    assert keys[1].command("Activate", dt_util.utcnow()) == b"hi"
    assert decode_keys({"locks": []}) == {}
    assert decode_keys(None) == {}


def test_parse_malformed_keys() -> None:
    """Test entries that aren't objects, or with a true/false device ID, are skipped."""
    handshake = {
        "handshakeKey": "aGk=",
        "payload": "aGk=",
        "expiration": "2099-01-01T00:00:00Z",
    }
    keys = parse_keys(
        ["junk", {**handshake, "deviceId": True}, {**handshake, "deviceId": 1}],
        ["junk", {"deviceId": True, "commandType": "Activate", "payload": "aGk="}],
    )
    assert list(keys) == [1]
    assert keys[1].commands == {}
