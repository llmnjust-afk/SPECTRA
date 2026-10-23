"""Mechanism calibration helpers."""

from __future__ import annotations

import math

from privfuse.dp.cost import CostVector


def zcdp_rho(epsilon: float, delta: float) -> float:
    """Concentration ``rho`` whose zCDP guarantee is exactly ``(epsilon, delta)``.

    Solving ``rho + 2 sqrt(rho log(1/delta)) = epsilon`` for ``rho`` gives a
    closed form, so no order grid or numerical search is needed.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    if not (0.0 < delta < 1.0):
        raise ValueError("delta must lie in (0, 1)")
    root = math.sqrt(math.log(1.0 / delta))
    return (math.sqrt(root * root + epsilon) - root) ** 2


def gaussian_sigma(epsilon: float, delta: float, sensitivity: float) -> float:
    """Noise scale of the Gaussian mechanism with guarantee ``(epsilon, delta)``."""
    if sensitivity < 0:
        raise ValueError("sensitivity must be non-negative")
    rho = zcdp_rho(epsilon, delta)
    if rho == 0.0:
        return float("inf")
    return sensitivity / math.sqrt(2.0 * rho)


def laplace_scale(epsilon: float, sensitivity: float) -> float:
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    if sensitivity < 0:
        raise ValueError("sensitivity must be non-negative")
    return sensitivity / epsilon


def gaussian_cost(epsilon: float, delta: float, sensitivity: float) -> CostVector:
    """Cost of a Gaussian mechanism calibrated for ``(epsilon, delta)``.

    The returned vector carries no explicit delta: the whole composition is
    accounted for in zCDP and converted once, at the total delta the caller
    asks for.  That avoids spending delta once per query.
    """
    rho = zcdp_rho(epsilon, delta)
    return CostVector(eps_pure=0.0, rho=rho * sensitivity**2, delta=0.0)


def laplace_cost(epsilon: float, sensitivity: float) -> CostVector:
    return CostVector.from_laplace(
        scale=laplace_scale(epsilon, sensitivity), sensitivity=sensitivity, delta=0.0
    )


def count_query_sensitivity() -> float:
    """Sensitivity of a COUNT query under add/remove-one neighbouring data."""
    return 1.0


def mean_query_sensitivity(value_range: float, n: int) -> float:
    if n <= 0:
        raise ValueError("n must be positive")
    return value_range / n
