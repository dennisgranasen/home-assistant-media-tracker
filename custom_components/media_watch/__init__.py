"""Media Watch integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TMDBApi
from .const import (
    ATTR_ALL_SEASONS,
    ATTR_DAYS,
    ATTR_EPISODE,
    ATTR_LIMIT,
    ATTR_SEASON,
    ATTR_SEASONS,
    ATTR_MEDIA_TYPE,
    ATTR_QUERY,
    ATTR_TMDB_ID,
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_SESSION_ID,
    DOMAIN,
    SERVICE_DISMISS,
    SERVICE_FOLLOW,
    SERVICE_MARK_EPISODE_UNWATCHED,
    SERVICE_MARK_EPISODE_WATCHED,
    SERVICE_MARK_SEASONS_UNWATCHED,
    SERVICE_MARK_SEASONS_WATCHED,
    SERVICE_MARK_UNWATCHED,
    SERVICE_MARK_WATCHED,
    SERVICE_REFRESH,
    SERVICE_SEARCH,
    SERVICE_UNDISMISS,
    SERVICE_UNFOLLOW,
    SERVICE_UPCOMING_EPISODES,
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

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_QUERY): vol.All(cv.string, vol.Length(min=1, max=200)),
        vol.Optional(ATTR_MEDIA_TYPE, default="tv"): vol.In(
            ["movie", "tv", "all"]
        ),
        vol.Optional(ATTR_LIMIT, default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=25)
        ),
    }
)


EPISODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TMDB_ID): cv.positive_int,
        vol.Required(ATTR_SEASON): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Required(ATTR_EPISODE): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
    }
)

SEASONS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TMDB_ID): cv.positive_int,
        vol.Optional(ATTR_SEASONS, default=[]): [
            vol.All(vol.Coerce(int), vol.Range(min=1))
        ],
        vol.Optional(ATTR_ALL_SEASONS, default=False): cv.boolean,
    }
)


UPCOMING_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DAYS, default=30): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=30)
        ),
        vol.Optional(ATTR_LIMIT, default=5): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
    }
)


def _search_result(
    item: dict[str, Any],
    media_type: str,
) -> dict[str, Any]:
    """Normalize a TMDB search result for service response data."""
    if media_type == "tv":
        title = item.get("name")
        original_title = item.get("original_name")
        date = item.get("first_air_date")
    else:
        title = item.get("title")
        original_title = item.get("original_title")
        date = item.get("release_date")

    return {
        "id": int(item["id"]),
        "media_type": media_type,
        "title": title,
        "original_title": original_title,
        "date": date,
        "poster_path": item.get("poster_path"),
        "overview": item.get("overview"),
        "vote_average": item.get("vote_average"),
        "vote_count": item.get("vote_count"),
        "popularity": item.get("popularity"),
    }


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

    # The first refresh intentionally loads only core watchlist/TV data so
    # entity registration is not held up by external discovery/award sites.
    # Populate those feeds immediately after the entities are available.
    deferred_refresh = hass.async_create_task(
        coordinator.async_request_refresh(),
        name="media_watch_deferred_discovery",
    )
    entry.async_on_unload(deferred_refresh.cancel)

    def schedule_refresh() -> None:
        """Refresh coordinator data without blocking a user action."""
        hass.async_create_task(coordinator.async_request_refresh())

    async def mark_watched(call: ServiceCall) -> None:
        media_type = call.data[ATTR_MEDIA_TYPE]
        tmdb_id = call.data[ATTR_TMDB_ID]

        # Local watched state is authoritative because TMDB has no
        # generic watched flag. Removing it from the TMDB watchlist
        # prevents it from remaining in the active queue.
        await store.mark_watched(media_type, tmdb_id)
        await api.set_watchlist(
            int(entry.data[CONF_ACCOUNT_ID]),
            media_type,
            tmdb_id,
            False,
        )
        schedule_refresh()

    async def mark_unwatched(call: ServiceCall) -> None:
        await store.mark_unwatched(
            call.data[ATTR_MEDIA_TYPE],
            call.data[ATTR_TMDB_ID],
        )
        schedule_refresh()

    async def dismiss(call: ServiceCall) -> None:
        await store.dismiss(
            call.data[ATTR_MEDIA_TYPE],
            call.data[ATTR_TMDB_ID],
        )
        schedule_refresh()

    async def undismiss(call: ServiceCall) -> None:
        await store.undismiss(
            call.data[ATTR_MEDIA_TYPE],
            call.data[ATTR_TMDB_ID],
        )
        schedule_refresh()

    async def follow(call: ServiceCall) -> None:
        """Add a movie/show to the TMDB watchlist.

        A TV show on the TMDB watchlist is treated as a followed show by
        Media Watch. A movie is treated as a wanted/watchlist movie.
        """
        media_type = call.data[ATTR_MEDIA_TYPE]
        tmdb_id = call.data[ATTR_TMDB_ID]

        # Explicitly following something should make it visible again.
        await store.mark_unwatched(media_type, tmdb_id)
        await store.undismiss(media_type, tmdb_id)

        await api.set_watchlist(
            int(entry.data[CONF_ACCOUNT_ID]),
            media_type,
            tmdb_id,
            True,
        )
        schedule_refresh()

    async def unfollow(call: ServiceCall) -> None:
        """Remove a movie/show from the TMDB watchlist."""
        await api.set_watchlist(
            int(entry.data[CONF_ACCOUNT_ID]),
            call.data[ATTR_MEDIA_TYPE],
            call.data[ATTR_TMDB_ID],
            False,
        )
        schedule_refresh()


    async def mark_episode_watched(call: ServiceCall) -> None:
        """Mark one TV episode watched."""
        await store.mark_episode_watched(
            int(call.data[ATTR_TMDB_ID]),
            int(call.data[ATTR_SEASON]),
            int(call.data[ATTR_EPISODE]),
        )
        schedule_refresh()

    async def mark_episode_unwatched(call: ServiceCall) -> None:
        """Mark one TV episode unwatched."""
        await store.mark_episode_unwatched(
            int(call.data[ATTR_TMDB_ID]),
            int(call.data[ATTR_SEASON]),
            int(call.data[ATTR_EPISODE]),
        )
        schedule_refresh()

    async def _resolve_seasons(call: ServiceCall) -> list[int]:
        """Resolve explicit seasons or all regular seasons from TMDB."""
        seasons = sorted(
            {
                int(item)
                for item in call.data.get(ATTR_SEASONS, [])
                if int(item) > 0
            }
        )

        if call.data.get(ATTR_ALL_SEASONS):
            details = await api.get_tv_details(
                int(call.data[ATTR_TMDB_ID]),
                coordinator.language,
            )
            seasons = sorted(
                {
                    int(season.get("season_number", 0))
                    for season in details.get("seasons", [])
                    if int(season.get("season_number", 0)) > 0
                }
            )

        return seasons

    async def mark_seasons_watched(call: ServiceCall) -> None:
        """Mark one, multiple, or all regular seasons watched."""
        seasons = await _resolve_seasons(call)
        if not seasons:
            return

        await store.mark_seasons_watched(
            int(call.data[ATTR_TMDB_ID]),
            seasons,
        )
        schedule_refresh()

    async def mark_seasons_unwatched(call: ServiceCall) -> None:
        """Reset one, multiple, or all regular seasons."""
        seasons = await _resolve_seasons(call)
        if not seasons:
            return

        await store.mark_seasons_unwatched(
            int(call.data[ATTR_TMDB_ID]),
            seasons,
        )
        schedule_refresh()


    async def upcoming_episodes(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Return upcoming episodes across all followed shows."""
        days = int(call.data[ATTR_DAYS])
        limit = int(call.data[ATTR_LIMIT])

        if days == 0:
            episodes = coordinator.data.get("episodes_today", [])
        elif days <= 7:
            all_episodes = coordinator.data.get(
                "episodes_next_7_days", []
            )
            from datetime import date, timedelta
            end_date = (date.today() + timedelta(days=days)).isoformat()
            episodes = [
                item
                for item in all_episodes
                if (item.get("air_date") or "") <= end_date
            ]
        else:
            all_episodes = coordinator.data.get(
                "episodes_next_30_days", []
            )
            from datetime import date, timedelta
            end_date = (date.today() + timedelta(days=days)).isoformat()
            episodes = [
                item
                for item in all_episodes
                if (item.get("air_date") or "") <= end_date
            ]

        return {
            "days": days,
            "limit": limit,
            "count": min(len(episodes), limit),
            "episodes": episodes[:limit],
        }

    async def search(call: ServiceCall) -> ServiceResponse:
        """Search TMDB and return candidates without changing state."""
        query = str(call.data[ATTR_QUERY]).strip()
        media_type = call.data[ATTR_MEDIA_TYPE]
        limit = int(call.data[ATTR_LIMIT])

        results: list[dict[str, Any]] = []

        if media_type in ("tv", "all"):
            tv_results = await api.search_tv(query, coordinator.language)
            results.extend(
                _search_result(item, "tv")
                for item in tv_results
            )

        if media_type in ("movie", "all"):
            movie_results = await api.search_movies(
                query, coordinator.language
            )
            results.extend(
                _search_result(item, "movie")
                for item in movie_results
            )

        # TMDB's popularity gives a reasonable default order when
        # combining movie + TV results.
        results.sort(
            key=lambda item: float(item.get("popularity") or 0),
            reverse=True,
        )

        return {
            "query": query,
            "count": min(len(results), limit),
            "results": results[:limit],
        }

    async def refresh(_: ServiceCall) -> None:
        schedule_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_WATCHED,
        mark_watched,
        schema=MEDIA_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_UNWATCHED,
        mark_unwatched,
        schema=MEDIA_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISMISS,
        dismiss,
        schema=MEDIA_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNDISMISS,
        undismiss,
        schema=MEDIA_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FOLLOW,
        follow,
        schema=MEDIA_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNFOLLOW,
        unfollow,
        schema=MEDIA_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_EPISODE_WATCHED,
        mark_episode_watched,
        schema=EPISODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_EPISODE_UNWATCHED,
        mark_episode_unwatched,
        schema=EPISODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_SEASONS_WATCHED,
        mark_seasons_watched,
        schema=SEASONS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_SEASONS_UNWATCHED,
        mark_seasons_unwatched,
        schema=SEASONS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPCOMING_EPISODES,
        upcoming_episodes,
        schema=UPCOMING_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH,
        search,
        schema=SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        refresh,
    )

    entry.async_on_unload(
        entry.add_update_listener(async_reload_entry)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload Media Watch."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unloaded:
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if entry_data is not None:
            entry_data["coordinator"].cancel_background_tasks()
        hass.data[DOMAIN].pop(entry.entry_id, None)

        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_MARK_WATCHED,
                SERVICE_MARK_EPISODE_UNWATCHED,
    SERVICE_MARK_EPISODE_WATCHED,
    SERVICE_MARK_SEASONS_UNWATCHED,
    SERVICE_MARK_SEASONS_WATCHED,
    SERVICE_MARK_UNWATCHED,
                SERVICE_DISMISS,
                SERVICE_UNDISMISS,
                SERVICE_FOLLOW,
                SERVICE_UNFOLLOW,
                SERVICE_MARK_EPISODE_WATCHED,
                SERVICE_MARK_EPISODE_UNWATCHED,
                SERVICE_MARK_SEASONS_WATCHED,
                SERVICE_MARK_SEASONS_UNWATCHED,
                SERVICE_UPCOMING_EPISODES,
                SERVICE_SEARCH,
                SERVICE_REFRESH,
            ):
                hass.services.async_remove(DOMAIN, service)

    return unloaded


async def async_reload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
