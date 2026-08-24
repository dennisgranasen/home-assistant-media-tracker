"""Asynchronous TMDB API client for Media Watch."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

BASE_URL = "https://api.themoviedb.org/3"


class TMDBError(Exception):
    """Base TMDB error."""


class TMDBAuthError(TMDBError):
    """TMDB authentication failed."""


class TMDBApi:
    """Small asynchronous TMDB API client."""

    def __init__(
        self,
        session: ClientSession,
        access_token: str,
        session_id: str | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._session_id = session_id

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        include_session: bool = True,
    ) -> dict[str, Any]:
        request_params = dict(params or {})
        if include_session and self._session_id:
            request_params.setdefault("session_id", self._session_id)

        try:
            async with asyncio.timeout(20):
                response = await self._session.request(
                    method,
                    f"{BASE_URL}{path}",
                    headers=self.headers,
                    params=request_params,
                    json=json,
                )
                response.raise_for_status()
                if response.content_type == "application/json":
                    return await response.json()
                return {}
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise TMDBAuthError(
                    f"TMDB authentication failed ({err.status})"
                ) from err
            raise TMDBError(f"TMDB HTTP error {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise TMDBError(f"TMDB request failed: {err}") from err

    async def validate_token(self) -> None:
        await self._request("GET", "/configuration", include_session=False)

    async def create_request_token(self) -> str:
        data = await self._request(
            "GET", "/authentication/token/new", include_session=False
        )
        return str(data["request_token"])

    async def create_session(self, request_token: str) -> str:
        data = await self._request(
            "POST",
            "/authentication/session/new",
            json={"request_token": request_token},
            include_session=False,
        )
        return str(data["session_id"])

    async def account_details(self) -> dict[str, Any]:
        return await self._request("GET", "/account")

    async def _paged_results(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            page_params = dict(params or {})
            page_params["page"] = page
            data = await self._request("GET", path, params=page_params)
            result.extend(data.get("results", []))
            if page >= int(data.get("total_pages", 1)):
                break
        return result

    async def get_movie_watchlist(
        self, account_id: int, language: str
    ) -> list[dict[str, Any]]:
        return await self._paged_results(
            f"/account/{account_id}/watchlist/movies",
            params={"language": language, "sort_by": "created_at.desc"},
        )

    async def get_tv_watchlist(
        self, account_id: int, language: str
    ) -> list[dict[str, Any]]:
        return await self._paged_results(
            f"/account/{account_id}/watchlist/tv",
            params={"language": language, "sort_by": "created_at.desc"},
        )

    async def set_watchlist(
        self,
        account_id: int,
        media_type: str,
        tmdb_id: int,
        watchlist: bool,
    ) -> None:
        await self._request(
            "POST",
            f"/account/{account_id}/watchlist",
            json={
                "media_type": media_type,
                "media_id": tmdb_id,
                "watchlist": watchlist,
            },
        )


    async def search_tv(
        self,
        query: str,
        language: str,
        *,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Search TMDB TV shows."""
        data = await self._request(
            "GET",
            "/search/tv",
            params={
                "query": query,
                "language": language,
                "page": page,
                "include_adult": "false",
            },
            include_session=False,
        )
        return data.get("results", [])

    async def search_movies(
        self,
        query: str,
        language: str,
        *,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Search TMDB movies."""
        data = await self._request(
            "GET",
            "/search/movie",
            params={
                "query": query,
                "language": language,
                "page": page,
                "include_adult": "false",
            },
            include_session=False,
        )
        return data.get("results", [])

    async def get_tv_details(
        self, tmdb_id: int, language: str
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"/tv/{tmdb_id}", params={"language": language}
        )


    async def get_tv_season(
        self,
        tmdb_id: int,
        season_number: int,
        language: str,
    ) -> dict[str, Any]:
        """Return TV season details including episodes."""
        return await self._request(
            "GET",
            f"/tv/{tmdb_id}/season/{season_number}",
            params={"language": language},
            include_session=False,
        )

    async def get_tv_watch_providers(self, tmdb_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/tv/{tmdb_id}/watch/providers")

    async def get_movie_watch_providers(self, tmdb_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/movie/{tmdb_id}/watch/providers")

    async def get_available_movie_providers(
        self, region: str
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/watch/providers/movie",
            params={"watch_region": region},
            include_session=False,
        )
        return data.get("results", [])

    async def get_available_tv_providers(
        self, region: str
    ) -> list[dict[str, Any]]:
        """Return TV providers available in a region."""
        data = await self._request(
            "GET",
            "/watch/providers/tv",
            params={"watch_region": region},
            include_session=False,
        )
        return data.get("results", [])

    async def discover_movies(
        self,
        *,
        region: str,
        language: str,
        provider_ids: list[int],
        min_rating: float,
        min_votes: int,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        if not provider_ids:
            return []

        return await self._paged_results(
            "/discover/movie",
            params={
                "language": language,
                "region": region,
                "watch_region": region,
                "with_watch_providers": "|".join(str(x) for x in provider_ids),
                "with_watch_monetization_types": "flatrate|free|ads",
                "vote_average.gte": min_rating,
                "vote_count.gte": min_votes,
                "sort_by": "popularity.desc",
                "include_adult": "false",
            },
            max_pages=max_pages,
        )
