"""E16: an exact sliding-window accountant as the strong baseline.

Section VII-E of the paper used to say that an exact accountant cannot express a
windowed SLO. That is false, and this experiment is the honest correction: an
implementation that keeps the full per-subject event log evaluates the window
exactly, without a sketch and without an error bound. This module measures what
that costs and what it buys at the population where it is affordable, and it
separates two guarantees that are easy to conflate:

* a *cumulative* hard cap, which bounds a subject's lifetime leakage;
* a *windowed* cap, which bounds the spend in any interval of length W and says
  nothing about what happened before the window.

Both are checked against exact ground truth, per allowed request, with a two
pointer over each subject's allowed events.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from privfuse.baselines import ExactGlobalPolicy, ExactWindowedPolicy, StaticQuotaPolicy
from privfuse.dp.cost import CostVector
from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.factory import build_privfuse
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA

CAPS = (1.0, 0.5)
SEEDS = (0, 1, 2)
WINDOW = 600.0
N_REQUESTS = 12000
N_SUBJECTS = 1500
POLICIES = ("privfuse", "exact_windowed", "exact_global", "static_quota")


def _build(name: str, trace: Any) -> Any:
    if name == "privfuse":
        return build_privfuse(trace)
    if name == "exact_windowed":
        return ExactWindowedPolicy(caps=trace.caps, window=WINDOW)
    if name == "exact_global":
        return ExactGlobalPolicy(caps=trace.caps)
    return StaticQuotaPolicy(caps=trace.caps)


def _windowed_truth(
    decisions: list[Any], window: float, cap: float
) -> dict[str, float]:
    """Worst windowed spend over the trace, and how many subjects cross the cap.

    For every allowed request we sum the spend of the same subject inside the
    trailing window that ends at that request. Costs are composed with the
    vector algebra, so the check uses the same epsilon conversion as the policy.
    """
    events: dict[str, list[tuple[float, CostVector]]] = defaultdict(list)
    for decision in decisions:
        if not decision.allowed:
            continue
        for subject in decision.request.subjects:
            events[subject].append((decision.request.timestamp, decision.charged))

    worst = 0.0
    breaching = 0
    for subject, log in events.items():
        queue: deque[tuple[float, CostVector]] = deque()
        peak = 0.0
        for timestamp, cost in log:
            queue.append((timestamp, cost))
            while queue and queue[0][0] <= timestamp - window:
                queue.popleft()
            total = CostVector.zero()
            for _, held in queue:
                total = total + held
            peak = max(peak, total.eps(EPS_DELTA))
        if peak > cap + 1e-9:
            breaching += 1
        worst = max(worst, peak)
    return {"windowed_peak_eps": worst, "windowed_breaching": float(breaching)}


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
                cap_eps = trace.caps[next(iter(trace.caps))]
                row["cumulative_breaching"] = float(
                    sum(
                        1
                        for s in market.truth.subjects()
                        if market.truth.get(s).eps(EPS_DELTA) > cap_eps + 1e-9
                    )
                )
                rows.append(row)
                print(
                    f"cap={cap} seed={seed} {name}: "
                    f"avail={row['availability']:.3f} cum_viol={int(row['hard_cap_violations'])} "
                    f"win_peak={row['windowed_peak_eps']:.3f} "
                    f"bytes={row.get('bytes', 0) / 1e6:.2f}MB",
                    flush=True,
                )
    write_csv("e16_windowed", rows)
    write_json(
        "e16_windowed_meta",
        {
            "caps": list(CAPS),
            "seeds": list(SEEDS),
            "window": WINDOW,
            "n_requests": N_REQUESTS,
            "n_subjects": N_SUBJECTS,
            "policies": list(POLICIES),
        },
    )
    return rows


if __name__ == "__main__":
    run()
