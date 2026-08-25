# Award Adapter Development

Media Watch uses award adapters so award sources can be added without changing
the discovery-card contract or the general profile UI.

## Current adapters

| Source | Media | Nominees/selections | Winners | Upstream |
|---|---|---:|---:|---|
| Academy Awards (Oscars) | Movies | Yes | Yes | Academy-derived curated dataset |
| Guldbaggen | Movies | Yes | Yes* | Official Guldbaggen archive |
| BAFTA Film Awards | Movies | Yes | Yes | Official BAFTA awards search |
| BAFTA Television Awards | TV | Yes | Yes | Official BAFTA awards search |
| Golden Globes – Film | Movies | Yes | Yes | Official Golden Globes nomination pages |
| Golden Globes – Television | TV | Yes | Yes | Official Golden Globes nomination pages |
| Primetime Emmy Awards | TV | Yes | Yes | Television Academy year pages |
| Festival de Cannes | Movies | Competition selection | Yes | Official Cannes retrospective |

`*` Guldbaggen's archive exposes historical nominees cleanly; winner marking varies
across archive generations, so the adapter also overlays explicit winner markers
when the official site exposes them.

## Architecture

Each adapter has three responsibilities:

1. Load and cache its historical award source.
2. Normalize award/category/title information.
3. Return title-level award facts to Media Watch.

The adapter should **not** fetch TMDB posters, providers, ratings or localized
metadata. The normal Media Watch enrichment pipeline does that after the award
candidate set has been built.

Files:

```text
custom_components/media_watch/
  award_adapter.py
  award_registry.py
  award_adapters/
    __init__.py
    oscars.py
```

## Creating an adapter

Create:

```text
custom_components/media_watch/award_adapters/guldbaggen.py
```

Example skeleton:

```python
from typing import Any

from ..award_adapter import AwardAdapter, AwardAdapterInfo


class GuldbaggenAwardAdapter(AwardAdapter):
    info = AwardAdapterInfo(
        source="guldbaggen",
        label="Guldbaggen",
        media_types=frozenset({"movie"}),
        supports_nominees=True,
        supports_winners=True,
    )

    async def async_categories(
        self,
        media_type: str,
    ) -> list[dict[str, str]]:
        # Read categories from the backing source when possible.
        return [
            {"value": "all", "label": "Alla kategorier"},
            {"value": "basta_film", "label": "Bästa film"},
        ]

    async def async_latest_award_year(
        self,
        media_type: str,
    ) -> int:
        return 2026

    async def async_filter_titles(
        self,
        *,
        media_type: str,
        year_from: int | None,
        year_to: int | None,
        category: str | None,
        status: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "title": "Example",
                "imdb_id": "tt1234567",
                "media_type": "movie",
                "award_years": [2025],
                "categories": ["basta_film"],
                "nominations": 3,
                "wins": 1,
                "winning_categories": ["basta_film"],
            }
        ]
```

Then register it in `award_registry.py`:

```python
from .award_adapters.guldbaggen import GuldbaggenAwardAdapter

ADAPTER_TYPES = {
    OscarsAwardAdapter.info.source: OscarsAwardAdapter,
    GuldbaggenAwardAdapter.info.source: GuldbaggenAwardAdapter,
}
```

That is enough for the profile UI to:

- hide the adapter for unsupported media types
- show it for supported media types
- request its category list dynamically

## Normalized title records

`async_filter_titles()` should return one row **per film/series**, not one row
per nomination.

Recommended shape:

```python
{
    "title": "The Movie",
    "imdb_id": "tt1234567",
    "tmdb_id": 123,  # optional
    "media_type": "movie",
    "award_years": [2022, 2023],
    "categories": ["best_film", "best_actor"],
    "nominations": 7,
    "wins": 2,
    "winning_categories": ["best_film", "best_actor"],
}
```

Prefer identifiers in this order:

1. IMDb ID
2. TMDB ID
3. Title + release year

IMDb/TMDB IDs avoid localization and remake ambiguity.

## Award status semantics

Adapters should support the shared Media Watch status model:

- `any`: nominated or winner
- `winner`: at least one win
- `nominated_no_win`: nominated but no wins in the selected filter scope
- `nominated_and_won`: nominated and at least one win in the selected scope

The adapter should collapse raw nominations to title level **before** applying
these title-level statuses.

## Categories

Do not hard-code categories in `config_flow.py`.

`async_categories()` is the source of truth. This lets the UI show only
categories relevant to the selected award provider.

Use stable internal values and separate display labels:

```python
{"value": "BEST PICTURE", "label": "Best Picture"}
```

The stable value is saved in the discovery profile.

## Film vs TV

Declare supported media explicitly:

```python
media_types=frozenset({"movie"})
```

or:

```python
media_types=frozenset({"movie", "tv"})
```

For example:

- Guldbaggen: `movie`
- Oscars: `movie`
- Emmys: `tv`
- Golden Globes: `movie`, `tv`
- BAFTA: preferably separate adapters for Film and Television if their
  category vocabularies/data sources differ substantially

## Caching

Historical sources must not be downloaded on every coordinator refresh.

Recommended pattern:

```python
self._records = None
self._lock = asyncio.Lock()
```

Fetch/parse once, keep normalized records in memory, then filter the local
dataset for each discovery profile.

If the source is large or expensive, a future adapter may additionally use
Home Assistant storage with a refresh timestamp.

## Source quality

Prefer:

1. official historical database/API/export
2. official structured pages
3. maintained public dataset derived from an official archive

Avoid brittle scraping if a structured source exists.

Document the source and licensing/provenance in the adapter module and README.

## Festival-style awards

Festivals such as Cannes do not always have a nominee/winner model equivalent
to Oscars/Emmys. They can still implement `AwardAdapter`, but category/status
normalization may map:

- Competition selection -> nomination
- Palme d'Or / Grand Prix / Jury Prize -> wins/categories

If this becomes too lossy, Media Watch can add a `FestivalAwardAdapter`
specialization later without changing the generic discovery-profile sensor.


## Hong Kong Film Awards

`HongKongFilmAwardsAdapter` uses the official Hong Kong Film Awards
Association archive at `hkfaa.com`.

- media type: movie
- source ID: `hong_kong_film_awards`
- historical ceremony pages: 1st through 44th
- modern pages: nominees + awardees
- early winner-only pages: only explicit awardee data is used; missing
  nominations are never inferred
- category selector: loaded from the latest official nominee/award page
- TMDB resolution: English film-title candidates extracted from the bilingual
  official archive, then resolved by the generic award pipeline

The award year exposed by the adapter is the ceremony year. For example the
44th Hong Kong Film Awards is 2026.
