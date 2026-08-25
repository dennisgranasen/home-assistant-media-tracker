
"""Historical awards data helpers."""

from __future__ import annotations

import asyncio
import csv
import io
from collections import defaultdict
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import OSCARS_DATA_URL


class OscarsRepository:
    """Cached historical Academy Awards dataset.

    The source is DLu/oscar_data, a curated dataset derived from the official
    Academy Awards Database and carrying IMDb title IDs for robust TMDB
    resolution.
    """

    def __init__(self, hass) -> None:
        self.hass = hass
        self._records: list[dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    async def async_records(self) -> list[dict[str, Any]]:
        if self._records is not None:
            return self._records

        async with self._lock:
            if self._records is not None:
                return self._records

            session = async_get_clientsession(self.hass)
            async with session.get(
                OSCARS_DATA_URL,
                timeout=45,
            ) as response:
                response.raise_for_status()
                text = await response.text()

            reader = csv.DictReader(
                io.StringIO(text),
                delimiter="\t",
            )
            records: list[dict[str, Any]] = []
            for row in reader:
                film = (row.get("Film") or "").strip()
                film_id = (row.get("FilmId") or "").strip()
                if not film or not film_id:
                    continue

                year_text = (row.get("Year") or "").strip()
                year_first = year_text.split("/", 1)[0]
                try:
                    award_year = int(year_first)
                except ValueError:
                    continue

                try:
                    ceremony = int(row.get("Ceremony") or 0)
                except ValueError:
                    ceremony = 0

                canonical = (
                    row.get("CanonicalCategory") or ""
                ).strip()
                category = (row.get("Category") or "").strip()
                winner = (
                    str(row.get("Winner") or "").strip().lower()
                    == "true"
                )
                recipients = [
                    value.strip()
                    for value in str(row.get("Nominees") or "").split("|")
                    if value.strip()
                ]
                if not recipients:
                    name = str(row.get("Name") or "").strip()
                    if name:
                        recipients = [name]

                # Early Academy rows can associate one nomination with more
                # than one film. Split title and IMDb-ID pairs so filtering is
                # always film-centric.
                films = film.split("|")
                film_ids = film_id.split("|")
                for index, title in enumerate(films):
                    imdb_id = (
                        film_ids[index]
                        if index < len(film_ids)
                        else ""
                    ).strip()
                    if not imdb_id.startswith("tt"):
                        continue

                    records.append(
                        {
                            "organization": "Academy Awards",
                            "award_source": "oscars",
                            "ceremony": ceremony,
                            "award_year": award_year,
                            # For modern ceremonies this is award_year + 1.
                            # Keep both concepts explicit in the data model.
                            "ceremony_year": (
                                award_year + 1
                                if award_year >= 1934
                                else None
                            ),
                            "class": (row.get("Class") or "").strip(),
                            "canonical_category": canonical,
                            "category": category,
                            "film": title.strip(),
                            "imdb_id": imdb_id,
                            "winner": winner,
                            "recipients": recipients,
                        }
                    )

            self._records = records
            return records

    async def async_categories(self) -> list[str]:
        records = await self.async_records()
        return sorted(
            {
                record["canonical_category"]
                for record in records
                if record.get("canonical_category")
            }
        )

    async def async_latest_award_year(self) -> int:
        records = await self.async_records()
        return max(record["award_year"] for record in records)

    async def async_filter_films(
        self,
        *,
        year_from: int | None,
        year_to: int | None,
        category: str | None,
        status: str,
    ) -> list[dict[str, Any]]:
        """Return award facts collapsed to one record per film."""
        records = await self.async_records()

        year_selected = []
        for record in records:
            year = int(record["award_year"])
            if year_from is not None and year < year_from:
                continue
            if year_to is not None and year > year_to:
                continue
            year_selected.append(record)

        selected = []
        for record in year_selected:
            if category and category != "all":
                if record.get("canonical_category") != category:
                    continue
            selected.append(record)

        grouped: dict[str, dict[str, Any]] = {}
        for record in selected:
            imdb_id = record["imdb_id"]
            item = grouped.setdefault(
                imdb_id,
                {
                    "imdb_id": imdb_id,
                    "film": record["film"],
                    "award_years": set(),
                    "categories": set(),
                    "nominations": 0,
                    "wins": 0,
                    "winning_categories": set(),
                    "records": [],
                },
            )
            item["award_years"].add(record["award_year"])
            if record.get("canonical_category"):
                item["categories"].add(
                    record["canonical_category"]
                )
            item["nominations"] += 1
            if record["winner"]:
                item["wins"] += 1
                if record.get("canonical_category"):
                    item["winning_categories"].add(
                        record["canonical_category"]
                    )
            item["records"].append(record)

        person_wins_by_film: dict[
            str, list[dict[str, str]]
        ] = defaultdict(list)
        for record in year_selected:
            if not record.get("winner"):
                continue
            canonical = str(record.get("canonical_category") or "")
            normalized_category = canonical.upper()
            if normalized_category.startswith(("ACTOR", "ACTRESS")):
                role = "acting"
            elif normalized_category.startswith("DIRECTING"):
                role = "directing"
            else:
                continue

            wins = person_wins_by_film[record["imdb_id"]]
            for recipient in record.get("recipients", []):
                person_win = {
                    "name": str(recipient),
                    "role": role,
                    "category": canonical,
                }
                if person_win not in wins:
                    wins.append(person_win)

        result = []
        for item in grouped.values():
            wins = int(item["wins"])
            nominations = int(item["nominations"])

            if status == "winner" and wins < 1:
                continue
            if status == "nominated_no_win" and wins != 0:
                continue
            if (
                status == "nominated_and_won"
                and not (nominations >= 1 and wins >= 1)
            ):
                continue

            result.append(
                {
                    "imdb_id": item["imdb_id"],
                    "film": item["film"],
                    "award_years": sorted(item["award_years"]),
                    "categories": sorted(item["categories"]),
                    "nominations": nominations,
                    "wins": wins,
                    "winning_categories": sorted(
                        item["winning_categories"]
                    ),
                    "person_wins": person_wins_by_film.get(
                        item["imdb_id"], []
                    ),
                    "records": item["records"],
                }
            )

        result.sort(
            key=lambda item: (
                -max(item["award_years"]),
                -item["wins"],
                -item["nominations"],
                item["film"],
            )
        )
        return result
