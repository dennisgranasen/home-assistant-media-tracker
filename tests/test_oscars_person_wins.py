"""Oscar recipient and person-win regression tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.media_watch.awards import OscarsRepository


def test_oscar_parser_preserves_nominee_names() -> None:
    payload = (
        "Ceremony\tYear\tClass\tCanonicalCategory\tCategory\tFilm\t"
        "FilmId\tName\tNominees\tNomineeIds\tWinner\n"
        "97\t2024\tActing\tACTRESS IN A LEADING ROLE\tACTRESS\t"
        "Anora\ttt28607951\tMikey Madison\tMikey Madison\tnm10673221\tTrue\n"
    )

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self) -> None:
            return None

        async def text(self) -> str:
            return payload

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    repository = OscarsRepository(SimpleNamespace(session=Session()))
    records = asyncio.run(repository.async_records())

    assert records[0]["recipients"] == ["Mikey Madison"]


def test_best_picture_filter_includes_person_wins_from_same_year() -> None:
    repository = OscarsRepository(None)
    repository._records = [
        {
            "imdb_id": "tt1",
            "film": "Example",
            "award_year": 2024,
            "canonical_category": "BEST PICTURE",
            "winner": True,
            "recipients": ["Studio"],
        },
        {
            "imdb_id": "tt1",
            "film": "Example",
            "award_year": 2024,
            "canonical_category": "ACTRESS IN A LEADING ROLE",
            "winner": True,
            "recipients": ["Actor One"],
        },
        {
            "imdb_id": "tt1",
            "film": "Example",
            "award_year": 2024,
            "canonical_category": "DIRECTING",
            "winner": True,
            "recipients": ["Director One"],
        },
        {
            "imdb_id": "tt1",
            "film": "Example",
            "award_year": 2020,
            "canonical_category": "ACTOR IN A LEADING ROLE",
            "winner": True,
            "recipients": ["Wrong Year"],
        },
    ]

    result = asyncio.run(
        repository.async_filter_films(
            year_from=2024,
            year_to=2024,
            category="BEST PICTURE",
            status="winner",
        )
    )

    assert result[0]["wins"] == 1
    assert result[0]["person_wins"] == [
        {
            "name": "Actor One",
            "role": "acting",
            "category": "ACTRESS IN A LEADING ROLE",
        },
        {
            "name": "Director One",
            "role": "directing",
            "category": "DIRECTING",
        },
    ]
