"""Data update coordinator for Media Watch."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .award_taxonomy import resolve_source_categories
from .award_registry import (
    create_adapter,
    label_for_source,
    providers_for_media_type,
)
from .api import TMDBApi, TMDBError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_FALLBACK_LANGUAGE,
    CONF_LANGUAGE,
    CONF_USE_PROFILE_LANGUAGE,
    CONF_PROVIDERS,
    CONF_REGION,
    CONF_UPCOMING_LIMIT,
    DEFAULT_FALLBACK_LANGUAGE,
    DEFAULT_LANGUAGE,
    DEFAULT_USE_PROFILE_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_UPCOMING_LIMIT,
    DOMAIN,
    EVENT_RELEASE_UPDATE,
    CONF_DISCOVERY_PROFILES,
    UPDATE_INTERVAL,
    OSCAR_BEST_PICTURE_2026,
    PROFILE_SOURCE_DISCOVER,
    PROFILE_SOURCE_PERSON,
    PROFILE_SOURCE_PERSONALIZED,
    PROFILE_AWARD_NONE,
    PROFILE_AWARD_OSCARS_BEST_PICTURE_2026,
    AWARD_SOURCE_NONE,
    AWARD_SOURCE_ANY,
    AWARD_STATUS_ANY,
    AWARD_STATUS_WINNER,
    AWARD_STATUS_NOMINATED_NO_WIN,
    AWARD_STATUS_NOMINATED_AND_WON,
    AWARD_PRESET_NONE,
    AWARD_PRESET_LATEST_WINNERS,
    AWARD_PRESET_LATEST_NOMINEES,
    AWARD_PRESET_BEST_PICTURE_WINNERS,
    AWARD_PRESET_BEST_PICTURE_NOMINEES,
)
from .store import MediaWatchStore

_LOGGER = logging.getLogger(__name__)

STREAMING_TYPES = ("flatrate", "free", "ads")
ALL_AVAILABILITY_TYPES = ("flatrate", "free", "ads", "rent", "buy")

AWARD_BADGE_ICONS = {
    "oscars": "mdi:trophy-award",
    "guldbaggen": "mdi:bug-outline",
    "bafta_film": "mdi:drama-masks",
    "golden_globes_film": "mdi:earth",
    "cannes": "mdi:palm-tree",
    "hong_kong_film_awards": "mdi:filmstrip",
}


def _merge_person_wins(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge person-level award wins while preserving their metadata."""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for group in groups:
        for win in group or []:
            name = str(win.get("name") or "").strip()
            role = str(win.get("role") or "").strip()
            category = str(win.get("category") or "").strip()
            if not name:
                continue
            merged.setdefault(
                (name.casefold(), role.casefold(), category.casefold()),
                {"name": name, "role": role, "category": category},
            )
    return list(merged.values())


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
        self._award_tmdb_cache: dict[str, dict[str, Any] | None] = {}
        self._english_person_name_cache: dict[int, str | None] = {}
        self._english_person_name_retry_after: dict[int, float] = {}
        self._watchlist_top_film_index_key: tuple[int, ...] | None = None
        self._watchlist_top_film_by_imdb: dict[
            str, list[dict[str, Any]]
        ] = {}
        self._watchlist_top_film_by_title: dict[
            str, list[dict[str, Any]]
        ] = {}
        self._watchlist_award_task: asyncio.Task[None] | None = None
        self._watchlist_award_publish_task: asyncio.Task[None] | None = None
        self._watchlist_award_publish_pending = False
        self._watchlist_award_failed_sources: set[str] = set()
        self._watchlist_award_retry_after = 0.0
        self._deferred_refresh_task: asyncio.Task[None] | None = None
        self._defer_discovery_profiles = True
        self._discovery_profile_tasks: dict[
            str, asyncio.Task[None]
        ] = {}
        self._discovery_profile_results: dict[
            str, dict[str, Any]
        ] = {}
        self._discovery_profile_last_scheduled: dict[str, float] = {}
        self._profile_diagnostics: dict[str, dict[str, Any]] = {}
        self._last_core_success: str | None = None
        self._last_core_error: str | None = None
        self._release_updates: list[dict[str, Any]] = []

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    @property
    def queue_diagnostics(self) -> dict[str, Any]:
        """Return UI-ready health details for core and profile queues."""
        diagnostics = getattr(self, "_profile_diagnostics", {})
        profiles = []
        for profile in self.discovery_profiles:
            profile_id = str(profile["id"])
            profiles.append(
                {
                    "id": profile_id,
                    "name": str(profile.get("name") or profile_id),
                    "media_type": str(
                        profile.get("media_type") or "movie"
                    ),
                    "source": str(
                        profile.get("source") or PROFILE_SOURCE_DISCOVER
                    ),
                    "status": "pending",
                    **dict(diagnostics.get(profile_id, {})),
                }
            )
        failed = sum(item.get("status") == "error" for item in profiles)
        active = sum(
            item.get("status") in {"scheduled", "updating"}
            for item in profiles
        )
        pending = sum(item.get("status") == "pending" for item in profiles)
        failed_awards = sorted(
            getattr(self, "_watchlist_award_failed_sources", set())
        )
        if failed or failed_awards or getattr(self, "_last_core_error", None):
            status = "degraded"
        elif active:
            status = "updating"
        elif pending or getattr(self, "_last_core_success", None) is None:
            status = "pending"
        else:
            status = "healthy"
        return {
            "status": status,
            "last_core_success": getattr(self, "_last_core_success", None),
            "last_core_error": getattr(self, "_last_core_error", None),
            "profile_count": len(profiles),
            "failed_profiles": failed,
            "active_profiles": active,
            "failed_award_sources": failed_awards,
            "profiles": profiles,
        }

    def profile_diagnostics(self, profile_id: str) -> dict[str, Any]:
        """Return current diagnostics for one dynamic profile sensor."""
        return next(
            (
                item
                for item in self.queue_diagnostics["profiles"]
                if str(item.get("id")) == profile_id
            ),
            {"id": profile_id, "status": "pending"},
        )

    @staticmethod
    def _digital_release_date(details: dict[str, Any], region: str) -> str | None:
        """Return the earliest regional TMDB digital release date."""
        dates = [
            str(item.get("release_date") or "")[:10]
            for country in (details.get("release_dates") or {}).get(
                "results", []
            )
            if str(country.get("iso_3166_1") or "").upper()
            == region.upper()
            for item in country.get("release_dates", [])
            if int(item.get("type") or 0) == 4
            and str(item.get("release_date") or "")[:10]
        ]
        return min(dates) if dates else None

    async def _async_track_watchlist_releases(
        self,
        movies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Persist Watchlist state and fire events only for later changes."""
        previous = self.store.watchlist_snapshots
        current: dict[str, dict[str, Any]] = {}
        updates: list[dict[str, Any]] = []

        for movie in movies:
            tmdb_id = int(movie["id"])
            key = str(tmdb_id)
            providers = sorted(
                [
                    {
                        "id": int(provider["id"]),
                        "name": provider.get("name"),
                    }
                    for provider in movie.get("my_provider_details", [])
                    if isinstance(provider, dict)
                    and provider.get("id") is not None
                ],
                key=lambda provider: provider["id"],
            )
            snapshot = {
                "tmdb_id": tmdb_id,
                "title": movie.get("title"),
                "release_date": movie.get("release_date"),
                "digital_release_date": movie.get("digital_release_date"),
                "region": self.region,
                "selected_provider_ids": sorted(self.provider_ids),
                "providers": providers,
            }
            current[key] = snapshot
            old = previous.get(key)
            if old is None:
                continue

            for field, change_type in (
                ("release_date", "release_date_changed"),
                ("digital_release_date", "digital_release_date_changed"),
            ):
                if field == "digital_release_date" and old.get(
                    "region"
                ) != snapshot.get("region"):
                    continue
                old_value = old.get(field)
                new_value = snapshot.get(field)
                if new_value and old_value != new_value:
                    if old_value is None:
                        change_type = change_type.replace(
                            "_changed", "_announced"
                        )
                    updates.append(
                        {
                            "change_type": change_type,
                            "media_type": "movie",
                            "tmdb_id": tmdb_id,
                            "title": snapshot["title"],
                            "old_value": old_value,
                            "new_value": new_value,
                        }
                    )

            old_provider_ids = {
                int(provider["id"])
                for provider in old.get("providers", [])
                if isinstance(provider, dict)
                and provider.get("id") is not None
            }
            added = [
                provider
                for provider in providers
                if provider["id"] not in old_provider_ids
            ]
            if added and old.get("selected_provider_ids") == snapshot.get(
                "selected_provider_ids"
            ):
                updates.append(
                    {
                        "change_type": "provider_added",
                        "media_type": "movie",
                        "tmdb_id": tmdb_id,
                        "title": snapshot["title"],
                        "providers": added,
                    }
                )

        if current != previous:
            await self.store.set_watchlist_snapshots(current)
        detected_at = dt_util.now().isoformat()
        for update in updates:
            update["region"] = self.region
            update["detected_at"] = detected_at
            self.hass.bus.async_fire(EVENT_RELEASE_UPDATE, update)
        self._release_updates = updates
        return updates

    async def async_mark_released_episodes_watched(
        self,
        tmdb_id: int,
    ) -> None:
        """Mark aired regular episodes watched, never future episodes."""
        details = await self.api.get_tv_details(tmdb_id, self.language)
        season_numbers = sorted(
            {
                int(season.get("season_number", 0))
                for season in details.get("seasons", [])
                if int(season.get("season_number", 0)) > 0
            }
        )
        season_details = await asyncio.gather(
            *(
                self.api.get_tv_season(
                    tmdb_id,
                    season_number,
                    self.language,
                )
                for season_number in season_numbers
            )
        )
        today = dt_util.now().date().isoformat()
        released = {
            season_number: sorted(
                {
                    int(episode.get("episode_number", 0))
                    for episode in season_data.get("episodes", [])
                    if int(episode.get("episode_number", 0)) > 0
                    and episode.get("air_date")
                    and str(episode["air_date"]) <= today
                }
            )
            for season_number, season_data in zip(
                season_numbers,
                season_details,
                strict=True,
            )
        }
        await self.store.set_released_episodes_watched(tmdb_id, released)

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

    def _localized_field(
        self,
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
                and str(primary.get("original_language") or "").casefold()
                != self.language.split("-", 1)[0].casefold()
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
        fallback_title = (
            str(fallback.get("title") or "").strip()
            if fallback
            else ""
        )
        if not fallback_title or fallback_title == title:
            fallback_title = None
        overview = self._localized_field(
            details,
            fallback,
            "overview",
        )
        tagline = self._localized_field(
            details,
            fallback,
            "tagline",
        )
        credits = details.get("credits") or {}
        crew = credits.get("crew") or []

        def people_for_jobs(jobs: set[str]) -> list[dict[str, Any]]:
            people: list[dict[str, Any]] = []
            seen: set[tuple[int, str]] = set()
            for person in crew:
                name = str(person.get("name") or "").strip()
                if person.get("job") not in jobs or not name:
                    continue
                key = (int(person.get("id") or 0), name)
                if key in seen:
                    continue
                seen.add(key)
                people.append({"id": key[0], "name": name})
            return people

        director_people = people_for_jobs({"Director"})
        writer_people = people_for_jobs(
            {"Writer", "Screenplay", "Story"}
        )
        cast_people = [
            {
                "id": int(person.get("id") or 0),
                "name": str(person.get("name") or "").strip(),
            }
            for person in (credits.get("cast") or [])
            if person.get("name")
        ][:3]
        directors = [person["name"] for person in director_people]
        writers = [person["name"] for person in writer_people]
        cast = [person["name"] for person in cast_people]
        production_countries = [
            {
                "code": country.get("iso_3166_1"),
                "name": country.get("name"),
            }
            for country in details.get("production_countries") or []
            if country.get("iso_3166_1") or country.get("name")
        ]
        collection_data = details.get("belongs_to_collection")
        collection = (
            {
                "id": collection_data.get("id"),
                "name": collection_data.get("name"),
                "poster_path": collection_data.get("poster_path"),
                "backdrop_path": collection_data.get("backdrop_path"),
            }
            if isinstance(collection_data, dict)
            else None
        )
        external_ids = details.get("external_ids") or {}
        imdb_id = str(external_ids.get("imdb_id") or "").strip()

        return {
            "id": tmdb_id,
            "title": title,
            "fallback_title": fallback_title,
            "original_title": details.get(
                "original_title",
                movie.get("original_title"),
            ),
            "original_language": details.get("original_language"),
            "imdb_id": imdb_id if imdb_id.startswith("tt") else None,
            "release_date": details.get(
                "release_date",
                movie.get("release_date"),
            ),
            "digital_release_date": self._digital_release_date(
                details,
                self.region,
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
            "tagline": tagline or "",
            "runtime": details.get("runtime"),
            "production_countries": production_countries,
            "collection": collection,
            "directors": directors,
            "writers": writers,
            "cast": cast,
            "_credit_people": {
                "directors": director_people,
                "writers": writer_people,
                "cast": cast_people,
            },
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

    async def _async_enrich_watchlist_awards(
        self,
        movies: list[dict[str, Any]],
    ) -> None:
        """Attach top-film award facts from every compatible adapter."""
        if not movies:
            return

        release_years = {
            int(str(movie.get("release_date") or "")[:4])
            for movie in movies
            if str(movie.get("release_date") or "")[:4].isdigit()
        }
        # Ceremonies can precede general release or occur in either of the
        # following two years. Limit web adapters to relevant years rather
        # than crawling their full history whenever Home Assistant starts.
        award_years = tuple(
            sorted(
                {
                    year + offset
                    for year in release_years
                    for offset in (-1, 0, 1, 2)
                }
            )
        )
        if not award_years:
            award_years = (dt_util.now().year,)

        index_matches = self._watchlist_top_film_index_key == award_years
        if index_matches:
            self._apply_watchlist_awards(movies)

        retry_due = (
            self._watchlist_award_failed_sources
            and asyncio.get_running_loop().time()
            >= self._watchlist_award_retry_after
        )
        if not index_matches or retry_due:
            if (
                self._watchlist_award_task is None
                or self._watchlist_award_task.done()
            ):
                self._watchlist_award_task = (
                    self.hass.async_create_background_task(
                        self._async_build_watchlist_top_film_index(
                            award_years
                        ),
                        "media_watch_watchlist_awards",
                    )
                )
                self._watchlist_award_task.add_done_callback(
                    lambda task: self._watchlist_awards_loaded(
                        task,
                        award_years,
                    )
                )
            return

    def _watchlist_awards_loaded(
        self,
        task: asyncio.Task[None],
        award_years: tuple[int, ...],
    ) -> None:
        """Refresh current coordinator data after an index build finishes."""
        if task.cancelled():
            return
        if error := task.exception():
            _LOGGER.warning(
                "Could not build the watchlist award index: %s",
                error,
            )
            return
        if self._watchlist_top_film_index_key != award_years:
            return
        if (
            self._watchlist_award_publish_task is None
            or self._watchlist_award_publish_task.done()
        ):
            self._watchlist_award_publish_task = (
                self.hass.async_create_background_task(
                    self._async_publish_watchlist_awards(),
                    "media_watch_publish_watchlist_awards",
                )
            )
        else:
            self._watchlist_award_publish_pending = True

    async def _async_publish_watchlist_awards(self) -> None:
        """Refresh again if a newer index finishes during publication."""
        while True:
            self._watchlist_award_publish_pending = False
            await self.async_refresh()
            if not self._watchlist_award_publish_pending:
                return

    def cancel_background_tasks(self) -> None:
        """Cancel coordinator-owned work when the config entry unloads."""
        for task in (
            self._watchlist_award_task,
            self._watchlist_award_publish_task,
            self._deferred_refresh_task,
            *self._discovery_profile_tasks.values(),
        ):
            if task is not None and not task.done():
                task.cancel()

    def _apply_watchlist_awards(
        self,
        movies: list[dict[str, Any]],
    ) -> None:
        """Apply the already loaded award index to watchlist items."""

        for movie in movies:
            imdb_id = str(movie.get("imdb_id") or "")
            awards = list(
                self._watchlist_top_film_by_imdb.get(imdb_id, [])
            )
            release_text = str(movie.get("release_date") or "")[:4]
            release_year = (
                int(release_text) if release_text.isdigit() else None
            )
            for title in (movie.get("title"), movie.get("original_title")):
                key = self._award_title_key(title)
                if key:
                    awards.extend(
                        award
                        for award in self._watchlist_top_film_by_title.get(
                            key, []
                        )
                        if release_year is None
                        or any(
                            release_year - 1
                            <= int(award_year)
                            <= release_year + 2
                            for award_year in award.get(
                                "award_years", []
                            )
                        )
                    )
            awards = self._merge_awards_by_source(awards)
            if not awards:
                continue

            movie["awards"] = awards
            movie["award"] = (
                awards[0]
                if len(awards) == 1
                else self._aggregate_awards(awards)
            )
            movie["award_summary"] = self._award_summary(movie)

    @staticmethod
    def _award_title_key(value: Any) -> str:
        """Normalize a title for local cross-source matching."""
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(
            char
            for char in normalized.casefold()
            if char.isalnum() and not unicodedata.combining(char)
        )

    @staticmethod
    def _award_year_ranges(
        years: tuple[int, ...],
    ) -> list[tuple[int, int]]:
        """Collapse relevant award years into contiguous query ranges."""
        ranges: list[tuple[int, int]] = []
        for year in years:
            if not ranges or year > ranges[-1][1] + 1:
                ranges.append((year, year))
            else:
                ranges[-1] = (ranges[-1][0], year)
        return ranges

    async def _async_build_watchlist_top_film_index(
        self,
        award_years: tuple[int, ...],
    ) -> None:
        by_imdb: dict[str, list[dict[str, Any]]] = {}
        by_title: dict[str, list[dict[str, Any]]] = {}
        ranges = self._award_year_ranges(award_years)
        failed_sources: set[str] = set()

        for info in providers_for_media_type("movie"):
            adapter = create_adapter(self.hass, info.source)
            if adapter is None:
                continue
            try:
                options = await adapter.async_categories("movie")
                categories = resolve_source_categories(
                    info.source,
                    "best_film",
                    options,
                )
                records: list[dict[str, Any]] = []
                for year_from, year_to in ranges:
                    for category in categories:
                        records.extend(
                            await adapter.async_filter_titles(
                                media_type="movie",
                                year_from=year_from,
                                year_to=year_to,
                                category=category,
                                status=AWARD_STATUS_ANY,
                            )
                        )
            except Exception as err:  # noqa: BLE001
                failed_sources.add(info.source)
                _LOGGER.warning(
                    "Could not load watchlist awards from %s: %s",
                    info.source,
                    err,
                )
                continue

            for record in records:
                award = {
                    "organization": info.label,
                    "source": info.source,
                    "award_years": list(record.get("award_years", [])),
                    "nominations": int(record.get("nominations", 0)),
                    "wins": int(record.get("wins", 0)),
                    "categories": list(record.get("categories", [])),
                    "winning_categories": list(
                        record.get("winning_categories", [])
                    ),
                    "recipients": list(record.get("recipients", [])),
                    "person_wins": list(record.get("person_wins", [])),
                    "badge": {
                        "source": info.source,
                        "label": info.label,
                        "icon": AWARD_BADGE_ICONS.get(
                            info.source,
                            "mdi:medal-outline",
                        ),
                    },
                }
                imdb_id = str(record.get("imdb_id") or "")
                if imdb_id.startswith("tt"):
                    by_imdb.setdefault(imdb_id, []).append(award)
                candidates = [
                    record.get("title"),
                    *record.get("title_candidates", []),
                ]
                for candidate in candidates:
                    key = self._award_title_key(candidate)
                    if key:
                        by_title.setdefault(key, []).append(award)

        self._watchlist_top_film_by_imdb = by_imdb
        self._watchlist_top_film_by_title = by_title
        # Publish successful sources even if one provider failed. Failed
        # providers are retried on a later refresh instead of suppressing all
        # watchlist awards or creating an immediate retry loop.
        self._watchlist_top_film_index_key = award_years
        self._watchlist_award_failed_sources = failed_sources
        self._watchlist_award_retry_after = (
            asyncio.get_running_loop().time() + 300.0
            if failed_sources
            else 0.0
        )

    @staticmethod
    def _merge_awards_by_source(
        awards: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Deduplicate title/IMDb matches and merge facts per source."""
        merged: dict[str, dict[str, Any]] = {}
        for award in awards:
            source = str(award.get("source") or "unknown")
            if source not in merged:
                merged[source] = dict(award)
                continue
            target = merged[source]
            for field in (
                "award_years",
                "categories",
                "winning_categories",
                "recipients",
            ):
                target[field] = sorted(
                    set(target.get(field, []))
                    | set(award.get(field, []))
                )
            target["person_wins"] = _merge_person_wins(
                target.get("person_wins", []),
                award.get("person_wins", []),
            )
            # A title can be reached through IMDb, title aliases and repeated
            # category queries; these are the same facts, not extra awards.
            target["nominations"] = max(
                int(target.get("nominations", 0)),
                int(award.get("nominations", 0)),
            )
            target["wins"] = max(
                int(target.get("wins", 0)),
                int(award.get("wins", 0)),
            )
        return [merged[source] for source in sorted(merged)]

    @staticmethod
    def _aggregate_awards(
        awards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build the legacy aggregate award field for multiple sources."""
        return {
            "organization": "Multiple award organizations",
            "source": AWARD_SOURCE_ANY,
            "sources": [award["source"] for award in awards],
            "award_years": sorted(
                {
                    year
                    for award in awards
                    for year in award.get("award_years", [])
                }
            ),
            "nominations": sum(
                int(award.get("nominations", 0)) for award in awards
            ),
            "wins": sum(int(award.get("wins", 0)) for award in awards),
            "categories": sorted(
                {
                    category
                    for award in awards
                    for category in award.get("categories", [])
                }
            ),
            "winning_categories": sorted(
                {
                    category
                    for award in awards
                    for category in award.get("winning_categories", [])
                }
            ),
            "recipients": sorted(
                {
                    recipient
                    for award in awards
                    for recipient in award.get("recipients", [])
                }
            ),
            "person_wins": _merge_person_wins(
                *[list(award.get("person_wins", [])) for award in awards]
            ),
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


    @staticmethod
    def _parse_optional_int(value: Any) -> int | None:
        """Parse an optional integer safely."""
        if value in (None, ""):
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_optional_year(cls, value: Any) -> int | None:
        """Parse a year, including legacy YYYY-MM-DD values."""
        if value in (None, ""):
            return None
        text = str(value).strip()
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 1800 <= year <= 2200:
                return year
        return cls._parse_optional_int(value)

    @staticmethod
    def _year_from_date(value: Any) -> int | None:
        """Extract a four-digit year from a TMDB date value."""
        if value in (None, ""):
            return None
        text = str(value).strip()
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 1800 <= year <= 2200:
                return year
        return None

    @property
    def discovery_profiles(self) -> list[dict[str, Any]]:
        """Return configured dynamic discovery profiles."""
        value = self.entry.options.get(CONF_DISCOVERY_PROFILES, [])
        if not isinstance(value, list):
            return []
        return [
            dict(profile)
            for profile in value
            if isinstance(profile, dict)
            and profile.get("id")
            and profile.get("name")
        ]

    def _needs_legacy_oscar_movies(self) -> bool:
        """Return whether a v0.13 fixed-Oscars profile still needs data."""
        return any(
            str(profile.get("award_filter", PROFILE_AWARD_NONE)).lower()
            == PROFILE_AWARD_OSCARS_BEST_PICTURE_2026
            and str(profile.get("media_type", "movie")).lower()
            == "movie"
            for profile in self.discovery_profiles
        )

    @staticmethod
    def _profile_date(item: dict[str, Any], media_type: str) -> str:
        if media_type == "tv":
            return str(item.get("first_air_date") or "")
        return str(item.get("release_date") or "")

    @staticmethod
    def _award_summary(
        item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Build compact UI metadata from existing award facts."""
        raw_awards = item.get("awards")
        if isinstance(raw_awards, list) and raw_awards:
            awards = [
                award
                for award in raw_awards
                if isinstance(award, dict)
            ]
        else:
            award = item.get("award")
            awards = [award] if isinstance(award, dict) else []

        if not awards:
            return None

        sources = sorted(
            {
                str(award["source"])
                for award in awards
                if award.get("source")
            }
        )
        organizations = sorted(
            {
                str(
                    award.get("organization")
                    or label_for_source(str(award.get("source") or ""))
                )
                for award in awards
                if award.get("organization") or award.get("source")
            }
        )
        nominations = sum(
            int(award.get("nominations", 0)) for award in awards
        )
        wins = sum(int(award.get("wins", 0)) for award in awards)
        badges = [
            dict(award["badge"])
            for award in awards
            if isinstance(award.get("badge"), dict)
        ]

        return {
            "nominations": nominations,
            "wins": wins,
            "winner": wins > 0,
            "sources": sources,
            "organizations": organizations,
            **({"badges": badges} if badges else {}),
            "award_years": sorted(
                {
                    int(year)
                    for award in awards
                    for year in award.get("award_years", [])
                }
            ),
            "categories": sorted(
                {
                    str(category)
                    for award in awards
                    for category in award.get("categories", [])
                }
            ),
            "winning_categories": sorted(
                {
                    str(category)
                    for award in awards
                    for category in award.get(
                        "winning_categories", []
                    )
                }
            ),
            "recipients": sorted(
                {
                    str(recipient)
                    for award in awards
                    for recipient in award.get("recipients", [])
                }
            ),
        }

    def _profile_post_filter(
        self,
        items: list[dict[str, Any]],
        profile: dict[str, Any],
        media_type: str,
        *,
        excluded_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Apply filters needed after enrichment/recommendation/award lookup."""
        blocked_ids = excluded_ids or set()
        include = set(self._parse_genre_ids(profile.get("include_genres", "")))
        exclude = set(self._parse_genre_ids(profile.get("exclude_genres", "")))
        match = str(profile.get("genre_match", "any")).lower()
        provider_scope = str(profile.get("provider_scope", "all")).lower()
        exclude_watched = bool(profile.get("exclude_watched", True))
        min_rating = float(profile.get("min_rating", 0) or 0)
        min_votes = int(profile.get("min_votes", 0) or 0)
        release_year_from = self._profile_release_year_from(profile)
        release_year_to = self._profile_release_year_to(profile)

        result: list[dict[str, Any]] = []
        for item in items:
            tmdb_id = int(item["id"])
            if tmdb_id in blocked_ids:
                continue
            if exclude_watched and self.store.is_watched(media_type, tmdb_id):
                continue
            if self.store.is_dismissed(media_type, tmdb_id):
                continue
            if provider_scope == "my" and not item.get(
                "available_on_my_services", False
            ):
                continue
            if float(item.get("vote_average") or 0) < min_rating:
                continue
            if int(item.get("vote_count") or 0) < min_votes:
                continue

            item_genres = {
                int(value)
                for value in item.get("genre_ids", [])
                if value is not None
            }
            if exclude and item_genres.intersection(exclude):
                continue
            if include:
                if match == "all":
                    if not include.issubset(item_genres):
                        continue
                elif not item_genres.intersection(include):
                    continue

            item_date = self._profile_date(item, media_type)
            item_year = self._year_from_date(item_date)
            if release_year_from is not None and (
                item_year is None or item_year < release_year_from
            ):
                continue
            if release_year_to is not None and (
                item_year is None or item_year > release_year_to
            ):
                continue

            result.append(item)

        sort_by = str(profile.get("sort_by", "popularity.desc"))
        reverse = sort_by.endswith(".desc")
        sort_field = sort_by.rsplit(".", 1)[0]

        def sort_value(item: dict[str, Any]) -> Any:
            if sort_field in {"primary_release_date", "first_air_date"}:
                return self._profile_date(item, media_type)
            if sort_field == "vote_average":
                return float(item.get("vote_average") or 0)
            if sort_field == "vote_count":
                return int(item.get("vote_count") or 0)
            return float(item.get("popularity") or 0)

        result.sort(key=sort_value, reverse=reverse)
        return result

    @staticmethod
    def _contains_cjk(value: str) -> bool:
        return bool(re.search(r"[\u3400-\u9fff]", value))

    async def _english_person_name(
        self,
        person_id: int,
        current_name: str,
    ) -> str:
        """Resolve one remaining CJK credit through cached TMDB aliases."""
        if person_id <= 0 or not self._contains_cjk(current_name):
            return current_name
        if person_id in self._english_person_name_cache:
            cached = self._english_person_name_cache[person_id]
            if cached:
                return cached
            if (
                asyncio.get_running_loop().time()
                < self._english_person_name_retry_after.get(person_id, 0.0)
            ):
                return current_name
            self._english_person_name_cache.pop(person_id, None)
        try:
            details = await self.api.get_person_details(
                person_id,
                "en-US",
            )
        except TMDBError as err:
            _LOGGER.debug(
                "Could not load English TMDB alias for person %s: %s",
                person_id,
                err,
            )
            self._english_person_name_cache[person_id] = None
            self._english_person_name_retry_after[person_id] = (
                asyncio.get_running_loop().time() + 300.0
            )
            return current_name

        candidates = [
            str(details.get("name") or "").strip(),
            *[
                str(alias).strip()
                for alias in details.get("also_known_as", [])
            ],
        ]
        english_name = next(
            (
                candidate
                for candidate in candidates
                if candidate
                and re.search(r"[A-Za-z]", candidate)
                and not self._contains_cjk(candidate)
            ),
            None,
        )
        self._english_person_name_cache[person_id] = english_name
        self._english_person_name_retry_after.pop(person_id, None)
        return english_name or current_name

    async def _translate_hong_kong_credits(
        self,
        item: dict[str, Any],
        aliases: dict[str, str],
    ) -> None:
        """Prefer HKFAA aliases, then query TMDB only for unmatched CJK."""
        credit_people = item.get("_credit_people", {})
        for field in ("directors", "writers", "cast"):
            people = {
                str(person.get("name") or "").strip(): int(
                    person.get("id") or 0
                )
                for person in credit_people.get(field, [])
            }
            translated: list[str] = []
            for raw_name in item.get(field, []):
                original_name = str(raw_name).strip()
                name = aliases.get(original_name, original_name)
                if name == original_name and self._contains_cjk(name):
                    name = await self._english_person_name(
                        people.get(original_name, 0),
                        original_name,
                    )
                translated.append(name)
            item[field] = translated


    async def _resolve_award_title(
        self,
        award_item: dict[str, Any],
        media_type: str,
        award_source: str,
    ) -> dict[str, Any] | None:
        """Resolve a normalized award title to TMDB and enrich it."""
        if media_type not in {"movie", "tv"}:
            _LOGGER.error(
                "Invalid award media type %r for source %r",
                media_type,
                award_source,
            )
            return None
        award_years = award_item.get("award_years") or []
        year_hint = (
            award_item.get("release_year")
            or (max(award_years) if award_years else "")
        )
        identity = (
            award_item.get("imdb_id")
            or award_item.get("tmdb_id")
            or award_item.get("stable_key")
            or str(award_item.get("title") or "").casefold()
        )
        cache_key = (
            f"{award_source}:{media_type}:{identity}:{year_hint}"
        )
        if cache_key in self._award_tmdb_cache:
            cached = self._award_tmdb_cache[cache_key]
            if cached is None:
                return None
            item = dict(cached)
        else:
            candidate = None
            tmdb_id = award_item.get("tmdb_id")
            imdb_id = str(award_item.get("imdb_id") or "")
            if tmdb_id:
                if media_type == "movie":
                    candidate = {"id": int(tmdb_id)}
                else:
                    candidate = {"id": int(tmdb_id)}
            elif imdb_id.startswith("tt"):
                found = await self.api.find_by_imdb_id(imdb_id, self.language)
                key = "movie_results" if media_type == "movie" else "tv_results"
                results = found.get(key) or []
                if results:
                    candidate = results[0]
            else:
                titles = list(award_item.get("title_candidates") or [])
                if award_item.get("title"):
                    titles.append(str(award_item["title"]))
                seen = set()
                titles = [x for x in titles if x and not (x.casefold() in seen or seen.add(x.casefold()))]
                award_years = award_item.get("award_years") or []
                target_year = max(award_years) if award_years else None
                for title in reversed(titles):
                    results = (
                        await self.api.search_movies(title, self.language)
                        if media_type == "movie"
                        else await self.api.search_tv(title, self.language)
                    )
                    if not results and self.fallback_language:
                        results = (
                            await self.api.search_movies(title, self.fallback_language)
                            if media_type == "movie"
                            else await self.api.search_tv(title, self.fallback_language)
                        )
                    if not results:
                        continue
                    def score(result: dict[str, Any]) -> tuple[int, float]:
                        date = str(result.get("release_date") or result.get("first_air_date") or "")
                        try:
                            year = int(date[:4])
                        except ValueError:
                            year = 0
                        year_score = 0 if target_year is None or year == 0 else max(0, 5 - abs(year - target_year))
                        return (year_score, float(result.get("popularity") or 0))
                    candidate = max(results[:10], key=score)
                    break
            if candidate is None:
                self._award_tmdb_cache[cache_key] = None
                return None
            item = (
                await self._enrich_movie(candidate)
                if media_type == "movie"
                else await self._enrich_tv_discovery(candidate)
            )
            self._award_tmdb_cache[cache_key] = dict(item)

        award_categories = list(award_item.get("categories", []))
        recipients = list(award_item.get("recipients", []))
        if award_source == "hong_kong_film_awards":
            aliases = {
                str(chinese).strip(): str(english).strip()
                for chinese, english in award_item.get(
                    "person_aliases", {}
                ).items()
                if str(chinese).strip() and str(english).strip()
            }
            await self._translate_hong_kong_credits(item, aliases)
        organization = (
            award_item.get("organization")
            or label_for_source(award_source)
        )
        item["award"] = {
            "organization": organization,
            "source": award_source,
            "award_years": award_item.get("award_years", []),
            "nominations": award_item.get("nominations", 0),
            "wins": award_item.get("wins", 0),
            "categories": award_categories,
            "winning_categories": award_item.get("winning_categories", []),
            "recipients": recipients,
            "person_wins": list(award_item.get("person_wins", [])),
            "badge": {
                "source": award_source,
                "label": organization,
                "icon": AWARD_BADGE_ICONS.get(
                    award_source,
                    "mdi:medal-outline",
                ),
            },
        }
        if len(award_categories) == 1 and recipients:
            category = str(award_categories[0]).casefold()
            if "director" in category or "directing" in category:
                item["directors"] = recipients
            elif "screenplay" in category or "writing" in category:
                item["writers"] = recipients
        return item

    async def _award_profile_candidates(
        self,
        profile: dict[str, Any],
        *,
        target_limit: int,
        resolution_batch_size: int,
        excluded_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Build an award candidate set from one or all adapters."""
        source = str(
            profile.get("award_source", AWARD_SOURCE_NONE)
        ).lower()
        media_type = str(profile.get("media_type", "movie"))
        preset = str(
            profile.get("award_preset", AWARD_PRESET_NONE)
        ).lower()
        requested_year_from = self._parse_optional_year(
            profile.get("award_year_from")
        )
        requested_year_to = self._parse_optional_year(
            profile.get("award_year_to")
        )
        requested_status = str(
            profile.get("award_status", AWARD_STATUS_ANY)
        ).lower()
        aggregate_status = requested_status
        if preset in {
            AWARD_PRESET_LATEST_WINNERS,
            AWARD_PRESET_BEST_PICTURE_WINNERS,
        }:
            aggregate_status = AWARD_STATUS_WINNER
        elif preset in {
            AWARD_PRESET_LATEST_NOMINEES,
            AWARD_PRESET_BEST_PICTURE_NOMINEES,
        }:
            aggregate_status = AWARD_STATUS_ANY
        requested_category = str(
            profile.get("award_category", "all") or "all"
        )

        if source == AWARD_SOURCE_ANY:
            source_ids = [
                info.source
                for info in providers_for_media_type(media_type)
            ]
        else:
            source_ids = [source]

        titles_by_source: dict[str, list[dict[str, Any]]] = {}
        for current_source in source_ids:
            adapter = create_adapter(self.hass, current_source)
            if (
                adapter is None
                or media_type not in adapter.info.media_types
            ):
                continue

            try:
                source_options = await adapter.async_categories(
                    media_type
                )
                year_from = requested_year_from
                year_to = requested_year_to
                status = requested_status

                if source == AWARD_SOURCE_ANY:
                    categories = resolve_source_categories(
                        current_source,
                        requested_category,
                        source_options,
                    )
                else:
                    categories = [requested_category]

                if preset in {
                    AWARD_PRESET_LATEST_WINNERS,
                    AWARD_PRESET_LATEST_NOMINEES,
                }:
                    latest_year = (
                        await adapter.async_latest_award_year(
                            media_type
                        )
                    )
                    year_from = latest_year
                    year_to = latest_year
                    categories = ["all"]
                    status = (
                        AWARD_STATUS_WINNER
                        if preset == AWARD_PRESET_LATEST_WINNERS
                        else AWARD_STATUS_ANY
                    )
                elif preset in {
                    AWARD_PRESET_BEST_PICTURE_WINNERS,
                    AWARD_PRESET_BEST_PICTURE_NOMINEES,
                }:
                    categories = resolve_source_categories(
                        current_source,
                        "best_film",
                        source_options,
                    )
                    status = (
                        AWARD_STATUS_WINNER
                        if preset
                        == AWARD_PRESET_BEST_PICTURE_WINNERS
                        else AWARD_STATUS_ANY
                    )

                if not categories:
                    continue

                raw_titles: list[dict[str, Any]] = []
                for category in categories:
                    raw_titles.extend(
                        await adapter.async_filter_titles(
                            media_type=media_type,
                            year_from=year_from,
                            year_to=year_to,
                            category=category,
                            status=AWARD_STATUS_ANY,
                        )
                    )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Award adapter %s failed for profile %s: %s",
                    current_source,
                    profile.get("id", profile.get("name", "unknown")),
                    err,
                )
                continue

            # Merge repeated title records from mapped categories within one
            # organization before applying category-scoped status semantics.
            merged: dict[str, dict[str, Any]] = {}
            for item in raw_titles:
                key = str(
                    item.get("tmdb_id")
                    or item.get("imdb_id")
                    or item.get("stable_key")
                    or (
                        f'{item.get("title", "").casefold()}:'
                        f'{item.get("release_year", "")}'
                    )
                )
                if key not in merged:
                    merged[key] = dict(item)
                    merged[key]["award_years"] = list(
                        item.get("award_years", [])
                    )
                    merged[key]["categories"] = list(
                        item.get("categories", [])
                    )
                    merged[key]["winning_categories"] = list(
                        item.get("winning_categories", [])
                    )
                    merged[key]["recipients"] = list(
                        item.get("recipients", [])
                    )
                    merged[key]["person_wins"] = list(
                        item.get("person_wins", [])
                    )
                    continue

                existing = merged[key]
                for field in (
                    "award_years",
                    "categories",
                    "winning_categories",
                    "recipients",
                ):
                    existing[field] = sorted(
                        set(existing.get(field, []))
                        | set(item.get(field, []))
                    )
                existing["person_wins"] = _merge_person_wins(
                    existing.get("person_wins", []),
                    item.get("person_wins", []),
                )
                existing["nominations"] = (
                    int(existing.get("nominations", 0))
                    + int(item.get("nominations", 0))
                )
                existing["wins"] = (
                    int(existing.get("wins", 0))
                    + int(item.get("wins", 0))
                )

            selected_categories = {
                category.casefold()
                for category in categories
                if category.casefold() != "all"
            }

            def status_matches(
                item: dict[str, Any],
                expected_status: str,
            ) -> bool:
                nominations = int(item.get("nominations", 0))
                wins = int(item.get("wins", 0))
                item_categories = {
                    str(category).casefold()
                    for category in item.get("categories", [])
                }
                winning_categories = {
                    str(category).casefold()
                    for category in item.get(
                        "winning_categories", []
                    )
                }
                if selected_categories:
                    nominated_in_scope = bool(
                        item_categories & selected_categories
                    )
                    won_in_scope = bool(
                        winning_categories & selected_categories
                    )
                else:
                    nominated_in_scope = nominations >= 1
                    won_in_scope = wins >= 1

                if expected_status == AWARD_STATUS_WINNER:
                    return won_in_scope
                if expected_status == AWARD_STATUS_NOMINATED_NO_WIN:
                    return nominated_in_scope and not won_in_scope
                if expected_status == AWARD_STATUS_NOMINATED_AND_WON:
                    return nominated_in_scope and won_in_scope
                return nominated_in_scope

            source_status = (
                AWARD_STATUS_ANY
                if source == AWARD_SOURCE_ANY
                else status
            )
            selected_titles = []
            for item in merged.values():
                if not status_matches(item, source_status):
                    continue
                selected = dict(item)
                selected["_award_source"] = current_source
                selected_titles.append(selected)
            titles_by_source[current_source] = selected_titles

        # Interleave organizations by source rank so a small Any-award queue
        # cannot be filled entirely by whichever adapter is registered first.
        award_titles: list[dict[str, Any]] = []
        max_source_titles = max(
            (len(items) for items in titles_by_source.values()),
            default=0,
        )
        for index in range(max_source_titles):
            for current_source in source_ids:
                source_titles = titles_by_source.get(current_source, [])
                if index < len(source_titles):
                    award_titles.append(source_titles[index])

        # Resolve progressively until enough candidates survive the profile
        # filters. Unlike the old fixed pre-filter cap, rejected early titles
        # cause later historical candidates to be considered. Small batches
        # avoid creating a TMDB request spike for broad award histories.
        batch_size = max(
            1,
            resolution_batch_size,
            len(source_ids) if source == AWARD_SOURCE_ANY else 1,
        )

        def any_status_matches(item: dict[str, Any]) -> bool:
            awards = item.get("_awards_by_source", {}).values()
            nominations = sum(
                int(award.get("nominations", 0))
                for award in awards
            )
            wins = sum(
                int(award.get("wins", 0))
                for award in awards
            )
            if aggregate_status == AWARD_STATUS_WINNER:
                return wins >= 1
            if aggregate_status == AWARD_STATUS_NOMINATED_NO_WIN:
                return nominations >= 1 and wins == 0
            if aggregate_status == AWARD_STATUS_NOMINATED_AND_WON:
                return nominations >= 1 and wins >= 1
            return nominations >= 1

        deduplicated: dict[int, dict[str, Any]] = {}
        for offset in range(0, len(award_titles), batch_size):
            batch = award_titles[offset : offset + batch_size]
            batch_results = await asyncio.gather(
                *(
                    self._resolve_award_title(
                        item,
                        media_type=media_type,
                        award_source=str(item["_award_source"]),
                    )
                    for item in batch
                ),
                return_exceptions=True,
            )
            resolved_batch: list[dict[str, Any]] = []
            for award_item, resolved in zip(
                batch,
                batch_results,
                strict=True,
            ):
                if isinstance(resolved, asyncio.CancelledError):
                    raise resolved
                if isinstance(resolved, BaseException):
                    _LOGGER.warning(
                        "Could not resolve award title from %s: %s",
                        award_item.get("_award_source"),
                        resolved,
                    )
                    continue
                if resolved is not None:
                    resolved_batch.append(resolved)

            # Different source title spellings may still resolve to one TMDB
            # ID. Keep one queue item and preserve category/year metadata.
            for item in resolved_batch:
                tmdb_id = int(item["id"])
                existing = deduplicated.get(tmdb_id)
                item_award = dict(item.get("award", {}))
                item_source = str(item_award.get("source", "unknown"))
                if existing is None:
                    item["_awards_by_source"] = {
                        item_source: item_award
                    }
                    deduplicated[tmdb_id] = item
                    continue

                awards_by_source = existing["_awards_by_source"]
                existing_award = awards_by_source.get(item_source)
                if existing_award is None:
                    awards_by_source[item_source] = item_award
                    if item_source == "hong_kong_film_awards":
                        for field in ("directors", "writers", "cast"):
                            if item.get(field):
                                existing[field] = list(item[field])
                    continue

                for field in (
                    "award_years",
                    "categories",
                    "winning_categories",
                    "recipients",
                ):
                    existing_award[field] = sorted(
                        set(existing_award.get(field, []))
                        | set(item_award.get(field, []))
                    )
                existing_award["person_wins"] = _merge_person_wins(
                    existing_award.get("person_wins", []),
                    item_award.get("person_wins", []),
                )
                existing_award["nominations"] = max(
                    int(existing_award.get("nominations", 0)),
                    int(item_award.get("nominations", 0)),
                )
                existing_award["wins"] = max(
                    int(existing_award.get("wins", 0)),
                    int(item_award.get("wins", 0)),
                )

            status_filtered = [
                item
                for item in deduplicated.values()
                if source != AWARD_SOURCE_ANY
                or any_status_matches(item)
            ]
            surviving = self._profile_post_filter(
                status_filtered,
                profile,
                media_type,
                excluded_ids=excluded_ids,
            )
            exhaustive_any_no_win = (
                source == AWARD_SOURCE_ANY
                and aggregate_status == AWARD_STATUS_NOMINATED_NO_WIN
            )
            if (
                not exhaustive_any_no_win
                and len(surviving) >= target_limit
            ):
                break

        result = [
            item
            for item in deduplicated.values()
            if source != AWARD_SOURCE_ANY
            or any_status_matches(item)
        ]
        for item in result:
            awards_by_source = item.pop("_awards_by_source")
            awards = [
                awards_by_source[key]
                for key in sorted(awards_by_source)
            ]
            if source != AWARD_SOURCE_ANY:
                item["award"] = awards[0]
                continue

            item["awards"] = awards
            item["award"] = {
                "organization": "Multiple award organizations",
                "source": AWARD_SOURCE_ANY,
                "sources": [award["source"] for award in awards],
                "award_years": sorted(
                    {
                        year
                        for award in awards
                        for year in award.get("award_years", [])
                    }
                ),
                "nominations": sum(
                    int(award.get("nominations", 0))
                    for award in awards
                ),
                "wins": sum(
                    int(award.get("wins", 0))
                    for award in awards
                ),
                "categories": sorted(
                    {
                        category
                        for award in awards
                        for category in award.get("categories", [])
                    }
                ),
                "winning_categories": sorted(
                    {
                        category
                        for award in awards
                        for category in award.get(
                            "winning_categories", []
                        )
                    }
                ),
                "recipients": sorted(
                    {
                        recipient
                        for award in awards
                        for recipient in award.get("recipients", [])
                    }
                ),
                "person_wins": _merge_person_wins(
                    *[
                        list(award.get("person_wins", []))
                        for award in awards
                    ]
                ),
            }

        return result

    def _profile_release_year_from(
        self,
        profile: dict[str, Any],
    ) -> int | None:
        """Resolve absolute and rolling release-year constraints."""
        year_from = self._parse_optional_year(
            profile.get("release_year_from")
            or profile.get("release_date_gte")
        )
        max_age = self._parse_optional_int(
            profile.get("release_max_age_years")
        )
        if max_age is not None and max_age >= 0:
            rolling_from = dt_util.now().year - max_age
            year_from = max(year_from or rolling_from, rolling_from)
        return year_from

    def _profile_release_date_gte(
        self,
        profile: dict[str, Any],
    ) -> str | None:
        """Translate a profile lower year bound to TMDB date format."""
        year = self._profile_release_year_from(profile)
        return f"{year:04d}-01-01" if year is not None else None

    def _profile_release_date_lte(
        self,
        profile: dict[str, Any],
    ) -> str | None:
        """Translate a profile upper year bound to TMDB date format."""
        year = self._profile_release_year_to(profile)
        return f"{year:04d}-12-31" if year is not None else None

    def _profile_release_year_to(
        self,
        profile: dict[str, Any],
    ) -> int | None:
        """Resolve the upper release year, including legacy profiles."""
        return self._parse_optional_year(
            profile.get("release_year_to")
            or profile.get("release_date_lte")
        )

    async def _person_profile_candidates(
        self,
        profile: dict[str, Any],
        media_type: str,
        excluded_ids: set[int],
        limit: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Resolve and enrich one person's deduplicated TMDB credits."""
        person_id = int(profile.get("person_id") or 0)
        if person_id <= 0:
            raise ValueError("Person profile is missing a TMDB person ID")
        credits = await self.api.get_person_combined_credits(
            person_id,
            self.language,
        )
        merged: dict[int, dict[str, Any]] = {}
        for group, role_field in (("cast", "character"), ("crew", "job")):
            for credit in credits.get(group) or []:
                if not isinstance(credit, dict):
                    continue
                if str(credit.get("media_type") or "") != media_type:
                    continue
                if credit.get("id") is None:
                    continue
                tmdb_id = int(credit["id"])
                item = merged.setdefault(tmdb_id, dict(credit))
                roles = item.setdefault("person_roles", [])
                role = str(credit.get(role_field) or "").strip()
                if role and role not in roles:
                    roles.append(role)

        source_count = len(merged)
        eligible = [
            item
            for item in merged.values()
            if int(item["id"]) not in excluded_ids
            and not self.store.is_dismissed(media_type, int(item["id"]))
            and not (
                bool(profile.get("exclude_watched", True))
                and self.store.is_watched(media_type, int(item["id"]))
            )
        ]
        eligible.sort(
            key=lambda item: float(item.get("popularity") or 0),
            reverse=True,
        )
        eligible_count = len(eligible)
        eligible = eligible[: max(80, min(400, limit * 4))]
        enriched = await asyncio.gather(
            *(
                self._enrich_movie(item)
                if media_type == "movie"
                else self._enrich_tv_discovery(item)
                for item in eligible
            )
        )
        for item in enriched:
            raw = merged.get(int(item["id"]), {})
            item["person"] = {
                "id": person_id,
                "name": profile.get("person_name"),
                "roles": list(raw.get("person_roles", [])),
            }
        return list(enriched), source_count, eligible_count

    async def _build_discovery_profiles(
        self,
        *,
        selected_ids: list[int],
        movie_provider_ids: list[int],
        tv_provider_ids: list[int],
        watchlist_ids: set[int],
        watchlist_tv_ids: set[int],
        personalized_movies: list[dict[str, Any]],
        personalized_tv: list[dict[str, Any]],
        oscar_movies: list[dict[str, Any]],
        profiles: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Build all configured discovery queues."""
        output: dict[str, dict[str, Any]] = {}

        for profile in (
            self.discovery_profiles if profiles is None else profiles
        ):
            profile_id = str(profile["id"])
            name = str(profile["name"])
            media_type = str(profile.get("media_type", "movie")).lower()
            if media_type not in {"movie", "tv"}:
                media_type = "movie"

            source = str(
                profile.get("source", PROFILE_SOURCE_DISCOVER)
            ).lower()
            award = str(
                profile.get("award_filter", PROFILE_AWARD_NONE)
            ).lower()
            provider_scope = str(
                profile.get("provider_scope", "all")
            ).lower()
            exclude_watched = bool(profile.get("exclude_watched", True))
            provider_ids = (
                selected_ids
                if provider_scope == "my"
                else (
                    movie_provider_ids
                    if media_type == "movie"
                    else tv_provider_ids
                )
            )

            limit = max(1, min(200, int(profile.get("limit", 30) or 30)))
            max_pages = max(
                1, min(20, int(profile.get("max_pages", 5) or 5))
            )
            min_rating = float(profile.get("min_rating", 0) or 0)
            min_votes = int(profile.get("min_votes", 0) or 0)
            include_genres = self._parse_genre_ids(
                profile.get("include_genres", "")
            )
            exclude_genres = self._parse_genre_ids(
                profile.get("exclude_genres", "")
            )
            genre_match = str(profile.get("genre_match", "any")).lower()
            if genre_match not in {"any", "all"}:
                genre_match = "any"

            items: list[dict[str, Any]]
            source_candidate_count = 0
            eligible_candidate_count = 0

            award_source = str(
                profile.get("award_source", AWARD_SOURCE_NONE)
            ).lower()

            # Historical award membership becomes the candidate set before
            # genre/rating/provider/date post-filters are applied.
            if award_source != AWARD_SOURCE_NONE:
                items = await self._award_profile_candidates(
                    profile,
                    target_limit=limit,
                    resolution_batch_size=4,
                    excluded_ids=(
                        watchlist_ids
                        if media_type == "movie"
                        else watchlist_tv_ids
                    ),
                )
                source_candidate_count = len(items)
                eligible_candidate_count = len(items)
            elif (
                award == PROFILE_AWARD_OSCARS_BEST_PICTURE_2026
                and media_type == "movie"
            ):
                # Backward compatibility with v0.13 profiles.
                items = [dict(item) for item in oscar_movies]
                source_candidate_count = len(items)
                eligible_candidate_count = len(items)
            elif source == PROFILE_SOURCE_PERSONALIZED:
                items = [
                    dict(item)
                    for item in (
                        personalized_movies
                        if media_type == "movie"
                        else personalized_tv
                    )
                ]
                source_candidate_count = len(items)
                eligible_candidate_count = len(items)
            elif source == PROFILE_SOURCE_PERSON:
                items, source_candidate_count, eligible_candidate_count = (
                    await self._person_profile_candidates(
                        profile,
                        media_type,
                        (
                            watchlist_ids
                            if media_type == "movie"
                            else watchlist_tv_ids
                        ),
                        limit,
                    )
                )
            else:
                if media_type == "movie":
                    raw = await self.api.discover_movies(
                        region=self.region,
                        language=self.language,
                        provider_ids=provider_ids,
                        min_rating=min_rating,
                        min_votes=min_votes,
                        include_genres=include_genres,
                        exclude_genres=exclude_genres,
                        genre_match=genre_match,
                        release_date_gte=self._profile_release_date_gte(
                            profile
                        ),
                        release_date_lte=self._profile_release_date_lte(
                            profile
                        ),
                        sort_by=str(
                            profile.get("sort_by", "popularity.desc")
                        ),
                        max_pages=max_pages,
                    )
                    source_candidate_count = len(raw)
                    exclude_ids = set(watchlist_ids)
                    if exclude_watched:
                        exclude_ids.update(self.store.watched_movies)
                    raw = [
                        item
                        for item in raw
                        if int(item["id"]) not in exclude_ids
                        and not self.store.is_dismissed(
                            "movie", int(item["id"])
                        )
                    ]
                    eligible_candidate_count = len(raw)
                    raw = raw[: max(limit * 2, limit)]
                    items = list(
                        await asyncio.gather(
                            *(self._enrich_movie(item) for item in raw)
                        )
                    )
                else:
                    raw = await self.api.discover_tv(
                        region=self.region,
                        language=self.language,
                        provider_ids=provider_ids,
                        min_rating=min_rating,
                        min_votes=min_votes,
                        include_genres=include_genres,
                        exclude_genres=exclude_genres,
                        genre_match=genre_match,
                        release_date_gte=self._profile_release_date_gte(
                            profile
                        ),
                        release_date_lte=self._profile_release_date_lte(
                            profile
                        ),
                        sort_by=str(
                            profile.get("sort_by", "popularity.desc")
                        ),
                        max_pages=max_pages,
                    )
                    source_candidate_count = len(raw)
                    exclude_ids = set(watchlist_tv_ids)
                    if exclude_watched:
                        exclude_ids.update(self.store.watched_tv)
                    raw = [
                        item
                        for item in raw
                        if int(item["id"]) not in exclude_ids
                        and not self.store.is_dismissed(
                            "tv", int(item["id"])
                        )
                    ]
                    eligible_candidate_count = len(raw)
                    raw = raw[: max(limit * 2, limit)]
                    items = list(
                        await asyncio.gather(
                            *(
                                self._enrich_tv_discovery(item)
                                for item in raw
                            )
                        )
                    )

            if source == PROFILE_SOURCE_PERSON and provider_scope == "all":
                items = [item for item in items if item.get("providers")]

            filtered_items = self._profile_post_filter(
                items,
                profile,
                media_type,
                excluded_ids=(
                    watchlist_ids
                    if media_type == "movie"
                    else watchlist_tv_ids
                ),
            )
            post_filter_count = len(filtered_items)
            items = filtered_items[:limit]

            for item in items:
                award_summary = self._award_summary(item)
                if award_summary is not None:
                    item["award_summary"] = award_summary

            output[profile_id] = {
                "id": profile_id,
                "name": name,
                "media_type": media_type,
                "source": source,
                "award_filter": award,
                "config": dict(profile),
                "items": items,
                "diagnostics": {
                    "requested_limit": limit,
                    "source_candidates": source_candidate_count,
                    "eligible_candidates": eligible_candidate_count,
                    "post_filter_candidates": post_filter_count,
                    "final_count": len(items),
                    "shortfall": max(0, limit - len(items)),
                },
            }

        return output

    def _schedule_discovery_profile_updates(
        self,
        *,
        selected_ids: list[int],
        movie_provider_ids: list[int],
        tv_provider_ids: list[int],
        watchlist_ids: set[int],
        watchlist_tv_ids: set[int],
    ) -> None:
        """Update each discovery profile independently in the background."""
        if not hasattr(self, "_profile_diagnostics"):
            self._profile_diagnostics = {}
        profiles = self.discovery_profiles
        configured_ids = {str(profile["id"]) for profile in profiles}
        for profile_id in set(self._discovery_profile_results) - configured_ids:
            self._discovery_profile_results.pop(profile_id, None)
            self._discovery_profile_last_scheduled.pop(profile_id, None)
            self._profile_diagnostics.pop(profile_id, None)
        for profile_id in set(self._discovery_profile_tasks) - configured_ids:
            task = self._discovery_profile_tasks.pop(profile_id)
            if not task.done():
                task.cancel()

        now = asyncio.get_running_loop().time()
        for profile in profiles:
            profile_id = str(profile["id"])
            task = self._discovery_profile_tasks.get(profile_id)
            if task is not None and not task.done():
                continue
            if (
                now
                - self._discovery_profile_last_scheduled.get(
                    profile_id, 0.0
                )
                < 60.0
            ):
                continue
            self._discovery_profile_last_scheduled[profile_id] = now
            previous = self._profile_diagnostics.get(profile_id, {})
            self._profile_diagnostics[profile_id] = {
                **previous,
                "id": profile_id,
                "name": str(profile.get("name") or profile_id),
                "media_type": str(profile.get("media_type") or "movie"),
                "source": str(
                    profile.get("source") or PROFILE_SOURCE_DISCOVER
                ),
                "status": "scheduled",
                "error": None,
            }
            self._discovery_profile_tasks[profile_id] = (
                self.hass.async_create_background_task(
                    self._async_build_and_publish_discovery_profile(
                        dict(profile),
                        selected_ids=selected_ids,
                        movie_provider_ids=movie_provider_ids,
                        tv_provider_ids=tv_provider_ids,
                        watchlist_ids=watchlist_ids,
                        watchlist_tv_ids=watchlist_tv_ids,
                    ),
                    f"media_watch_discovery_{profile_id}",
                )
            )

    async def _async_build_and_publish_discovery_profile(
        self,
        profile: dict[str, Any],
        *,
        selected_ids: list[int],
        movie_provider_ids: list[int],
        tv_provider_ids: list[int],
        watchlist_ids: set[int],
        watchlist_tv_ids: set[int],
    ) -> None:
        """Build one profile and publish it without delaying other feeds."""
        profile_id = str(profile["id"])
        media_type = str(profile.get("media_type", "movie")).lower()
        source = str(
            profile.get("source", PROFILE_SOURCE_DISCOVER)
        ).lower()
        candidate_limit = max(
            50,
            min(800, int(profile.get("limit", 30) or 30) * 4),
        )
        personalized_movies: list[dict[str, Any]] = []
        personalized_tv: list[dict[str, Any]] = []
        oscar_movies: list[dict[str, Any]] = []
        if not hasattr(self, "_profile_diagnostics"):
            self._profile_diagnostics = {}
        started = asyncio.get_running_loop().time()
        attempted_at = dt_util.now().isoformat()
        previous_diagnostics = self._profile_diagnostics.get(profile_id, {})
        self._profile_diagnostics[profile_id] = {
            **previous_diagnostics,
            "id": profile_id,
            "name": str(profile.get("name") or profile_id),
            "media_type": media_type,
            "source": source,
            "status": "updating",
            "last_attempt": attempted_at,
            "error": None,
        }

        try:
            if source == PROFILE_SOURCE_PERSONALIZED:
                if media_type == "tv":
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
                        limit=candidate_limit,
                    )
                else:
                    personalized_movies = (
                        await self._personalized_recommendations(
                            media_type="movie",
                            seed_ids=[
                                *self.store.watched_movies,
                                *watchlist_ids,
                            ],
                            exclude_ids={
                                *self.store.watched_movies,
                                *watchlist_ids,
                            },
                            limit=candidate_limit,
                        )
                    )

            if (
                str(
                    profile.get("award_filter", PROFILE_AWARD_NONE)
                ).lower()
                == PROFILE_AWARD_OSCARS_BEST_PICTURE_2026
                and media_type == "movie"
            ):
                oscar_movies = await self._resolve_oscar_best_picture()
                oscar_movies = [
                    movie
                    for movie in oscar_movies
                    if int(movie["id"]) not in watchlist_ids
                    and not self.store.is_dismissed(
                        "movie", int(movie["id"])
                    )
                ]

            output = await self._build_discovery_profiles(
                selected_ids=selected_ids,
                movie_provider_ids=movie_provider_ids,
                tv_provider_ids=tv_provider_ids,
                watchlist_ids=watchlist_ids,
                watchlist_tv_ids=watchlist_tv_ids,
                personalized_movies=personalized_movies,
                personalized_tv=personalized_tv,
                oscar_movies=oscar_movies,
                profiles=[profile],
            )
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self._profile_diagnostics[profile_id] = {
                **self._profile_diagnostics[profile_id],
                "status": "error",
                "duration_ms": round(
                    (asyncio.get_running_loop().time() - started) * 1000
                ),
                "error": f"{type(err).__name__}: {err}",
            }
            _LOGGER.warning(
                "Discovery profile %s failed without affecting other feeds: %s",
                profile.get("name", profile_id),
                err,
            )
            if isinstance(getattr(self, "data", None), dict):
                self.async_update_listeners()
            return

        feed = output.get(profile_id)
        if feed is None:
            return
        self._profile_diagnostics[profile_id] = {
            **self._profile_diagnostics[profile_id],
            **dict(feed.get("diagnostics", {})),
            "status": "ready",
            "last_success": dt_util.now().isoformat(),
            "duration_ms": round(
                (asyncio.get_running_loop().time() - started) * 1000
            ),
            "error": None,
        }
        self._discovery_profile_results[profile_id] = feed
        current_data = getattr(self, "data", None)
        if isinstance(current_data, dict):
            current_data.setdefault("discovery_profiles", {})[
                profile_id
            ] = feed
            self.async_update_listeners()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            self._last_core_error = None
            defer_discovery = self._defer_discovery_profiles
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

            movie_details = await asyncio.gather(
                *(self._enrich_movie(movie) for movie in visible_watchlist)
            )
            tv_details = await asyncio.gather(
                *(self._enrich_tv(show) for show in watchlist_tv)
            )
            release_updates = await self._async_track_watchlist_releases(
                list(movie_details)
            )

            tv_provider_ids = sorted(
                {
                    int(provider["provider_id"])
                    for provider in tv_providers
                    if provider.get("provider_id") is not None
                }
            )
            if not defer_discovery:
                self._schedule_discovery_profile_updates(
                    selected_ids=selected_ids,
                    movie_provider_ids=sorted(provider_catalog),
                    tv_provider_ids=tv_provider_ids,
                    watchlist_ids=watchlist_ids,
                    watchlist_tv_ids=watchlist_tv_ids,
                )
            # Keep the authoritative mapping by reference. A very fast
            # background profile can finish while this refresh is returning;
            # sharing the mapping prevents the returned coordinator payload
            # from overwriting that newly published feed with a stale copy.
            discovery_profiles = self._discovery_profile_results
            oscar_movies: list[dict[str, Any]] = []

            # External award sites must never hold up entity registration.
            # This schedules an uncached watchlist index in the background;
            # cached facts are applied synchronously on later refreshes.
            if not defer_discovery:
                await self._async_enrich_watchlist_awards(movie_details)

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

            result = {
                "movie_watchlist": movie_details,
                "following_tv": tv_details,
                "upcoming_episodes_all": global_upcoming,
                "upcoming_episodes_next": global_next_episodes[
                    : self.upcoming_limit
                ],
                "episodes_today": episodes_today,
                "episodes_next_7_days": episodes_next_7_days,
                "episodes_next_30_days": episodes_next_30_days,
                "oscar_movies": oscar_movies,
                "discovery_profiles": discovery_profiles,
                "selected_providers": selected_providers,
                "provider_ids": selected_ids,
                "watched_movies": self.store.watched_movies,
                "dismissed_movies": self.store.dismissed_movies,
                "release_updates": release_updates,
            }
            self._last_core_success = dt_util.now().isoformat()
            self._defer_discovery_profiles = False
            return result

        except TMDBError as err:
            self._last_core_error = str(err)
            raise UpdateFailed(
                f"Error communicating with TMDB: {err}"
            ) from err
        except Exception as err:  # noqa: BLE001
            self._last_core_error = f"{type(err).__name__}: {err}"
            raise
