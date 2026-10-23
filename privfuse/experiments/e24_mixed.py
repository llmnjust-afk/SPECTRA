"""E24: does the hard cap survive a mixture of pure DP and zCDP?

A cost vector carries a pure-DP part ``eps_pure`` and a zCDP part ``rho``.  The
cap is scalar, so admission must test the converted total
``g(c) = eps_pure + rho + 2 sqrt(rho ln(1/delta))`` against the cap.  Testing the
two components against separate allowances looks equivalent and is not: both can
pass while the converted total is roughly twice the cap.

This experiment runs the same mixed stream through three budget domains:

* ``scalar``    -- admit iff ``g(spend + cost) <= cap`` (ours);
* ``component`` -- admit iff ``eps_pure <= cap`` and ``rho <= rho_max(cap)``,
  the two independent allowances a reviewer proposed;
* ``reference``  -- an independent float accountant that recomputes g from the
  admitted list, to check that the scalar policy's own bookkeeping is not the
  thing being trusted.

Mechanisms are the ones the costs come from: Laplace (pure DP) and Gaussian
(zCDP), both with ``delta = 0`` in the vector, converted once at the market
delta.  Caps differ per subject to exercise the heterogeneous case.
"""

from __future__ import annotations

import math
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.dp.mechanisms import laplace_cost, zcdp_rho
from privfuse.experiments.common import write_csv, write_json
from privfuse.trace.generator import EPS_DELTA

DELTA = EPS_DELTA
CAPS = (0.5, 1.0, 2.0)
OFFERED = 40
LAPLACE_EPS = 0.05
GAUSSIAN_EPS = 0.09


def _rho_max(cap: float) -> float:
    """Largest rho with g(0, rho) <= cap, solved in closed form."""
    root = math.sqrt(math.log(1.0 / DELTA))
    return (math.sqrt(math.log(1.0 / DELTA) + cap) - root) ** 2


def _stream(mix: str) -> list[CostVector]:
    lap = laplace_cost(LAPLACE_EPS, 1.0)
    gau = CostVector(eps_pure=0.0, rho=zcdp_rho(GAUSSIAN_EPS, DELTA))
    if mix == "laplace":
        return [lap] * OFFERED
    if mix == "gaussian":
        return [gau] * OFFERED
    return [lap if index % 2 == 0 else gau for index in range(OFFERED)]


def _admit(costs: list[CostVector], cap: float, policy: str) -> list[CostVector]:
    admitted: list[CostVector] = []
    spend = CostVector.zero()
    rho_cap = _rho_max(cap)
    for cost in costs:
        nxt = spend + cost
        if policy == "scalar":
            ok = nxt.eps(DELTA) <= cap + 1e-12
        elif policy == "component":
            ok = (
                nxt.eps_pure <= cap + 1e-12
                and nxt.rho <= rho_cap + 1e-15
            )
        else:
            ok = True
        if ok:
            admitted.append(cost)
            spend = nxt
    return admitted


def _reference_eps(costs: list[CostVector]) -> float:
    pure = math.fsum(c.eps_pure for c in costs)
    rho = math.fsum(c.rho for c in costs)
    return pure + rho + (2.0 * math.sqrt(rho * math.log(1.0 / DELTA)) if rho > 0 else 0.0)


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mix in ("laplace", "gaussian", "mixed"):
        costs = _stream(mix)
        for cap in CAPS:
            for policy in ("scalar", "component", "every"):
                admitted = _admit(costs, cap, policy)
                eps = _reference_eps(admitted)
                rows.append(
                    {
                        "mix": mix,
                        "cap": cap,
                        "policy": policy,
                        "offered": float(len(costs)),
                        "admitted": float(len(admitted)),
                        "admitted_frac": len(admitted) / len(costs),
                        "worst_eps": eps,
                        "ratio": eps / cap,
                        "violations": float(eps > cap + 1e-9),
                        "components_ok": float(
                            sum(c.eps_pure for c in admitted) <= cap + 1e-12
                            and sum(c.rho for c in admitted) <= _rho_max(cap) + 1e-15
                        ),
                    }
                )
            print(
                f"{mix:>8} cap={cap:4.1f} "
                + " ".join(
                    f"{r['policy'][:4]}={r['admitted']:.0f}/{r['ratio']:.2f}"
                    for r in rows[-3:]
                ),
                flush=True,
            )
    write_csv("e24_mixed", rows)
    write_json(
        "e24_mixed_meta",
        {
            "delta": DELTA,
            "caps": list(CAPS),
            "offered": OFFERED,
            "laplace_eps": LAPLACE_EPS,
            "gaussian_eps": GAUSSIAN_EPS,
            "note": "component tests eps_pure<=cap and rho<=rho_max(cap) separately",
        },
    )
    return rows


if __name__ == "__main__":
    run()
