"""The JSON Bold's API sends, as documented or observed.

These are type hints only: nothing checks Bold actually sends these shapes,
so parsing still checks each value's type before using it.
"""

from typing import Any, TypedDict


def json_objects(items: Any) -> list[Any]:
    """Return the JSON objects in a list, for the caller to type."""
    return (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )


class ReferencePayload(TypedDict, total=False):
    """Another object, e.g. an event's device or organization."""

    id: int
    name: str


class PersonPayload(TypedDict, total=False):
    """A user or account, e.g. who triggered an event, or a device's owner."""

    userId: int
    accountId: int
    organizationId: int
    name: str
    firstName: str
    lastName: str
    emailAddress: str


class DeviceTypePayload(TypedDict, total=False):
    """A device's type: 1 is a lock, 2 a Bold Connect."""

    id: int
    name: str
    description: str


class ModelPayload(TypedDict, total=False):
    """A device's model."""

    id: int
    name: str
    description: str
    type: DeviceTypePayload


class SettingsPayload(TypedDict, total=False):
    """A device's settings."""

    activationTime: int | str
    lockedStatus: bool


class FeaturesPayload(TypedDict, total=False):
    """What a device supports."""

    remoteAccess: bool
    eventLog: bool
    lockedStatus: bool


class GatewayPayload(TypedDict, total=False):
    """The Bold Connect serving a device; a Connect reports itself."""

    id: int
    rssi: int
    rssiLevel: str
    lastSeen: str


class DevicePayload(TypedDict, total=False):
    """A device, from GET /v2/devices."""

    id: int
    name: str
    model: ModelPayload
    owner: PersonPayload
    settings: SettingsPayload
    features: FeaturesPayload
    gateway: GatewayPayload
    actualFirmwareVersion: int
    requiredFirmwareVersion: int
    batteryLevel: str
    isActiveUntil: str
    locked: str
    lastLocked: str


class ReadingsPayload(TypedDict, total=False):
    """Readings a lock reports: in a status event, or a debug event's body."""

    voltageIdle: int
    voltageUnderLoad: int
    uptime: int


class EventPayload(ReadingsPayload, total=False):
    """An event, from GET /v2/events or pushed to a webhook, without an ID."""

    id: int
    type: str
    category: str
    time: str
    device: ReferencePayload
    organization: ReferencePayload
    result: str
    method: str
    status: str
    user: PersonPayload
    account: PersonPayload
    triggeredBy: PersonPayload
    remoteActivation: bool
    connect: ReferencePayload
    activationTime: int | str
    keepActiveUntil: str
    body: ReadingsPayload


class AccountPayload(TypedDict, total=False):
    """The signed-in account, from GET /v1/account."""

    id: int
    firstName: str
    lastName: str
    email: str


class WebhookPayload(TypedDict, total=False):
    """A webhook, from GET /v3/webhooks."""

    id: int
    webhookUrl: str
    types: list[str]


class CommandResponsePayload(TypedDict, total=False):
    """The response to a remote activation or deactivation."""

    deviceId: int
    errorCode: str
    errorMessage: str
    activationTime: int | str


class HandshakePayload(TypedDict, total=False):
    """A Bluetooth handshake, from GET /v2/controller/handshakes."""

    deviceId: int
    handshakeKey: str
    payload: str
    expiration: str


class CommandPayload(TypedDict, total=False):
    """A signed Bluetooth command, from GET /v2/controller/commands."""

    deviceId: int
    commandType: str
    payload: str
    expiration: str
