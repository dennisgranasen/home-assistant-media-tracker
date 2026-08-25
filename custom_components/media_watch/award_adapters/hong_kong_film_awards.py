
"""Hong Kong Film Awards adapter using the official HKFAA archive."""

from __future__ import annotations

import re
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo
from ..const import AWARD_SOURCE_HONG_KONG_FILM_AWARDS
from .web_common import (
    aggregate_records,
    fetch_lines,
    fetch_table_rows,
    in_year_range,
)


class HongKongFilmAwardsAdapter(AwardAdapter):
    """Historical Hong Kong Film Awards nominees and winners.

    Official archive pages are published per ceremony at hkfaa.com. Modern
    pages explicitly contain nominee and awardee lists; the earliest archive
    pages can contain winners only. The adapter never invents missing
    nominations.
    """

    info = AwardAdapterInfo(
        source=AWARD_SOURCE_HONG_KONG_FILM_AWARDS,
        label="Hong Kong Film Awards",
        media_types=frozenset({"movie"}),
        supports_nominees=True,
        supports_winners=True,
    )

    BASE_URL = "https://www.hkfaa.com"
    FIRST_CEREMONY = 1
    LATEST_CEREMONY = 44

    # Current official voting rules list these competitive categories.
    # async_categories() also augments this from the current official page.
    DEFAULT_CATEGORIES = [
        "Best Film",
        "Best Director",
        "Best Screenplay",
        "Best Actor",
        "Best Actress",
        "Best Supporting Actor",
        "Best Supporting Actress",
        "Best New Performer",
        "Best Cinematography",
        "Best Film Editing",
        "Best Art Direction",
        "Best Costume & Make Up Design",
        "Best Action Choreography",
        "Best Original Film Score",
        "Best Original Film Song",
        "Best Sound Design",
        "Best Visual Effects",
        "Best New Director",
        "Best Asian Chinese Language Film",
    ]

    def __init__(self, hass) -> None:
        super().__init__(hass)
        self._records_by_ceremony: dict[int, list[dict[str, Any]]] = {}

    @classmethod
    def _url(cls, ceremony: int) -> str:
        if ceremony == cls.LATEST_CEREMONY:
            return f"{cls.BASE_URL}/winnerlist.html"
        return f"{cls.BASE_URL}/winnerlist{ceremony:02d}.html"

    @staticmethod
    def _ceremony_year(ceremony: int) -> int:
        # 42nd=2024, 43rd=2025, 44th=2026. The inaugural ceremony was
        # held in 1982, so preserve that historical exception.
        if ceremony == 1:
            return 1982
        return ceremony + 1982

    @staticmethod
    def _looks_like_english_category(text: str) -> bool:
        value = re.sub(r"\s+", " ", text).strip()
        if not value:
            return False
        if value in {
            "Best Film",
            "Best Director",
            "Best Screenplay",
            "Best Actor",
            "Best Actress",
            "Best Supporting Actor",
            "Best Supporting Actress",
            "Best New Performer",
            "Best Cinematography",
            "Best Film Editing",
            "Best Art Direction",
            "Best Costume & Makeup Design",
            "Best Costume & Make Up Design",
            "Best Action Choreography",
            "Best Original Film Score",
            "Best Original Film Song",
            "Best Sound Design",
            "Best Visual Effects",
            "Best New Director",
            "Best Asian Chinese Language Film",
            "Best Asian Film",
        }:
            return True
        return bool(
            re.fullmatch(
                r"Best [A-Za-z][A-Za-z &'’/.-]{2,70}",
                value,
            )
        )

    @staticmethod
    def _clean_numbered(text: str) -> str:
        return re.sub(r"^\s*\d+\.\s*", "", text).strip()

    @staticmethod
    def _english_chunks(text: str) -> list[str]:
        """Extract useful English title-ish strings from bilingual text."""
        chunks: list[str] = []
        for line in re.split(r"[\n\r]+", text):
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            cleaned = HongKongFilmAwardsAdapter._clean_numbered(line)

            # Film title in parentheses is common in acting/directing/writing.
            for match in re.findall(r"\(([^()]{2,120})\)", cleaned):
                value = match.strip()
                if re.search(r"[A-Za-z]", value):
                    chunks.append(value)

            # All/mostly Latin lines are useful title candidates.
            latin = sum(ch.isascii() and ch.isalpha() for ch in cleaned)
            letters = sum(ch.isalpha() for ch in cleaned)
            if letters and latin / letters >= 0.65:
                # Drop obvious credits/company labels.
                if not re.match(
                    r"^(Presented|Produced|Executive Producer|Co-presented|"
                    r"Director|Screenplay|Cinematography|Music|Song|"
                    r"Costume|Visual Effects|Sound|Editing)\b",
                    cleaned,
                    re.I,
                ):
                    chunks.append(cleaned)

        result: list[str] = []
        for value in chunks:
            value = re.sub(r"^\d+\.\s*", "", value).strip(" -–—:;")
            if value and value not in result:
                result.append(value)
        return result

    @classmethod
    def _title_candidates(
        cls,
        nominee_text: str,
        category: str,
    ) -> list[str]:
        candidates = cls._english_chunks(nominee_text)

        # Best Film entries often contain "Chinese title English title" with
        # no parentheses. Prefer the final English-looking chunk.
        if category in {
            "Best Film",
            "Best Asian Chinese Language Film",
            "Best Asian Film",
        }:
            if candidates:
                return candidates[-2:] if len(candidates) > 1 else candidates

        # For person/crew categories, parenthesized film titles are generally
        # the best TMDB resolution candidate, so preserve those first.
        return candidates

    @classmethod
    def _parse_rows(
        cls,
        rows: list[list[str]],
        ceremony: int,
    ) -> list[dict[str, Any]]:
        """Parse official nominee/awardee table rows when table structure exists."""
        records: list[dict[str, Any]] = []
        award_year = cls._ceremony_year(ceremony)
        category: str | None = None

        for row in rows:
            cells = [re.sub(r"\s+", " ", c.replace("\n", " ")).strip() for c in row]
            if not cells:
                continue

            # Category rows often include Chinese and English headings in one
            # or adjacent cells.
            for cell in cells:
                lines = [
                    re.sub(r"\s+", " ", x).strip()
                    for x in re.split(r"[\n\r]+", cell)
                    if x.strip()
                ]
                for value in lines + [cell]:
                    if cls._looks_like_english_category(value):
                        category = value
                        break
                if category:
                    break

            if not category:
                continue

            # HKFAA tables conventionally have nominee/candidate and awardee
            # columns. Numbered cells are nominee entries.
            nominee_cells = [
                c for c in cells if re.match(r"^\s*\d+\.", c)
            ]
            if nominee_cells:
                for nominee in nominee_cells:
                    title_candidates = cls._title_candidates(
                        nominee, category
                    )
                    if not title_candidates:
                        continue
                    records.append(
                        {
                            "media_type": "movie",
                            "award_year": award_year,
                            "ceremony": ceremony,
                            "category": category,
                            "title": title_candidates[-1],
                            "title_candidates": title_candidates,
                            "stable_key": (
                                f"{award_year}:{category}:"
                                f"{title_candidates[-1].casefold()}"
                            ),
                            "winner": False,
                            "_nominee_text": nominee,
                        }
                    )

                # Any non-numbered cell after nominees can be the awardee.
                winner_text = " ".join(
                    c
                    for c in cells
                    if c
                    and not re.match(r"^\s*\d+\.", c)
                    and not cls._looks_like_english_category(c)
                )
                if winner_text:
                    cls._mark_winner(records, category, award_year, winner_text)

        return records

    @classmethod
    def _mark_winner(
        cls,
        records: list[dict[str, Any]],
        category: str,
        award_year: int,
        winner_text: str,
    ) -> None:
        """Match an official awardee cell to one nominee record."""
        normalized = re.sub(r"\s+", " ", winner_text).casefold()
        winner_candidates = [
            x.casefold() for x in cls._english_chunks(winner_text)
        ]

        candidates = [
            r
            for r in records
            if r["award_year"] == award_year
            and r["category"] == category
        ]

        # Prefer title candidate overlap.
        for record in candidates:
            record_titles = [
                str(x).casefold()
                for x in record.get("title_candidates", [])
            ]
            if any(
                title
                and (
                    title in normalized
                    or any(title == w or title in w or w in title for w in winner_candidates)
                )
                for title in record_titles
            ):
                record["winner"] = True
                return

        # Fallback to nominee/person text overlap.
        for record in candidates:
            nominee = re.sub(
                r"\s+", " ", str(record.get("_nominee_text", ""))
            ).casefold()
            if nominee and (
                nominee in normalized or normalized in nominee
            ):
                record["winner"] = True
                return

    @classmethod
    def _parse_lines_fallback(
        cls,
        lines: list[str],
        ceremony: int,
    ) -> list[dict[str, Any]]:
        """Fallback parser for older archive pages without useful tables."""
        records: list[dict[str, Any]] = []
        award_year = cls._ceremony_year(ceremony)
        category: str | None = None
        numbered_seen: dict[str, int] = {}

        for line in lines:
            value = re.sub(r"\s+", " ", line).strip()
            if cls._looks_like_english_category(value):
                category = value
                numbered_seen[category] = 0
                continue
            if not category:
                continue

            if re.match(r"^\d+\.", value):
                numbered_seen[category] += 1
                title_candidates = cls._title_candidates(value, category)
                if title_candidates:
                    records.append(
                        {
                            "media_type": "movie",
                            "award_year": award_year,
                            "ceremony": ceremony,
                            "category": category,
                            "title": title_candidates[-1],
                            "title_candidates": title_candidates,
                            "stable_key": (
                                f"{award_year}:{category}:"
                                f"{title_candidates[-1].casefold()}"
                            ),
                            "winner": False,
                            "_nominee_text": value,
                        }
                    )
                continue

            # Once numbered nominees exist, repeated title/person lines before
            # the next category are awardee text.
            if numbered_seen.get(category, 0):
                cls._mark_winner(
                    records,
                    category,
                    award_year,
                    value,
                )

        return records

    async def _load_ceremony(
        self,
        ceremony: int,
    ) -> list[dict[str, Any]]:
        if ceremony in self._records_by_ceremony:
            return self._records_by_ceremony[ceremony]

        url = self._url(ceremony)
        rows = await fetch_table_rows(self.hass, url)
        records = self._parse_rows(rows, ceremony)

        # Some old HKFAA pages have a much simpler layout; the plain-text
        # fallback can still recover winners/nominees that use numbered lists.
        if not records:
            lines = await fetch_lines(self.hass, url)
            records = self._parse_lines_fallback(lines, ceremony)

        # The first ceremonies can be winner-only pages. If no numbered
        # nominees are exposed, do not manufacture nominations. They remain
        # available only to winner-oriented filters when parsable.
        self._records_by_ceremony[ceremony] = records
        return records

    async def async_categories(
        self,
        media_type: str,
    ) -> list[dict[str, str]]:
        if media_type != "movie":
            return []

        # Use the latest official nominee page for the current category set.
        records = await self._load_ceremony(self.LATEST_CEREMONY)
        categories = sorted(
            {r["category"] for r in records if r.get("category")}
        )
        if not categories:
            categories = list(self.DEFAULT_CATEGORIES)

        return [
            {"value": "all", "label": "All categories"},
            *[
                {"value": category, "label": category}
                for category in categories
            ],
        ]

    async def async_latest_award_year(
        self,
        media_type: str,
    ) -> int:
        if media_type != "movie":
            raise ValueError(
                "Hong Kong Film Awards only supports movie media type"
            )
        return self._ceremony_year(self.LATEST_CEREMONY)

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

        first_year = self._ceremony_year(self.FIRST_CEREMONY)
        latest_year = self._ceremony_year(self.LATEST_CEREMONY)
        start = max(first_year, year_from or first_year)
        end = min(latest_year, year_to or latest_year)

        ceremonies = [
            ceremony
            for ceremony in range(
                self.FIRST_CEREMONY,
                self.LATEST_CEREMONY + 1,
            )
            if start <= self._ceremony_year(ceremony) <= end
        ]

        records: list[dict[str, Any]] = []
        for ceremony in ceremonies:
            try:
                records.extend(
                    await self._load_ceremony(ceremony)
                )
            except Exception:
                # A missing/moved historical page should not break unrelated
                # Media Watch feeds. Other ceremonies remain usable.
                continue

        selected = [
            record
            for record in records
            if in_year_range(
                int(record["award_year"]),
                year_from,
                year_to,
            )
            and (
                not category
                or category == "all"
                or record["category"] == category
            )
        ]
        return aggregate_records(selected, status)
