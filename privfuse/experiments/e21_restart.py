"""E21: kill the coordinator process and restart it from its log.

E19 injects faults inside one process; the ledger stays alive, so it never loses
a committed charge.  This experiment removes that assumption.  A worker process
runs the settlement path and kills itself with SIGKILL at a chosen step: before
the reservation, after it, after the commit, or after the answer has been handed
to the client.  A fresh process then restarts from the same log and continues.

Two arms run the identical schedule and the identical trace:

* ``durable`` -- the coordinator writes every transition to an fsync-ed log and
  replays it on restart;
* ``volatile`` -- the coordinator keeps its state in memory only, which is what
  the implementation shipped before this experiment.

The quantity both arms are scored on is client-side: the answers the tenant
actually holds.  That is the information that left the building, and it does not
depend on what the ledger believes about itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.experiments.common import write_csv, write_json
from privfuse.ledger.durable import DurableLedger
from privfuse.ledger.ledger import State
from privfuse.trace.generator import EPS_DELTA

N_REQUESTS = 600
N_SUBJECTS = 10
CAP = 0.2
SEED = 1
TTL = 30.0
KILLS = (
    (60, "before_reserve"),
    (130, "after_reserve"),
    (200, "after_commit"),
    (270, "after_answer"),
    (340, "after_reserve"),
    (410, "after_commit"),
)


def _run_worker(spec_path: Path) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "privfuse.experiments._e21_worker", str(spec_path)],
        check=False,
        capture_output=True,
    )
    return completed.returncode


def _reconcile(answers_path: Path, wal: Path | None) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in answers_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    answered = {record["tx"] for record in records}
    spend: dict[str, CostVector] = {}
    for record in records:
        cost = CostVector(eps_pure=record["eps_pure"], rho=record["rho"])
        for subject in record["subjects"]:
            spend[subject] = spend.get(subject, CostVector.zero()) + cost
    worst = max((cost.eps(EPS_DELTA) for cost in spend.values()), default=0.0)
    result: dict[str, Any] = {
        "answers": float(len(records)),
        "distinct_answers": float(len(answered)),
        "duplicate_answers": float(len(records) - len(answered)),
        "worst_client_eps": worst,
        "client_violations": float(worst > CAP + 1e-9),
        "subjects_over_cap": float(
            sum(1 for cost in spend.values() if cost.eps(EPS_DELTA) > CAP + 1e-9)
        ),
    }
    if wal is not None:
        ledger = DurableLedger(wal, ttl=TTL, delta=EPS_DELTA)
        committed = {
            tx for tx in answered if ledger.state(tx) is State.COMMITTED
        }
        ledger_worst = max(
            (cost.eps(EPS_DELTA) for cost in (ledger.committed(s) for s in spend)),
            default=0.0,
        )
        result.update(
            {
                "wal_records": float(ledger.replayed),
                "torn_records": float(ledger.torn_records),
                "free_answers": float(len(answered) - len(committed)),
                "withheld": float(
                    sum(
                        1
                        for tx, res in ledger._reservations.items()
                        if res.state is State.COMMITTED and tx not in answered
                    )
                ),
                "ledger_worst_eps": ledger_worst,
                "ledger_violations": float(ledger_worst > CAP + 1e-9),
            }
        )
        ledger.close()
    return result


def _durability_cost(samples: int = 300) -> list[dict[str, float]]:
    '''Per-transaction cost of fsync-ing each transition, on this filesystem.'''
    import tempfile as _tempfile
    import time

    from privfuse.ledger.ledger import SettlementLedger

    rows: list[dict[str, float]] = []
    with _tempfile.TemporaryDirectory() as tmp:
        for name in ("memory", "durable"):
            path = Path(tmp) / f"{name}.wal"
            ledger = (
                SettlementLedger(ttl=TTL, delta=EPS_DELTA)
                if name == "memory"
                else DurableLedger(path, ttl=TTL, delta=EPS_DELTA)
            )
            costs = {"a": CostVector.from_gaussian(100.0, 1.0)}
            started = time.perf_counter()
            for index in range(samples):
                ledger.reserve(f"t{index}", "ten", costs, now=float(index), platform="p0")
                ledger.commit(f"t{index}", now=float(index) + 0.1)
            elapsed = time.perf_counter() - started
            if isinstance(ledger, DurableLedger):
                ledger.close()
            rows.append({"ledger": name, "us_per_transaction": 1e6 * elapsed / samples})
    return rows


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for arm in ("durable", "volatile"):
            arm_dir = base / arm
            arm_dir.mkdir()
            wal = arm_dir / "settlement.wal"
            answers = arm_dir / "answers.jsonl"
            kills = 0
            for index, point in KILLS:
                spec = {
                    "wal": str(wal),
                    "answers": str(answers),
                    "durable": arm == "durable",
                    "n_requests": N_REQUESTS,
                    "n_subjects": N_SUBJECTS,
                    "cap": CAP,
                    "seed": SEED,
                    "ttl": TTL,
                    "kill_index": index,
                    "kill_point": point,
                }
                spec_path = arm_dir / f"spec_{index}_{point}.json"
                spec_path.write_text(json.dumps(spec), encoding="utf-8")
                code = _run_worker(spec_path)
                kills += int(code == -9)
                print(f"{arm}: kill at {index} ({point}) -> exit {code}", flush=True)
            spec["kill_index"] = -1
            spec_path = arm_dir / "spec_final.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            code = _run_worker(spec_path)
            print(f"{arm}: final run -> exit {code}", flush=True)
            row: dict[str, Any] = {
                "arm": arm,
                "kills": float(kills),
                "n_requests": float(N_REQUESTS),
                "n_subjects": float(N_SUBJECTS),
                "cap": CAP,
            }
            row.update(_reconcile(answers, wal if arm == "durable" else None))
            rows.append(row)
            print(f"{arm}: {row}", flush=True)
    write_csv("e21_restart", rows)
    write_csv("e21_cost", _durability_cost())
    write_json(
        "e21_restart_meta",
        {
            "kills": [{"index": index, "point": point} for index, point in KILLS],
            "n_requests": N_REQUESTS,
            "n_subjects": N_SUBJECTS,
            "cap": CAP,
            "seed": SEED,
            "ttl": TTL,
            "metric": "client-side answers; worst per-subject spend is a sum over answers held",
        },
    )
    return rows


if __name__ == "__main__":
    run()
