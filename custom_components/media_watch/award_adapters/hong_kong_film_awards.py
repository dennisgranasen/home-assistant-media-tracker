
"""Hong Kong Film Awards adapter using the official HKFAA archive."""

from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)


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
        "Best Costume & Makeup Design",
        "Best Action Choreography",
        "Best Original Film Score",
        "Best Original Film Song",
        "Best Sound Design",
        "Best Visual Effects",
        "Best New Director",
        "Best Asian Chinese Language Film",
    ]

    CHINESE_CATEGORIES = {
        "最佳電影": "Best Film",
        "最佳導演": "Best Director",
        "最佳編劇": "Best Screenplay",
        "最佳男主角": "Best Actor",
        "最佳女主角": "Best Actress",
        "最佳男配角": "Best Supporting Actor",
        "最佳女配角": "Best Supporting Actress",
        "最佳新演員": "Best New Performer",
        "最佳攝影": "Best Cinematography",
        "最佳剪接": "Best Film Editing",
        "最佳美術指導": "Best Art Direction",
        "最佳服裝造型設計": "Best Costume & Makeup Design",
        "最佳動作設計": "Best Action Choreography",
        "最佳原創電影音樂": "Best Original Film Score",
        "最佳原創電影歌曲": "Best Original Film Song",
        "最佳音響效果": "Best Sound Design",
        "最佳視覺效果": "Best Visual Effects",
        "新晉導演": "Best New Director",
    }

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
            "Best Costume & Makeup Design",
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

    @classmethod
    def _category_name(cls, text: str) -> str | None:
        """Normalize an English or Chinese HKFAA category heading."""
        value = re.sub(r"\s+", " ", text).strip()
        if cls._looks_like_english_category(value):
            return value
        return cls.CHINESE_CATEGORIES.get(value)

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
    def _entry_lines(
        cls,
        nominee_text: str,
    ) -> list[str]:
        """Return nominee text before production-company credit lines."""
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in re.split(r"[\n\r]+", nominee_text)
            if re.sub(r"\s+", " ", line).strip()
        ]
        if lines:
            lines[0] = cls._clean_numbered(lines[0])

        # Credits follow the nominee title/person lines and must never become
        # TMDB title candidates (for example a production company ending in
        # "Hong Kong" or "Tianjin").
        entry_lines: list[str] = []
        for line in lines:
            if re.match(
                r"^(出品|監製|聯合出品|Presented|Produced|"
                r"Executive Producer|Co-presented)\b",
                line,
                re.I,
            ):
                break
            entry_lines.append(line)
        return entry_lines

    @classmethod
    def _title_candidates(
        cls,
        nominee_text: str,
        category: str,
    ) -> list[str]:
        entry_lines = cls._entry_lines(nominee_text)
        entry_text = "\n".join(entry_lines)

        top_film_categories = {
            "Best Film",
            "Best Asian Chinese Language Film",
            "Best Asian Film",
        }
        if category in top_film_categories and entry_lines:
            title_line = entry_lines[0]
            candidates = [title_line]
            english_suffix = re.search(
                r"([A-Z][A-Z0-9 &'’.,:!?/-]{1,119})$",
                title_line,
            )
            if english_suffix:
                english_title = english_suffix.group(1).strip()
                if english_title and english_title != title_line:
                    candidates.append(english_title)
                    words = english_title.split()
                    if (
                        len(words) >= 3
                        and len(words[0]) <= 4
                        and words[0] == words[-1]
                    ):
                        candidates.append(" ".join(words[1:]))
        else:
            # Person/crew categories put the English film title in
            # parentheses after the English recipient name. Never send the
            # recipient's name to TMDB as though it were a movie title.
            candidates = []
            for line in entry_lines:
                for value in re.findall(r"\(([^()]{1,120})\)", line):
                    value = value.strip()
                    if re.search(r"[A-Za-z]", value):
                        candidates.append(value)
            candidates = list(dict.fromkeys(candidates))
            if not candidates:
                candidates = cls._english_chunks(entry_text)

        # The earliest winner-only pages contain Chinese text only. Crew and
        # acting winners include the film title in parentheses; Best Film is
        # the title itself. TMDB can resolve these original-language titles.
        if not candidates:
            parenthesized = [
                value.strip()
                for value in re.findall(r"[（(]([^（）()]{1,120})[）)]", entry_text)
                if value.strip()
            ]
            if parenthesized:
                candidates.extend(parenthesized)
            elif category in {
                "Best Film",
                "Best Asian Chinese Language Film",
                "Best Asian Film",
            }:
                value = cls._clean_numbered(entry_text).strip()
                if value:
                    candidates.append(value)

        # Best Film entries often contain "Chinese title English title" with
        # no parentheses. Prefer the final English-looking chunk.
        if category in top_film_categories:
            if candidates:
                return candidates[-2:] if len(candidates) > 1 else candidates

        # For person/crew categories, parenthesized film titles are generally
        # the best TMDB resolution candidate, so preserve those first.
        return candidates

    @classmethod
    def _recipients(
        cls,
        nominee_text: str,
        category: str,
    ) -> list[str]:
        """Extract English recipient names from bilingual nominee text."""
        if category in {
            "Best Film",
            "Best Asian Chinese Language Film",
            "Best Asian Film",
        }:
            return []

        recipients: list[str] = []
        for line in cls._entry_lines(nominee_text):
            match = re.search(
                r"([A-Za-z][A-Za-z .,'’/-]+?)\s*\([^()]+\)\s*$",
                line,
            )
            if not match:
                continue
            for name in match.group(1).split(","):
                name = name.strip()
                if name and name not in recipients:
                    recipients.append(name)
        return recipients

    @classmethod
    def _parse_rows(
        cls,
        rows: list[list[str]],
        ceremony: int,
    ) -> list[dict[str, Any]]:
        """Parse HKFAA nominee/awardee tables.

        HKFAA mixes Chinese and English text inside the same table cell. Keep
        the original cell line boundaries while detecting category headings;
        flattening them first makes values such as "最佳電影\\nBest Film"
        impossible to recognize reliably.
        """
        records: list[dict[str, Any]] = []
        award_year = cls._ceremony_year(ceremony)
        category: str | None = None

        for raw_row in rows:
            if not raw_row:
                continue

            cell_lines: list[list[str]] = []
            flat_cells: list[str] = []
            for raw_cell in raw_row:
                lines = [
                    re.sub(r"\s+", " ", part).strip()
                    for part in re.split(r"[\n\r]+", raw_cell)
                    if re.sub(r"\s+", " ", part).strip()
                ]
                cell_lines.append(lines)
                flat_cells.append(" ".join(lines).strip())

            # Find an English category heading either on its own line or as
            # the English tail of a bilingual heading.
            detected_category: str | None = None
            for lines in cell_lines:
                for value in lines:
                    if normalized := cls._category_name(value):
                        detected_category = normalized
                        break
                if detected_category:
                    break

            if detected_category:
                category = detected_category

            if not category:
                continue

            # Numbered entries are nominees/candidates.
            nominee_cells: list[str] = []
            for lines in cell_lines:
                current_nominee: list[str] = []
                for line in lines:
                    if re.match(r"^\s*\d+\.", line):
                        if current_nominee:
                            nominee_cells.append(
                                "\n".join(current_nominee)
                            )
                        current_nominee = [line]
                    elif current_nominee:
                        current_nominee.append(line)
                if current_nominee:
                    nominee_cells.append("\n".join(current_nominee))

            for nominee in nominee_cells:
                title_candidates = cls._title_candidates(
                    nominee,
                    category,
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
                        "recipients": cls._recipients(
                            nominee,
                            category,
                        ),
                        "stable_key": (
                            f"{award_year}:"
                            f"{title_candidates[-1].casefold()}"
                        ),
                        "winner": False,
                        "_nominee_text": nominee,
                    }
                )

            if not nominee_cells:
                # Early archive pages expose two-column winner-only rows in
                # Chinese. Preserve only the explicit winner and do not infer
                # a missing nominee slate.
                if len(flat_cells) == 2:
                    title_candidates = cls._title_candidates(
                        flat_cells[1],
                        category,
                    )
                    if title_candidates:
                        records.append(
                            {
                                "media_type": "movie",
                                "award_year": award_year,
                                "ceremony": ceremony,
                                "category": category,
                                "title": title_candidates[-1],
                                "title_candidates": title_candidates,
                                "recipients": cls._recipients(
                                    flat_cells[1],
                                    category,
                                ),
                                "stable_key": (
                                    f"{award_year}:"
                                    f"{title_candidates[-1].casefold()}"
                                ),
                                "winner": True,
                            }
                        )
                continue

            # The awardee is normally in a separate non-numbered table cell.
            winner_parts: list[str] = []
            for lines, flat in zip(cell_lines, flat_cells):
                if not flat:
                    continue
                if re.match(r"^\s*\d+\.", flat):
                    continue
                if any(
                    cls._looks_like_english_category(value)
                    for value in lines
                ):
                    continue

                # Skip table headers.
                if flat.casefold() in {
                    "nominee",
                    "nominees",
                    "candidate",
                    "candidates",
                    "awardee",
                    "winner",
                    "得獎者",
                    "候選者",
                    "獎項",
                }:
                    continue

                winner_parts.extend(lines)

            if winner_parts:
                cls._mark_winner(
                    records,
                    category,
                    award_year,
                    " ".join(winner_parts),
                )

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
            if normalized := cls._category_name(value):
                category = normalized
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
                                f"{award_year}:"
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
        cached = self._records_by_ceremony.get(ceremony)
        if cached:
            return cached

        url = self._url(ceremony)
        rows = await fetch_table_rows(
            self.hass,
            url,
            number_ordered_list_items=True,
        )
        records = self._parse_rows(rows, ceremony)

        # Some old HKFAA pages have a much simpler layout; the plain-text
        # fallback can still recover winners/nominees that use numbered lists.
        if not records:
            lines = await fetch_lines(self.hass, url)
            records = self._parse_lines_fallback(lines, ceremony)

        if not records:
            _LOGGER.warning(
                "HKFAA ceremony %s returned no parseable award records",
                ceremony,
            )

        # The first ceremonies can be winner-only pages. If no numbered
        # nominees are exposed, do not manufacture nominations. They remain
        # available only to winner-oriented filters when parsable.
        if records:
            self._records_by_ceremony[ceremony] = records
        return records

    async def async_categories(
        self,
        media_type: str,
    ) -> list[dict[str, str]]:
        if media_type != "movie":
            return []

        # Prefer the current official archive, but profile configuration must
        # remain usable if HKFAA is temporarily unavailable or changes markup.
        try:
            records = await self._load_ceremony(
                self.LATEST_CEREMONY
            )
            categories = sorted(
                {
                    str(record["category"])
                    for record in records
                    if record.get("category")
                }
            )
        except Exception:
            categories = []

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
            except Exception as err:  # noqa: BLE001
                # A missing/moved historical page should not break unrelated
                # Media Watch feeds. Other ceremonies remain usable.
                _LOGGER.warning(
                    "Could not load HKFAA ceremony %s: %s",
                    ceremony,
                    err,
                )
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
