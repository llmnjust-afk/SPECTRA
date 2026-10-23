"""E14: hot-table churn sensitivity.

The hot table is the component that makes estimates exact for heavy subjects.
Its correctness does not depend on which subjects it holds, but its accuracy
does: a subject that is evicted and later returns is re-seeded from the
Count-Min upper bound, so its counter stays safe but becomes pessimistic. This
experiment manufactures that situation by rotating cohorts of newly hot
subjects through the table, and measures what churn costs in availability and
in over-estimate, and whether it can ever cost safety.

Variants hold the base workload fixed and vary only the cohort size per epoch
(0 = no churn) and the table capacity. A capacity of 1 is the no-hot-table
control, where churn should be invisible because every subject is sketch-only.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from privfuse.control.admission import QueryRequest
from privfuse.dp.mechanisms import gaussian_cost
from privfuse.experiments.common import write_csv, write_json
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA, TraceConfig, generate_trace

BASE = dict(n_requests=6000, n_subjects=1500, zipf_alpha=1.15)
VARIANTS = [(256, 0), (256, 100), (256, 400), (32, 400), (1, 400)]
CAPS = (1.0, 0.15)
SEEDS = (0, 1, 2)
EPOCHS = 4
REPEAT = 40


def _churn_requests(trace: Any, cohort: int) -> list[QueryRequest]:
    """Newly hot subjects per epoch, each queried REPEAT times in its epoch."""
    if cohort == 0:
        return []
    pool = trace.subjects[1200:]
    span = trace.config.duration / EPOCHS
    extra: list[QueryRequest] = []
    for epoch in range(EPOCHS):
        start = epoch * span
        step = span / (cohort * REPEAT)
        for j in range(cohort):
            subject = pool[(epoch * cohort + j) % len(pool)]
            for k in range(REPEAT):
                slot = j * REPEAT + k
                extra.append(
                    QueryRequest(
                        request_id=f"x{epoch:02d}{j:04d}{k:03d}",
                        tenant=f"t{(j + k) % 40:03d}",
                        platform=f"p{(j + k) % 3}",
                        subjects=(subject,),
                        cost=gaussian_cost(0.02, EPS_DELTA, 1.0),
                        timestamp=start + slot * step,
                    )
                )
    return extra


def _over_estimates(policy: Any, truth: Any) -> dict[str, float]:
    """Relative over-estimate of the upper bound, over subjects with real spend."""
    ratios: list[float] = []
    for subject in truth.subjects():
        actual = truth.get(subject).eps(EPS_DELTA)
        if actual <= 0.0:
            continue
        bound = policy.controller.accountant.upper_bound_eps(subject, EPS_DELTA)
        ratios.append(bound / actual - 1.0)
    if not ratios:
        return {"over_mean": 0.0, "over_p99": 0.0, "over_50pct": 0.0}
    array = np.asarray(ratios)
    return {
        "over_mean": float(array.mean()),
        "over_p99": float(np.percentile(array, 99)),
        "over_50pct": float((array > 0.5).mean()),
    }


def _one(cap: float, hot: int, cohort: int, seed: int) -> dict[str, Any]:
    cfg = TraceConfig(**BASE, cap_eps=cap, seed=seed)
    trace = generate_trace(cfg)
    requests = trace.requests + _churn_requests(trace, cohort)
    requests.sort(key=lambda r: r.timestamp)
    policy = build_privfuse(
        trace, config=PrivFuseConfig(hot_capacity=hot), delta=EPS_DELTA
    )
    market = Market(
        policy=policy,
        caps=trace.caps,
        platforms=tuple(f"p{i}" for i in range(cfg.n_platforms)),
        delta=EPS_DELTA,
    )
    started = time.perf_counter()
    result = market.run(requests)
    elapsed = time.perf_counter() - started
    row: dict[str, Any] = {
        "cap": cap,
        "hot_capacity": hot,
        "cohort": cohort,
        "seed": seed,
        "requests": len(result.decisions),
        "elapsed": elapsed,
    }
    row.update(result.summary())
    row.update(_over_estimates(policy, market.truth))
    base = [d for d in result.decisions if d.request.request_id.startswith("r")]
    row["base_requests"] = float(len(base))
    row["base_availability"] = (
        sum(1 for d in base if d.allowed) / len(base) if base else 1.0
    )
    row["hot_entries"] = float(len(policy.controller.accountant.hot_estimates()))
    row["us_per_request"] = 1e6 * elapsed / max(1, len(result.decisions))
    return row


def _line(row: dict[str, Any]) -> str:
    return (
        f"cap={row['cap']} hot={row['hot_capacity']} cohort={row['cohort']} "
        f"seed={row['seed']}: avail={row['availability']:.3f} "
        f"viol={int(row['hard_cap_violations'])} base_avail={row['base_availability']:.3f} "
        f"over_p99={row['over_p99']:.2f}"
    )


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cap in CAPS:
        chosen = VARIANTS if cap == BASE.get("cap_eps", 1.0) else [(256, 0), (256, 400), (1, 400)]
        for hot, cohort in chosen:
            for seed in SEEDS:
                rows.extend([_one(cap, hot, cohort, seed)])
                print(_line(rows[-1]), flush=True)
    write_csv("e14_churn", rows)
    write_json(
        "e14_churn_meta",
        {
            "variants": [list(v) for v in VARIANTS],
            "caps": list(CAPS),
            "seeds": list(SEEDS),
            "epochs": EPOCHS,
            "repeat": REPEAT,
            "base": BASE,
        },
    )
    return rows


if __name__ == "__main__":
    run()
