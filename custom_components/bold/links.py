"""Locks linked to their door sensors, for the Bold integration.

Each link is a config subentry, titled with the lock's and the door sensor's
names in Home Assistant, which it follows as they're renamed.
"""

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_DOOR_SENSOR, CONF_LOCK, DOMAIN, SUBENTRY_DOOR_SENSOR
from .coordinator import BoldConfigEntry

# A link's title: the lock, then its door sensor.
TITLE_LOCK = "🔒 "
TITLE_ARROW = " → "
TITLE_DOOR = "🚪 "


def link_title(lock_name: str, door_name: str) -> str:
    """Return a link's title."""
    return f"{TITLE_LOCK}{lock_name}{TITLE_ARROW}{TITLE_DOOR}{door_name}"


def title_lock_name(title: str) -> str:
    """Return the lock's name from a link's title, as it was then."""
    return title.partition(TITLE_ARROW)[0].removeprefix(TITLE_LOCK)


@callback
def lock_entity_id(hass: HomeAssistant, device_id: int) -> str | None:
    """Return the entity ID of a Bold lock."""
    return er.async_get(hass).async_get_entity_id(Platform.LOCK, DOMAIN, str(device_id))


@callback
def async_follow_links(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Follow linked locks and door sensors as they're renamed.

    A changed entity ID reloads, so the lock follows its door sensor. A changed
    name updates the link's title.
    """
    registry = er.async_get(hass)
    # Each link's lock and door sensor entity IDs, by subentry ID.
    links: dict[str, tuple[str, str]] = {}
    for subentry in entry.get_subentries_of_type(SUBENTRY_DOOR_SENSOR):
        lock = lock_entity_id(hass, subentry.data[CONF_LOCK])
        door = er.async_resolve_entity_id(registry, subentry.data[CONF_DOOR_SENSOR])
        if lock is not None and door is not None:
            links[subentry.subentry_id] = (lock, door)
    if links:
        _LinkFollower(hass, entry, links).async_start()


class _LinkFollower:
    """Follows the entities of an entry's links."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BoldConfigEntry,
        links: dict[str, tuple[str, str]],
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._links = links
        self._entity_ids = {
            entity_id for entity_ids in links.values() for entity_id in entity_ids
        }
        self._registry = er.async_get(hass)
        self._registry_ids = {
            registry_entry.id
            for entity_id in self._entity_ids
            if (registry_entry := self._registry.async_get(entity_id)) is not None
        }

    @callback
    def async_start(self) -> None:
        # Renamed while Home Assistant wasn't running.
        self._update_titles()
        self._entry.async_on_unload(
            async_track_state_change_event(
                self._hass, self._entity_ids, self._state_changed
            )
        )
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._reload,
                event_filter=self._entity_id_changed,
            )
        )

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        # Most changes are the door opening or closing.
        if old is None or new is None or old.name != new.name:
            self._update_titles(event.data["entity_id"])

    def _update_titles(self, entity_id: str | None = None) -> None:
        for subentry_id, (lock, door) in self._links.items():
            if (subentry := self._entry.subentries.get(subentry_id)) is not None and (
                entity_id is None or entity_id in (lock, door)
            ):
                self._update_title(subentry, lock, door)

    def _update_title(self, subentry: ConfigSubentry, lock: str, door: str) -> None:
        # Only with both names known, rather than reading one from the title.
        if not (
            (lock_state := self._hass.states.get(lock))
            and (door_state := self._hass.states.get(door))
        ):
            return
        title = link_title(lock_state.name, door_state.name)
        if title != subentry.title:
            self._hass.config_entries.async_update_subentry(
                self._entry, subentry, title=title
            )

    @callback
    def _entity_id_changed(self, data: er.EventEntityRegistryUpdatedData) -> bool:
        return (
            data["action"] == "update"
            and "entity_id" in data["changes"]
            and (registry_entry := self._registry.async_get(data["entity_id"]))
            is not None
            and registry_entry.id in self._registry_ids
        )

    @callback
    def _reload(self, _: Event[er.EventEntityRegistryUpdatedData]) -> None:
        self._hass.config_entries.async_schedule_reload(self._entry.entry_id)
