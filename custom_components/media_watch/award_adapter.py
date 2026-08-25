
"""Common interface for award-history adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AwardAdapterInfo:
    """Capabilities exposed to the config flow."""

    source: str
    label: str
    media_types: frozenset[str]
    supports_nominees: bool = True
    supports_winners: bool = True


class AwardAdapter(ABC):
    """Base interface for award providers.

    An adapter owns:
    - loading/caching its historical source data
    - normalizing category names
    - filtering award records by year/category/status
    - returning film/TV title identifiers that Media Watch can resolve to TMDB

    Adapters must not perform TMDB enrichment themselves.
    """

    info: AwardAdapterInfo

    def __init__(self, hass) -> None:
        self.hass = hass

    @abstractmethod
    async def async_categories(
        self,
        media_type: str,
    ) -> list[dict[str, str]]:
        """Return selector options for categories valid for this source."""

    @abstractmethod
    async def async_latest_award_year(
        self,
        media_type: str,
    ) -> int:
        """Return the latest award year present in the source."""

    @abstractmethod
    async def async_filter_titles(
        self,
        *,
        media_type: str,
        year_from: int | None,
        year_to: int | None,
        category: str | None,
        status: str,
    ) -> list[dict[str, Any]]:
        """Return one normalized record per title.

        Recommended normalized output:

        {
            "title": "Example",
            "imdb_id": "tt1234567",      # preferred when available
            "tmdb_id": 123,              # optional alternative
            "media_type": "movie",
            "award_years": [2024],
            "categories": ["BEST FILM"],
            "nominations": 4,
            "wins": 2,
            "winning_categories": ["BEST FILM"],
            "records": [...],             # optional raw normalized records
        }

        At least one stable resolution key should be present:
        IMDb ID, TMDB ID, or as a last resort title + release year.
        """
