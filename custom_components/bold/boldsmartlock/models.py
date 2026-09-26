"""Bold devices and events, as the Bold API returns them."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import re
from typing import Any

from .payloads import (
    DevicePayload,
    DeviceTypePayload,
    EventPayload,
    FeaturesPayload,
    GatewayPayload,
    ModelPayload,
    PersonPayload,
    ReadingsPayload,
    ReferencePayload,
    SettingsPayload,
)

DEVICE_TYPE_LOCK = 1
DEVICE_TYPE_GATEWAY = 2


def parse_datetime(value: str | None) -> datetime | None:
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
# Matched against a stripped value: surrounding \s* made it quadratic on
# long runs of spaces.
_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$")
_ISO_DURATION_RE = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


def parse_duration(value: float | str | None) -> timedelta | None:
    """Parse a duration from the API.

    Durations are sometimes integers (seconds), and sometimes Scala
    FiniteDuration strings, whose exact format is undocumented; accept the
    common spellings ("5 seconds", "5s", "PT5S").
    """
    try:
        return _parse_duration(value)
    except OverflowError, ValueError:
        # Too long for a timedelta, or not a number (NaN).
        return None


def _parse_duration(value: float | str | None) -> timedelta | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if not isinstance(value, str):
        return None
    if match := _ISO_DURATION_RE.match(value.strip().upper()):
        days, hours, minutes, seconds = (float(g) if g else 0 for g in match.groups())
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if (match := _DURATION_RE.match(value.strip())) and (
        unit := _DURATION_UNITS.get(match.group(2).lower())
    ) is not None:
        return timedelta(seconds=float(match.group(1)) * unit)
    return None


# Bold's JSON isn't guaranteed to have the documented shape; these take a
# value only if it has the expected type. They're typed by the field types
# in payloads, so mypy catches a misspelled field: .get() returns object.
def _int(value: int | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: str | None) -> str | None:
    return value if isinstance(value, str) else None


def _flag(value: bool | None) -> bool:
    return value is True


def _lower(value: str | None) -> str | None:
    return value.lower() if isinstance(value, str) else None


def _dict(value: Any) -> Any:
    """Return an object, or an empty one; typed by the caller."""
    return value if isinstance(value, dict) else {}


def _person_name(person: PersonPayload | None) -> str | None:
    """Return the display name of a user, account or triggeredBy object."""
    if not isinstance(person, dict):
        return None
    name = " ".join(
        part
        for part in (person.get("firstName"), person.get("lastName"))
        if isinstance(part, str) and part
    )
    return name or _str(person.get("emailAddress")) or None


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


def _number(value: float | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _millivolts(value: float | None) -> float | None:
    """Convert a voltage in millivolts, as Bold reports it, to volts.

    Zero means the lock didn't measure it.
    """
    if (number := _number(value)) is None or number <= 0:
        return None
    return round(number / 1000, 3)


# How Bold reports bolt positions: "LOCKED" on devices, "Locked" in events.
_BOLT_STATES = {"LOCKED": True, "UNLOCKED": False}


def _bolt_state(value: str | None) -> bool | None:
    return _BOLT_STATES.get(value.upper()) if isinstance(value, str) else None


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
    raw: DevicePayload = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, data: DevicePayload) -> BoldDevice | None:
        """Create a device from an API response, if it has an ID."""
        if (device_id := _int(data.get("id"))) is None:
            return None
        model: ModelPayload = _dict(data.get("model"))
        device_type: DeviceTypePayload = _dict(model.get("type"))
        owner: PersonPayload = _dict(data.get("owner"))
        features: FeaturesPayload = _dict(data.get("features"))
        settings: SettingsPayload = _dict(data.get("settings"))
        gateway: GatewayPayload = _dict(data.get("gateway"))
        return cls(
            id=device_id,
            name=_str(data.get("name")) or f"Bold {device_id}",
            type_id=_int(device_type.get("id")),
            model_name=_str(model.get("description")) or _str(model.get("name")),
            organization_id=_int(owner.get("organizationId")),
            actual_firmware_version=_int(data.get("actualFirmwareVersion")),
            required_firmware_version=_int(data.get("requiredFirmwareVersion")),
            battery_level=_lower(data.get("batteryLevel")),
            activation_time=parse_duration(settings.get("activationTime")),
            is_active_until=parse_datetime(data.get("isActiveUntil")),
            reports_bolt=_flag(features.get("lockedStatus"))
            and _flag(settings.get("lockedStatus")),
            bolt_locked=_bolt_state(data.get("locked")),
            bolt_changed=parse_datetime(data.get("lastLocked")),
            remote_access=_flag(features.get("remoteAccess")),
            event_log=_flag(features.get("eventLog")),
            gateway_id=_int(gateway.get("id")),
            gateway_rssi=_int(gateway.get("rssi")),
            gateway_rssi_level=_lower(gateway.get("rssiLevel")),
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
    raw: EventPayload = field(repr=False, compare=False)

    @classmethod
    def from_api(cls, data: EventPayload) -> BoldEvent | None:
        """Create an event from an API response, if it is well formed."""
        time = parse_datetime(data.get("time"))
        if not _str(data.get("type")) or time is None:
            return None
        connect: ReferencePayload | None = data.get("connect")
        # Status events report at the top level, debug events in a body.
        report: ReadingsPayload = {}
        if data["type"] == BoldEventType.STATUS:
            report = data
        elif data["type"] == BoldEventType.DEBUG and isinstance(
            body := data.get("body"), dict
        ):
            report = body
        return cls(
            id=_int(data.get("id")),
            type=data["type"],
            time=time,
            device_id=_int(_dict(data.get("device")).get("id")),
            result=_str(data.get("result")),
            method=_str(data.get("method")),
            user_name=(
                _person_name(data.get("user"))
                or _person_name(data.get("account"))
                or _person_name(data.get("triggeredBy"))
            ),
            # Remote activations name the Bold Connect they went through;
            # "remoteActivation" is documented but not always sent.
            remote_activation=_flag(data.get("remoteActivation")) or bool(connect),
            activation_time=parse_duration(data.get("activationTime")),
            keep_active_until=parse_datetime(data.get("keepActiveUntil")),
            bolt_locked=(
                _bolt_state(data.get("status"))
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
