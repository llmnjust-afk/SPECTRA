"""E12: does the settlement path stay sound and useful under concurrency?

Two questions. First, atomicity: when many platform threads race for the same
subject's budget, can the cap be overshot? Second, throughput: how does the
reference implementation scale with threads?

Reservations are serialised per subject by striped locks, so threads working on
different subjects do not contend. A single global lock is measured alongside as
the naive alternative; it is correct but collapses under thread pressure because
every request queues behind every other one.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.experiments.common import write_csv, write_json
from privfuse.ledger.ledger import Coordinator
from privfuse.trace.generator import EPS_DELTA

COST = CostVector(eps_pure=0.01, rho=0.0, delta=0.0)


def _atomicity(
    n_threads: int, per_thread: int, cap: float, striped: bool = True
) -> dict[str, Any]:
    coordinator = Coordinator(caps={"s1": cap}, ttl=1000.0, striped=striped)
    admitted = 0
    lock = threading.Lock()

    def worker(k: int) -> None:
        nonlocal admitted
        for i in range(per_thread):
            ok, _ = coordinator.try_reserve(f"t{k}-{i}", "ten", f"p{k}", {"s1": COST})
            if ok:
                coordinator.commit(f"t{k}-{i}")
                with lock:
                    admitted += 1

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(n_threads)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    spent = coordinator.ledger.committed("s1").eps(EPS_DELTA)
    return {
        "mode": "atomicity_striped" if striped else "atomicity_global",
        "threads": n_threads,
        "attempts": n_threads * per_thread,
        "admitted": admitted,
        "expected_admitted": int(cap / COST.eps(EPS_DELTA) + 1e-9),
        "spent_eps": spent,
        "cap": cap,
        "violations": int(spent > cap + 1e-12),
        "seconds": elapsed,
        "ops_per_second": (n_threads * per_thread) / elapsed,
    }


def _throughput(
    n_threads: int, per_thread: int, striped: bool = True
) -> dict[str, Any]:
    caps = {
        f"t{k}-s{i}": 1000.0 for k in range(n_threads) for i in range(per_thread)
    }
    coordinator = Coordinator(caps=caps, ttl=1000.0, striped=striped)

    def worker(k: int) -> None:
        for i in range(per_thread):
            subject = f"t{k}-s{i}"
            coordinator.try_reserve(f"x{k}-{i}", "ten", f"p{k}", {subject: COST})
            coordinator.commit(f"x{k}-{i}")

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(n_threads)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    total = n_threads * per_thread
    return {
        "mode": "throughput_striped" if striped else "throughput_global",
        "threads": n_threads,
        "attempts": total,
        "admitted": total,
        "expected_admitted": total,
        "spent_eps": 0.0,
        "cap": 0.0,
        "violations": 0,
        "seconds": elapsed,
        "ops_per_second": total / elapsed,
    }


def run() -> list[dict[str, Any]]:
    rows = [_atomicity(threads, 200, 1.0) for threads in (2, 4, 8, 16)]
    rows.append(_atomicity(4, 200, 1.0, striped=False))
    rows += [_throughput(threads, 4000) for threads in (1, 2, 4)]
    rows += [_throughput(threads, 4000, striped=False) for threads in (1, 4)]
    write_csv("e12_concurrency", rows)
    write_json(
        "e12_concurrency_meta",
        {
            "cost_eps": COST.eps(EPS_DELTA),
            "note": "throughput uses disjoint subjects; atomicity shares one subject",
        },
    )
    return rows


if __name__ == "__main__":
    for row in run():
        print(row)
