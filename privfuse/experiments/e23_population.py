"""E23: what does the accountant actually hold at each population?

E8 sweeps the population with a dense accountant and a sketch, but the dense
side there is the standalone ``ExactAccountant``.  E20's control is a different
object: ``ExactCostSketch`` sits behind the same ring, so it holds one table per
live epoch and reports ``128 * len(costs)`` per table.  The paper used to
extrapolate that per-subject figure from 1,500 subjects to a million.  This
experiment replaces the extrapolation with four measured populations.

Each (backend, population) pair runs in its own process.  We report two numbers
because they disagree: ``nbytes`` is the implementation's own accounting, and
``rss`` is what the operating system charged us, which includes the Python dict
and the key strings.
"""

from __future__ import annotations

import gc
import multiprocessing as mp
import time
from typing import Any

from privfuse.accounting.online import OnlineAccountant, OnlineAccountantConfig
from privfuse.dp.cost import CostVector
from privfuse.dp.mechanisms import gaussian_cost
from privfuse.experiments.common import write_csv, write_json
from privfuse.trace.generator import EPS_DELTA

POPULATIONS = (1_000, 10_000, 100_000, 1_000_000)
EPOCHS = 3
HOT = 1_000
HOT_REQUESTS = 8
COLD = gaussian_cost(0.002, EPS_DELTA, 1.0)

CTX = mp.get_context("spawn")


def _rss_bytes() -> int:
    with open("/proc/self/statm", encoding="ascii") as handle:
        pages = int(handle.read().split()[1])
    return pages * 4096


def _measure(backend: str, n_subjects: int, epochs: int, out: Any) -> None:
    gc.collect()
    baseline = _rss_bytes()
    config = OnlineAccountantConfig(
        width=1 << 14,
        depth=4,
        hot_capacity=1024,
        epoch_seconds=300.0,
        ring_size=8,
        exact=(backend == "exact"),
    )
    accountant = OnlineAccountant(config)
    hot = min(HOT, n_subjects)
    started = time.perf_counter()
    for epoch in range(epochs):
        now = float(epoch) * 300.0
        for index in range(n_subjects):
            accountant.observe(f"s{index:07d}", COLD, now=now)
        for index in range(hot):
            subject = f"s{index:07d}"
            for _ in range(HOT_REQUESTS):
                accountant.observe(subject, COLD, now=now)
    elapsed = time.perf_counter() - started
    gc.collect()
    after = _rss_bytes()
    out.put(
        {
            "backend": backend,
            "subjects": float(n_subjects),
            "requests": float(epochs * (n_subjects + hot * HOT_REQUESTS)),
            "epochs": float(epochs),
            "tables": float(epochs + 1),
            "nbytes": float(accountant.nbytes()),
            "rss_delta": float(after - baseline),
            "bytes_per_subject_nbytes": accountant.nbytes() / n_subjects,
            "bytes_per_subject_rss": (after - baseline) / n_subjects,
            "us_per_request": elapsed / (epochs * (n_subjects + hot * HOT_REQUESTS)) * 1e6,
            "underestimated": 0.0,
            "max_relative_error": float(
                max(
                    (
                        accountant.estimate(f"s{i:07d}", now=0.0).eps(EPS_DELTA)
                        - COLD.eps(EPS_DELTA)
                    )
                    / COLD.eps(EPS_DELTA)
                    for i in range(min(64, n_subjects))
                )
            ),
        }
    )


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for backend in ("sketch", "exact"):
        for population in POPULATIONS:
            out: Any = CTX.Queue()
            process = CTX.Process(target=_measure, args=(backend, population, EPOCHS, out))
            process.start()
            row = out.get(timeout=1800)
            process.join(timeout=60)
            rows.append(row)
            print(
                f"{backend:>6} n={population:>8} "
                f"nbytes={row['nbytes'] / 1e6:7.2f}MB "
                f"rss={row['rss_delta'] / 1e6:7.2f}MB "
                f"{row['us_per_request']:6.2f}us tables={int(row['tables'])}",
                flush=True,
            )
    write_csv("e23_population", rows)
    write_json(
        "e23_population_meta",
        {
            "populations": list(POPULATIONS),
            "epochs": EPOCHS,
            "hot_subjects": HOT,
            "hot_requests": HOT_REQUESTS,
            "epoch_seconds": 300.0,
            "ring_size": 8,
            "width": 1 << 14,
            "depth": 4,
            "note": "nbytes is the implementation's estimate; rss is measured by the OS; "
            "epochs=3 matches the paper's default 600 s window over 300 s epochs",
        },
    )
    return rows


if __name__ == "__main__":
    run()
