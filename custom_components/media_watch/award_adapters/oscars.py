
"""Academy Awards adapter."""

from __future__ import annotations

from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from ..awards import OscarsRepository
from ..const import AWARD_SOURCE_OSCARS


class OscarsAwardAdapter(AwardAdapter):
    """Adapter over the historical Academy Awards dataset."""

    info = AwardAdapterInfo(
        source=AWARD_SOURCE_OSCARS,
        label="Academy Awards (Oscars)",
        media_types=frozenset({"movie"}),
        supports_nominees=True,
        supports_winners=True,
    )

    def __init__(self, hass) -> None:
        super().__init__(hass)
        self._repo = OscarsRepository(hass)

    async def async_categories(
        self,
        media_type: str,
    ) -> list[dict[str, str]]:
        if media_type != "movie":
            return []

        categories = await self._repo.async_categories()
        return [
            {"value": "all", "label": "All categories"},
            *[
                {
                    "value": category,
                    "label": self._humanize_category(category),
                }
                for category in categories
            ],
        ]

    async def async_latest_award_year(
        self,
        media_type: str,
    ) -> int:
        if media_type != "movie":
            raise ValueError("Oscars only supports movie media type")
        return await self._repo.async_latest_award_year()

    async def async_filter_titles(
        self,
        *,
        media_type: str,
        year_from: int | None,
        year_to: int | None,
        category: str | None,
        status: str,
    ) -> list[dict[str, Any]]:
        if media_type != "movie":
            return []

        records = await self._repo.async_filter_films(
            year_from=year_from,
            year_to=year_to,
            category=category,
            status=status,
        )

        return [
            {
                "title": item["film"],
                "imdb_id": item["imdb_id"],
                "media_type": "movie",
                "award_years": item["award_years"],
                "categories": item["categories"],
                "nominations": item["nominations"],
                "wins": item["wins"],
                "winning_categories": item["winning_categories"],
                "records": item.get("records", []),
            }
            for item in records
        ]

    @staticmethod
    def _humanize_category(category: str) -> str:
        special = {
            "BEST PICTURE": "Best Picture",
            "DIRECTING": "Directing",
            "ANIMATED FEATURE FILM": "Animated Feature Film",
            "INTERNATIONAL FEATURE FILM": "International Feature Film",
            "DOCUMENTARY FEATURE FILM": "Documentary Feature Film",
        }
        return special.get(category, category.title())
