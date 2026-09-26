"""Push: Bold sends events to a Home Assistant webhook, within seconds.

Webhooks need Home Assistant to be reachable from the internet: through its
external URL, or Home Assistant Cloud. Without that, or if Bold refuses the
webhook, the integration keeps polling. Polling also continues as a safety
net, and speeds up again if the webhook stops delivering.
"""

import contextlib
import hmac
from http import HTTPStatus
import logging
import secrets

from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .boldsmartlock import WEBHOOK_SECRET_HEADER, BoldClient, BoldError, BoldEvent
from .const import DOMAIN, PUSHED_EVENT_TYPES
from .coordinator import BoldConfigEntry

_LOGGER = logging.getLogger(__name__)

CONF_WEBHOOK_ID = "webhook_id"
CONF_WEBHOOK_SECRET = "webhook_secret"
CONF_CLOUDHOOK_URL = "cloudhook_url"
# Bold webhook IDs, by organization ID.
CONF_BOLD_WEBHOOKS = "bold_webhooks"


@callback
def async_setup_push(hass: HomeAssistant, entry: BoldConfigEntry) -> None:
    """Receive pushed events, and ask Bold to send them, in the background."""
    if CONF_WEBHOOK_ID not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_WEBHOOK_ID: secrets.token_hex(16),
                CONF_WEBHOOK_SECRET: secrets.token_urlsafe(32),
            },
        )
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async def handle(
        hass: HomeAssistant, webhook_id: str, request: Request
    ) -> Response:
        return await _async_handle_webhook(entry, request)

    webhook.async_register(
        hass,
        DOMAIN,
        "Bold Smart Lock",
        webhook_id,
        handle,
        local_only=False,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
    entry.async_create_background_task(
        hass, _async_register_with_bold(hass, entry), "Register Bold webhook"
    )


async def _async_handle_webhook(entry: BoldConfigEntry, request: Request) -> Response:
    """Handle events pushed by Bold."""
    if not hmac.compare_digest(
        request.headers.get(WEBHOOK_SECRET_HEADER, ""),
        entry.data[CONF_WEBHOOK_SECRET],
    ):
        _LOGGER.debug("Ignoring a webhook request without Bold's secret")
        return Response(status=HTTPStatus.UNAUTHORIZED)
    try:
        payload = await request.json()
    except ValueError:
        return Response(status=HTTPStatus.BAD_REQUEST)
    items = payload if isinstance(payload, list) else [payload]
    events = [
        event
        for item in items
        if isinstance(item, dict) and (event := BoldEvent.from_api(item))
    ]
    if entry.state is ConfigEntryState.LOADED:
        entry.runtime_data.events.async_handle_push(events)
    return Response(status=HTTPStatus.OK)


async def _async_webhook_url(hass: HomeAssistant, entry: BoldConfigEntry) -> str | None:
    """Return a URL Bold can reach the webhook on, if there is one."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    try:
        return get_url(hass, allow_internal=False, allow_ip=False) + (
            webhook.async_generate_path(webhook_id)
        )
    except NoURLAvailableError:
        pass
    if "cloud" in hass.config.components:
        from homeassistant.components import cloud  # noqa: PLC0415

        if cloud.async_active_subscription(hass):
            if url := entry.data.get(CONF_CLOUDHOOK_URL):
                return str(url)
            url = await cloud.async_create_cloudhook(hass, webhook_id)
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_CLOUDHOOK_URL: url}
            )
            return url
    return None


async def _async_register_with_bold(
    hass: HomeAssistant, entry: BoldConfigEntry
) -> None:
    """Point a Bold webhook for each organization at this webhook.

    Existing webhooks are reused and updated, so restarts don't add more.
    """
    data = entry.runtime_data
    if (url := await _async_webhook_url(hass, entry)) is None:
        _LOGGER.info(
            "Home Assistant isn't reachable from the internet, so Bold can't "
            "push events; polling for activity instead"
        )
        return
    organizations = {
        device.organization_id
        for device in data.devices.data.values()
        if device.is_lock and device.event_log and device.organization_id is not None
    }
    stored: dict[str, int] = dict(entry.data.get(CONF_BOLD_WEBHOOKS, {}))
    path = webhook.async_generate_path(entry.data[CONF_WEBHOOK_ID])
    registered: dict[str, int] = {}
    try:
        for organization_id in organizations:
            ours = [
                existing
                for existing in await data.client.get_webhooks(organization_id)
                if existing.get("id") == stored.get(str(organization_id))
                or existing.get("webhookUrl") == url
                or str(existing.get("webhookUrl", "")).endswith(path)
            ]
            for duplicate in ours[1:]:
                await data.client.delete_webhook(duplicate["id"])
            if ours:
                await data.client.update_webhook(
                    ours[0]["id"],
                    url,
                    PUSHED_EVENT_TYPES,
                    entry.data[CONF_WEBHOOK_SECRET],
                )
                registered[str(organization_id)] = ours[0]["id"]
            else:
                registered[str(organization_id)] = await data.client.create_webhook(
                    organization_id,
                    url,
                    PUSHED_EVENT_TYPES,
                    entry.data[CONF_WEBHOOK_SECRET],
                )
    except BoldError as err:
        _LOGGER.info(
            "Couldn't set up Bold's webhook (%s); polling for activity instead", err
        )
        return
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_BOLD_WEBHOOKS: registered}
    )
    if registered:
        _LOGGER.debug("Bold pushes events to %s", url)
        data.events.async_set_push_active(active=True)


async def async_remove_push(
    hass: HomeAssistant, entry: BoldConfigEntry, client: BoldClient | None
) -> None:
    """Delete the Bold webhooks and cloudhook of a removed config entry."""
    if client is not None:
        for webhook_id in entry.data.get(CONF_BOLD_WEBHOOKS, {}).values():
            try:
                await client.delete_webhook(webhook_id)
            except BoldError as err:
                _LOGGER.warning("Couldn't delete Bold's webhook: %s", err)
    if CONF_CLOUDHOOK_URL in entry.data and "cloud" in hass.config.components:
        from homeassistant.components import cloud  # noqa: PLC0415

        with contextlib.suppress(cloud.CloudNotAvailable):
            await cloud.async_delete_cloudhook(hass, entry.data[CONF_WEBHOOK_ID])
