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



class UpcomingMediaCardSensor(MediaWatchSensor):
    """Compatibility feed for custom:upcoming-media-card.

    Upcoming Media Card expects a `data` attribute containing a template
    record followed by media records. This adapter deliberately keeps the
    backend independent of the frontend card.
    """

    _attr_name = "Upcoming Media Card"
    _attr_icon = "mdi:movie-open-clock"

    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = (
            f"{entry.entry_id}_upcoming_media_card"
        )

    @property
    def _items(self) -> list[dict[str, Any]]:
        episodes = self.coordinator.data.get(
            "episodes_next_30_days", []
        )

        # First record is Upcoming Media Card's display template.
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
            poster_path = item.get("poster_path")
            poster = (
                f"{self.TMDB_IMAGE_BASE}{poster_path}"
                if poster_path
                else None
            )

            provider_names = (
                item.get("my_providers")
                or item.get("providers")
                or []
            )
            provider = ", ".join(provider_names)

            provider_details = (
                item.get("my_provider_details")
                or item.get("provider_details")
                or []
            )

            air_date = item.get("air_date")
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
                    "id": item.get("id"),
                    "tmdb_id": item.get("tmdb_id"),
                    "title": item.get("show"),
                    "season": item.get("season"),
                    "episode_number": item.get("episode"),
                    "episode": episode_label,
                    "number": code,
                    "airdate": air_date,
                    "release": air_date,
                    "runtime": item.get("runtime"),
                    "provider": provider,
                    "studio": provider,
                    "provider_details": provider_details,
                    "poster": poster,
                    "fanart": None,
                    "flag": (
                        not item.get(
                            "available_on_my_services",
                            False,
                        )
                    ),
                    "summary": item.get("overview") or "",
                    "deep_link": (
                        "https://www.themoviedb.org/tv/"
                        f"{item.get('tmdb_id')}"
                    ),
                }
            )

        return data

    @property
    def native_value(self) -> int:
        # Do not count the template record.
        return max(0, len(self._items) - 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"data": self._items}


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
