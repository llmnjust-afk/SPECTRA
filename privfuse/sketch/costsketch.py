"""Vector-valued sketching over privacy costs."""

from __future__ import annotations

from typing import Iterable

from privfuse.dp.cost import CostVector
from privfuse.sketch.countmin import CountMinSketch, SpaceSaving


class HotTable:
    """Bounded exact table for the heaviest subjects.

    Admission is decided by a Space-Saving summary, but the stored value is the
    exact composed cost, so a tracked subject never suffers sketch error.  The
    table is an optimisation for accuracy, not for safety: evicted subjects fall
    back to the (still conservative) Count-Min estimate.

    A subject that is re-admitted after eviction cannot recover its true history
    from this table, so the caller seeds the counter with the sketch's upper
    bound for the past.  The counter therefore stays an upper bound at all
    times while remaining exact for subjects tracked from their first request.
    """

    def __init__(self, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = int(capacity)
        self._summary = SpaceSaving(capacity=capacity)
        self._costs: dict[str, CostVector] = {}

    def contains(self, subject: str) -> bool:
        return subject in self._costs

    def add(
        self, subject: str, cost: CostVector, seed: CostVector | None = None
    ) -> None:
        was_tracked = subject in self._costs
        evicted = self._summary.add(subject, max(cost.eps(1e-5), 1e-12))
        if evicted is not None:
            self._costs.pop(evicted, None)
        if not self._summary.contains(subject):
            return
        if was_tracked:
            self._costs[subject] = self._costs[subject] + cost
            return
        self._costs[subject] = (seed or CostVector.zero()) + cost

    def estimate(self, subject: str) -> CostVector | None:
        return self._costs.get(subject)

    def keys(self) -> Iterable[str]:
        return self._costs.keys()

    def items(self) -> Iterable[tuple[str, CostVector]]:
        return self._costs.items()

    def reset(self) -> None:
        self._summary.reset()
        self._costs.clear()

    def nbytes(self) -> int:
        return self._summary.nbytes() + 256 * len(self._costs)


class CostSketch:
    """One Count-Min sketch per accounting layer plus a hot table."""

    def __init__(
        self,
        width: int = 1 << 14,
        depth: int = 4,
        hot_capacity: int = 1024,
        seed: int = 0,
    ) -> None:
        self.width = int(width)
        self.depth = int(depth)
        self._pure = CountMinSketch(width=width, depth=depth, seed=seed)
        self._rho = CountMinSketch(width=width, depth=depth, seed=seed + 1)
        self.hot = HotTable(capacity=hot_capacity)
        self.events = 0

    def add(self, subject: str, cost: CostVector) -> None:
        if cost.is_zero():
            return
        seed = None
        if not self.hot.contains(subject):
            seed = CostVector(
                eps_pure=self._pure.estimate(subject),
                rho=self._rho.estimate(subject),
                delta=0.0,
            )
        if cost.eps_pure:
            self._pure.add(subject, cost.eps_pure)
        if cost.rho:
            self._rho.add(subject, cost.rho)
        self.hot.add(subject, cost, seed=seed)
        self.events += 1

    def estimate(self, subject: str) -> CostVector:
        exact = self.hot.estimate(subject)
        if exact is not None:
            return exact
        return CostVector(
            eps_pure=self._pure.estimate(subject),
            rho=self._rho.estimate(subject),
            delta=0.0,
        )

    def error_bound(self) -> CostVector:
        """Deterministic additive over-estimate for any single subject."""
        return CostVector(
            eps_pure=self._pure.error_bound(),
            rho=self._rho.error_bound(),
            delta=0.0,
        )

    def upper_bound(self, subject: str) -> CostVector:
        return self.estimate(subject) + self.error_bound()

    def estimate_pair(self, subject: str, upper: bool = False) -> tuple[float, float]:
        """``(eps_pure, rho)`` without materialising intermediate cost objects."""
        exact = self.hot.estimate(subject)
        if exact is not None:
            return exact.eps_pure, exact.rho
        pure = self._pure.estimate(subject)
        rho = self._rho.estimate(subject)
        if upper:
            pure += self._pure.error_bound()
            rho += self._rho.error_bound()
        return pure, rho

    def total_mass(self) -> float:
        return self._pure.total_mass + self._rho.total_mass

    def nbytes(self) -> int:
        return self._pure.nbytes() + self._rho.nbytes() + self.hot.nbytes()

    def reset(self) -> None:
        self._pure.reset()
        self._rho.reset()
        self.hot.reset()
        self.events = 0
