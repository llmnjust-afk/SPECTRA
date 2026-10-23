"""Privacy cost algebra.

A :class:`CostVector` is the unit of account for PrivFuse.  Every transaction
produces one, the ledger reserves and commits them, and the SLO layer compares
their composition against a budget.

A cost carries two additive components:

* ``eps_pure`` -- pure ``(epsilon, 0)``-DP mass.  Laplace-style mechanisms and
  any mechanism without a concentration calibration live here; basic
  composition adds these exactly.
* ``rho`` -- zCDP concentration, the natural parameter for the Gaussian
  mechanism (``rho = sensitivity^2 / (2 sigma^2)``).

The two compose independently: ``rho`` is additive under sequential composition
and converts back with ``eps = rho + 2 sqrt(rho log(1/delta))``.  zCDP is used
rather than a fixed grid of Renyi orders because the conversion has no order
floor: a grid fine enough for ``epsilon = 0.02`` at ``delta = 1e-5`` would need
Renyi orders in the thousands, and would silently over-charge every transaction
whose epsilon fell below the floor.

Keeping ``eps_pure`` separate is what makes mixing Gaussian and Laplace
transactions sound instead of falling back to a vacuous bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class CostVector:
    """A privacy cost with a pure-DP part and a zCDP part."""

    eps_pure: float = 0.0
    rho: float = 0.0
    delta: float = 0.0

    def __post_init__(self) -> None:
        if self.eps_pure < 0:
            raise ValueError("eps_pure must be non-negative")
        if self.rho < 0:
            raise ValueError("rho must be non-negative")
        if not (0.0 <= self.delta < 1.0):
            raise ValueError("delta must lie in [0, 1)")

    @classmethod
    def zero(cls) -> "CostVector":
        return cls(0.0, 0.0, 0.0)

    @classmethod
    def from_gaussian(
        cls, sigma: float, sensitivity: float, delta: float = 0.0
    ) -> "CostVector":
        """zCDP calibration of the Gaussian mechanism."""
        if sigma <= 0:
            raise ValueError("sigma must be positive")
        if sensitivity < 0:
            raise ValueError("sensitivity must be non-negative")
        return cls(eps_pure=0.0, rho=(sensitivity**2) / (2.0 * sigma**2), delta=delta)

    @classmethod
    def from_laplace(
        cls, scale: float, sensitivity: float, delta: float = 0.0
    ) -> "CostVector":
        """Pure-epsilon calibration of the Laplace mechanism."""
        if scale <= 0:
            raise ValueError("scale must be positive")
        if sensitivity < 0:
            raise ValueError("sensitivity must be non-negative")
        return cls(eps_pure=sensitivity / scale, rho=0.0, delta=delta)

    @classmethod
    def from_epsilon(cls, epsilon: float, delta: float = 0.0) -> "CostVector":
        """A declared pure ``epsilon`` cost with no concentration refinement."""
        if epsilon < 0:
            raise ValueError("epsilon must be non-negative")
        if not (0.0 <= delta < 1.0):
            raise ValueError("delta must lie in [0, 1)")
        return cls(eps_pure=float(epsilon), rho=0.0, delta=float(delta))

    def __add__(self, other: "CostVector") -> "CostVector":
        if not isinstance(other, CostVector):
            return NotImplemented
        return CostVector(
            eps_pure=self.eps_pure + other.eps_pure,
            rho=self.rho + other.rho,
            delta=self.delta + other.delta,
        )

    __radd__ = __add__

    def scale(self, k: float) -> "CostVector":
        if k < 0:
            raise ValueError("scale factor must be non-negative")
        return CostVector(eps_pure=self.eps_pure * k, rho=self.rho * k, delta=self.delta * k)

    def eps(self, delta: float | None = None) -> float:
        """Tightest ``epsilon`` at the requested total ``delta``."""
        target = self.delta if delta is None else delta
        bound = self.eps_pure
        if self.rho <= 0.0:
            return float(bound)
        if not (0.0 < target < 1.0):
            return float(bound)
        return float(bound + self.rho + 2.0 * math.sqrt(self.rho * math.log(1.0 / target)))

    def componentwise_max(self, other: "CostVector") -> "CostVector":
        """Upper envelope of two estimates, used to merge sketch and exact views."""
        return CostVector(
            eps_pure=max(self.eps_pure, other.eps_pure),
            rho=max(self.rho, other.rho),
            delta=max(self.delta, other.delta),
        )

    def dominates(self, other: "CostVector") -> bool:
        """True when ``self`` is at least as large as ``other`` in every coordinate."""
        return (
            self.eps_pure >= other.eps_pure - 1e-12
            and self.rho >= other.rho - 1e-15
            and self.delta >= other.delta - 1e-15
        )

    def is_zero(self) -> bool:
        return self.eps_pure == 0.0 and self.rho == 0.0 and self.delta == 0.0


def sum_costs(costs: Iterable[CostVector]) -> CostVector:
    total = CostVector.zero()
    for cost in costs:
        total = total + cost
    return total
