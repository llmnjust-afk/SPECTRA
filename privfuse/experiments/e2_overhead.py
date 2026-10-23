"""E2: per-request accounting overhead."""

from __future__ import annotations

import time
from typing import Any

from privfuse.accounting.online import (
    OnlineAccountant,
    OnlineAccountantConfig,
    ring_epochs_for,
)
from privfuse.dp.accountant import ExactAccountant
from privfuse.dp.mechanisms import gaussian_cost
from privfuse.experiments.common import write_csv, write_json
from privfuse.trace.generator import EPS_DELTA

COST = gaussian_cost(0.02, EPS_DELTA, 1.0)


def _bench_online(width: int, n_subjects: int, n_ops: int = 20000) -> tuple[float, float, int]:
    accountant = OnlineAccountant(
        OnlineAccountantConfig(
            width=width,
            depth=4,
            epoch_seconds=300.0,
            ring_size=ring_epochs_for(600.0, 300.0),
        )
    )
    start = time.perf_counter()
    for i in range(n_ops):
        subject = f"s{i % n_subjects:06d}"
        accountant.observe(subject, COST, now=float(i) * 0.1)
        accountant.upper_bound_eps(subject, EPS_DELTA, now=float(i) * 0.1, window=None)
    elapsed = time.perf_counter() - start
    return 1e6 * elapsed / n_ops, accountant.nbytes() / 1e6, accountant.nbytes()


def _bench_exact(n_subjects: int, n_ops: int = 20000) -> tuple[float, float, int]:
    exact = ExactAccountant()
    start = time.perf_counter()
    for i in range(n_ops):
        subject = f"s{i % n_subjects:06d}"
        exact.add(subject, COST, timestamp=float(i) * 0.1)
        exact.get(subject).eps(EPS_DELTA)
    elapsed = time.perf_counter() - start
    return 1e6 * elapsed / n_ops, 256 * exact.n_subjects() / 1e6, 256 * exact.n_subjects()


def run(widths: list[int] | None = None) -> list[dict[str, Any]]:
    widths = widths or [1 << 10, 1 << 12, 1 << 14, 1 << 16]
    rows: list[dict[str, Any]] = []
    for width in widths:
        us, mb, nbytes = _bench_online(width=width, n_subjects=5000)
        rows.append(
            {
                "backend": "privfuse_sketch",
                "width": width,
                "us_per_request": us,
                "memory_mb": mb,
                "bytes": nbytes,
            }
        )
    us, mb, nbytes = _bench_exact(n_subjects=5000)
    rows.append(
        {
            "backend": "exact",
            "width": 0,
            "us_per_request": us,
            "memory_mb": mb,
            "bytes": nbytes,
        }
    )
    write_csv("e2_overhead", rows)
    write_json(
        "e2_overhead_meta",
        {
            "slowdown_vs_exact": float(
                next(r["us_per_request"] for r in rows if r["width"] == (1 << 14)) / us
            )
        },
    )
    return rows


if __name__ == "__main__":
    for row in run():
        print(row)
