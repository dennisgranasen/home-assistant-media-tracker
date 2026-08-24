"""Data update coordinator for Media Watch."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
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
    CONF_UPCOMING_LIMIT,
    DEFAULT_DISCOVERY_LIMIT,
    DEFAULT_LANGUAGE,
    DEFAULT_MIN_RATING,
    DEFAULT_MIN_VOTES,
    DEFAULT_REGION,
    DEFAULT_UPCOMING_LIMIT,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .store import MediaWatchStore

_LOGGER = logging.getLogger(__name__)

STREAMING_TYPES = ("flatrate", "free", "ads")
ALL_AVAILABILITY_TYPES = ("flatrate", "free", "ads", "rent", "buy")


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
    def upcoming_limit(self) -> int:
        return int(
            self._option(
                CONF_UPCOMING_LIMIT,
                DEFAULT_UPCOMING_LIMIT,
            )
        )

    @property
    def provider_ids(self) -> list[int]:
        value = self._option(CONF_PROVIDERS, [])
        return [int(item) for item in value]

    def _availability_for_region(
        self,
        provider_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Return all TMDB availability for the configured region.

        The public `providers` field is deliberately NOT filtered by the
        user's selected services. Selected services only affect discovery
        and `available_on_my_services`.
        """
        region = provider_data.get("results", {}).get(self.region, {})
        selected = set(self.provider_ids)

        by_type: dict[str, list[dict[str, Any]]] = {}
        all_streaming: list[dict[str, Any]] = []
        seen_streaming: set[int] = set()

        for availability_type in ALL_AVAILABILITY_TYPES:
            items: list[dict[str, Any]] = []
            for provider in region.get(availability_type, []):
                provider_id = int(provider["provider_id"])
                item = {
                    "id": provider_id,
                    "name": provider.get("provider_name"),
                    "logo_path": provider.get("logo_path"),
                    "display_priority": provider.get("display_priority"),
                }
                items.append(item)

                if (
                    availability_type in STREAMING_TYPES
                    and provider_id not in seen_streaming
                ):
                    all_streaming.append(item)
                    seen_streaming.add(provider_id)

            by_type[availability_type] = items

        my_streaming = [
            provider
            for provider in all_streaming
            if provider["id"] in selected
        ]

        return {
            "providers": [provider["name"] for provider in all_streaming],
            "provider_details": all_streaming,
            "my_providers": [provider["name"] for provider in my_streaming],
            "my_provider_details": my_streaming,
            "available_on_my_services": bool(my_streaming),
            "availability": by_type,
            "watch_link": region.get("link"),
        }

    async def _enrich_movie(
        self, movie: dict[str, Any]
    ) -> dict[str, Any]:
        tmdb_id = int(movie["id"])
        provider_data = await self.api.get_movie_watch_providers(tmdb_id)
        availability = self._availability_for_region(provider_data)

        return {
            "id": tmdb_id,
            "title": movie.get("title"),
            "original_title": movie.get("original_title"),
            "release_date": movie.get("release_date"),
            "vote_average": movie.get("vote_average"),
            "vote_count": movie.get("vote_count"),
            "overview": movie.get("overview"),
            "poster_path": movie.get("poster_path"),
            **availability,
            "watched": self.store.is_watched("movie", tmdb_id),
            "dismissed": self.store.is_dismissed("movie", tmdb_id),
        }



    async def _enrich_tv(self, show: dict[str, Any]) -> dict[str, Any]:
        """Enrich a followed TV show with airing, progress and schedule."""
        tmdb_id = int(show["id"])
        details, provider_data = await asyncio.gather(
            self.api.get_tv_details(tmdb_id, self.language),
            self.api.get_tv_watch_providers(tmdb_id),
        )
        availability = self._availability_for_region(provider_data)

        nxt = details.get("next_episode_to_air")
        next_to_air = None
        if nxt:
            season = nxt.get("season_number")
            number = nxt.get("episode_number")
            next_to_air = {
                "id": nxt.get("id"),
                "name": nxt.get("name"),
                "season": season,
                "episode": number,
                "code": (
                    f"S{int(season):02d}E{int(number):02d}"
                    if season is not None and number is not None
                    else None
                ),
                "air_date": nxt.get("air_date"),
                "runtime": nxt.get("runtime"),
                "overview": nxt.get("overview"),
            }

        seasons = [
            season
            for season in details.get("seasons", [])
            if int(season.get("season_number", 0)) > 0
        ]

        progress = self.store.tv_progress(tmdb_id)
        watched_seasons = set(progress["watched_seasons"])

        target_season = next(
            (
                int(season["season_number"])
                for season in seasons
                if int(season["season_number"]) not in watched_seasons
            ),
            None,
        )

        # Fetch only seasons that can currently matter:
        # - the first not-completely-watched season, for next-to-watch
        # - the season containing TMDB's next episode to air
        # - later seasons whose season air date is within the next month
        today = date.today()
        horizon = today + timedelta(days=30)

        season_numbers: set[int] = set()
        if target_season is not None:
            season_numbers.add(target_season)

        if nxt and nxt.get("season_number") is not None:
            season_numbers.add(int(nxt["season_number"]))

        for season in seasons:
            number = int(season.get("season_number", 0))
            air_date = season.get("air_date")
            if not air_date:
                continue
            try:
                season_date = date.fromisoformat(air_date)
            except ValueError:
                continue
            if today <= season_date <= horizon:
                season_numbers.add(number)

        season_payloads: dict[int, dict[str, Any]] = {}
        if season_numbers:
            payloads = await asyncio.gather(
                *(
                    self.api.get_tv_season(
                        tmdb_id,
                        number,
                        self.language,
                    )
                    for number in sorted(season_numbers)
                )
            )
            season_payloads = {
                number: payload
                for number, payload in zip(
                    sorted(season_numbers),
                    payloads,
                    strict=True,
                )
            }

        next_to_watch = None
        if target_season is not None:
            season_details = season_payloads.get(target_season)
            if season_details is None:
                season_details = await self.api.get_tv_season(
                    tmdb_id,
                    target_season,
                    self.language,
                )

            for episode in season_details.get("episodes", []):
                episode_number = int(episode.get("episode_number", 0))
                if episode_number <= 0:
                    continue

                if self.store.is_episode_watched(
                    tmdb_id,
                    target_season,
                    episode_number,
                ):
                    continue

                season_number = int(
                    episode.get("season_number", target_season)
                )
                next_to_watch = {
                    "id": episode.get("id"),
                    "name": episode.get("name"),
                    "season": season_number,
                    "episode": episode_number,
                    "code": f"S{season_number:02d}E{episode_number:02d}",
                    "air_date": episode.get("air_date"),
                    "runtime": episode.get("runtime"),
                    "overview": episode.get("overview"),
                    "still_path": episode.get("still_path"),
                }
                break

        upcoming_episodes: list[dict[str, Any]] = []

        for season_number, season_details in season_payloads.items():
            for episode in season_details.get("episodes", []):
                air_date = episode.get("air_date")
                if not air_date:
                    continue
                try:
                    episode_date = date.fromisoformat(air_date)
                except ValueError:
                    continue
                if not (today <= episode_date <= horizon):
                    continue

                episode_number = int(episode.get("episode_number", 0))
                if episode_number <= 0:
                    continue

                upcoming_episodes.append(
                    {
                        "id": episode.get("id"),
                        "name": episode.get("name"),
                        "season": season_number,
                        "episode": episode_number,
                        "code": (
                            f"S{season_number:02d}E{episode_number:02d}"
                        ),
                        "air_date": air_date,
                        "runtime": episode.get("runtime"),
                        "overview": episode.get("overview"),
                        "still_path": episode.get("still_path"),
                    }
                )

        upcoming_episodes.sort(
            key=lambda item: (
                item.get("air_date") or "9999-12-31",
                int(item.get("season") or 0),
                int(item.get("episode") or 0),
            )
        )

        season_summary = [
            {
                "season": int(season.get("season_number", 0)),
                "name": season.get("name"),
                "episode_count": season.get("episode_count"),
                "air_date": season.get("air_date"),
                "poster_path": season.get("poster_path"),
                "watched": int(season.get("season_number", 0))
                in watched_seasons,
            }
            for season in seasons
        ]

        return {
            "id": tmdb_id,
            "name": details.get("name", show.get("name")),
            "original_name": details.get("original_name"),
            "poster_path": details.get("poster_path"),
            "status": details.get("status"),
            "next_episode": next_to_air,
            "next_episode_to_air": next_to_air,
            "next_episode_to_watch": next_to_watch,
            "upcoming_episodes": upcoming_episodes,
            "seasons": season_summary,
            "progress": progress,
            **availability,
            "watched": self.store.is_watched("tv", tmdb_id),
            "dismissed": self.store.is_dismissed("tv", tmdb_id),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            account_id = int(self.entry.data[CONF_ACCOUNT_ID])

            (
                watchlist_movies,
                watchlist_tv,
                movie_providers,
                tv_providers,
            ) = await asyncio.gather(
                self.api.get_movie_watchlist(account_id, self.language),
                self.api.get_tv_watchlist(account_id, self.language),
                self.api.get_available_movie_providers(self.region),
                self.api.get_available_tv_providers(self.region),
            )

            selected_ids = self.provider_ids

            # Union movie and TV provider catalogues. TMDB exposes these
            # separately even though many provider IDs occur in both.
            provider_catalog: dict[int, dict[str, Any]] = {}
            for provider in [*movie_providers, *tv_providers]:
                provider_id = int(provider["provider_id"])
                current = provider_catalog.get(provider_id)
                if current is None or int(
                    provider.get("display_priority", 9999)
                ) < int(current.get("display_priority", 9999)):
                    provider_catalog[provider_id] = provider

            selected_providers = {
                provider_id: {
                    "name": provider_catalog[provider_id].get("provider_name"),
                    "logo_path": provider_catalog[provider_id].get("logo_path"),
                }
                for provider_id in selected_ids
                if provider_id in provider_catalog
            }

            discovered = await self.api.discover_movies(
                region=self.region,
                language=self.language,
                provider_ids=selected_ids,
                min_rating=float(
                    self._option(CONF_MIN_RATING, DEFAULT_MIN_RATING)
                ),
                min_votes=int(
                    self._option(CONF_MIN_VOTES, DEFAULT_MIN_VOTES)
                ),
            )

            visible_watchlist = [
                movie
                for movie in watchlist_movies
                if not self.store.is_watched("movie", int(movie["id"]))
            ]

            visible_discovery = [
                movie
                for movie in discovered
                if not self.store.is_watched("movie", int(movie["id"]))
                and not self.store.is_dismissed("movie", int(movie["id"]))
            ][: int(
                self._option(
                    CONF_DISCOVERY_LIMIT,
                    DEFAULT_DISCOVERY_LIMIT,
                )
            )]

            movie_details = await asyncio.gather(
                *(self._enrich_movie(movie) for movie in visible_watchlist)
            )
            tv_details = await asyncio.gather(
                *(self._enrich_tv(show) for show in watchlist_tv)
            )
            discovery_details = await asyncio.gather(
                *(self._enrich_movie(movie) for movie in visible_discovery)
            )

            global_upcoming: list[dict[str, Any]] = []

            for show in tv_details:
                for episode in show.get("upcoming_episodes", []):
                    global_upcoming.append(
                        {
                            "tmdb_id": show["id"],
                            "show": show["name"],
                            "poster_path": show.get("poster_path"),
                            "providers": show.get("providers", []),
                            "my_providers": show.get("my_providers", []),
                            "available_on_my_services": show.get(
                                "available_on_my_services", False
                            ),
                            **episode,
                        }
                    )

            global_upcoming.sort(
                key=lambda item: (
                    item.get("air_date") or "9999-12-31",
                    item.get("show") or "",
                    int(item.get("season") or 0),
                    int(item.get("episode") or 0),
                )
            )

            today_iso = date.today().isoformat()
            week_end = (date.today() + timedelta(days=7)).isoformat()
            month_end = (date.today() + timedelta(days=30)).isoformat()

            episodes_today = [
                item
                for item in global_upcoming
                if item.get("air_date") == today_iso
            ]
            episodes_next_7_days = [
                item
                for item in global_upcoming
                if today_iso <= (item.get("air_date") or "") <= week_end
            ]
            episodes_next_30_days = [
                item
                for item in global_upcoming
                if today_iso <= (item.get("air_date") or "") <= month_end
            ]

            return {
                "movie_watchlist": movie_details,
                "following_tv": tv_details,
                "upcoming_episodes_all": global_upcoming,
                "upcoming_episodes_next": global_upcoming[
                    : self.upcoming_limit
                ],
                "episodes_today": episodes_today,
                "episodes_next_7_days": episodes_next_7_days,
                "episodes_next_30_days": episodes_next_30_days,
                "discovered_movies": discovery_details,
                "selected_providers": selected_providers,
                "provider_ids": selected_ids,
                "watched_movies": self.store.watched_movies,
                "dismissed_movies": self.store.dismissed_movies,
            }

        except TMDBError as err:
            raise UpdateFailed(
                f"Error communicating with TMDB: {err}"
            ) from err
