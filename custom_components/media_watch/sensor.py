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
            "providers": self.coordinator.data.get("providers", {}),
        }
