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
    CONF_FALLBACK_LANGUAGE,
    CONF_LANGUAGE,
    CONF_USE_PROFILE_LANGUAGE,
    CONF_MIN_RATING,
    CONF_MIN_VOTES,
    CONF_PROVIDERS,
    CONF_REGION,
    CONF_UPCOMING_LIMIT,
    DEFAULT_DISCOVERY_LIMIT,
    DEFAULT_FALLBACK_LANGUAGE,
    DEFAULT_LANGUAGE,
    DEFAULT_USE_PROFILE_LANGUAGE,
    DEFAULT_MIN_RATING,
    DEFAULT_MIN_VOTES,
    DEFAULT_REGION,
    DEFAULT_UPCOMING_LIMIT,
    DOMAIN,
    CONF_DISCOVERY_MAX_PAGES,
    CONF_DISCOVERY_INCLUDE_GENRES,
    CONF_DISCOVERY_EXCLUDE_GENRES,
    CONF_DISCOVERY_GENRE_MATCH,
    CONF_DISCOVERY_PROVIDER_SCOPE,
    DEFAULT_DISCOVERY_MAX_PAGES,
    DEFAULT_DISCOVERY_INCLUDE_GENRES,
    DEFAULT_DISCOVERY_EXCLUDE_GENRES,
    DEFAULT_DISCOVERY_GENRE_MATCH,
    DEFAULT_DISCOVERY_PROVIDER_SCOPE,
    UPDATE_INTERVAL,
    OSCAR_BEST_PICTURE_2026,
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
        self._profile_language: str | None = None
        self._profile_region: str | None = None

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    @property
    def use_profile_language(self) -> bool:
        return bool(
            self._option(
                CONF_USE_PROFILE_LANGUAGE,
                DEFAULT_USE_PROFILE_LANGUAGE,
            )
        )

    @property
    def region(self) -> str:
        if self.use_profile_language and self._profile_region:
            return self._profile_region
        return str(self._option(CONF_REGION, DEFAULT_REGION))

    @property
    def language(self) -> str:
        if self.use_profile_language and self._profile_language:
            return self._profile_language
        return str(self._option(CONF_LANGUAGE, DEFAULT_LANGUAGE))

    @property
    def fallback_language(self) -> str | None:
        value = str(
            self._option(
                CONF_FALLBACK_LANGUAGE,
                DEFAULT_FALLBACK_LANGUAGE,
            )
        ).strip()
        if not value or value.lower() in {"none", "null", "off"}:
            return None
        if value == self.language:
            return None
        return value

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


    async def _refresh_profile_locale(self) -> None:
        """Read the locale exposed by TMDB's account details endpoint."""
        account = await self.api.account_details()

        language = account.get("iso_639_1")
        region = account.get("iso_3166_1")

        if language:
            language = str(language)
            if region:
                self._profile_language = f"{language}-{region}"
            else:
                self._profile_language = language

        if region:
            self._profile_region = str(region)

    @staticmethod
    def _localized_field(
        primary: dict[str, Any],
        fallback: dict[str, Any] | None,
        field: str,
        original_field: str | None = None,
    ) -> Any:
        """Choose translated field, then fallback translation, then original.

        TMDB detail requests fall back to original-language metadata when the
        requested translation is missing. For translated text fields, an empty
        primary value is always treated as missing. For title/name fields we
        also treat a primary value identical to the original title/name as
        missing when the original language differs from the requested language;
        the caller handles that by passing fallback details.
        """
        primary_value = primary.get(field)
        fallback_value = fallback.get(field) if fallback else None

        if isinstance(primary_value, str) and primary_value.strip():
            if (
                original_field
                and fallback
                and primary_value == primary.get(original_field)
                and fallback_value
                and fallback_value != fallback.get(original_field)
            ):
                return fallback_value
            return primary_value

        if isinstance(fallback_value, str) and fallback_value.strip():
            return fallback_value

        if original_field:
            return primary.get(original_field) or (
                fallback.get(original_field) if fallback else None
            )

        return primary_value if primary_value not in ("", None) else fallback_value

    async def _localized_movie_details(
        self,
        tmdb_id: int,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Fetch primary and optional fallback movie metadata."""
        primary = await self.api.get_movie_details(
            tmdb_id,
            self.language,
        )

        fallback = None
        if self.fallback_language:
            fallback = await self.api.get_movie_details(
                tmdb_id,
                self.fallback_language,
            )

        return primary, fallback

    async def _localized_tv_details(
        self,
        tmdb_id: int,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Fetch primary and optional fallback TV metadata."""
        primary = await self.api.get_tv_details(
            tmdb_id,
            self.language,
        )

        fallback = None
        if self.fallback_language:
            fallback = await self.api.get_tv_details(
                tmdb_id,
                self.fallback_language,
            )

        return primary, fallback

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
        """Add localized details, availability and local state to a movie."""
        tmdb_id = int(movie["id"])

        (details, fallback), provider_data = await asyncio.gather(
            self._localized_movie_details(tmdb_id),
            self.api.get_movie_watch_providers(tmdb_id),
        )
        availability = self._availability_for_region(provider_data)

        title = self._localized_field(
            details,
            fallback,
            "title",
            "original_title",
        )
        overview = self._localized_field(
            details,
            fallback,
            "overview",
        )

        return {
            "id": tmdb_id,
            "title": title,
            "original_title": details.get(
                "original_title",
                movie.get("original_title"),
            ),
            "original_language": details.get("original_language"),
            "release_date": details.get(
                "release_date",
                movie.get("release_date"),
            ),
            "vote_average": details.get(
                "vote_average",
                movie.get("vote_average"),
            ),
            "vote_count": details.get(
                "vote_count",
                movie.get("vote_count"),
            ),
            "overview": overview or "",
            "poster_path": details.get(
                "poster_path",
                movie.get("poster_path"),
            ),
            "genre_ids": [
                int(genre["id"])
                for genre in details.get("genres", [])
                if genre.get("id") is not None
            ],
            "genres": [
                {
                    "id": int(genre["id"]),
                    "name": genre.get("name"),
                }
                for genre in details.get("genres", [])
                if genre.get("id") is not None
            ],
            "language": self.language,
            "fallback_language": self.fallback_language,
            **availability,
            "watched": self.store.is_watched("movie", tmdb_id),
            "dismissed": self.store.is_dismissed("movie", tmdb_id),
        }


    async def _enrich_tv_discovery(
        self,
        show: dict[str, Any],
    ) -> dict[str, Any]:
        """Enrich TV metadata without fetching episode/season progress."""
        tmdb_id = int(show["id"])
        (details, fallback_details), provider_data = await asyncio.gather(
            self._localized_tv_details(tmdb_id),
            self.api.get_tv_watch_providers(tmdb_id),
        )
        availability = self._availability_for_region(provider_data)

        return {
            "id": tmdb_id,
            "name": self._localized_field(
                details,
                fallback_details,
                "name",
                "original_name",
            ) or show.get("name"),
            "original_name": details.get(
                "original_name",
                show.get("original_name"),
            ),
            "original_language": details.get("original_language"),
            "first_air_date": details.get(
                "first_air_date",
                show.get("first_air_date"),
            ),
            "vote_average": details.get(
                "vote_average",
                show.get("vote_average"),
            ),
            "vote_count": details.get(
                "vote_count",
                show.get("vote_count"),
            ),
            "overview": self._localized_field(
                details,
                fallback_details,
                "overview",
            ) or "",
            "poster_path": details.get(
                "poster_path",
                show.get("poster_path"),
            ),
            "genre_ids": [
                int(genre["id"])
                for genre in details.get("genres", [])
                if genre.get("id") is not None
            ],
            "genres": [
                {
                    "id": int(genre["id"]),
                    "name": genre.get("name"),
                }
                for genre in details.get("genres", [])
                if genre.get("id") is not None
            ],
            "language": self.language,
            "fallback_language": self.fallback_language,
            **availability,
            "watched": self.store.is_watched("tv", tmdb_id),
            "dismissed": self.store.is_dismissed("tv", tmdb_id),
        }

    async def _personalized_recommendations(
        self,
        *,
        media_type: str,
        seed_ids: list[int],
        exclude_ids: set[int],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Aggregate TMDB recommendations from local/watchlist seed items."""
        scores: dict[int, dict[str, Any]] = {}

        # Bound API work while still using a useful cross-section of history.
        for seed_id in seed_ids[-20:]:
            if media_type == "movie":
                recommendations = await self.api.get_movie_recommendations(
                    seed_id,
                    self.language,
                )
            else:
                recommendations = await self.api.get_tv_recommendations(
                    seed_id,
                    self.language,
                )

            for rank, item in enumerate(recommendations[:20]):
                tmdb_id = int(item["id"])
                if tmdb_id in exclude_ids:
                    continue
                if self.store.is_dismissed(media_type, tmdb_id):
                    continue
                if self.store.is_watched(media_type, tmdb_id):
                    continue

                current = scores.setdefault(
                    tmdb_id,
                    {
                        "item": item,
                        "seed_hits": 0,
                        "rank_score": 0.0,
                    },
                )
                current["seed_hits"] += 1
                current["rank_score"] += 1.0 / (rank + 1)

        ranked = sorted(
            scores.values(),
            key=lambda value: (
                -int(value["seed_hits"]),
                -float(value["rank_score"]),
                -float(value["item"].get("vote_average") or 0),
                -float(value["item"].get("popularity") or 0),
            ),
        )[:limit]

        enriched: list[dict[str, Any]] = []
        for value in ranked:
            item = value["item"]
            if media_type == "movie":
                detail = await self._enrich_movie(item)
            else:
                detail = await self._enrich_tv_discovery(item)

            detail["recommendation"] = {
                "seed_hits": int(value["seed_hits"]),
                "score": round(float(value["rank_score"]), 4),
            }
            enriched.append(detail)

        return enriched

    async def _enrich_tv(self, show: dict[str, Any]) -> dict[str, Any]:
        """Enrich a followed TV show with airing, progress and schedule."""
        tmdb_id = int(show["id"])
        (details, fallback_details), provider_data = await asyncio.gather(
            self._localized_tv_details(tmdb_id),
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
            "name": self._localized_field(
                details,
                fallback_details,
                "name",
                "original_name",
            ) or show.get("name"),
            "original_name": details.get("original_name"),
            "original_language": details.get("original_language"),
            "poster_path": details.get("poster_path"),
            "language": self.language,
            "fallback_language": self.fallback_language,
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


    async def _resolve_oscar_best_picture(
        self,
    ) -> list[dict[str, Any]]:
        """Resolve the current Best Picture slate to TMDB movies.

        The Academy is the authoritative source for the slate; TMDB is used
        only to resolve the media record, localization and streaming data.
        """
        results: list[dict[str, Any]] = []

        for award in OSCAR_BEST_PICTURE_2026:
            title = award["title"]

            candidates = await self.api.search_movies(
                title,
                self.language,
            )

            if not candidates and self.fallback_language:
                candidates = await self.api.search_movies(
                    title,
                    self.fallback_language,
                )

            if not candidates:
                continue

            # Prefer an exact localized or original-title match, then TMDB's
            # own search ordering. 2026 Oscars honor 2025 releases, which is
            # used as a secondary disambiguator.
            exact = [
                item
                for item in candidates
                if str(item.get("title", "")).casefold() == title.casefold()
                or str(item.get("original_title", "")).casefold()
                == title.casefold()
            ]

            pool = exact or candidates

            def candidate_key(item: dict[str, Any]) -> tuple[int, float]:
                release = str(item.get("release_date") or "")
                year_match = 1 if release.startswith("2025-") else 0
                return (
                    year_match,
                    float(item.get("popularity") or 0),
                )

            selected = max(pool, key=candidate_key)
            enriched = await self._enrich_movie(selected)

            enriched["source"] = "oscars"
            enriched["award"] = {
                "ceremony_year": 2026,
                "film_year": 2025,
                "category": "Best Picture",
                "winner": bool(award["winner"]),
                "status": (
                    "winner"
                    if award["winner"]
                    else "nominee"
                ),
            }

            results.append(enriched)

        results.sort(
            key=lambda item: (
                0 if item.get("award", {}).get("winner") else 1,
                -(float(item.get("vote_average") or 0)),
                item.get("title") or "",
            )
        )

        return results


    @staticmethod
    def _parse_genre_ids(value: Any) -> list[int]:
        """Parse comma-separated or list genre IDs."""
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            raw = list(value)
        else:
            raw = str(value).replace(";", ",").split(",")

        result: list[int] = []
        for item in raw:
            text = str(item).strip()
            if not text:
                continue
            try:
                genre_id = int(text)
            except ValueError:
                continue
            if genre_id not in result:
                result.append(genre_id)
        return result

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            account_id = int(self.entry.data[CONF_ACCOUNT_ID])

            if self.use_profile_language:
                await self._refresh_profile_locale()

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

            # Discovery is intentionally generated across all streaming
            # providers known by TMDB for the configured region. The
            # companion card can then filter the same feed to either all
            # regional providers or only the user's selected providers.
            discovery_provider_scope = str(
                self._option(
                    CONF_DISCOVERY_PROVIDER_SCOPE,
                    DEFAULT_DISCOVERY_PROVIDER_SCOPE,
                )
            ).lower()
            discovery_max_pages = max(
                1,
                min(
                    20,
                    int(
                        self._option(
                            CONF_DISCOVERY_MAX_PAGES,
                            DEFAULT_DISCOVERY_MAX_PAGES,
                        )
                    ),
                ),
            )
            discovery_include_genres = self._parse_genre_ids(
                self._option(
                    CONF_DISCOVERY_INCLUDE_GENRES,
                    DEFAULT_DISCOVERY_INCLUDE_GENRES,
                )
            )
            discovery_exclude_genres = self._parse_genre_ids(
                self._option(
                    CONF_DISCOVERY_EXCLUDE_GENRES,
                    DEFAULT_DISCOVERY_EXCLUDE_GENRES,
                )
            )
            discovery_genre_match = str(
                self._option(
                    CONF_DISCOVERY_GENRE_MATCH,
                    DEFAULT_DISCOVERY_GENRE_MATCH,
                )
            ).lower()
            if discovery_genre_match not in {"any", "all"}:
                discovery_genre_match = "any"

            discovery_provider_ids = (
                sorted(selected_ids)
                if discovery_provider_scope == "my"
                else sorted(provider_catalog)
            )
            tv_discovery_provider_ids = (
                sorted(selected_ids)
                if discovery_provider_scope == "my"
                else sorted(
                    {
                        int(provider["provider_id"])
                        for provider in tv_providers
                        if provider.get("provider_id") is not None
                    }
                )
            )

            discovered = await self.api.discover_movies(
                region=self.region,
                language=self.language,
                provider_ids=discovery_provider_ids,
                min_rating=float(
                    self._option(CONF_MIN_RATING, DEFAULT_MIN_RATING)
                ),
                min_votes=int(
                    self._option(CONF_MIN_VOTES, DEFAULT_MIN_VOTES)
                ),
                include_genres=discovery_include_genres,
                exclude_genres=discovery_exclude_genres,
                genre_match=discovery_genre_match,
                max_pages=discovery_max_pages,
            )

            discovered_tv = await self.api.discover_tv(
                region=self.region,
                language=self.language,
                provider_ids=tv_discovery_provider_ids,
                min_rating=float(
                    self._option(CONF_MIN_RATING, DEFAULT_MIN_RATING)
                ),
                min_votes=int(
                    self._option(CONF_MIN_VOTES, DEFAULT_MIN_VOTES)
                ),
                include_genres=discovery_include_genres,
                exclude_genres=discovery_exclude_genres,
                genre_match=discovery_genre_match,
                max_pages=discovery_max_pages,
            )

            visible_watchlist = [
                movie
                for movie in watchlist_movies
                if not self.store.is_watched("movie", int(movie["id"]))
            ]

            watchlist_ids = {
                int(movie["id"])
                for movie in watchlist_movies
            }
            watchlist_tv_ids = {
                int(show["id"])
                for show in watchlist_tv
            }

            visible_discovery = [
                movie
                for movie in discovered
                if int(movie["id"]) not in watchlist_ids
                and not self.store.is_watched("movie", int(movie["id"]))
                and not self.store.is_dismissed("movie", int(movie["id"]))
            ][: int(
                self._option(
                    CONF_DISCOVERY_LIMIT,
                    DEFAULT_DISCOVERY_LIMIT,
                )
            )]

            visible_tv_discovery = [
                show
                for show in discovered_tv
                if int(show["id"]) not in watchlist_tv_ids
                and not self.store.is_watched("tv", int(show["id"]))
                and not self.store.is_dismissed("tv", int(show["id"]))
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
            tv_discovery_details = await asyncio.gather(
                *(
                    self._enrich_tv_discovery(show)
                    for show in visible_tv_discovery
                )
            )

            personalized_limit = int(
                self._option(
                    CONF_DISCOVERY_LIMIT,
                    DEFAULT_DISCOVERY_LIMIT,
                )
            )

            personalized_movies = await self._personalized_recommendations(
                media_type="movie",
                seed_ids=[
                    *self.store.watched_movies,
                    *watchlist_ids,
                ],
                exclude_ids={
                    *self.store.watched_movies,
                    *watchlist_ids,
                },
                limit=personalized_limit,
            )

            personalized_tv = await self._personalized_recommendations(
                media_type="tv",
                seed_ids=[
                    *self.store.watched_tv,
                    *watchlist_tv_ids,
                ],
                exclude_ids={
                    *self.store.watched_tv,
                    *watchlist_tv_ids,
                },
                limit=personalized_limit,
            )

            oscar_movies = await self._resolve_oscar_best_picture()
            oscar_movies = [
                movie
                for movie in oscar_movies
                if not self.store.is_watched(
                    "movie", int(movie["id"])
                )
                and not self.store.is_dismissed(
                    "movie", int(movie["id"])
                )
            ]

            for movie in oscar_movies:
                movie["on_watchlist"] = (
                    int(movie["id"]) in watchlist_ids
                )

            global_next_episodes: list[dict[str, Any]] = []

            for show in tv_details:
                episode = show.get("next_episode_to_air")
                if not episode or not episode.get("air_date"):
                    continue

                global_next_episodes.append(
                    {
                        "tmdb_id": show["id"],
                        "show": show["name"],
                        "poster_path": show.get("poster_path"),
                        "providers": show.get("providers", []),
                        "provider_details": show.get(
                            "provider_details", []
                        ),
                        "my_providers": show.get(
                            "my_providers", []
                        ),
                        "my_provider_details": show.get(
                            "my_provider_details", []
                        ),
                        "available_on_my_services": show.get(
                            "available_on_my_services", False
                        ),
                        **episode,
                    }
                )

            global_next_episodes.sort(
                key=lambda item: (
                    item.get("air_date") or "9999-12-31",
                    item.get("show") or "",
                    int(item.get("season") or 0),
                    int(item.get("episode") or 0),
                )
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
                "upcoming_episodes_next": global_next_episodes[
                    : self.upcoming_limit
                ],
                "episodes_today": episodes_today,
                "episodes_next_7_days": episodes_next_7_days,
                "episodes_next_30_days": episodes_next_30_days,
                "discovered_movies": discovery_details,
                "discovered_tv": tv_discovery_details,
                "personalized_movies": personalized_movies,
                "personalized_tv": personalized_tv,
                "oscar_movies": oscar_movies,
                "selected_providers": selected_providers,
                "provider_ids": selected_ids,
                "discovery_provider_ids": discovery_provider_ids,
                "discovery_backend_filter": {
                    "provider_scope": discovery_provider_scope,
                    "include_genres": discovery_include_genres,
                    "exclude_genres": discovery_exclude_genres,
                    "genre_match": discovery_genre_match,
                    "max_pages": discovery_max_pages,
                },
                "watched_movies": self.store.watched_movies,
                "dismissed_movies": self.store.dismissed_movies,
            }

        except TMDBError as err:
            raise UpdateFailed(
                f"Error communicating with TMDB: {err}"
            ) from err
