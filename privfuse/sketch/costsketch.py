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
    """

    def __init__(self, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = int(capacity)
        self._summary = SpaceSaving(capacity=capacity)
        self._costs: dict[str, CostVector] = {}
        self._evicted: set[str] = set()
        self.sealed = False

    def add(self, subject: str, cost: CostVector) -> None:
        if self.sealed:
            return
        evicted = self._summary.add(subject, max(cost.eps(1e-5), 1e-12))
        if evicted is not None:
            self._costs.pop(evicted, None)
            self._evicted.add(evicted)
            if len(self._evicted) > 8 * self.capacity:
                self.sealed = True
                self._costs.clear()
                return
        if not self._summary.contains(subject):
            return
        if subject in self._evicted:
            return
        current = self._costs.get(subject, CostVector.zero())
        self._costs[subject] = current + cost

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
        if cost.eps_pure:
            self._pure.add(subject, cost.eps_pure)
        if cost.rho:
            self._rho.add(subject, cost.rho)
        self.hot.add(subject, cost)
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
