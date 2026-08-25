"""Guldbaggen award adapter using the official Guldbaggen archive."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from .web_common import (
    aggregate_records,
    fetch_text,
    in_year_range,
)


class _CurrentNomineeParser(HTMLParser):
    """Parse the official current nominee cards and their winner class."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, Any]] = []
        self._award_depth = 0
        self._text_depth = 0
        self._category: str | None = None
        self._year: int | None = None
        self._winner = False
        self._title = ""
        self._credit = ""
        self._capture: str | None = None
        self._parts: list[str] = []

    @staticmethod
    def _classes(attrs) -> set[str]:
        return {
            value
            for key, raw in attrs
            if key == "class"
            for value in str(raw).split()
        }

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        classes = self._classes(attrs)
        if tag == "div":
            if self._award_depth:
                self._award_depth += 1
            elif "awardRow" in classes:
                self._award_depth = 1
                self._category = None
                self._year = None

            if self._text_depth:
                self._text_depth += 1
            elif self._award_depth and "text" in classes:
                self._text_depth = 1
                self._winner = "isWinner" in classes
                self._title = ""
                self._credit = ""

        if self._award_depth and tag in {"h2", "h3", "h4"}:
            self._capture = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == self._capture:
            value = re.sub(r"\s+", " ", "".join(self._parts)).strip()
            if tag == "h2":
                self._category = value
            elif tag == "h3" and self._text_depth:
                self._title = value
            elif tag == "h3" and re.fullmatch(r"(?:19|20)\d{2}", value):
                self._year = int(value)
            elif tag == "h4":
                self._credit = value
            self._capture = None
            self._parts = []

        if tag != "div":
            return
        if self._text_depth:
            self._text_depth -= 1
            if self._text_depth == 0:
                self._emit()
        if self._award_depth:
            self._award_depth -= 1

    @staticmethod
    def _film_title(category: str, title: str, credit: str) -> str:
        if category in {
            "Bästa film",
            "Bästa dokumentärfilm",
            "Bästa kortfilm",
            "Guldbaggens publikpris",
        }:
            return title
        role_match = re.search(r"\bi\s+(.+)$", credit, re.I)
        if role_match:
            return role_match.group(1).strip()
        for_match = re.match(r"för\s+(.+)$", credit, re.I)
        return for_match.group(1).strip() if for_match else ""

    def _emit(self) -> None:
        category = self._category or ""
        film = self._film_title(category, self._title, self._credit)
        if not category or not film:
            return
        recipients = [] if film == self._title else [self._title]
        record = {
            "media_type": "movie",
            "category": category,
            "title": film,
            "title_candidates": [film],
            "recipients": recipients,
            "winner": self._winner,
        }
        if self._year is not None:
            record["award_year"] = self._year
        self.records.append(record)


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
        archive_html = await fetch_text(self.hass, self.ARCHIVE_URL)
        archive_parser = _CurrentNomineeParser()
        archive_parser.feed(archive_html)
        records = [
            record
            for record in archive_parser.records
            if record.get("award_year") is not None
        ]

        # Current nominee cards mark the winner structurally with
        # div.text.isWinner. Parse that class together with its h3/h4 content;
        # the visible VINNARE label follows the title and cannot be interpreted
        # correctly as a flat sequence of text lines.
        try:
            current_html = await fetch_text(self.hass, self.CURRENT_URL)
            parser = _CurrentNomineeParser()
            parser.feed(current_html)
            year_match = re.search(
                r"(?:nominerade|vinnare)[^<]{0,40}((?:19|20)\d{2})",
                current_html,
                re.I,
            )
            latest_year = (
                int(year_match.group(1))
                if year_match
                else max(
                    (r["award_year"] for r in records),
                    default=0,
                )
                + 1
            )
            current_records = [
                {**record, "award_year": latest_year}
                for record in parser.records
            ]
            if current_records:
                records = [
                    record
                    for record in records
                    if record["award_year"] != latest_year
                ]
                records.extend(current_records)
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
