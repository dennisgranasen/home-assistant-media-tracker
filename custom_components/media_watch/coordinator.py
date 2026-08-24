"""Data update coordinator for Media Watch."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import TMDBApi, TMDBError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_DISCOVERY_LIMIT,
    CONF_LANGUAGE,
    CONF_MIN_RATING,
    CONF_MIN_VOTES,
    CONF_PROVIDERS,
    CONF_REGION,
    DEFAULT_DISCOVERY_LIMIT,
    DEFAULT_LANGUAGE,
    DEFAULT_MIN_RATING,
    DEFAULT_MIN_VOTES,
    DEFAULT_REGION,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .store import MediaWatchStore

_LOGGER = logging.getLogger(__name__)


class MediaWatchCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate TMDB data and local Media Watch state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: TMDBApi,
        store: MediaWatchStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.api = api
        self.store = store

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    @property
    def region(self) -> str:
        return str(self._option(CONF_REGION, DEFAULT_REGION))

    @property
    def language(self) -> str:
        return str(self._option(CONF_LANGUAGE, DEFAULT_LANGUAGE))

    @property
    def provider_ids(self) -> list[int]:
        value = self._option(CONF_PROVIDERS, [])
        return [int(item) for item in value]

    def _provider_names_for_region(
        self, provider_data: dict[str, Any]
    ) -> list[str]:
        region = provider_data.get("results", {}).get(self.region, {})
        configured = set(self.provider_ids)
        names: list[str] = []
        for key in ("flatrate", "free", "ads"):
            for provider in region.get(key, []):
                provider_id = provider.get("provider_id")
                name = provider.get("provider_name")
                if provider_id in configured and name and name not in names:
                    names.append(name)
        return names

    async def _enrich_movie(
        self, movie: dict[str, Any]
    ) -> dict[str, Any]:
        tmdb_id = int(movie["id"])
        providers = await self.api.get_movie_watch_providers(tmdb_id)
        return {
            "id": tmdb_id,
            "title": movie.get("title"),
            "original_title": movie.get("original_title"),
            "release_date": movie.get("release_date"),
            "vote_average": movie.get("vote_average"),
            "vote_count": movie.get("vote_count"),
            "overview": movie.get("overview"),
            "poster_path": movie.get("poster_path"),
            "providers": self._provider_names_for_region(providers),
            "watched": self.store.is_watched("movie", tmdb_id),
            "dismissed": self.store.is_dismissed("movie", tmdb_id),
        }

    async def _enrich_tv(self, show: dict[str, Any]) -> dict[str, Any]:
        tmdb_id = int(show["id"])
        details, providers = await asyncio.gather(
            self.api.get_tv_details(tmdb_id, self.language),
            self.api.get_tv_watch_providers(tmdb_id),
        )
        nxt = details.get("next_episode_to_air")
        episode = None
        if nxt:
            episode = {
                "id": nxt.get("id"),
                "name": nxt.get("name"),
                "season": nxt.get("season_number"),
                "episode": nxt.get("episode_number"),
                "air_date": nxt.get("air_date"),
                "runtime": nxt.get("runtime"),
                "overview": nxt.get("overview"),
            }
        return {
            "id": tmdb_id,
            "name": details.get("name", show.get("name")),
            "original_name": details.get("original_name"),
            "poster_path": details.get("poster_path"),
            "status": details.get("status"),
            "next_episode": episode,
            "providers": self._provider_names_for_region(providers),
            "watched": self.store.is_watched("tv", tmdb_id),
            "dismissed": self.store.is_dismissed("tv", tmdb_id),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            account_id = int(self.entry.data[CONF_ACCOUNT_ID])

            watchlist_movies, watchlist_tv, all_providers = await asyncio.gather(
                self.api.get_movie_watchlist(account_id, self.language),
                self.api.get_tv_watchlist(account_id, self.language),
                self.api.get_available_movie_providers(self.region),
            )

            selected_ids = self.provider_ids
            provider_names = {
                int(provider["provider_id"]): provider.get("provider_name", "")
                for provider in all_providers
                if int(provider["provider_id"]) in selected_ids
            }

            discovered = await self.api.discover_movies(
                region=self.region,
                language=self.language,
                provider_ids=selected_ids,
                min_rating=float(
                    self._option(CONF_MIN_RATING, DEFAULT_MIN_RATING)
                ),
                min_votes=int(self._option(CONF_MIN_VOTES, DEFAULT_MIN_VOTES)),
            )

            visible_watchlist = [
                movie for movie in watchlist_movies
                if not self.store.is_watched("movie", int(movie["id"]))
            ]
            visible_discovery = [
                movie for movie in discovered
                if not self.store.is_watched("movie", int(movie["id"]))
                and not self.store.is_dismissed("movie", int(movie["id"]))
            ][: int(self._option(CONF_DISCOVERY_LIMIT, DEFAULT_DISCOVERY_LIMIT))]

            movie_details = await asyncio.gather(
                *(self._enrich_movie(movie) for movie in visible_watchlist)
            )
            tv_details = await asyncio.gather(
                *(self._enrich_tv(show) for show in watchlist_tv)
            )

            return {
                "movie_watchlist": movie_details,
                "following_tv": tv_details,
                "discovered_movies": visible_discovery,
                "providers": provider_names,
                "provider_ids": selected_ids,
                "watched_movies": self.store.watched_movies,
                "dismissed_movies": self.store.dismissed_movies,
            }
        except TMDBError as err:
            raise UpdateFailed(f"Error communicating with TMDB: {err}") from err
