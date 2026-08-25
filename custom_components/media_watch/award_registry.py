"""Registry for award-history adapters."""

from __future__ import annotations

import time
from typing import Type

from .award_adapter import AwardAdapter, AwardAdapterInfo
from .award_adapters.bafta import BaftaFilmAwardAdapter, BaftaTelevisionAwardAdapter
from .award_adapters.cannes import CannesAwardAdapter
from .award_adapters.emmys import EmmysAwardAdapter
from .award_adapters.golden_globes import GoldenGlobesFilmAwardAdapter, GoldenGlobesTelevisionAwardAdapter
from .award_adapters.guldbaggen import GuldbaggenAwardAdapter
from .award_adapters.hong_kong_film_awards import HongKongFilmAwardsAdapter
from .award_adapters.oscars import OscarsAwardAdapter
from .const import AWARD_SOURCE_NONE

ADAPTER_TYPES: dict[str, Type[AwardAdapter]] = {
    adapter.info.source: adapter
    for adapter in (
        OscarsAwardAdapter,
        GuldbaggenAwardAdapter,
        BaftaFilmAwardAdapter,
        BaftaTelevisionAwardAdapter,
        GoldenGlobesFilmAwardAdapter,
        GoldenGlobesTelevisionAwardAdapter,
        EmmysAwardAdapter,
        CannesAwardAdapter,
        HongKongFilmAwardsAdapter,
    )
}
ADAPTER_CACHE_TTL = 6 * 60 * 60


def providers_for_media_type(media_type: str) -> list[AwardAdapterInfo]:
    return sorted(
        [a.info for a in ADAPTER_TYPES.values() if media_type in a.info.media_types],
        key=lambda info: info.label.casefold(),
    )


def create_adapter(hass, source: str) -> AwardAdapter | None:
    adapter_type = ADAPTER_TYPES.get(source)
    if adapter_type is None:
        return None
    cache = hass.data.setdefault("media_watch_award_adapters", {})
    timestamps = hass.data.setdefault(
        "media_watch_award_adapter_timestamps", {}
    )
    now = time.monotonic()
    if source in cache and source not in timestamps:
        timestamps[source] = now
    cached_at = float(timestamps.get(source, 0.0))
    if source not in cache or now - cached_at >= ADAPTER_CACHE_TTL:
        cache[source] = adapter_type(hass)
        timestamps[source] = now
    return cache[source]


async def async_categories(
    hass,
    source: str,
    media_type: str,
) -> list[dict[str, str]]:
    """Return award categories without allowing a provider failure to crash options."""
    if source == AWARD_SOURCE_NONE:
        return []

    adapter = create_adapter(hass, source)
    if adapter is None or media_type not in adapter.info.media_types:
        return []

    try:
        categories = await adapter.async_categories(media_type)
    except Exception:
        return [{"value": "all", "label": "All categories"}]

    return categories or [{"value": "all", "label": "All categories"}]
