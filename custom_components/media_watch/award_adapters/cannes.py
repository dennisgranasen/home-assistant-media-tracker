"""Festival de Cannes adapter using the official retrospective."""

from __future__ import annotations

import re
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from .web_common import aggregate_records, fetch_lines

CATEGORIES = ["Palme d'or", "Grand Prix", "Jury Prize", "Award for Best Director", "Award for Best Screenplay", "Award for Best Actress", "Award for Best Actor", "Caméra d'or", "Official Selection – In Competition"]


class CannesAwardAdapter(AwardAdapter):
    info = AwardAdapterInfo(source="cannes", label="Festival de Cannes", media_types=frozenset({"movie"}), supports_nominees=True, supports_winners=True)

    async def async_categories(self, media_type: str) -> list[dict[str, str]]:
        if media_type != "movie": return []
        return [{"value": "all", "label": "All prizes / competition selection"}] + [{"value": x, "label": x} for x in CATEGORIES]

    async def async_latest_award_year(self, media_type: str) -> int:
        return 2026

    @staticmethod
    def _film_from_line(line: str) -> str:
        # Retrospective uses "FILM by DIRECTOR" or "PERSON for FILM".
        if " for " in line:
            return line.rsplit(" for ", 1)[-1].strip()
        if " by " in line:
            return line.rsplit(" by ", 1)[0].strip()
        return line.strip()

    async def _year_records(self, year: int) -> list[dict[str, Any]]:
        records = []
        # Competition selection is the festival equivalent of nomination.
        try:
            lines = await fetch_lines(self.hass, f"https://www.festival-cannes.com/en/retrospective/{year}/")
            in_comp = False
            for line in lines:
                if line == "In Competition": in_comp = True; continue
                if in_comp and line in {"Un Certain Regard", "Out of Competition", "Cannes Premiere", "Special Screenings", "Short films"}: break
                if in_comp and " by " in line:
                    records.append({"media_type": "movie", "award_year": year, "category": "Official Selection – In Competition", "title": self._film_from_line(line), "title_candidates": [self._film_from_line(line)], "winner": False})
        except Exception:
            pass
        try:
            lines = await fetch_lines(self.hass, f"https://www.festival-cannes.com/en/retrospective/{year}/awards/")
            for i, line in enumerate(lines[:-1]):
                nxt = lines[i + 1]
                category = next((c for c in CATEGORIES[:-1] if nxt.startswith(c) or c in nxt), None)
                if category:
                    film = self._film_from_line(line)
                    if film and len(film) > 1:
                        records.append({"media_type": "movie", "award_year": year, "category": category, "title": film, "title_candidates": [film], "winner": True})
        except Exception:
            pass
        return records

    async def async_filter_titles(self, *, media_type: str, year_from: int | None, year_to: int | None, category: str | None, status: str) -> list[dict[str, Any]]:
        if media_type != "movie": return []
        lo, hi = year_from or 1946, year_to or 2026
        records = []
        for year in range(lo, hi + 1):
            try:
                yr = await self._year_records(year)
                records.extend(r for r in yr if not category or category == "all" or r["category"] == category)
            except Exception:
                continue
        return aggregate_records(records, status)
