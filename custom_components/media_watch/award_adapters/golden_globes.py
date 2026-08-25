"""Golden Globes adapters using official yearly nominations pages."""

from __future__ import annotations

import re
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from .web_common import aggregate_records, fetch_lines

MOVIE_CATEGORIES = ["Best Motion Picture - Drama", "Best Motion Picture - Musical or Comedy", "Best Motion Picture - Animated", "Best Motion Picture - Non-English Language", "Best Director - Motion Picture", "Best Screenplay - Motion Picture", "Best Performance by a Female Actor in a Motion Picture – Drama", "Best Performance by a Male Actor in a Motion Picture – Drama", "Best Performance by a Female Actor in a Motion Picture – Musical or Comedy", "Best Performance by a Male Actor in a Motion Picture – Musical or Comedy"]
TV_CATEGORIES = ["Best Television Series - Drama", "Best Television Series - Musical or Comedy", "Best Television Limited Series, Anthology Series, or Motion Picture Made for Television", "Best Performance by a Female Actor in a Television Series – Drama", "Best Performance by a Male Actor in a Television Series - Drama", "Best Performance by a Female Actor in a Television Series – Musical or Comedy", "Best Performance by a Male Actor in a Television Series - Musical or Comedy", "Best Performance by a Female Actor in a Supporting Role on Television", "Best Performance by a Male Actor in a Supporting Role on Television"]


class _GoldenGlobesAdapter(AwardAdapter):
    media_type = "movie"
    categories = MOVIE_CATEGORIES

    async def async_categories(self, media_type: str) -> list[dict[str, str]]:
        if media_type != self.media_type:
            return []
        return [{"value": "all", "label": "All categories"}] + [{"value": x, "label": x} for x in self.categories]

    async def async_latest_award_year(self, media_type: str) -> int:
        return 2026

    async def _year_records(self, year: int) -> list[dict[str, Any]]:
        lines = await fetch_lines(self.hass, f"https://goldenglobes.com/nominations/{year}")
        records = []
        category = None
        i = 0
        while i < len(lines):
            line = lines[i]
            if line in self.categories:
                category = line
                i += 1
                continue
            if category and line == "Winner":
                # Winner is followed by nominee/person and sometimes the title.
                vals = []
                j = i + 1
                while j < len(lines) and len(vals) < 3:
                    if lines[j] in self.categories or lines[j] == "Winner" or re.fullmatch(rf"{year} Nominee", lines[j]):
                        break
                    vals.append(lines[j]); j += 1
                if vals:
                    records.append({"media_type": self.media_type, "award_year": year, "category": category, "title": vals[-1], "title_candidates": vals, "winner": True})
                i = j; continue
            if category and re.fullmatch(rf"{year} Nominee", line):
                vals = []
                j = i + 1
                while j < len(lines) and len(vals) < 3:
                    if lines[j] in self.categories or lines[j] == "Winner" or re.fullmatch(rf"{year} Nominee", lines[j]):
                        break
                    vals.append(lines[j]); j += 1
                if vals:
                    records.append({"media_type": self.media_type, "award_year": year, "category": category, "title": vals[-1], "title_candidates": vals, "winner": False})
                i = j; continue
            i += 1
        return records

    async def async_filter_titles(self, *, media_type: str, year_from: int | None, year_to: int | None, category: str | None, status: str) -> list[dict[str, Any]]:
        if media_type != self.media_type:
            return []
        lo = year_from or 1944
        hi = year_to or await self.async_latest_award_year(media_type)
        records = []
        for year in range(lo, hi + 1):
            try:
                year_records = await self._year_records(year)
                records.extend(r for r in year_records if not category or category == "all" or r["category"] == category)
            except Exception:
                continue
        return aggregate_records(records, status)


class GoldenGlobesFilmAwardAdapter(_GoldenGlobesAdapter):
    info = AwardAdapterInfo(source="golden_globes_film", label="Golden Globes – Film", media_types=frozenset({"movie"}))


class GoldenGlobesTelevisionAwardAdapter(_GoldenGlobesAdapter):
    info = AwardAdapterInfo(source="golden_globes_tv", label="Golden Globes – Television", media_types=frozenset({"tv"}))
    media_type = "tv"
    categories = TV_CATEGORIES
