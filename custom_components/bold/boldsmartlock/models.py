"""Bold devices and events, as the Bold API returns them."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import re
from typing import Any

DEVICE_TYPE_LOCK = 1
DEVICE_TYPE_GATEWAY = 2


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp from the API."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


_DURATION_UNITS = {
    "": 1,
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "ms": 0.001,
    "milli": 0.001,
    "millis": 0.001,
    "millisecond": 0.001,
    "milliseconds": 0.001,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")
_ISO_DURATION_RE = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


def parse_duration(value: Any) -> timedelta | None:
    """Parse a duration from the API.

    Durations are sometimes integers (seconds), and sometimes Scala
    FiniteDuration strings, whose exact format is undocumented; accept the
    common spellings ("5 seconds", "5s", "PT5S").
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if not isinstance(value, str):
        return None
    if match := _ISO_DURATION_RE.match(value.strip().upper()):
        days, hours, minutes, seconds = (float(g) if g else 0 for g in match.groups())
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if (match := _DURATION_RE.match(value)) and (
        unit := _DURATION_UNITS.get(match.group(2).lower())
    ) is not None:
        return timedelta(seconds=float(match.group(1)) * unit)
    return None


def _person_name(person: Any) -> str | None:
    """Return the display name of a user, account or triggeredBy object."""
    if not isinstance(person, dict):
        return None
    name = " ".join(
        part for part in (person.get("firstName"), person.get("lastName")) if part
    )
    return name or person.get("emailAddress") or None


class BoldEventType(StrEnum):
    """Types of event in Bold's event log that the client interprets.

    Bold has more; BoldEvent.type keeps whatever Bold sent.
    """

    ACTIVATION = "DeviceActivation"
    DEACTIVATION = "DeviceDeactivation"
    LOCKED = "DeviceLocked"
    STATUS = "DeviceStatus"
    DEBUG = "DeviceDebug"
    TAMPER_FAULTY_PIN = "DeviceTamperFaultyPin"
    TAMPER_ROTATIONS = "DeviceTamperRotations"
    TAMPER_VIBRATION = "DeviceTamperVibration"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _millivolts(value: Any) -> float | None:
    """Convert a voltage in millivolts, as Bold reports it, to volts.

    Zero means the lock didn't measure it.
    """
    if (number := _number(value)) is None or number <= 0:
        return None
    return round(number / 1000, 3)


# How Bold reports bolt positions: "LOCKED" on devices, "Locked" in events.
_BOLT_STATES = {"LOCKED": True, "UNLOCKED": False}


@dataclass(frozen=True)
class BoldDevice:
    """A Bold device, from GET /v2/devices."""

    id: int
    name: str
    type_id: int | None
    model_name: str | None
    organization_id: int | None
    actual_firmware_version: int | None
    required_firmware_version: int | None
    battery_level: str | None
    battery_last_measurement: datetime | None
    activation_time: timedelta | None
    is_active_until: datetime | None
    # Whether the lock reports its bolt position (an upgraded lock, with it
    # turned on), whether the bolt is thrown, and when that last changed.
    reports_bolt: bool
    bolt_locked: bool | None
    bolt_changed: datetime | None
    remote_access: bool
    event_log: bool
    gateway_id: int | None
    gateway_rssi: int | None
    gateway_rssi_level: str | None
    gateway_last_seen: datetime | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BoldDevice:
        """Create a device from an API response."""
        model = data.get("model") or {}
        features = data.get("features") or {}
        settings = data.get("settings") or {}
        gateway = data.get("gateway") or {}
        battery_level = data.get("batteryLevel")
        return cls(
            id=data["id"],
            name=data.get("name") or f"Bold {data['id']}",
            type_id=(model.get("type") or {}).get("id"),
            model_name=model.get("description") or model.get("name"),
            organization_id=(data.get("owner") or {}).get("organizationId"),
            actual_firmware_version=data.get("actualFirmwareVersion"),
            required_firmware_version=data.get("requiredFirmwareVersion"),
            battery_level=(
                battery_level.lower() if isinstance(battery_level, str) else None
            ),
            battery_last_measurement=parse_datetime(data.get("batteryLastMeasurement")),
            activation_time=parse_duration(settings.get("activationTime")),
            is_active_until=parse_datetime(data.get("isActiveUntil")),
            reports_bolt=bool(features.get("lockedStatus"))
            and bool(settings.get("lockedStatus")),
            bolt_locked=_BOLT_STATES.get(str(data.get("locked")).upper()),
            bolt_changed=parse_datetime(data.get("lastLocked")),
            remote_access=bool(features.get("remoteAccess")),
            event_log=bool(features.get("eventLog")),
            gateway_id=gateway.get("id"),
            gateway_rssi=gateway.get("rssi"),
            gateway_rssi_level=(
                rssi_level.lower()
                if isinstance(rssi_level := gateway.get("rssiLevel"), str)
                else None
            ),
            gateway_last_seen=parse_datetime(gateway.get("lastSeen")),
            raw=data,
        )

    @property
    def is_lock(self) -> bool:
        """Return whether the device is a lock."""
        return self.type_id == DEVICE_TYPE_LOCK

    @property
    def is_gateway(self) -> bool:
        """Return whether the device is a Bold Connect."""
        return self.type_id == DEVICE_TYPE_GATEWAY

    @property
    def update_available(self) -> bool:
        """Return whether the device firmware needs an update."""
        if (
            self.actual_firmware_version is None
            or self.required_firmware_version is None
        ):
            return False
        return self.actual_firmware_version < self.required_firmware_version


@dataclass(frozen=True)
class BoldEvent:
    """An event, from GET /v2/events or pushed to a webhook.

    Pushed events have no ID.
    """

    id: int | None
    type: str
    time: datetime
    device_id: int | None
    result: str | None
    method: str | None
    user_name: str | None
    remote_activation: bool
    activation_time: timedelta | None
    keep_active_until: datetime | None
    bolt_locked: bool | None
    # Battery voltages in volts, from status and debug events; None when not
    # measured. Debug events only carry the voltage at rest.
    voltage_idle: float | None
    voltage_under_load: float | None
    # Seconds since the lock started, from status and debug events.
    uptime: float | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BoldEvent | None:
        """Create an event from an API response, if it is well formed."""
        time = parse_datetime(data.get("time"))
        if not data.get("type") or time is None:
            return None
        event_id = data.get("id")
        # Status events report at the top level, debug events in a body.
        report: dict[str, Any] = {}
        if data["type"] == BoldEventType.STATUS:
            report = data
        elif data["type"] == BoldEventType.DEBUG and isinstance(
            body := data.get("body"), dict
        ):
            report = body
        return cls(
            id=event_id if isinstance(event_id, int) else None,
            type=data["type"],
            time=time,
            device_id=(data.get("device") or {}).get("id"),
            result=data.get("result"),
            method=data.get("method"),
            user_name=(
                _person_name(data.get("user"))
                or _person_name(data.get("account"))
                or _person_name(data.get("triggeredBy"))
            ),
            # Remote activations name the Bold Connect they went through;
            # "remoteActivation" is documented but not always sent.
            remote_activation=bool(data.get("remoteActivation") or data.get("connect")),
            activation_time=parse_duration(data.get("activationTime")),
            keep_active_until=parse_datetime(data.get("keepActiveUntil")),
            bolt_locked=(
                _BOLT_STATES.get(str(data.get("status")).upper())
                if data["type"] == BoldEventType.LOCKED
                else None
            ),
            voltage_idle=_millivolts(report.get("voltageIdle")),
            voltage_under_load=(
                _millivolts(report.get("voltageUnderLoad"))
                if data["type"] == BoldEventType.STATUS
                else None
            ),
            uptime=_number(report.get("uptime")),
            raw=data,
        )

    @property
    def key(self) -> tuple[str, int | None, datetime, bool | None]:
        """Identify the event, whether it was polled or pushed."""
        return (
            self.type,
            self.device_id,
            self.time.replace(microsecond=0),
            self.bolt_locked,
        )

    @property
    def successful(self) -> bool:
        """Return whether an activation succeeded."""
        return self.result == "Success"

    @property
    def sort_key(self) -> tuple[datetime, int]:
        """Order events by time, then ID."""
        return (self.time, self.id or 0)
