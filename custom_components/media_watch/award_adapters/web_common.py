"""Shared helpers for official-web award adapters."""

from __future__ import annotations

import asyncio
import html
import re
from collections import defaultdict
from html.parser import HTMLParser
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession


AWARD_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Home Assistant) "
        "AppleWebKit/537.36 Chrome/149 Safari/537.36 "
        "MediaWatch/0.16"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}



class _BlockTextParser(HTMLParser):
    BLOCKS = {"h1", "h2", "h3", "h4", "h5", "p", "li", "article", "section", "div", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def lines(self) -> list[str]:
        text = html.unescape("".join(self.parts)).replace("\xa0", " ")
        return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if re.sub(r"\s+", " ", line).strip()]


async def fetch_lines(hass, url: str) -> list[str]:
    cache = hass.data.setdefault("media_watch_award_http_cache", {})
    if url in cache:
        return list(cache[url])
    session = async_get_clientsession(hass)
    async with session.get(url, timeout=45, headers=AWARD_HTTP_HEADERS) as response:
        response.raise_for_status()
        text = await response.text()
    parser = _BlockTextParser()
    parser.feed(text)
    lines = parser.lines()
    cache[url] = list(lines)
    return lines


def aggregate_records(records: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    """Collapse raw nomination/winner records to one row per title-ish key."""
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        candidates = [x.strip() for x in record.get("title_candidates", []) if str(x).strip()]
        if not candidates:
            title = str(record.get("title") or "").strip()
            if title:
                candidates = [title]
        if not candidates:
            continue
        key = str(
            record.get("stable_key")
            or (
                f"{candidates[-1]}:"
                f"{record.get('release_year') or record.get('award_year') or ''}"
            )
        ).casefold()
        item = grouped.setdefault(
            key,
            {
                "stable_key": key,
                "title": candidates[-1],
                "title_candidates": [],
                "media_type": record.get("media_type", "movie"),
                "award_years": set(),
                "categories": set(),
                "nominations": 0,
                "wins": 0,
                "winning_categories": set(),
                "recipients": set(),
                "records": [],
            },
        )
        for candidate in candidates:
            if candidate not in item["title_candidates"]:
                item["title_candidates"].append(candidate)
        if record.get("award_year") is not None:
            item["award_years"].add(int(record["award_year"]))
        category = str(record.get("category") or "").strip()
        if category:
            item["categories"].add(category)
        for recipient in record.get("recipients", []):
            if recipient:
                item["recipients"].add(str(recipient))
        item["nominations"] += 1
        if record.get("winner"):
            item["wins"] += 1
            if category:
                item["winning_categories"].add(category)
        item["records"].append(record)

    result = []
    for item in grouped.values():
        wins = item["wins"]
        nominations = item["nominations"]
        if status == "winner" and wins < 1:
            continue
        if status == "nominated_no_win" and wins != 0:
            continue
        if status == "nominated_and_won" and not (nominations >= 1 and wins >= 1):
            continue
        result.append(
            {
                **item,
                "award_years": sorted(item["award_years"]),
                "categories": sorted(item["categories"]),
                "winning_categories": sorted(item["winning_categories"]),
                "recipients": sorted(item["recipients"]),
            }
        )
    result.sort(key=lambda x: (-(max(x["award_years"]) if x["award_years"] else 0), -x["wins"], -x["nominations"], x["title"]))
    return result


def in_year_range(year: int, year_from: int | None, year_to: int | None) -> bool:
    return (year_from is None or year >= year_from) and (year_to is None or year <= year_to)



class _TableTextParser(HTMLParser):
    """Extract visible text grouped into table rows/cells."""

    def __init__(
        self,
        *,
        number_ordered_list_items: bool = False,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_tag: str | None = None
        self._number_ordered_list_items = number_ordered_list_items
        self._ordered_list_counters: list[int] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._cell_tag = tag
            self._ordered_list_counters = []
        elif tag == "ol" and self._cell_parts is not None:
            self._ordered_list_counters.append(0)
        elif tag == "li" and self._cell_parts is not None:
            self._cell_parts.append("\n")
            if (
                self._number_ordered_list_items
                and self._ordered_list_counters
            ):
                self._ordered_list_counters[-1] += 1
                self._cell_parts.append(
                    f"{self._ordered_list_counters[-1]}. "
                )
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if (
            tag in {"td", "th"}
            and self._row is not None
            and self._cell_parts is not None
        ):
            text = html.unescape("".join(self._cell_parts)).replace("\xa0", " ")
            text = re.sub(r"[ \t\r\f\v]+", " ", text)
            text = re.sub(r"\n+", "\n", text).strip()
            self._row.append(text)
            self._cell_parts = None
            self._cell_tag = None
            self._ordered_list_counters = []
        elif tag == "li" and self._cell_parts is not None:
            self._cell_parts.append("\n")
        elif tag == "ol" and self._ordered_list_counters:
            self._ordered_list_counters.pop()
        elif tag == "tr" and self._row is not None:
            if any(cell.strip() for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)


async def fetch_table_rows(
    hass,
    url: str,
    *,
    number_ordered_list_items: bool = False,
) -> list[list[str]]:
    """Fetch and cache an HTML page parsed into table rows."""
    cache_variant = "numbered" if number_ordered_list_items else "plain"
    key = f"table:{cache_variant}:{url}"
    cache = hass.data.setdefault("media_watch_award_http_cache", {})
    if key in cache:
        return [list(row) for row in cache[key]]

    session = async_get_clientsession(hass)
    async with session.get(url, timeout=45, headers=AWARD_HTTP_HEADERS) as response:
        response.raise_for_status()
        text = await response.text()

    parser = _TableTextParser(
        number_ordered_list_items=number_ordered_list_items
    )
    parser.feed(text)
    cache[key] = [list(row) for row in parser.rows]
    return parser.rows
