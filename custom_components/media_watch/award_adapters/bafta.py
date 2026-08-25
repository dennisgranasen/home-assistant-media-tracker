"""BAFTA Film and Television adapters using BAFTA's official awards archive."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from .web_common import aggregate_records, fetch_lines, in_year_range

BASE = "https://www.bafta.org/awards/search/"
COMMON_FILM = ["Best Film", "Outstanding British Film", "Leading Actor", "Leading Actress", "Supporting Actor", "Supporting Actress", "Director", "Original Screenplay", "Adapted Screenplay", "Animated Film", "Documentary", "Film Not in the English Language", "Cinematography", "Editing", "Costume Design", "Production Design", "Sound", "Special Visual Effects", "Casting"]
COMMON_TV = ["Drama Series", "Comedy Entertainment Programme", "Scripted Comedy", "Mini-Series", "Leading Actor", "Leading Actress", "Supporting Actor", "Supporting Actress", "Male Performance in a Comedy", "Female Performance in a Comedy", "International", "Single Drama", "Factual Series", "Specialist Factual"]


class _BaftaAdapter(AwardAdapter):
    bafta_type = "Film"
    media_type = "movie"
    categories = COMMON_FILM

    async def async_categories(self, media_type: str) -> list[dict[str, str]]:
        if media_type != self.media_type:
            return []
        return [{"value": "all", "label": "All categories"}] + [{"value": x, "label": x} for x in self.categories]

    async def async_latest_award_year(self, media_type: str) -> int:
        return 2026

    async def _year_records(self, year: int, category: str | None) -> list[dict[str, Any]]:
        query = {"award-year": str(year), "type": self.bafta_type, "winner": "nominee"}
        if category and category != "all":
            query["search"] = category
        lines = await fetch_lines(self.hass, BASE + "?" + urlencode(query))
        records: list[dict[str, Any]] = []
        current_category = None
        status = None
        for i, line in enumerate(lines):
            m = re.match(rf"{year}\s*/\s*{re.escape(self.bafta_type)}", line, re.I)
            if m:
                current_category = None
                status = None
                continue
            if line in {"Winner", "Nominee"}:
                status = line
                continue
            if line in self.categories or (category and category != "all" and line.casefold() == category.casefold()):
                current_category = line
                continue
            if current_category and status and line not in {current_category} and not line.startswith("Load More"):
                # BAFTA result cards put the nominated work/person in the heading and,
                # for performance awards, commonly place the programme/film immediately
                # after it. Keep a short candidate window; TMDB resolution picks the title.
                candidates = [line]
                for nxt in lines[i + 1:i + 4]:
                    if nxt in {"Winner", "Nominee"} or re.match(r"\d{4}\s*/", nxt):
                        break
                    if nxt != current_category and len(nxt) < 160:
                        candidates.append(nxt)
                records.append({"media_type": self.media_type, "award_year": year, "category": current_category, "title": candidates[-1], "title_candidates": candidates, "winner": status == "Winner"})
                current_category = None
                status = None
        return records

    async def async_filter_titles(self, *, media_type: str, year_from: int | None, year_to: int | None, category: str | None, status: str) -> list[dict[str, Any]]:
        if media_type != self.media_type:
            return []
        lo = year_from or 1947
        hi = year_to or await self.async_latest_award_year(media_type)
        records: list[dict[str, Any]] = []
        for year in range(lo, hi + 1):
            try:
                records.extend(await self._year_records(year, category))
            except Exception:
                continue
        return aggregate_records(records, status)


class BaftaFilmAwardAdapter(_BaftaAdapter):
    info = AwardAdapterInfo(source="bafta_film", label="BAFTA Film Awards", media_types=frozenset({"movie"}))


class BaftaTelevisionAwardAdapter(_BaftaAdapter):
    info = AwardAdapterInfo(source="bafta_tv", label="BAFTA Television Awards", media_types=frozenset({"tv"}))
    bafta_type = "Television"
    media_type = "tv"
    categories = COMMON_TV
