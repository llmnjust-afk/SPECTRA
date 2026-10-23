"""E1: accounting accuracy of the one-sided sketch against exact composition."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from privfuse.dp.accountant import ExactAccountant
from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.sketch.costsketch import CostSketch
from privfuse.trace.generator import EPS_DELTA


def evaluate(width: int, hot_capacity: int, n_requests: int = 8000, seed: int = 0) -> dict[str, Any]:
    trace = default_trace(n_requests=n_requests, n_subjects=3000, seed=seed)
    sketch = CostSketch(width=width, depth=4, hot_capacity=hot_capacity)
    truth = ExactAccountant()

    started = time.perf_counter()
    for request in trace.requests:
        for subject in request.subjects:
            sketch.add(subject, request.cost)
            truth.add(subject, request.cost)
    elapsed = time.perf_counter() - started

    errors: list[float] = []
    relative: list[float] = []
    truth_values: list[float] = []
    false_negatives = 0
    for subject in truth.subjects():
        true_eps = truth.get(subject).eps(EPS_DELTA)
        if true_eps <= 1e-12:
            continue
        estimate = sketch.estimate(subject).eps(EPS_DELTA)
        errors.append(estimate - true_eps)
        relative.append((estimate - true_eps) / true_eps)
        truth_values.append(true_eps)
        if estimate < true_eps - 1e-12:
            false_negatives += 1

    top_cut = np.quantile(truth_values, 0.99) if truth_values else 0.0
    top_relative = [
        rel for rel, true in zip(relative, truth_values) if true >= top_cut
    ]
    return {
        "width": width,
        "hot_capacity": hot_capacity,
        "requests": len(trace.requests),
        "subjects": len(errors),
        "false_negatives": false_negatives,
        "mean_relative_error": float(np.mean(relative)),
        "p99_relative_error": float(np.quantile(relative, 0.99)),
        "max_relative_error": float(np.max(relative)),
        "top1pct_relative_error": float(np.mean(top_relative)) if top_relative else 0.0,
        "mean_absolute_error": float(np.mean(errors)),
        "p99_absolute_error": float(np.quantile(errors, 0.99)),
        "bytes": sketch.nbytes(),
        "update_us": 1e6 * elapsed / max(1, len(trace.requests)),
        "total_mass": sketch.total_mass(),
        "error_bound": sketch.error_bound().eps(EPS_DELTA),
    }


def run(widths: list[int] | None = None) -> list[dict[str, Any]]:
    widths = widths or [1 << 9, 1 << 11, 1 << 13, 1 << 15]
    rows: list[dict[str, Any]] = []
    for width in widths:
        for hot_capacity in (1, 1024):
            rows.append(evaluate(width=width, hot_capacity=hot_capacity))
    write_csv("e1_accounting", rows)
    write_json(
        "e1_accounting_meta",
        {
            "rows": len(rows),
            "false_negatives_total": float(sum(r["false_negatives"] for r in rows)),
            "max_error_bound_ratio": float(
                max(r["error_bound"] for r in rows) / max(1e-9, max(r["total_mass"] for r in rows))
            ),
        },
    )
    return rows


if __name__ == "__main__":
    for row in run():
        print(row)
