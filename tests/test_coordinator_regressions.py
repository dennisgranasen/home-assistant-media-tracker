"""Regression tests for discovery-profile coordinator refactors."""

from __future__ import annotations

import asyncio
from types import MethodType, SimpleNamespace

import pytest

from custom_components.media_watch import coordinator as coordinator_module
from custom_components.media_watch import api as api_module
from custom_components.media_watch.api import TMDBApi
from custom_components.media_watch.const import (
    AWARD_PRESET_BEST_PICTURE_WINNERS,
    AWARD_SOURCE_ANY,
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
    coordinator.hass = SimpleNamespace(
        data={},
        async_create_task=lambda coro, *, name=None: asyncio.create_task(
            coro,
            name=name,
        ),
    )
    coordinator._award_tmdb_cache = {}
    coordinator._watchlist_award_task = None
    coordinator.async_update_listeners = lambda: None
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


def test_profile_post_filter_excludes_watchlist_watched_and_dismissed() -> None:
    class Store:
        def is_watched(self, _media_type: str, tmdb_id: int) -> bool:
            return tmdb_id == 2

        def is_dismissed(self, _media_type: str, tmdb_id: int) -> bool:
            return tmdb_id == 3

    coordinator = _coordinator()
    coordinator.store = Store()
    items = [{"id": tmdb_id} for tmdb_id in range(1, 6)]

    result = coordinator._profile_post_filter(
        items,
        {},
        "movie",
        excluded_ids={1},
    )

    assert [item["id"] for item in result] == [4, 5]


def test_profile_post_filter_can_include_watched_titles() -> None:
    class Store:
        def is_watched(self, _media_type: str, tmdb_id: int) -> bool:
            return tmdb_id == 2

        def is_dismissed(self, _media_type: str, tmdb_id: int) -> bool:
            return tmdb_id == 3

    coordinator = _coordinator()
    coordinator.store = Store()
    items = [{"id": tmdb_id} for tmdb_id in range(1, 6)]

    result = coordinator._profile_post_filter(
        items,
        {"exclude_watched": False},
        "movie",
        excluded_ids={1},
    )

    assert [item["id"] for item in result] == [2, 4, 5]


def test_movie_enrichment_exposes_ui_metadata_without_extra_endpoint() -> None:
    class Api:
        async def get_movie_details(self, _tmdb_id, language):
            if language == "en-US":
                return {"tagline": "Fallback tagline"}
            return {
                "id": 7,
                "title": "Localized title",
                "original_title": "Original title",
                "original_language": "fr",
                "external_ids": {"imdb_id": "tt1234567"},
                "tagline": "",
                "runtime": 123,
                "production_countries": [
                    {"iso_3166_1": "FR", "name": "France"}
                ],
                "belongs_to_collection": {
                    "id": 99,
                    "name": "Example Collection",
                    "poster_path": "/collection.jpg",
                    "backdrop_path": "/collection-backdrop.jpg",
                },
                "credits": {
                    "crew": [
                        {"job": "Director", "name": "Director One"},
                        {"job": "Director", "name": "Director One"},
                    ],
                    "cast": [
                        {"name": "Actor One"},
                        {"name": "Actor Two"},
                        {"name": "Actor Three"},
                        {"name": "Actor Four"},
                    ],
                },
                "genres": [],
            }

        async def get_movie_watch_providers(self, _tmdb_id):
            return {"results": {}}

    coordinator = _coordinator()
    coordinator.api = Api()
    coordinator.entry = SimpleNamespace(
        options={
            "language": "sv-SE",
            "fallback_language": "en-US",
        }
    )
    coordinator._profile_language = None
    coordinator._profile_region = None

    result = asyncio.run(coordinator._enrich_movie({"id": 7}))

    assert result["tagline"] == "Fallback tagline"
    assert result["runtime"] == 123
    assert result["original_language"] == "fr"
    assert result["imdb_id"] == "tt1234567"
    assert result["production_countries"] == [
        {"code": "FR", "name": "France"}
    ]
    assert result["collection"]["name"] == "Example Collection"
    assert result["directors"] == ["Director One"]
    assert result["cast"] == ["Actor One", "Actor Two", "Actor Three"]


def test_award_summary_uses_source_details_without_double_counting_any() -> None:
    item = {
        "award": {
            "source": "any",
            "nominations": 3,
            "wins": 1,
        },
        "awards": [
            {
                "source": "oscars",
                "organization": "Academy Awards",
                "award_years": [2024],
                "categories": ["Best Picture"],
                "winning_categories": ["Best Picture"],
                "recipients": ["Director One"],
                "nominations": 1,
                "wins": 1,
            },
            {
                "source": "bafta_film",
                "organization": "BAFTA Film Awards",
                "award_years": [2024],
                "categories": ["Best Film", "Director"],
                "winning_categories": [],
                "recipients": ["Writer One", "Writer Two"],
                "nominations": 2,
                "wins": 0,
            },
        ],
    }

    summary = MediaWatchCoordinator._award_summary(item)

    assert summary == {
        "nominations": 3,
        "wins": 1,
        "winner": True,
        "sources": ["bafta_film", "oscars"],
        "organizations": ["Academy Awards", "BAFTA Film Awards"],
        "award_years": [2024],
        "categories": ["Best Film", "Best Picture", "Director"],
        "winning_categories": ["Best Picture"],
        "recipients": ["Director One", "Writer One", "Writer Two"],
    }


def test_award_recipient_overrides_localized_director_name() -> None:
    coordinator = _coordinator()

    async def enrich(self, candidate):
        return {"id": candidate["id"], "directors": ["梁栢堅"]}

    coordinator._enrich_movie = MethodType(enrich, coordinator)

    result = asyncio.run(
        coordinator._resolve_award_title(
            {
                "tmdb_id": 7,
                "categories": ["Best Director"],
                "recipients": ["Patrick Leung Pak Kin"],
            },
            media_type="movie",
            award_source="hong_kong_film_awards",
        )
    )

    assert result["directors"] == ["Patrick Leung Pak Kin"]
    assert result["award"]["recipients"] == [
        "Patrick Leung Pak Kin"
    ]


def test_watchlist_movies_receive_cached_top_film_awards(
    monkeypatch,
) -> None:
    calls: list[tuple[str, int, int, str]] = []

    class Adapter:
        def __init__(self, source, label, category, records):
            self.info = SimpleNamespace(source=source, label=label)
            self.category = category
            self.records = records

        async def async_categories(self, media_type):
            assert media_type == "movie"
            return [
                {"value": "all", "label": "All"},
                {"value": self.category, "label": self.category},
            ]

        async def async_filter_titles(
            self, *, media_type, year_from, year_to, category, status
        ):
            assert media_type == "movie"
            assert status == "any"
            calls.append((self.info.source, year_from, year_to, category))
            return list(self.records)

    adapters = {
        "oscars": Adapter(
            "oscars",
            "Academy Awards (Oscars)",
            "BEST PICTURE",
            [
                {
                    "title": "Localized title does not matter",
                    "imdb_id": "tt1234567",
                    "award_years": [2024],
                    "categories": ["BEST PICTURE"],
                    "nominations": 1,
                    "wins": 1,
                    "winning_categories": ["BEST PICTURE"],
                }
            ],
        ),
        "guldbaggen": Adapter(
            "guldbaggen",
            "Guldbaggen",
            "Bästa film",
            [
                {
                    "title": "En annan titel",
                    "award_years": [2024],
                    "categories": ["Bästa film"],
                    "nominations": 1,
                    "wins": 0,
                    "winning_categories": [],
                },
                {
                    "title": "Återträffen",
                    "title_candidates": ["Återträffen"],
                    "award_years": [2024],
                    "categories": ["Bästa film"],
                    "nominations": 1,
                    "wins": 1,
                    "winning_categories": ["Bästa film"],
                }
            ],
        ),
    }
    monkeypatch.setattr(
        coordinator_module,
        "providers_for_media_type",
        lambda media_type: [adapter.info for adapter in adapters.values()],
    )
    monkeypatch.setattr(
        coordinator_module,
        "create_adapter",
        lambda hass, source: adapters[source],
    )
    coordinator = _coordinator()
    coordinator._watchlist_top_film_index_key = None
    coordinator._watchlist_top_film_by_imdb = {}
    coordinator._watchlist_top_film_by_title = {}
    movies = [
        {
            "id": 1,
            "imdb_id": "tt1234567",
            "title": "En annan titel",
            "release_date": "2023-05-01",
        },
        {
            "id": 2,
            "imdb_id": "tt7654321",
            "title": "The Reunion",
            "original_title": "Atertraffen",
            "release_date": "2023-09-01",
        },
    ]

    async def enrich() -> None:
        await coordinator._async_enrich_watchlist_awards(movies)
        assert "award" not in movies[0]
        await coordinator._watchlist_award_task
        await asyncio.sleep(0)
        await coordinator._async_enrich_watchlist_awards(movies)

    asyncio.run(enrich())

    assert len(calls) == 2
    assert movies[0]["award"]["source"] == "any"
    assert [award["source"] for award in movies[0]["awards"]] == [
        "guldbaggen",
        "oscars",
    ]
    assert [
        badge["icon"]
        for badge in movies[0]["award_summary"]["badges"]
    ] == ["mdi:bug-outline", "mdi:trophy-award"]
    assert movies[0]["award_summary"]["winner"] is True
    assert movies[0]["award_summary"]["winning_categories"] == [
        "BEST PICTURE"
    ]
    assert movies[1]["award"]["source"] == "guldbaggen"
    assert movies[1]["award"]["badge"]["icon"] == "mdi:bug-outline"
    assert movies[1]["award_summary"]["badges"] == [
        {
            "source": "guldbaggen",
            "label": "Guldbaggen",
            "icon": "mdi:bug-outline",
        }
    ]


def test_movie_details_append_credits_and_external_ids() -> None:
    api = object.__new__(TMDBApi)
    captured: dict[str, object] = {}

    async def request(self, method, path, **kwargs):
        captured.update(
            {"method": method, "path": path, **kwargs}
        )
        return {}

    api._request = MethodType(request, api)

    asyncio.run(api.get_movie_details(7, "sv-SE"))

    assert captured["path"] == "/movie/7"
    assert captured["params"] == {
        "language": "sv-SE",
        "append_to_response": "credits,external_ids",
    }


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


def test_top_film_preset_merges_mapped_source_categories(
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
    result = asyncio.run(
        coordinator._award_profile_candidates(
            {
                "media_type": "movie",
                "award_source": "test",
                "award_preset": AWARD_PRESET_BEST_PICTURE_WINNERS,
            },
            target_limit=1,
            resolution_batch_size=1,
        )
    )

    assert result[0]["award"]["nominations"] == 2
    assert result[0]["award"]["wins"] == 1


def test_award_winner_must_match_selected_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Adapter:
        info = SimpleNamespace(media_types={"movie"})

        async def async_latest_award_year(self, _media_type):
            return 2026

        async def async_categories(self, _media_type):
            return [
                {"value": "all", "label": "All"},
                {"value": "BEST PICTURE", "label": "Best Picture"},
            ]

        async def async_filter_titles(self, **_kwargs):
            # Simulate an adapter returning title-level facts broader than
            # the requested category. Only the second title won Best Picture.
            return [
                {
                    "title": "Won directing only",
                    "stable_key": "wrong",
                    "award_years": [2026],
                    "categories": ["BEST PICTURE", "DIRECTING"],
                    "winning_categories": ["DIRECTING"],
                    "nominations": 2,
                    "wins": 1,
                },
                {
                    "title": "Won Best Picture",
                    "stable_key": "right",
                    "award_years": [2026],
                    "categories": ["BEST PICTURE"],
                    "winning_categories": ["BEST PICTURE"],
                    "nominations": 1,
                    "wins": 1,
                },
            ]

    coordinator = _coordinator()
    monkeypatch.setattr(
        coordinator_module,
        "create_adapter",
        lambda _hass, _source: Adapter(),
    )

    async def resolve(self, item, **_kwargs):
        return {
            "id": 1 if item["stable_key"] == "wrong" else 2,
            "award": {
                "award_years": item["award_years"],
                "categories": item["categories"],
                "winning_categories": item["winning_categories"],
                "nominations": item["nominations"],
                "wins": item["wins"],
            },
        }

    coordinator._resolve_award_title = MethodType(resolve, coordinator)

    result = asyncio.run(
        coordinator._award_profile_candidates(
            {
                "media_type": "movie",
                "award_source": "test",
                "award_category": "BEST PICTURE",
                "award_status": "winner",
            },
            target_limit=10,
            resolution_batch_size=2,
        )
    )

    assert [item["id"] for item in result] == [2]


def test_any_award_aggregates_sources_and_isolates_failed_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Adapter:
        info = SimpleNamespace(media_types={"movie"})

        def __init__(
            self,
            source: str,
            category: str,
            *,
            winner: bool,
        ) -> None:
            self.source = source
            self.category = category
            self.winner = winner

        async def async_categories(self, _media_type):
            return [
                {"value": "all", "label": "All"},
                {"value": self.category, "label": self.category},
            ]

        async def async_filter_titles(self, **_kwargs):
            return [
                {
                    "title": "Shared winner",
                    "imdb_id": "tt1234567",
                    "award_years": [2026],
                    "categories": [self.category],
                    "winning_categories": (
                        [self.category] if self.winner else []
                    ),
                    "nominations": 1,
                    "wins": 1 if self.winner else 0,
                }
            ]

    class FailingAdapter(Adapter):
        async def async_categories(self, _media_type):
            raise RuntimeError("source unavailable")

    adapters = {
        "source_a": Adapter("source_a", "A BEST", winner=True),
        "source_b": Adapter("source_b", "B BEST", winner=False),
        "source_bad": FailingAdapter(
            "source_bad", "BAD BEST", winner=False
        ),
    }
    coordinator = _coordinator()
    monkeypatch.setattr(
        coordinator_module,
        "providers_for_media_type",
        lambda _media_type: [
            SimpleNamespace(source=source) for source in adapters
        ],
    )
    monkeypatch.setattr(
        coordinator_module,
        "create_adapter",
        lambda _hass, source: adapters[source],
    )
    monkeypatch.setattr(
        coordinator_module,
        "resolve_source_categories",
        lambda source, generic, _options: (
            [adapters[source].category]
            if generic == "best_film" and source != "source_bad"
            else []
        ),
    )

    async def resolve(self, item, *, award_source, **_kwargs):
        return {
            "id": 42,
            "award": {
                "organization": award_source,
                "source": award_source,
                "award_years": item["award_years"],
                "categories": item["categories"],
                "winning_categories": item["winning_categories"],
                "nominations": item["nominations"],
                "wins": item["wins"],
            },
        }

    coordinator._resolve_award_title = MethodType(resolve, coordinator)

    result = asyncio.run(
        coordinator._award_profile_candidates(
            {
                "media_type": "movie",
                "award_source": AWARD_SOURCE_ANY,
                "award_category": "best_film",
                "award_status": "winner",
            },
            target_limit=1,
            resolution_batch_size=1,
        )
    )

    assert len(result) == 1
    assert result[0]["award"]["source"] == AWARD_SOURCE_ANY
    assert result[0]["award"]["sources"] == ["source_a", "source_b"]
    assert result[0]["award"]["wins"] == 1
    assert [award["source"] for award in result[0]["awards"]] == [
        "source_a",
        "source_b",
    ]

    no_win_result = asyncio.run(
        coordinator._award_profile_candidates(
            {
                "media_type": "movie",
                "award_source": AWARD_SOURCE_ANY,
                "award_category": "best_film",
                "award_status": "nominated_no_win",
            },
            target_limit=1,
            resolution_batch_size=1,
        )
    )
    assert no_win_result == []


def test_any_award_no_win_checks_later_results_from_every_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Adapter:
        info = SimpleNamespace(media_types={"movie"})

        def __init__(self, source: str) -> None:
            self.source = source

        async def async_categories(self, _media_type):
            return [{"value": "all", "label": "All"}]

        async def async_filter_titles(self, **_kwargs):
            if self.source == "early_nomination":
                return [
                    {
                        "title": "Shared film",
                        "imdb_id": "tt1234567",
                        "categories": ["Best Film"],
                        "winning_categories": [],
                        "nominations": 1,
                        "wins": 0,
                    }
                ]
            return [
                {
                    "title": "Unrelated film",
                    "imdb_id": "tt7654321",
                    "categories": ["Best Film"],
                    "winning_categories": [],
                    "nominations": 1,
                    "wins": 0,
                },
                {
                    "title": "Shared film",
                    "imdb_id": "tt1234567",
                    "categories": ["Best Film"],
                    "winning_categories": ["Best Film"],
                    "nominations": 1,
                    "wins": 1,
                },
            ]

    adapters = {
        source: Adapter(source)
        for source in ("early_nomination", "later_win")
    }
    coordinator = _coordinator()
    monkeypatch.setattr(
        coordinator_module,
        "providers_for_media_type",
        lambda _media_type: [
            SimpleNamespace(source=source) for source in adapters
        ],
    )
    monkeypatch.setattr(
        coordinator_module,
        "create_adapter",
        lambda _hass, source: adapters[source],
    )
    monkeypatch.setattr(
        coordinator_module,
        "resolve_source_categories",
        lambda _source, _generic, _options: ["all"],
    )

    async def resolve(self, item, *, award_source, **_kwargs):
        return {
            "id": 42 if item["title"] == "Shared film" else 99,
            "award": {
                "organization": award_source,
                "source": award_source,
                "award_years": [],
                "categories": item["categories"],
                "winning_categories": item["winning_categories"],
                "nominations": item["nominations"],
                "wins": item["wins"],
            },
        }

    coordinator._resolve_award_title = MethodType(resolve, coordinator)

    result = asyncio.run(
        coordinator._award_profile_candidates(
            {
                "media_type": "movie",
                "award_source": AWARD_SOURCE_ANY,
                "award_category": "all",
                "award_status": "nominated_no_win",
            },
            target_limit=1,
            resolution_batch_size=1,
        )
    )

    assert [item["id"] for item in result] == [99]


def test_award_resolution_continues_until_filters_have_enough_candidates(
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

    resolved_ids: list[int] = []

    async def resolve(self, item, **_kwargs):
        tmdb_id = int(item["title"].split()[-1])
        resolved_ids.append(tmdb_id)
        return {
            "id": tmdb_id,
            "available_on_my_services": tmdb_id >= 2,
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
            {
                "media_type": "movie",
                "award_source": "test",
                "provider_scope": "my",
            },
            target_limit=1,
            resolution_batch_size=2,
            excluded_ids={2},
        )
    )

    filtered = coordinator._profile_post_filter(
        result,
        {"provider_scope": "my"},
        "movie",
        excluded_ids={2},
    )
    assert [item["id"] for item in filtered] == [3]
    assert resolved_ids == [0, 1, 2, 3]


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


def test_tmdb_rate_limit_retries_after_server_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, status, payload=None, headers=None):
            self.status = status
            self._payload = payload or {}
            self.headers = headers or {}
            self.content_type = "application/json"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        async def json(self):
            return self._payload

    class Session:
        def __init__(self):
            self.responses = [
                Response(429, headers={"Retry-After": "2"}),
                Response(200, payload={"ok": True}),
            ]

        def request(self, *_args, **_kwargs):
            return self.responses.pop(0)

    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    api = TMDBApi(Session(), "token")

    result = asyncio.run(
        api._request("GET", "/test", include_session=False)
    )

    assert result == {"ok": True}
    assert delays == [2.0]
