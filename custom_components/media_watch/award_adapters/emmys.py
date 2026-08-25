"""Primetime Emmy adapter using Television Academy official year pages."""

from __future__ import annotations

import re
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from .web_common import aggregate_records, fetch_lines

CATEGORIES = ["Comedy Series", "Drama Series", "Limited Or Anthology Series", "Television Movie", "Lead Actor", "Lead Actress", "Supporting Actor", "Supporting Actress", "Guest Actor", "Guest Actress", "Directing", "Writing", "Reality Competition Program", "Talk Series", "Scripted Variety Series", "Animated Program"]


class EmmysAwardAdapter(AwardAdapter):
    info = AwardAdapterInfo(source="emmys", label="Primetime Emmy Awards", media_types=frozenset({"tv"}))

    async def async_categories(self, media_type: str) -> list[dict[str, str]]:
        if media_type != "tv": return []
        return [{"value": "all", "label": "All categories"}] + [{"value": x, "label": x} for x in CATEGORIES]

    async def async_latest_award_year(self, media_type: str) -> int:
        return 2026

    async def _year_records(self, year: int) -> list[dict[str, Any]]:
        lines = await fetch_lines(self.hass, f"https://www.televisionacademy.com/awards/nominees-winners/{year}")
        records = []
        category = None
        for i, line in enumerate(lines):
            if line in CATEGORIES or any(line.endswith(" " + c) for c in CATEGORIES):
                category = line if line in CATEGORIES else next((c for c in CATEGORIES if line.endswith(" " + c)), category)
                continue
            if category and "Winner" in line and f"{year}" in line:
                # Official result lines generally contain PROGRAM Winner CATEGORY - YEAR.
                title = line.split("Winner", 1)[0].strip()
                if title:
                    records.append({"media_type": "tv", "award_year": year, "category": category, "title": title, "title_candidates": [title], "winner": True})
            elif category and "Nominee" in line and f"{year}" in line:
                title = line.split("Nominee", 1)[0].strip()
                if title:
                    records.append({"media_type": "tv", "award_year": year, "category": category, "title": title, "title_candidates": [title], "winner": False})
        return records

    async def async_filter_titles(self, *, media_type: str, year_from: int | None, year_to: int | None, category: str | None, status: str) -> list[dict[str, Any]]:
        if media_type != "tv": return []
        lo, hi = year_from or 1949, year_to or 2026
        records = []
        for year in range(lo, hi + 1):
            try:
                yr = await self._year_records(year)
                records.extend(r for r in yr if not category or category == "all" or category in r["category"])
            except Exception:
                continue
        return aggregate_records(records, status)
