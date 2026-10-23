"""E25: does the monitored violation rate track the population violation rate?

The SLO is defined over every subject-epoch, but the controller can only sample
the hot table.  The generator holds exact ground truth, so the gap can be
measured directly: at fixed checkpoints the experiment recomputes the windowed
spend of every subject, compares that population rate with the rate the hot
table reports, and counts the violations the monitor misses.

The trace is compressed into 600 s so that the 600 s window binds; the soft
threshold is 0.8 of a 0.5-eps cap.  Popularity is swept from heavy-tailed
(alpha 1.15) to flat (alpha 0.6), the regime in which the violators stop being
heavy hitters.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.experiments.common import write_csv
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.trace.generator import EPS_DELTA, TraceConfig, generate_trace

ALPHAS = (0.5, 0.8)
CAP = 0.5
CHECKPOINT = 500
WINDOW = 600.0
DURATION = 600.0


def _true_window(
    history: dict[str, deque], now: float, window: float
) -> dict[str, float]:
    """Composed epsilon over the window: add cost vectors, then convert.

    Summing per-event epsilon would overstate the loss, because g is
    subadditive; zCDP composition adds rho and converts once.
    """
    spend: dict[str, float] = {}
    cutoff = now - window
    for subject, events in history.items():
        total = CostVector.zero()
        for stamp, value in reversed(events):
            if stamp < cutoff:
                break
            total = total + value
        composed = total.eps(EPS_DELTA)
        if composed > 0.0:
            spend[subject] = composed
    return spend


def _run(trace, hot_capacity: int, alpha: float) -> list[dict[str, Any]]:
    config = PrivFuseConfig(window=WINDOW, hot_capacity=hot_capacity)
    controller = build_privfuse(trace, config).controller
    history: dict[str, deque] = {}
    rows: list[dict[str, Any]] = []
    total = len(trace.subjects)
    for index, request in enumerate(trace.requests):
        decision = controller.evaluate(request)
        if decision.allowed:
            controller.complete(decision, now=request.timestamp)
            for subject in request.subjects:
                history.setdefault(subject, deque()).append(
                    (request.timestamp, decision.charged)
                )
                while (
                    history[subject]
                    and history[subject][0][0] < request.timestamp - WINDOW
                ):
                    history[subject].popleft()
        if index % CHECKPOINT:
            continue
        now = request.timestamp
        spend = _true_window(history, now, WINDOW)
        threshold = alpha * CAP
        true_violating = {s for s, value in spend.items() if value > threshold + 1e-12}
        hot = dict(controller.accountant.hot_estimates(now=now, window=WINDOW))
        flagged = {
            s for s, cost in hot.items() if cost.eps(EPS_DELTA) > threshold + 1e-12
        }
        sketch_flagged = {
            s
            for s in spend
            if controller.accountant.upper_bound_eps(
                s, EPS_DELTA, now=now, window=WINDOW
            )
            > threshold + 1e-12
        }
        caught = flagged & true_violating
        sketch_caught = sketch_flagged & true_violating
        rows.append(
            {
                "hot_capacity": float(hot_capacity),
                "alpha": alpha,
                "checkpoint": float(index),
                "subjects": float(total),
                "active": float(len(spend)),
                "hot": float(len(hot)),
                "coverage": float(len(hot) / total),
                "p_true": float(len(true_violating) / total),
                "p_monitored": float(len(flagged) / total),
                "true_violating": float(len(true_violating)),
                "flagged": float(len(flagged)),
                "missed": float(len(true_violating - flagged)),
                "false_alarms": float(len(flagged - true_violating)),
                "recall": (
                    float(len(caught) / len(true_violating)) if true_violating else 1.0
                ),
                "p_sketch": float(len(sketch_flagged) / total),
                "sketch_recall": (
                    float(len(sketch_caught) / len(true_violating))
                    if true_violating
                    else 1.0
                ),
                "sketch_false_alarms": float(len(sketch_flagged - true_violating)),
            }
        )
    return rows


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for zipf in (1.15, 0.6):
        trace = generate_trace(
            TraceConfig(
                seed=3, duration=DURATION, cap_eps=CAP, zipf_alpha=zipf
            )
        )
        for alpha in ALPHAS:
            for hot_capacity in (8, 64, 256, 1024):
                block = _run(trace, hot_capacity, alpha)
                rows.extend({**row, "zipf": zipf} for row in block)
                print(f"zipf={zipf} alpha={alpha} H={hot_capacity} done", flush=True)
    write_csv("e25_population_slo", rows)
    summary: list[dict[str, Any]] = []
    for zipf in (1.15, 0.6):
        for alpha in ALPHAS:
            for hot_capacity in (8, 64, 256, 1024):
                block = [
                    r
                    for r in rows
                    if r["zipf"] == zipf
                    and r["alpha"] == alpha
                    and r["hot_capacity"] == float(hot_capacity)
                ]
                violated = sum(r["true_violating"] for r in block)
                summary.append(
                    {
                        "zipf": zipf,
                        "alpha": alpha,
                        "hot_capacity": hot_capacity,
                        "checkpoints": len(block),
                        "p_true": sum(r["p_true"] for r in block) / len(block),
                        "p_monitored": sum(r["p_monitored"] for r in block) / len(block),
                        "coverage": sum(r["coverage"] for r in block) / len(block),
                        "true_violating": violated,
                        "missed": sum(r["missed"] for r in block),
                        "false_alarms": sum(r["false_alarms"] for r in block),
                        "recall": (
                            sum(r["recall"] * r["true_violating"] for r in block) / violated
                            if violated
                            else 1.0
                        ),
                        "p_sketch": sum(r["p_sketch"] for r in block) / len(block),
                        "sketch_recall": (
                            sum(r["sketch_recall"] * r["true_violating"] for r in block)
                            / violated
                            if violated
                            else 1.0
                        ),
                        "sketch_false_alarms": sum(r["sketch_false_alarms"] for r in block),
                    }
                )
    write_csv("e25_population_slo_summary", summary)
    return rows


if __name__ == "__main__":
    rows = run()
    print(len(rows), "checkpoints")
