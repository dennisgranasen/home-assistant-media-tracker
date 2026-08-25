"""Guldbaggen award adapter using the official Guldbaggen archive."""

from __future__ import annotations

import re
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from .web_common import aggregate_records, fetch_lines, in_year_range


class GuldbaggenAwardAdapter(AwardAdapter):
    info = AwardAdapterInfo(
        source="guldbaggen",
        label="Guldbaggen",
        media_types=frozenset({"movie"}),
        supports_nominees=True,
        supports_winners=True,
    )
    ARCHIVE_URL = "https://www.guldbaggen.se/arkiv/"
    CURRENT_URL = "https://www.guldbaggen.se/nominerade/"

    def __init__(self, hass) -> None:
        super().__init__(hass)
        self._records: list[dict[str, Any]] | None = None

    async def _load(self) -> list[dict[str, Any]]:
        if self._records is not None:
            return self._records
        lines = await fetch_lines(self.hass, self.ARCHIVE_URL)
        records: list[dict[str, Any]] = []
        category: str | None = None
        year: int | None = None
        skip_prefixes = ("Producent", "Regi:", "Manus:", "Foto:", "Skådespelare:")
        for line in lines:
            if re.fullmatch(r"(?:19|20)\d{2}", line):
                year = int(line)
                continue
            if line.startswith("Bästa ") or line in {"Gullspira", "Hedersguldbagge", "Guldbaggens publikpris", "Guldpiga"}:
                category = line
                continue
            if not category or year is None or line.startswith(skip_prefixes):
                continue
            if line in {"Tidigare år", "Filtrera på:", "Arkiv"}:
                continue
            # The official archive exposes the nominated work/person followed by
            # credit text. For person categories, the following credit often contains
            # "för <film>"; both strings are kept as title candidates so TMDB resolution
            # can select the media title rather than the person name.
            if len(line) > 1 and not line.endswith(":"):
                records.append({"media_type": "movie", "award_year": year, "category": category, "title": line, "title_candidates": [line], "winner": False})

        # Current official nominee page explicitly marks winners. Overlay winner facts
        # for the latest completed film year where the site provides VINNARE labels.
        try:
            current = await fetch_lines(self.hass, self.CURRENT_URL)
            cur_category = None
            latest_year = max((r["award_year"] for r in records), default=0) + 1
            winner_pending = False
            for line in current:
                if line.upper() == "VINNARE":
                    winner_pending = True
                    continue
                if line.startswith("Bästa "):
                    cur_category = line
                    continue
                if winner_pending and cur_category and line and not line.startswith(("Producent", "Regi", "för rollen", "för ")):
                    records.append({"media_type": "movie", "award_year": latest_year, "category": cur_category, "title": line, "title_candidates": [line], "winner": True})
                    winner_pending = False
        except Exception:
            pass
        self._records = records
        return records

    async def async_categories(self, media_type: str) -> list[dict[str, str]]:
        if media_type != "movie":
            return []
        records = await self._load()
        cats = sorted({r["category"] for r in records})
        return [{"value": "all", "label": "Alla kategorier"}] + [{"value": c, "label": c} for c in cats]

    async def async_latest_award_year(self, media_type: str) -> int:
        records = await self._load()
        return max(r["award_year"] for r in records)

    async def async_filter_titles(self, *, media_type: str, year_from: int | None, year_to: int | None, category: str | None, status: str) -> list[dict[str, Any]]:
        records = await self._load()
        selected = [r for r in records if in_year_range(r["award_year"], year_from, year_to) and (not category or category == "all" or r["category"] == category)]
        return aggregate_records(selected, status)
