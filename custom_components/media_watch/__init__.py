"""Media Watch integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TMDBApi
from .const import (
    ATTR_MEDIA_TYPE,
    ATTR_TMDB_ID,
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_SESSION_ID,
    DOMAIN,
    SERVICE_DISMISS,
    SERVICE_MARK_UNWATCHED,
    SERVICE_MARK_WATCHED,
    SERVICE_REFRESH,
    SERVICE_UNDISMISS,
)
from .coordinator import MediaWatchCoordinator
from .store import MediaWatchStore

PLATFORMS = [Platform.SENSOR]

MEDIA_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MEDIA_TYPE): vol.In(["movie", "tv"]),
        vol.Required(ATTR_TMDB_ID): cv.positive_int,
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up Media Watch from a config entry."""
    api = TMDBApi(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_TOKEN],
        entry.data[CONF_SESSION_ID],
    )
    store = MediaWatchStore(hass)
    await store.async_load()

    coordinator = MediaWatchCoordinator(hass, entry, api, store)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "store": store,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def mark_watched(call: ServiceCall) -> None:
        media_type = call.data[ATTR_MEDIA_TYPE]
        tmdb_id = call.data[ATTR_TMDB_ID]
        await store.mark_watched(media_type, tmdb_id)
        await api.set_watchlist(
            int(entry.data[CONF_ACCOUNT_ID]),
            media_type,
            tmdb_id,
            False,
        )
        await coordinator.async_request_refresh()

    async def mark_unwatched(call: ServiceCall) -> None:
        await store.mark_unwatched(
            call.data[ATTR_MEDIA_TYPE], call.data[ATTR_TMDB_ID]
        )
        await coordinator.async_request_refresh()

    async def dismiss(call: ServiceCall) -> None:
        await store.dismiss(
            call.data[ATTR_MEDIA_TYPE], call.data[ATTR_TMDB_ID]
        )
        await coordinator.async_request_refresh()

    async def undismiss(call: ServiceCall) -> None:
        await store.undismiss(
            call.data[ATTR_MEDIA_TYPE], call.data[ATTR_TMDB_ID]
        )
        await coordinator.async_request_refresh()

    async def refresh(_: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_MARK_WATCHED, mark_watched, schema=MEDIA_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_MARK_UNWATCHED, mark_unwatched, schema=MEDIA_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS, dismiss, schema=MEDIA_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNDISMISS, undismiss, schema=MEDIA_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload Media Watch."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_MARK_WATCHED,
                SERVICE_MARK_UNWATCHED,
                SERVICE_DISMISS,
                SERVICE_UNDISMISS,
                SERVICE_REFRESH,
            ):
                hass.services.async_remove(DOMAIN, service)
    return unloaded


async def async_reload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
