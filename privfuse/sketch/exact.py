"""Exact cost table with the interface of :class:`CostSketch`.

This is the control condition for the approximation: the same accountant, ring,
breaker and coordinator, backed by a dense table instead of a sketch.  It exists
so an experiment can isolate what the sketch buys at a population where a dense
table still fits, rather than comparing against a baseline that also lacks the
window, the degradation path and the transaction.
"""

from __future__ import annotations

from typing import Iterable

from privfuse.dp.cost import CostVector


class ExactCostSketch:
    """Dense per-subject table exposing the sketch interface."""

    def __init__(self, width: int = 0, depth: int = 0, hot_capacity: int = 0, seed: int = 0) -> None:
        self.width = int(width)
        self.depth = int(depth)
        self._costs: dict[str, CostVector] = {}
        self.events = 0

    @property
    def hot(self) -> "ExactCostSketch":
        return self

    def keys(self) -> Iterable[str]:
        return self._costs.keys()

    def items(self) -> Iterable[tuple[str, CostVector]]:
        return self._costs.items()

    def contains(self, subject: str) -> bool:
        return subject in self._costs

    def add(self, subject: str, cost: CostVector) -> None:
        if cost.is_zero():
            return
        self._costs[subject] = self._costs.get(subject, CostVector.zero()) + cost
        self.events += 1

    def estimate(self, subject: str) -> CostVector:
        return self._costs.get(subject, CostVector.zero())

    def estimate_pair(self, subject: str, upper: bool = False) -> tuple[float, float]:
        cost = self.estimate(subject)
        return cost.eps_pure, cost.rho

    def error_bound(self) -> CostVector:
        return CostVector.zero()

    def upper_bound(self, subject: str) -> CostVector:
        return self.estimate(subject)

    def total_mass(self) -> float:
        return float(sum(c.eps(1e-5) for c in self._costs.values()))

    def nbytes(self) -> int:
        return 128 * len(self._costs) + 64

    def reset(self) -> None:
        self._costs.clear()
        self.events = 0
