"""E26: is the sketch still the right estimator when the active set is sparse?

E23 compares the sketch with an exact window table that allocates one slot per
subject per epoch.  At a million subjects that table is 1.2 GB, but only a
fraction of the population is active inside any window, so a sparse exact map is
the honest competitor.  This experiment measures, for the same window and ring,
the memory of three estimators and of the settlement state behind them:

* ``exact-dense``: ``N x ring`` float64 slots, indexed by subject;
* ``exact-sparse``: one ring per active subject, in a dictionary;
* ``sketch``: four Count-Min rows plus a hot table, independent of ``N``.

Python object overhead is measured with ``tracemalloc``; the dense array is
measured with ``nbytes``.  Ledger cost is measured on ``min(U, 10^5)`` commits
and extrapolated per committed subject, and the WAL cost is the measured record
size times the number of records.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import time
import tracemalloc
from typing import Any

import numpy as np

from privfuse.accounting.online import OnlineAccountant, OnlineAccountantConfig
from privfuse.dp.cost import CostVector
from privfuse.experiments.common import write_csv
from privfuse.ledger.durable import DurableLedger
from privfuse.ledger.ledger import Coordinator
from privfuse.trace.generator import EPS_DELTA

N = 1_000_000
RING = 4
ACTIVITY = (0.01, 0.1, 0.5, 1.0)
COST = CostVector(eps_pure=0.0, rho=4.3e-6, delta=0.0)
SAMPLE = 20_000
LEDGER_SAMPLE = 100_000


def _sparse_bytes(subjects: int) -> tuple[int, float]:
    tracemalloc.start()
    table = {f"s{i:07d}": [0.0] * RING for i in range(subjects)}
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    started = time.perf_counter()
    for i in range(min(subjects, SAMPLE)):
        table[f"s{i:07d}"][i % RING] += COST.rho
    elapsed = (time.perf_counter() - started) / min(subjects, SAMPLE)
    return current, elapsed * 1e6


def _sketch() -> tuple[int, float]:
    accountant = OnlineAccountant(OnlineAccountantConfig(epoch_seconds=300.0, ring_size=RING))
    tracemalloc.start()
    started = time.perf_counter()
    for i in range(SAMPLE):
        accountant.observe(f"s{i:07d}", COST, now=0.0)
    elapsed = (time.perf_counter() - started) / SAMPLE
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return accountant.nbytes(), elapsed * 1e6


def _ledger_bytes(subjects: int) -> tuple[float, float]:
    """Bytes per committed subject and per-commit microseconds."""
    sample = min(subjects, LEDGER_SAMPLE)
    coordinator = Coordinator(caps={}, ttl=30.0)
    for i in range(sample):
        coordinator.caps[f"s{i:07d}"] = 1.0
    tracemalloc.start()
    started = time.perf_counter()
    for i in range(sample):
        coordinator.try_reserve(f"tx{i}", "t", "p0", {f"s{i:07d}": COST})
        coordinator.commit(f"tx{i}")
    elapsed = (time.perf_counter() - started) / sample
    current, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return current / sample, elapsed * 1e6


def _wal_bytes() -> float:
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "wal.log"
        coordinator = Coordinator(caps={}, ttl=30.0, ledger=DurableLedger(str(path), ttl=30.0))
        for i in range(500):
            coordinator.caps[f"s{i:07d}"] = 1.0
            coordinator.try_reserve(f"tx{i}", "t", "p0", {f"s{i:07d}": COST})
            coordinator.commit(f"tx{i}")
        coordinator.ledger.close()
        return path.stat().st_size / 500.0


def run() -> list[dict[str, Any]]:
    sketch_bytes, sketch_us = _sketch()
    per_commit, commit_us = _ledger_bytes(int(max(ACTIVITY) * N))
    wal_per_tx = _wal_bytes()
    rows: list[dict[str, Any]] = []
    for activity in ACTIVITY:
        subjects = int(activity * N)
        sparse_bytes, sparse_us = _sparse_bytes(subjects)
        dense_bytes = N * RING * 8
        ledger_bytes = per_commit * subjects
        wal_bytes = wal_per_tx * subjects
        for name, estimator_bytes, update_us in (
            ("exact_dense", dense_bytes, 0.0),
            ("exact_sparse", sparse_bytes, sparse_us),
            ("sketch", sketch_bytes, sketch_us),
        ):
            rows.append(
                {
                    "activity": activity,
                    "active_subjects": float(subjects),
                    "estimator": name,
                    "estimator_bytes": float(estimator_bytes),
                    "estimator_mb": estimator_bytes / 2**20,
                    "ledger_bytes": float(ledger_bytes),
                    "wal_bytes": float(wal_bytes),
                    "total_bytes": float(estimator_bytes + ledger_bytes + wal_bytes),
                    "total_mb": (estimator_bytes + ledger_bytes + wal_bytes) / 2**20,
                    "update_us": update_us,
                    "commit_us": commit_us if name != "exact_dense" else 0.0,
                    "subjects": float(N),
                    "ring": float(RING),
                }
            )
            print(
                f"activity={activity:.0%} {name}: estimator {estimator_bytes/2**20:.1f} MB, "
                f"total {(estimator_bytes+ledger_bytes+wal_bytes)/2**20:.1f} MB",
                flush=True,
            )
    write_csv("e26_sparse", rows)
    return rows


if __name__ == "__main__":
    run()
