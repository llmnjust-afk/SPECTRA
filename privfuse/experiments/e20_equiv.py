"""E20: an equi-functional exact baseline.

The exact baselines in E4 and E16 differ from PrivFuse in more than the
estimator: they have no window, no degradation path and no coordinator.  That
makes it impossible to attribute a difference to approximation.  This experiment
removes the confound.  Both policies run the same accountant ring, the same
breaker, the same admission controller and the same two-phase coordinator; the
only change is the store behind the accountant, a dense per-subject table instead
of a Count-Min sketch with a hot table.

What the exact store buys is exactness, which at a population where it fits is
worth little: both are sound, and the exact one is faster and smaller.  What it
costs is the slope, 128 bytes per subject with no ceiling.
"""

from __future__ import annotations

import time
from typing import Any

from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.experiments.e16_windowed import _windowed_truth
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA

CAPS = (1.0, 0.5)
SEEDS = (0, 1, 2)
WINDOW = 600.0
N_REQUESTS = 12000
N_SUBJECTS = 1500
POLICIES = ("privfuse", "privfuse_exact")


def _build(name: str, trace: Any) -> Any:
    if name == "privfuse":
        return build_privfuse(trace)
    return build_privfuse(trace, PrivFuseConfig(exact=True))


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cap in CAPS:
        for seed in SEEDS:
            trace = default_trace(
                n_requests=N_REQUESTS, n_subjects=N_SUBJECTS, cap_eps=cap, seed=seed
            )
            for name in POLICIES:
                policy = _build(name, trace)
                market = Market(
                    policy=policy,
                    caps=trace.caps,
                    platforms=tuple(f"p{i}" for i in range(trace.config.n_platforms)),
                    delta=EPS_DELTA,
                )
                started = time.perf_counter()
                result = market.run(trace.requests)
                elapsed = time.perf_counter() - started
                row: dict[str, Any] = {
                    "cap": cap,
                    "seed": seed,
                    "policy": name,
                    "window": WINDOW,
                    "requests": len(result.decisions),
                    "us_per_request": 1e6 * elapsed / max(1, len(result.decisions)),
                }
                row.update(result.summary())
                row.update(_windowed_truth(result.decisions, WINDOW, cap))
                rows.append(row)
                print(
                    f"cap={cap} seed={seed} {name}: "
                    f"avail={row['availability']:.3f} "
                    f"viol={int(row['hard_cap_violations'])} "
                    f"win_peak={row['windowed_peak_eps']:.3f} "
                    f"us={row['us_per_request']:.1f} "
                    f"bytes={row.get('bytes', 0) / 1e6:.2f}MB",
                    flush=True,
                )
    write_csv("e20_equiv", rows)
    write_json(
        "e20_equiv_meta",
        {
            "caps": list(CAPS),
            "seeds": list(SEEDS),
            "window": WINDOW,
            "n_requests": N_REQUESTS,
            "n_subjects": N_SUBJECTS,
            "policies": list(POLICIES),
            "note": "identical ring, breaker, admission controller and coordinator; "
            "only the accountant store differs",
        },
    )
    return rows


if __name__ == "__main__":
    run()
