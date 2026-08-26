"""Persistent local state for Media Watch."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


class MediaWatchStore:
    """Store watched, dismissed and TV progress state."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, Any] = {
            "watched_movies": [],
            "watched_tv": [],
            "dismissed_movies": [],
            "dismissed_tv": [],
            "tv_progress": {},
            "watchlist_snapshots": {},
        }

    async def async_load(self) -> None:
        saved = await self._store.async_load()
        if not saved:
            return

        for key in (
            "watched_movies",
            "watched_tv",
            "dismissed_movies",
            "dismissed_tv",
        ):
            values = saved.get(key)
            if isinstance(values, list):
                self._data[key] = [int(item) for item in values]

        progress = saved.get("tv_progress")
        if isinstance(progress, dict):
            self._data["tv_progress"] = progress

        snapshots = saved.get("watchlist_snapshots")
        if isinstance(snapshots, dict):
            self._data["watchlist_snapshots"] = snapshots

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    @property
    def watchlist_snapshots(self) -> dict[str, dict[str, Any]]:
        """Return a copy of persisted movie release/provider snapshots."""
        return {
            str(key): dict(value)
            for key, value in self._data["watchlist_snapshots"].items()
            if isinstance(value, dict)
        }

    async def set_watchlist_snapshots(
        self,
        snapshots: dict[str, dict[str, Any]],
    ) -> None:
        """Persist the current Watchlist snapshot as one atomic update."""
        self._data["watchlist_snapshots"] = {
            str(key): dict(value) for key, value in snapshots.items()
        }
        await self.async_save()

    @staticmethod
    def _key(media_type: str, prefix: str) -> str:
        if media_type == "movie":
            return f"{prefix}_movies"
        if media_type == "tv":
            return f"{prefix}_tv"
        raise ValueError(f"Unsupported media type: {media_type}")

    def is_watched(self, media_type: str, tmdb_id: int) -> bool:
        return tmdb_id in self._data[self._key(media_type, "watched")]

    def is_dismissed(self, media_type: str, tmdb_id: int) -> bool:
        return tmdb_id in self._data[self._key(media_type, "dismissed")]

    async def mark_watched(self, media_type: str, tmdb_id: int) -> None:
        watched = self._data[self._key(media_type, "watched")]
        dismissed = self._data[self._key(media_type, "dismissed")]
        if tmdb_id not in watched:
            watched.append(tmdb_id)
        if tmdb_id in dismissed:
            dismissed.remove(tmdb_id)
        await self.async_save()

    async def mark_unwatched(self, media_type: str, tmdb_id: int) -> None:
        watched = self._data[self._key(media_type, "watched")]
        if tmdb_id in watched:
            watched.remove(tmdb_id)
            await self.async_save()

    async def dismiss(self, media_type: str, tmdb_id: int) -> None:
        dismissed = self._data[self._key(media_type, "dismissed")]
        if tmdb_id not in dismissed:
            dismissed.append(tmdb_id)
            await self.async_save()

    async def undismiss(self, media_type: str, tmdb_id: int) -> None:
        dismissed = self._data[self._key(media_type, "dismissed")]
        if tmdb_id in dismissed:
            dismissed.remove(tmdb_id)
            await self.async_save()

    def _tv_progress(self, tmdb_id: int) -> dict[str, Any]:
        """Return/create progress record for a TV show."""
        progress = self._data["tv_progress"]
        key = str(tmdb_id)
        if key not in progress:
            progress[key] = {
                "watched_seasons": [],
                "watched_episodes": {},
            }
        return progress[key]

    def tv_progress(self, tmdb_id: int) -> dict[str, Any]:
        """Return a normalized copy of TV progress."""
        progress = self._tv_progress(tmdb_id)
        return {
            "watched_seasons": sorted(
                int(item) for item in progress.get("watched_seasons", [])
            ),
            "watched_episodes": {
                str(season): sorted(int(ep) for ep in episodes)
                for season, episodes in progress.get(
                    "watched_episodes", {}
                ).items()
            },
        }

    def is_season_watched(self, tmdb_id: int, season: int) -> bool:
        progress = self._tv_progress(tmdb_id)
        return season in [
            int(item) for item in progress.get("watched_seasons", [])
        ]

    def is_episode_watched(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> bool:
        if self.is_season_watched(tmdb_id, season):
            return True

        progress = self._tv_progress(tmdb_id)
        watched = progress.get("watched_episodes", {}).get(
            str(season), []
        )
        return episode in [int(item) for item in watched]

    async def mark_episode_watched(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> None:
        progress = self._tv_progress(tmdb_id)
        episodes = progress.setdefault("watched_episodes", {}).setdefault(
            str(season), []
        )
        if episode not in episodes:
            episodes.append(episode)
        await self.async_save()

    async def mark_episode_unwatched(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
    ) -> None:
        progress = self._tv_progress(tmdb_id)

        # If the whole season was marked watched, convert it into
        # per-episode progress lazily by removing the season marker.
        # The caller can then explicitly mark the episodes it wants.
        seasons = progress.setdefault("watched_seasons", [])
        if season in seasons:
            seasons.remove(season)

        episodes = progress.setdefault("watched_episodes", {}).setdefault(
            str(season), []
        )
        if episode in episodes:
            episodes.remove(episode)

        await self.async_save()

    async def mark_seasons_watched(
        self,
        tmdb_id: int,
        seasons: list[int],
    ) -> None:
        progress = self._tv_progress(tmdb_id)
        watched_seasons = progress.setdefault("watched_seasons", [])
        watched_episodes = progress.setdefault("watched_episodes", {})

        for season in seasons:
            if season not in watched_seasons:
                watched_seasons.append(season)
            watched_episodes.pop(str(season), None)

        await self.async_save()

    async def mark_seasons_unwatched(
        self,
        tmdb_id: int,
        seasons: list[int],
    ) -> None:
        progress = self._tv_progress(tmdb_id)
        watched_seasons = progress.setdefault("watched_seasons", [])
        watched_episodes = progress.setdefault("watched_episodes", {})

        for season in seasons:
            if season in watched_seasons:
                watched_seasons.remove(season)
            watched_episodes.pop(str(season), None)

        await self.async_save()

    async def set_released_episodes_watched(
        self,
        tmdb_id: int,
        episodes_by_season: dict[int, list[int]],
    ) -> None:
        """Replace whole-season markers with released episode progress."""
        progress = self._tv_progress(tmdb_id)
        watched_seasons = progress.setdefault("watched_seasons", [])
        watched_episodes = progress.setdefault("watched_episodes", {})

        for season, episodes in episodes_by_season.items():
            while season in watched_seasons:
                watched_seasons.remove(season)

            unique_episodes = sorted({int(episode) for episode in episodes})
            if unique_episodes:
                watched_episodes[str(season)] = unique_episodes
            else:
                watched_episodes.pop(str(season), None)

        await self.async_save()

    @property
    def watched_movies(self) -> list[int]:
        return list(self._data["watched_movies"])

    @property
    def dismissed_movies(self) -> list[int]:
        return list(self._data["dismissed_movies"])


    @property
    def watched_tv(self) -> list[int]:
        return list(self._data["watched_tv"])

    @property
    def dismissed_tv(self) -> list[int]:
        return list(self._data["dismissed_tv"])
