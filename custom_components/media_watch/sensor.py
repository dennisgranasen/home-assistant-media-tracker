"""Sensors for Media Watch."""

from __future__ import annotations

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
            MovieDiscoveryFeedSensor(coordinator, entry),
            UpcomingMediaCardSensor(coordinator, entry),
            DiscoverySensor(coordinator, entry),
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
            "original_title": item.get("original_title"),
            "release_date": item.get("release_date"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
            "overview": item.get("overview") or "",
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
            "deep_link": (
                "https://www.themoviedb.org/movie/"
                f"{item.get('id')}"
            ),
        }


class MovieDiscoveryFeedSensor(_MediaTrackerFeedSensor):
    """Movie discovery feed for the companion card."""

    _attr_name = "Discovery"
    _attr_icon = "mdi:movie-search-outline"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_discovery"

    @property
    def _items(self) -> list[dict[str, Any]]:
        return [
            self._movie_item(item)
            for item in self.coordinator.data.get("discovered_movies", [])
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
            "source": "discovery",
            "tmdb_id": item.get("id"),
            "title": item.get("title"),
            "original_title": item.get("original_title"),
            "release_date": item.get("release_date"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
            "overview": item.get("overview") or "",
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
            "deep_link": (
                "https://www.themoviedb.org/movie/"
                f"{item.get('id')}"
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
            "original_title": item.get("original_title"),
            "release_date": item.get("release_date"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
            "overview": item.get("overview") or "",
            "poster": self._poster_url(
                item.get("poster_path")
            ),
            "providers": provider_names,
            "provider": ", ".join(provider_names),
            "provider_details": self._provider_details(item),
            "available_on_my_services": item.get(
                "available_on_my_services", False
            ),
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


class DiscoverySensor(MediaWatchSensor):
    _attr_name = "Movie discovery"
    _attr_icon = "mdi:movie-search"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_movie_discovery"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("discovered_movies", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "movies": self.coordinator.data.get("discovered_movies", []),
            "selected_providers": self.coordinator.data.get(
                "selected_providers", {}
            ),
        }
