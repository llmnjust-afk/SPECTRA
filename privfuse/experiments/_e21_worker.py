"""Worker process for E21: run a workload and die at a chosen settlement step.

Run as ``python3 -m privfuse.experiments._e21_worker <spec.json>``. The spec
names the WAL, the client-side answer log, the trace parameters and the point at
which the process should kill itself with SIGKILL (no unwinding, no flush).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

from privfuse.experiments.common import default_trace
from privfuse.ledger.durable import DurableLedger
from privfuse.ledger.ledger import Coordinator, LedgerError, SettlementLedger, State

KILL_POINTS = ("before_reserve", "after_reserve", "after_commit", "after_answer")


def _now() -> float:
    return time.time()


def _append_answer(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _answered(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["tx"])
    return done


def main(spec_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text())
    answers_path = Path(spec["answers"])
    trace = default_trace(
        n_requests=spec["n_requests"],
        n_subjects=spec["n_subjects"],
        cap_eps=spec["cap"],
        seed=spec["seed"],
    )
    delta = 1e-5
    if spec["durable"]:
        ledger: SettlementLedger = DurableLedger(spec["wal"], ttl=spec["ttl"], delta=delta)
    else:
        ledger = SettlementLedger(ttl=spec["ttl"], delta=delta)
    coordinator = Coordinator(caps=trace.caps, ttl=spec["ttl"], delta=delta, ledger=ledger)

    done = _answered(answers_path)
    kill_index = int(spec.get("kill_index", -1))
    kill_point = spec.get("kill_point", KILL_POINTS[0])
    ledger.tick(_now())

    for index, request in enumerate(trace.requests):
        tx_id = f"t{index:04d}"
        if tx_id in done:
            continue
        costs = {subject: request.cost for subject in request.subjects}

        if 0 <= kill_index <= index and kill_point == "before_reserve":
            os.kill(os.getpid(), signal.SIGKILL)

        state = ledger.state(tx_id)
        if state is State.COMMITTED:
            continue
        if state is State.RESERVED:
            coordinator.commit(tx_id, now=_now())
        elif state in (State.RELEASED, State.EXPIRED):
            continue
        else:
            try:
                admitted, _ = coordinator.try_reserve(
                    tx_id, request.tenant, request.platform, costs, now=_now()
                )
            except LedgerError:
                continue
            if not admitted:
                continue

        if 0 <= kill_index <= index and kill_point == "after_reserve":
            os.kill(os.getpid(), signal.SIGKILL)

        coordinator.commit(tx_id, now=_now())
        if 0 <= kill_index <= index and kill_point == "after_commit":
            os.kill(os.getpid(), signal.SIGKILL)

        _append_answer(
            answers_path,
            {
                "tx": tx_id,
                "subjects": list(request.subjects),
                "eps_pure": request.cost.eps_pure,
                "rho": request.cost.rho,
            },
        )
        if 0 <= kill_index <= index and kill_point == "after_answer":
            os.kill(os.getpid(), signal.SIGKILL)

    if isinstance(ledger, DurableLedger):
        ledger.close()


if __name__ == "__main__":
    main(sys.argv[1])
