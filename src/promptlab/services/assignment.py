"""Deterministic, stateless subject assignment (hash bucketing).

All functions are pure: the same salt, traffic percentage, weights and subject always yield the
same result on every replica, without storing assignments.
"""

from __future__ import annotations

import bisect
import hashlib
from collections.abc import Sequence
from functools import lru_cache

BUCKETS = 10_000


def bucket(value: str) -> int:
    """Map ``value`` uniformly onto ``[0, BUCKETS)``."""
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:15], 16) % BUCKETS


def is_enrolled(salt: str, traffic_percent: int, subject_id: str) -> bool:
    """Traffic gate: whether ``subject_id`` falls into the experiment's ``traffic_percent``."""
    return bucket(f"{salt}:traffic:{subject_id}") < traffic_percent * (BUCKETS // 100)


@lru_cache(maxsize=4096)
def _boundaries(weights: tuple[int, ...]) -> tuple[int, ...]:
    if len(weights) > BUCKETS:
        raise ValueError("too many variants")
    if not weights or any(w <= 0 for w in weights):
        raise ValueError("weights must be positive")
    total = sum(weights)
    # Largest-remainder apportionment of the buckets, with at least one bucket per variant.
    shares = [max(1, w * BUCKETS // total) for w in weights]
    remainders = [(w * BUCKETS % total, -i) for i, w in enumerate(weights)]
    surplus = BUCKETS - sum(shares)
    if surplus > 0:
        # surplus < len(weights): every floor dropped less than one bucket.
        for _, neg_index in sorted(remainders, reverse=True)[:surplus]:
            shares[-neg_index] += 1
    while surplus < 0:
        # Minimum-one adjustments overshot: take buckets back from the largest shares.
        largest = max(range(len(shares)), key=lambda i: (shares[i], -i))
        shares[largest] -= 1
        surplus += 1
    cumulative: list[int] = []
    running = 0
    for share in shares:
        running += share
        cumulative.append(running)
    return tuple(cumulative)


def variant_boundaries(weights: Sequence[int]) -> tuple[int, ...]:
    """Cumulative upper bucket bounds per variant; the last bound is always ``BUCKETS``.

    Every positive weight receives a non-empty range.
    """
    return _boundaries(tuple(weights))


def choose_variant(salt: str, weights: Sequence[int], subject_id: str) -> int:
    """Index of the variant ``subject_id`` is assigned to (ignores the traffic gate)."""
    point = bucket(f"{salt}:variant:{subject_id}")
    return bisect.bisect_right(variant_boundaries(weights), point)


def assign(salt: str, traffic_percent: int, weights: Sequence[int], subject_id: str) -> int | None:
    """Variant index for an enrolled subject, ``None`` when the traffic gate excludes it.

    The traffic gate and the variant choice hash different inputs, so changing the traffic
    percentage never moves already-enrolled subjects between variants.
    """
    if not is_enrolled(salt, traffic_percent, subject_id):
        return None
    return choose_variant(salt, weights, subject_id)
