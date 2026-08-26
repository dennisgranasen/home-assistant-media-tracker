"""Sensors for Media Watch."""

from __future__ import annotations

from homeassistant.util import slugify

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MediaWatchCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MediaWatchCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities(
        [
            MovieWatchlistSensor(coordinator, entry),
            FollowingTVSensor(coordinator, entry),
            UpcomingEpisodesSensor(coordinator, entry),
            NextEpisodesToWatchSensor(coordinator, entry),
            NextUpcomingEpisodesSensor(coordinator, entry),
            EpisodesTodaySensor(coordinator, entry),
            EpisodesNext7DaysSensor(coordinator, entry),
            EpisodesNext30DaysSensor(coordinator, entry),
            EpisodesFeedSensor(coordinator, entry),
            MovieWatchlistFeedSensor(coordinator, entry),
            QueueDiagnosticsSensor(coordinator, entry),
            ReleaseUpdatesSensor(coordinator, entry),
            UpcomingMediaCardSensor(coordinator, entry),
        ]
    )

    profiles = entry.options.get("discovery_profiles", [])
    async_add_entities(
        [
            DiscoveryProfileFeedSensor(coordinator, entry, profile)
            for profile in profiles
            if isinstance(profile, dict)
            and profile.get("id")
            and profile.get("name")
        ]
    )


class MediaWatchSensor(
    CoordinatorEntity[MediaWatchCoordinator], SensorEntity
):
    """Base Media Watch sensor."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MediaWatchCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Media Watch",
            manufacturer="Media Watch",
            model="TMDB",
        )


class MovieWatchlistSensor(MediaWatchSensor):
    _attr_name = "Movie watchlist"
    _attr_icon = "mdi:movie-open"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_movie_watchlist"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("movie_watchlist", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"movies": self.coordinator.data.get("movie_watchlist", [])}


class FollowingTVSensor(MediaWatchSensor):
    _attr_name = "Following TV"
    _attr_icon = "mdi:television-classic"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_following_tv"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("following_tv", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"shows": self.coordinator.data.get("following_tv", [])}


class QueueDiagnosticsSensor(MediaWatchSensor):
    """Summarize core, profile, and award queue health."""

    _attr_name = "Queue diagnostics"
    _attr_icon = "mdi:list-status"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_queue_diagnostics"

    @property
    def native_value(self) -> str:
        return str(self.coordinator.queue_diagnostics["status"])

    @property
    def available(self) -> bool:
        """Keep diagnostics readable when the main coordinator fails."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.coordinator.queue_diagnostics


class ReleaseUpdatesSensor(MediaWatchSensor):
    """Expose changes emitted during the most recent Watchlist refresh."""

    _attr_name = "Release updates"
    _attr_icon = "mdi:movie-check-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_release_updates"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("release_updates", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "event_type": "media_watch_release_update",
            "updates": self.coordinator.data.get("release_updates", []),
        }


class UpcomingEpisodesSensor(MediaWatchSensor):
    _attr_name = "Upcoming episodes"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_upcoming_episodes"

    @property
    def _episodes(self) -> list[dict[str, Any]]:
        episodes = []
        for show in self.coordinator.data.get("following_tv", []):
            episode = show.get("next_episode")
            if episode:
                episodes.append(
                    {
                        "tmdb_id": show["id"],
                        "show": show["name"],
                        "poster_path": show.get("poster_path"),
                        "providers": show.get("providers", []),
                        **episode,
                    }
                )
        return sorted(
            episodes, key=lambda item: item.get("air_date") or "9999-12-31"
        )

    @property
    def native_value(self) -> int:
        return len(self._episodes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"episodes": self._episodes}



class NextEpisodesToWatchSensor(MediaWatchSensor):
    """Next unwatched episode for each followed show."""

    _attr_name = "Next episodes to watch"
    _attr_icon = "mdi:play-box-multiple-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.entry_id}_next_episodes_to_watch"
        )

    @property
    def _episodes(self) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []

        for show in self.coordinator.data.get(
            "following_tv", []
        ):
            episode = show.get("next_episode_to_watch")
            if not episode:
                continue

            episodes.append(
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

        return episodes

    @property
    def native_value(self) -> int:
        return len(self._episodes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"episodes": self._episodes}



class _EpisodeReleaseListSensor(MediaWatchSensor):
    """Base sensor for global episode release lists."""

    data_key: str = ""

    @property
    def _episodes(self) -> list[dict[str, Any]]:
        return list(self.coordinator.data.get(self.data_key, []))

    @property
    def native_value(self) -> int:
        return len(self._episodes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"episodes": self._episodes}


class NextUpcomingEpisodesSensor(_EpisodeReleaseListSensor):
    _attr_name = "Next upcoming episodes"
    _attr_icon = "mdi:calendar-arrow-right"
    data_key = "upcoming_episodes_next"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.entry_id}_next_upcoming_episodes"
        )


class EpisodesTodaySensor(_EpisodeReleaseListSensor):
    _attr_name = "Episodes today"
    _attr_icon = "mdi:calendar-today"
    data_key = "episodes_today"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_episodes_today"


class EpisodesNext7DaysSensor(_EpisodeReleaseListSensor):
    _attr_name = "Episodes next 7 days"
    _attr_icon = "mdi:calendar-week"
    data_key = "episodes_next_7_days"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.entry_id}_episodes_next_7_days"
        )


class EpisodesNext30DaysSensor(_EpisodeReleaseListSensor):
    _attr_name = "Episodes next 30 days"
    _attr_icon = "mdi:calendar-month"
    data_key = "episodes_next_30_days"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.entry_id}_episodes_next_30_days"
        )





class _MediaTrackerFeedSensor(MediaWatchSensor):
    """Base class for Media Tracker Card feed sensors."""

    _attr_icon = "mdi:play-box-multiple-outline"

    @property
    def native_value(self) -> int:
        return len(self._items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # All companion-card feeds intentionally use the same single
        # payload attribute.
        return {"items": self._items}


class EpisodesFeedSensor(_MediaTrackerFeedSensor):
    """One next-to-watch episode per followed TV show."""

    _attr_name = "Episodes"
    _attr_icon = "mdi:play-box-multiple-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_episodes"

    @property
    def _items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        for show in self.coordinator.data.get("following_tv", []):
            episode = show.get("next_episode_to_watch")
            if not episode:
                continue

            items.append(
                {
                    "media_type": "tv",
                    "source": "episodes",
                    "tmdb_id": show["id"],
                    "title": show["name"],
                    "original_title": show.get("original_name"),
                    "poster": (
                        f"https://image.tmdb.org/t/p/w500{show['poster_path']}"
                        if show.get("poster_path")
                        else None
                    ),
                    "season": episode.get("season"),
                    "episode_number": episode.get("episode"),
                    "number": episode.get("code"),
                    "episode": episode.get("name"),
                    "airdate": episode.get("air_date"),
                    "runtime": episode.get("runtime"),
                    "overview": episode.get("overview") or "",
                    "provider": ", ".join(
                        show.get("my_providers")
                        or show.get("providers")
                        or []
                    ),
                    "provider_details": (
                        show.get("my_provider_details")
                        or show.get("provider_details")
                        or []
                    ),
                    "available_on_my_services": show.get(
                        "available_on_my_services", False
                    ),
                    "deep_link": (
                        "https://www.themoviedb.org/tv/"
                        f"{show['id']}"
                    ),
                }
            )

        # Aired backlog first. Within each group sort by air date.
        # Missing dates are last.
        from datetime import date
        today = date.today().isoformat()

        def sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
            airdate = item.get("airdate")
            if not airdate:
                return (2, "9999-12-31", item.get("title") or "")
            return (
                0 if airdate <= today else 1,
                airdate,
                item.get("title") or "",
            )

        return sorted(items, key=sort_key)


class MovieWatchlistFeedSensor(_MediaTrackerFeedSensor):
    """Movie watchlist feed for the companion card."""

    _attr_name = "Watchlist"
    _attr_icon = "mdi:bookmark-multiple-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_watchlist"

    @property
    def _items(self) -> list[dict[str, Any]]:
        return [
            self._movie_item(item)
            for item in self.coordinator.data.get("movie_watchlist", [])
        ]

    @staticmethod
    def _movie_item(item: dict[str, Any]) -> dict[str, Any]:
        providers = (
            item.get("my_providers")
            or item.get("providers")
            or []
        )
        return {
            "media_type": "movie",
            "source": "watchlist",
            "tmdb_id": item.get("id"),
            "title": item.get("title"),
            "fallback_title": item.get("fallback_title"),
            "original_title": item.get("original_title"),
            "imdb_id": item.get("imdb_id"),
            "original_language": item.get("original_language"),
            "release_date": item.get("release_date"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
            "overview": item.get("overview") or "",
            "tagline": item.get("tagline") or "",
            "runtime": item.get("runtime"),
            "production_countries": item.get(
                "production_countries", []
            ),
            "collection": item.get("collection"),
            "directors": item.get("directors", []),
            "writers": item.get("writers", []),
            "cast": item.get("cast", []),
            "genre_ids": item.get("genre_ids", []),
            "genres": item.get("genres", []),
            "poster": (
                f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
                if item.get("poster_path")
                else None
            ),
            "providers": providers,
            "provider": ", ".join(providers),
            "provider_details": (
                item.get("my_provider_details")
                or item.get("provider_details")
                or []
            ),
            "available_on_my_services": item.get(
                "available_on_my_services", False
            ),
            "award": item.get("award"),
            "awards": item.get("awards", []),
            "award_summary": item.get("award_summary"),
            "deep_link": (
                "https://www.themoviedb.org/movie/"
                f"{item.get('id')}"
            ),
        }


def _movie_feed_item(
    item: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    """Render an enriched movie for a generic profile feed."""
    providers = (
        item.get("my_providers")
        or item.get("providers")
        or []
    )
    return {
        "media_type": "movie",
        "source": source,
        "tmdb_id": item.get("id"),
        "title": item.get("title"),
        "fallback_title": item.get("fallback_title"),
        "original_title": item.get("original_title"),
        "imdb_id": item.get("imdb_id"),
        "original_language": item.get("original_language"),
        "release_date": item.get("release_date"),
        "vote_average": item.get("vote_average"),
        "vote_count": item.get("vote_count"),
        "overview": item.get("overview") or "",
        "tagline": item.get("tagline") or "",
        "runtime": item.get("runtime"),
        "production_countries": item.get(
            "production_countries", []
        ),
        "collection": item.get("collection"),
        "directors": item.get("directors", []),
        "writers": item.get("writers", []),
        "cast": item.get("cast", []),
        "poster": (
            f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
            if item.get("poster_path")
            else None
        ),
        "genre_ids": item.get("genre_ids", []),
        "genres": item.get("genres", []),
        "providers": providers,
        "provider": ", ".join(providers),
        "provider_details": (
            item.get("my_provider_details")
            or item.get("provider_details")
            or []
        ),
        "available_on_my_services": item.get(
            "available_on_my_services", False
        ),
        "watched": item.get("watched", False),
        "recommendation": item.get("recommendation"),
        "person": item.get("person"),
        "people": item.get("people", []),
        "source_profiles": item.get("source_profiles", []),
        "award": item.get("award"),
        "award_summary": item.get("award_summary"),
        "deep_link": (
            "https://www.themoviedb.org/movie/"
            f"{item.get('id')}"
        ),
    }


def _tv_feed_item(
    item: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    """Render an enriched TV show for a generic profile feed."""
    providers = (
        item.get("my_providers")
        or item.get("providers")
        or []
    )
    return {
        "media_type": "tv",
        "source": source,
        "tmdb_id": item.get("id"),
        "title": item.get("name"),
        "original_title": item.get("original_name"),
        "release_date": item.get("first_air_date"),
        "vote_average": item.get("vote_average"),
        "vote_count": item.get("vote_count"),
        "overview": item.get("overview") or "",
        "poster": (
            f"https://image.tmdb.org/t/p/w500{item['poster_path']}"
            if item.get("poster_path")
            else None
        ),
        "genre_ids": item.get("genre_ids", []),
        "genres": item.get("genres", []),
        "providers": providers,
        "provider": ", ".join(providers),
        "provider_details": (
            item.get("my_provider_details")
            or item.get("provider_details")
            or []
        ),
        "available_on_my_services": item.get(
            "available_on_my_services", False
        ),
        "recommendation": item.get("recommendation"),
        "person": item.get("person"),
        "people": item.get("people", []),
        "source_profiles": item.get("source_profiles", []),
        "deep_link": (
            "https://www.themoviedb.org/tv/"
            f"{item.get('id')}"
        ),
    }


class DiscoveryProfileFeedSensor(_MediaTrackerFeedSensor):
    """One dedicated Home Assistant entity per discovery profile."""

    _attr_icon = "mdi:movie-search-outline"

    def __init__(
        self,
        coordinator,
        entry,
        profile: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry)
        self._profile = dict(profile)
        profile_id = str(profile["id"])
        profile_name = str(profile["name"])

        self._attr_name = profile_name
        self._attr_unique_id = (
            f"{entry.entry_id}_discovery_profile_{profile_id}"
        )

        # Give HA a deterministic and card-friendly object-id suggestion while
        # still letting the entity registry handle collisions/renames safely.
        self._attr_suggested_object_id = (
            f"media_watch_{slugify(profile_id)}"
        )

    @property
    def _feed(self) -> dict[str, Any]:
        profile_id = str(self._profile["id"])
        return self.coordinator.data.get(
            "discovery_profiles", {}
        ).get(profile_id, {})

    @property
    def _items(self) -> list[dict[str, Any]]:
        profile_id = str(self._profile["id"])
        feed = self._feed
        media_type = str(
            feed.get(
                "media_type",
                self._profile.get("media_type", "movie"),
            )
        )
        raw_items = feed.get("items", [])

        items: list[dict[str, Any]] = []
        for item in raw_items:
            if media_type == "tv":
                rendered = _tv_feed_item(item, "profile")
            else:
                rendered = _movie_feed_item(item, "profile")

            rendered["profile"] = {
                "id": profile_id,
                "name": self._profile.get("name"),
                "source": self._profile.get("source", "discover"),
                "award_source": self._profile.get(
                    "award_source", "none"
                ),
            }
            if item.get("award"):
                rendered["award"] = item.get("award")
            if item.get("awards"):
                rendered["awards"] = item.get("awards")
            items.append(rendered)

        return items

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        feed = self._feed
        return {
            "items": self._items,
            "profile_id": self._profile.get("id"),
            "profile_name": self._profile.get("name"),
            "media_type": feed.get(
                "media_type",
                self._profile.get("media_type", "movie"),
            ),
            "source": feed.get(
                "source",
                self._profile.get("source", "discover"),
            ),
            "award_source": self._profile.get(
                "award_source", "none"
            ),
            "award_category": self._profile.get(
                "award_category", "all"
            ),
            "award_status": self._profile.get(
                "award_status", "any"
            ),
            "award_year_from": self._profile.get(
                "award_year_from", ""
            ),
            "award_year_to": self._profile.get(
                "award_year_to", ""
            ),
            "exclude_watched": self._profile.get(
                "exclude_watched", True
            ),
            "profile": dict(self._profile),
            "diagnostics": self.coordinator.profile_diagnostics(
                str(self._profile.get("id") or "")
            ),
        }


class UpcomingMediaCardSensor(MediaWatchSensor):
    """Compatibility and companion feed for Media Tracker Card.

    `data` remains compatible with the Upcoming Media Card style TV feed.
    Movie lists are exposed in dedicated attributes for Media Tracker Card.
    """

    _attr_name = "Upcoming Media Card"
    _attr_icon = "mdi:movie-open-clock"

    TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w500"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.entry_id}_upcoming_media_card"
        )

    @classmethod
    def _poster_url(cls, poster_path: str | None) -> str | None:
        if not poster_path:
            return None
        return f"{cls.TMDB_POSTER_BASE}{poster_path}"

    @staticmethod
    def _provider_names(item: dict[str, Any]) -> list[str]:
        return (
            item.get("my_providers")
            or item.get("providers")
            or []
        )

    @staticmethod
    def _provider_details(item: dict[str, Any]) -> list[dict[str, Any]]:
        return (
            item.get("my_provider_details")
            or item.get("provider_details")
            or []
        )

    @property
    def _episode_items(self) -> list[dict[str, Any]]:
        episodes = self.coordinator.data.get(
            "upcoming_episodes_next", []
        )

        data: list[dict[str, Any]] = [
            {
                "title_default": "$title",
                "line1_default": "$episode",
                "line2_default": "$release",
                "line3_default": "$provider",
                "line4_default": "",
                "icon": "mdi:television-classic",
            }
        ]

        for item in episodes:
            provider_names = self._provider_names(item)
            code = item.get("code") or ""
            episode_name = item.get("name") or ""
            episode_label = code
            if episode_name:
                episode_label = (
                    f"{code} · {episode_name}"
                    if code
                    else episode_name
                )

            data.append(
                {
                    "media_type": "tv",
                    "id": item.get("id"),
                    "tmdb_id": item.get("tmdb_id"),
                    "title": item.get("show"),
                    "season": item.get("season"),
                    "episode_number": item.get("episode"),
                    "episode": episode_label,
                    "number": code,
                    "airdate": item.get("air_date"),
                    "release": item.get("air_date"),
                    "runtime": item.get("runtime"),
                    "provider": ", ".join(provider_names),
                    "studio": ", ".join(provider_names),
                    "provider_details": self._provider_details(item),
                    "poster": self._poster_url(
                        item.get("poster_path")
                    ),
                    "fanart": None,
                    "flag": not item.get(
                        "available_on_my_services", False
                    ),
                    "summary": item.get("overview") or "",
                    "deep_link": (
                        "https://www.themoviedb.org/tv/"
                        f"{item.get('tmdb_id')}"
                    ),
                }
            )

        return data

    def _movie_item(
        self,
        item: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        provider_names = self._provider_names(item)

        return {
            "media_type": "movie",
            "source": source,
            "tmdb_id": item.get("id"),
            "title": item.get("title"),
            "fallback_title": item.get("fallback_title"),
            "original_title": item.get("original_title"),
            "imdb_id": item.get("imdb_id"),
            "original_language": item.get("original_language"),
            "release_date": item.get("release_date"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
            "overview": item.get("overview") or "",
            "tagline": item.get("tagline") or "",
            "runtime": item.get("runtime"),
            "production_countries": item.get(
                "production_countries", []
            ),
            "collection": item.get("collection"),
            "directors": item.get("directors", []),
            "writers": item.get("writers", []),
            "cast": item.get("cast", []),
            "poster": self._poster_url(
                item.get("poster_path")
            ),
            "providers": provider_names,
            "provider": ", ".join(provider_names),
            "provider_details": self._provider_details(item),
            "available_on_my_services": item.get(
                "available_on_my_services", False
            ),
            "award": item.get("award"),
            "awards": item.get("awards", []),
            "award_summary": item.get("award_summary"),
            "watched": item.get("watched", False),
            "dismissed": item.get("dismissed", False),
            "deep_link": (
                "https://www.themoviedb.org/movie/"
                f"{item.get('id')}"
            ),
        }

    @property
    def _watchlist_movies(self) -> list[dict[str, Any]]:
        return [
            self._movie_item(item, source="watchlist")
            for item in self.coordinator.data.get(
                "movie_watchlist", []
            )
        ]

    @property
    def _discovery_movies(self) -> list[dict[str, Any]]:
        return [
            self._movie_item(item, source="discovery")
            for item in self.coordinator.data.get(
                "discovered_movies", []
            )
        ]

    @property
    def native_value(self) -> int:
        # Keep state useful as a total media count for the companion card.
        return (
            max(0, len(self._episode_items) - 1)
            + len(self._watchlist_movies)
            + len(self._discovery_movies)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            # Backwards-compatible TV feed.
            "data": self._episode_items,
            # Native companion-card sections.
            "upcoming_episodes": self._episode_items[1:],
            "watchlist_movies": self._watchlist_movies,
            "discovery_movies": self._discovery_movies,
        }
