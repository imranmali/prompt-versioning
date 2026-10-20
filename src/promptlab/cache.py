"""Small bounded in-process TTL cache (per instance; never required for correctness)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable


class TTLCache[K: Hashable, V]:
    """LRU cache whose entries expire ``ttl_seconds`` after insertion.

    A ``ttl_seconds`` of 0 disables caching entirely.
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: K, default: V | None = None) -> V | None:
        if not self.enabled:
            return default
        entry = self._data.get(key)
        if entry is None:
            return default
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._data[key]
            return default
        self._data.move_to_end(key)
        return value

    def set(self, key: K, value: V) -> None:
        if not self.enabled:
            return
        self._data[key] = (self._clock() + self.ttl_seconds, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def invalidate(self, key: K) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()
