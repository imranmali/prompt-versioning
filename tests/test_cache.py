from __future__ import annotations

import pytest

from promptlab.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_get_set_and_expiry() -> None:
    clock = FakeClock()
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=5, clock=clock)
    cache.set("a", 1)
    assert cache.get("a") == 1
    clock.now = 5.1
    assert cache.get("a") is None
    assert len(cache) == 0


def test_lru_eviction() -> None:
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=60, max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1  # refresh "a"
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_disabled_cache_never_stores() -> None:
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=0)
    assert not cache.enabled
    cache.set("a", 1)
    assert cache.get("a", 7) == 7
    assert len(cache) == 0


def test_invalidate_and_clear() -> None:
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.invalidate("a")
    cache.invalidate("missing")
    assert cache.get("a") is None
    cache.clear()
    assert len(cache) == 0


def test_invalid_size() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        TTLCache(ttl_seconds=1, max_entries=0)
