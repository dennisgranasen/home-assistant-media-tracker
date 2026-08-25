"""Regression tests for discovery-profile coordinator refactors."""

from __future__ import annotations

import asyncio
from types import MethodType, SimpleNamespace

import pytest

from custom_components.media_watch import coordinator as coordinator_module
from custom_components.media_watch.const import (
    PROFILE_AWARD_OSCARS_BEST_PICTURE_2026,
)
from custom_components.media_watch.coordinator import MediaWatchCoordinator
from custom_components.media_watch.award_adapters.web_common import (
    aggregate_records,
)


class _Store:
    watched_movies: list[int] = []
    watched_tv: list[int] = []

    def is_watched(self, _media_type: str, _tmdb_id: int) -> bool:
        return False

    def is_dismissed(self, _media_type: str, _tmdb_id: int) -> bool:
        return False


def _coordinator() -> MediaWatchCoordinator:
    coordinator = object.__new__(MediaWatchCoordinator)
    coordinator.store = _Store()
    coordinator.hass = SimpleNamespace(data={})
    coordinator._award_tmdb_cache = {}
    return coordinator


def test_legacy_release_dates_apply_to_post_filter() -> None:
    coordinator = _coordinator()
    profile = {
        "release_date_gte": "2020-01-01",
        "release_date_lte": "2021-12-31",
    }
    items = [
        {"id": 1, "release_date": "2019-05-01"},
        {"id": 2, "release_date": "2020-05-01"},
        {"id": 3, "release_date": "2021-09-01"},
        {"id": 4, "release_date": "2022-01-01"},
    ]

    result = coordinator._profile_post_filter(items, profile, "movie")

    assert [item["id"] for item in result] == [2, 3]


def test_web_awards_merge_categories_but_separate_same_title_by_year() -> None:
    records = [
        {
            "title": "Shared title",
            "title_candidates": ["Shared title"],
            "award_year": 1990,
            "category": "Film",
            "winner": True,
        },
        {
            "title": "Shared title",
            "title_candidates": ["Shared title"],
            "award_year": 1990,
            "category": "Director",
            "winner": False,
        },
        {
            "title": "Shared title",
            "title_candidates": ["Shared title"],
            "award_year": 2020,
            "category": "Film",
            "winner": False,
        },
    ]

    result = aggregate_records(records, "any")

    assert len(result) == 2
    older = next(item for item in result if item["award_years"] == [1990])
    assert older["categories"] == ["Director", "Film"]
    assert older["nominations"] == 2
    assert older["wins"] == 1


def test_fixed_oscars_are_loaded_only_for_legacy_profile() -> None:
    coordinator = _coordinator()
    coordinator.entry = SimpleNamespace(options={"discovery_profiles": []})
    assert coordinator._needs_legacy_oscar_movies() is False

    coordinator.entry.options["discovery_profiles"] = [
        {
            "id": "legacy",
            "name": "Legacy Oscars",
            "media_type": "movie",
            "award_filter": PROFILE_AWARD_OSCARS_BEST_PICTURE_2026,
        }
    ]
    assert coordinator._needs_legacy_oscar_movies() is True


def test_award_status_is_applied_after_category_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Adapter:
        info = SimpleNamespace(media_types={"movie"})

        async def async_latest_award_year(self, _media_type):
            return 2026

        async def async_categories(self, _media_type):
            return [
                {"value": "all", "label": "All"},
                {"value": "Film A", "label": "Film A"},
                {"value": "Film B", "label": "Film B"},
            ]

        async def async_filter_titles(self, *, category, status, **_kwargs):
            assert status == "any"
            return [
                {
                    "title": "Shared title",
                    "stable_key": "shared title",
                    "award_years": [2026],
                    "categories": [category],
                    "winning_categories": [category] if category == "Film A" else [],
                    "nominations": 1,
                    "wins": 1 if category == "Film A" else 0,
                }
            ]

    coordinator = _coordinator()
    monkeypatch.setattr(
        coordinator_module, "create_adapter", lambda _hass, _source: Adapter()
    )
    monkeypatch.setattr(
        coordinator_module,
        "resolve_source_categories",
        lambda *_args: ["Film A", "Film B"],
    )

    async def resolve(self, item, *, media_type, award_source):
        return {
            "id": 10,
            "award": {
                "source": award_source,
                "award_years": item["award_years"],
                "categories": item["categories"],
                "winning_categories": item["winning_categories"],
                "nominations": item["nominations"],
                "wins": item["wins"],
            },
        }

    coordinator._resolve_award_title = MethodType(resolve, coordinator)
    base_profile = {
        "media_type": "movie",
        "award_source": "test",
        "award_category_mode": "generic",
        "award_generic_category": "best_film",
    }

    excluded = asyncio.run(
        coordinator._award_profile_candidates(
            {**base_profile, "award_status": "nominated_no_win"},
            resolution_batch_size=1,
        )
    )
    included = asyncio.run(
        coordinator._award_profile_candidates(
            {**base_profile, "award_status": "nominated_and_won"},
            resolution_batch_size=1,
        )
    )

    assert excluded == []
    assert included[0]["award"]["nominations"] == 2
    assert included[0]["award"]["wins"] == 1


def test_award_resolution_batch_size_does_not_truncate_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Adapter:
        info = SimpleNamespace(media_types={"movie"})

        async def async_latest_award_year(self, _media_type):
            return 2026

        async def async_categories(self, _media_type):
            return [{"value": "all", "label": "All"}]

        async def async_filter_titles(self, **_kwargs):
            return [
                {
                    "title": f"Title {index}",
                    "award_years": [2026],
                    "categories": ["all"],
                    "winning_categories": [],
                    "nominations": 1,
                    "wins": 0,
                }
                for index in range(5)
            ]

    coordinator = _coordinator()
    monkeypatch.setattr(
        coordinator_module, "create_adapter", lambda _hass, _source: Adapter()
    )

    async def resolve(self, item, **_kwargs):
        return {
            "id": int(item["title"].split()[-1]),
            "award": {
                "award_years": item["award_years"],
                "categories": item["categories"],
                "winning_categories": [],
                "nominations": 1,
                "wins": 0,
            },
        }

    coordinator._resolve_award_title = MethodType(resolve, coordinator)

    result = asyncio.run(
        coordinator._award_profile_candidates(
            {"media_type": "movie", "award_source": "test"},
            resolution_batch_size=2,
        )
    )

    assert [item["id"] for item in result] == [0, 1, 2, 3, 4]


def test_title_cache_separates_award_year_hints() -> None:
    class Api:
        calls = 0

        async def search_movies(self, _title, _language):
            self.calls += 1
            return [{"id": self.calls, "release_date": "2020-01-01"}]

    coordinator = _coordinator()
    coordinator.api = Api()
    coordinator._profile_language = None
    coordinator._profile_region = None
    coordinator.entry = SimpleNamespace(options={"language": "en-US"})

    async def enrich(self, candidate):
        return {"id": candidate["id"]}

    coordinator._enrich_movie = MethodType(enrich, coordinator)

    first = asyncio.run(
        coordinator._resolve_award_title(
            {"title": "Same title", "award_years": [1990]},
            media_type="movie",
            award_source="test",
        )
    )
    second = asyncio.run(
        coordinator._resolve_award_title(
            {"title": "Same title", "award_years": [2020]},
            media_type="movie",
            award_source="test",
        )
    )

    assert first["id"] != second["id"]
    assert coordinator.api.calls == 2
