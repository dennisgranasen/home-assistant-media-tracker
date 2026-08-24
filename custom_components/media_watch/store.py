"""Persistent local state for Media Watch."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


class MediaWatchStore:
    """Store watched and dismissed state independently of TMDB."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, list[int]] = {
            "watched_movies": [],
            "watched_tv": [],
            "dismissed_movies": [],
            "dismissed_tv": [],
        }

    async def async_load(self) -> None:
        saved = await self._store.async_load()
        if not saved:
            return
        for key in self._data:
            values = saved.get(key)
            if isinstance(values, list):
                self._data[key] = [int(item) for item in values]

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

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

    @property
    def watched_movies(self) -> list[int]:
        return list(self._data["watched_movies"])

    @property
    def dismissed_movies(self) -> list[int]:
        return list(self._data["dismissed_movies"])
