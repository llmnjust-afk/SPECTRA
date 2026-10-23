"""One-sided additive sketches.

The online accountant relies on a single structural property: the sketch must
never *under*-estimate.  Under-estimation would let a tenant slip past the
circuit breaker, which is exactly the failure PrivFuse exists to prevent.
Count-Min with non-negative updates has that property, and so does Space-Saving
with additive weights; both are used here.
"""

from __future__ import annotations

import heapq
import zlib

import numpy as np


class CountMinSketch:
    """Additive Count-Min sketch with conservative update.

    With ``width`` columns and ``depth`` rows the estimate over-shoots the true
    mass by at most ``total_mass / width`` and never under-shoots, for any
    sequence of non-negative updates.

    The update raises every cell below ``min + value`` to ``min + value`` rather
    than only the cells equal to the minimum.  With unit increments the two are
    the same, but with arbitrary real weights the classical variant can leave a
    collision cell just below the new minimum and turn the estimate into an
    *under*-estimate -- which is precisely the failure mode the breaker cannot
    tolerate.
    """

    def __init__(self, width: int = 1 << 14, depth: int = 4, seed: int = 0) -> None:
        if width <= 0 or depth <= 0:
            raise ValueError("width and depth must be positive")
        self.width = int(width)
        self.depth = int(depth)
        self.seed = int(seed)
        rng = np.random.default_rng(seed)
        self._salts = [int(x) for x in rng.integers(0, 2**31 - 1, size=depth)]
        self.table = np.zeros((depth, width), dtype=np.float64)
        self.total_mass = 0.0
        self.updates = 0

    def _columns(self, key: str) -> list[int]:
        raw = key.encode("utf-8")
        return [zlib.crc32(raw, salt) % self.width for salt in self._salts]

    def add(self, key: str, value: float) -> None:
        if value < 0:
            raise ValueError("CountMinSketch only supports non-negative updates")
        if value == 0.0:
            return
        cols = self._columns(key)
        table = self.table
        current = min(table[i, c] for i, c in enumerate(cols))
        target = current + value
        for i, c in enumerate(cols):
            if table[i, c] < target:
                table[i, c] = target
        self.total_mass += value
        self.updates += 1

    def estimate(self, key: str) -> float:
        cols = self._columns(key)
        table = self.table
        return float(min(table[i, c] for i, c in enumerate(cols)))

    def error_bound(self) -> float:
        """Deterministic worst-case over-estimate for a single query."""
        return self.total_mass / self.width

    def reset(self) -> None:
        self.table.fill(0.0)
        self.total_mass = 0.0
        self.updates = 0

    def nbytes(self) -> int:
        return int(self.table.nbytes)

    def merge(self, other: "CountMinSketch") -> None:
        """Cell-wise max merge, used to align replicas of the same stream."""
        if (self.width, self.depth) != (other.width, other.depth):
            raise ValueError("cannot merge sketches of different shape")
        np.maximum(self.table, other.table, out=self.table)
        self.total_mass = max(self.total_mass, other.total_mass)


class SpaceSaving:
    """Space-Saving heavy-hitter summary with additive weights.

    Tracked counters are upper bounds on the true mass, so merging this summary
    with the Count-Min estimate by taking the maximum stays safe.  The minimum
    counter is maintained with a lazy heap so that insertion stays
    ``O(log n)`` instead of the ``O(n)`` linear scan of the textbook version.
    """

    def __init__(self, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = int(capacity)
        self.counters: dict[str, float] = {}
        self.errors: dict[str, float] = {}
        self.total_mass = 0.0
        self._heap: list[tuple[float, int, str]] = []
        self._seq = 0

    def _push(self, key: str, value: float) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (value, self._seq, key))

    def _pop_min(self) -> str:
        while self._heap:
            value, _, key = heapq.heappop(self._heap)
            if key in self.counters and abs(self.counters[key] - value) <= 1e-15:
                return key
        return min(self.counters, key=self.counters.__getitem__)

    def add(self, key: str, value: float) -> str | None:
        """Insert or update ``key``; return the evicted key, if any."""
        if value < 0:
            raise ValueError("SpaceSaving only supports non-negative updates")
        if value == 0.0:
            return None
        self.total_mass += value
        if key in self.counters:
            self.counters[key] += value
            self._push(key, self.counters[key])
            return None
        if len(self.counters) < self.capacity:
            self.counters[key] = value
            self.errors[key] = 0.0
            self._push(key, value)
            return None
        victim = self._pop_min()
        floor = self.counters.pop(victim)
        self.errors.pop(victim, None)
        self.counters[key] = floor + value
        self.errors[key] = floor
        self._push(key, self.counters[key])
        return victim

    def estimate(self, key: str) -> float | None:
        return self.counters.get(key)

    def contains(self, key: str) -> bool:
        return key in self.counters

    def top(self, n: int) -> list[tuple[str, float]]:
        return sorted(self.counters.items(), key=lambda kv: kv[1], reverse=True)[:n]

    def reset(self) -> None:
        self.counters.clear()
        self.errors.clear()
        self._heap.clear()
        self._seq = 0
        self.total_mass = 0.0

    def nbytes(self) -> int:
        return 8 * (len(self.counters) + len(self.errors)) + 64 * len(self.counters)
