"""E10: how much does the choice of accountant cost?

Three composition backends are compared on the same sequence of Gaussian
charges: the zCDP accountant used by PrivFuse, a Renyi-DP accountant over a
fixed order grid (Mironov 2017), and textbook basic composition.

Two numbers matter. First, calibration error: for a single charge worth
``eps``, what does the accountant report? Basic composition reports exactly
``eps``, zCDP inverts its own conversion and therefore returns ``eps`` to
machine precision, and a finite order grid cannot represent a small epsilon at
all -- its floor is ``log(1/delta) / (alpha_max - 1)``. Second, tightness after
many charges: what does 100 charges cost?
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from privfuse.dp.cost import CostVector
from privfuse.dp.mechanisms import gaussian_cost, zcdp_rho
from privfuse.experiments.common import write_csv, write_json
from privfuse.trace.generator import EPS_DELTA

ORDERS = [1 + x for x in np.geomspace(1.0, 511.0, 128)]


class RDPAccountant:
    """Renyi accountant evaluated on a fixed order grid, then converted."""

    def __init__(self, orders: list[float] | None = None) -> None:
        self.orders = list(orders or ORDERS)
        self._rdp = [0.0] * len(self.orders)

    def add_gaussian(self, sigma: float) -> None:
        for i, alpha in enumerate(self.orders):
            self._rdp[i] += alpha / (2.0 * sigma * sigma)

    def eps(self, delta: float) -> float:
        best = math.inf
        for alpha, value in zip(self.orders, self._rdp):
            candidate = value + math.log(1.0 / delta) / (alpha - 1.0)
            best = min(best, candidate)
        return best

    @property
    def floor(self) -> float:
        return math.log(1.0 / EPS_DELTA) / (max(self.orders) - 1.0)


class BasicAccountant:
    def __init__(self) -> None:
        self.total = 0.0

    def add(self, eps: float) -> None:
        self.total += eps

    def eps(self, delta: float) -> float:
        return self.total


def _calibrate(accountant: Any, target: float, delta: float) -> tuple[float, bool]:
    """Bisect on sigma so that one charge reports ``target``.

    Returns the sigma and whether the target was reachable at all. A grid has a
    floor: as sigma grows the reported epsilon converges to
    ``log(1/delta) / (alpha_max - 1)`` and never goes below it, so a target under
    that floor cannot be calibrated and the loop would otherwise return a
    meaningless sigma.
    """
    low, high = 1e-3, 1e3
    accountant.__init__()  # type: ignore[misc]
    accountant.add_gaussian(high)
    if accountant.eps(delta) > target:
        return high, False
    for _ in range(200):
        mid = 0.5 * (low + high)
        accountant.__init__()  # type: ignore[misc]
        accountant.add_gaussian(mid)
        if accountant.eps(delta) > target:
            low = mid
        else:
            high = mid
    sigma = 0.5 * (low + high)
    accountant.__init__()  # type: ignore[misc]
    accountant.add_gaussian(sigma)
    reached = abs(accountant.eps(delta) - target) <= 1e-3 * max(target, 1e-9)
    return sigma, reached


def run(targets: list[float] | None = None, counts: list[int] | None = None) -> list[dict[str, Any]]:
    targets = targets or [0.02, 0.1, 0.5]
    counts = counts or [1, 10, 100]
    rows: list[dict[str, Any]] = []
    for target in targets:
        cost = gaussian_cost(target, EPS_DELTA, 1.0)
        sigma = math.sqrt(1.0 / (2.0 * zcdp_rho(target, EPS_DELTA)))
        rdp = RDPAccountant()
        rdp_sigma, rdp_reached = _calibrate(rdp, target, EPS_DELTA)
        for count in counts:
            zcdp = CostVector(eps_pure=0.0, rho=0.0, delta=0.0)
            for _ in range(count):
                zcdp = zcdp + cost
            rdp = RDPAccountant()
            for _ in range(count):
                rdp.add_gaussian(rdp_sigma)
            basic = BasicAccountant()
            for _ in range(count):
                basic.add(target)
            rows.append(
                {
                    "backend": "zcdp",
                    "target_eps": target,
                    "count": count,
                    "sigma": sigma,
                    "sigma_ratio_vs_zcdp": 1.0,
                    "reported_eps": zcdp.eps(EPS_DELTA),
                    "reached_target": True,
                }
            )
            rows.append(
                {
                    "backend": "rdp_grid",
                    "target_eps": target,
                    "count": count,
                    "sigma": rdp_sigma,
                    "sigma_ratio_vs_zcdp": rdp_sigma / sigma,
                    "reported_eps": rdp.eps(EPS_DELTA),
                    "reached_target": bool(rdp_reached),
                }
            )
            rows.append(
                {
                    "backend": "basic",
                    "target_eps": target,
                    "count": count,
                    "sigma": sigma,
                    "sigma_ratio_vs_zcdp": 1.0,
                    "reported_eps": basic.eps(EPS_DELTA),
                    "reached_target": True,
                }
            )
        print(
            f"target={target}: zCDP(100)={rows[-3]['reported_eps']:.4f} "
            f"RDP(100)={rows[-2]['reported_eps']:.4f} "
            f"calibrated={rdp_reached} basic(100)={rows[-1]['reported_eps']:.2f} "
            f"floor={RDPAccountant().floor:.4f}",
            flush=True,
        )
    write_csv("e10_accountant", rows)
    write_json(
        "e10_accountant_meta",
        {
            "orders": len(ORDERS),
            "order_min": min(ORDERS),
            "order_max": max(ORDERS),
            "rdp_floor": RDPAccountant().floor,
            "delta": EPS_DELTA,
        },
    )
    return rows


if __name__ == "__main__":
    run()
