"""Regression tests for award cache lifetime."""

from types import SimpleNamespace

from custom_components.media_watch import award_registry
from custom_components.media_watch.award_adapters import web_common


def test_http_cache_expires_after_ttl(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(web_common.time, "monotonic", lambda: now[0])
    hass = SimpleNamespace(data={})

    web_common._store_cached_value(hass, "page", ["value"])
    assert web_common._cached_value(hass, "page") == ["value"]

    now[0] += web_common.AWARD_HTTP_CACHE_TTL + 1

    assert web_common._cached_value(hass, "page") is None
    assert "page" not in hass.data["media_watch_award_http_cache"]


def test_adapter_cache_recreates_stale_adapter(monkeypatch) -> None:
    class Adapter:
        instances = 0

        def __init__(self, hass):
            self.hass = hass
            Adapter.instances += 1

    now = [100.0]
    monkeypatch.setattr(award_registry.time, "monotonic", lambda: now[0])
    monkeypatch.setitem(award_registry.ADAPTER_TYPES, "test", Adapter)
    hass = SimpleNamespace(data={})

    first = award_registry.create_adapter(hass, "test")
    assert award_registry.create_adapter(hass, "test") is first

    now[0] += award_registry.ADAPTER_CACHE_TTL + 1
    second = award_registry.create_adapter(hass, "test")

    assert second is not first
    assert Adapter.instances == 2
