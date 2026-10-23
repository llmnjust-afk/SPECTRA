"""E19: settlement under injected faults.

Proposition 2 (*exactly-once settlement*) is an argument, and E12 only crashes a
client at a random point. Here the crash is placed at a named step of the
transaction, so each clause of the argument has its own row: after the
reservation (nothing executed), after execution (answer withheld), after commit
(answer withheld, charge kept), a client retry with the same transaction id, and
a retry that arrives after the TTL has already released the hold.

The invariants are read off the ledger rather than off the caller's bookkeeping:
an answer never leaves without a committed charge, no transaction is charged
twice, in-flight spend never exceeds the cap, and a reservation abandoned by a
dead client returns to the pool after one TTL.

Part B prices the fault tolerance at a cap large enough to see it: with crash
probability q over the three steps and the TTL expiring holds, availability falls
only by the share of budget frozen inside one TTL. Part C is the architectural
control: the same workload against one ledger per platform instead of the shared
coordinator.
"""

from __future__ import annotations

import random
import threading
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.experiments.common import write_csv, write_json
from privfuse.ledger.ledger import Coordinator, LedgerError
from privfuse.trace.generator import EPS_DELTA

CAP = 1.0
SWEEP_CAP = 50.0
UNIT = CostVector(eps_pure=0.05, rho=0.0, delta=0.0)
UNIT_EPS = UNIT.eps(EPS_DELTA)
TTL = 5.0
STEP_SECONDS = 0.05
SUBJECTS = ("s0", "s1", "s2")
PLATFORMS = ("p0", "p1", "p2")


def _tx(tx_id: str, tenant: str, platform: str, subject: str = "s0") -> dict[str, Any]:
    return {
        "tx_id": tx_id,
        "tenant": tenant,
        "platform": platform,
        "costs": {subject: UNIT},
    }


def _attempt(coord: Coordinator, tx: dict[str, Any], fault: str, now: float) -> str:
    """One platform-side transaction with an optional crash point.

    Returns ``answered``, ``rejected`` or ``crashed``. A crashed transaction
    delivers nothing, which is what the answer-withheld rule requires.
    """
    ok, _ = coord.try_reserve(tx["tx_id"], tx["tenant"], tx["platform"], tx["costs"], now=now)
    if not ok:
        return "rejected"
    if fault in ("after_reserve", "after_execute"):
        return "crashed"
    coord.commit(tx["tx_id"], now=now)
    if fault == "after_commit":
        return "crashed"
    return "answered"


def _row(part: str, fault: str, coord: Coordinator, answered: int, **extra: Any) -> dict[str, Any]:
    ledger = coord.ledger
    spent = ledger.committed_eps("s0")
    row: dict[str, Any] = {
        "part": part,
        "fault": fault,
        "answers": float(answered),
        "commits": float(ledger.commits),
        "answers_without_charge": float(max(0, answered - ledger.commits)),
        "duplicate_commits": float(ledger.duplicate_commits),
        "spent_eps": spent,
        "cap_violations": float(spent > coord.caps["s0"] + 1e-12),
    }
    row.update(extra)
    return row


def fault_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fault in ("none", "after_reserve", "after_execute", "after_commit"):
        for retry in ("immediate", "after_ttl"):
            coord = Coordinator(caps={s: CAP for s in SUBJECTS}, ttl=TTL)
            status = _attempt(coord, _tx("x1", "t0", "p0"), fault, now=0.0)
            answered = 1 if status == "answered" else 0
            held = coord.ledger.reserved_eps("s0")
            retry_status = "-"
            reclaimed = 0.0
            if status == "crashed":
                if retry == "after_ttl":
                    coord.tick(now=TTL + 1.0)
                    reclaimed = 1.0 if coord.ledger.reserved_eps("s0") == 0.0 else 0.0
                    retry_now = TTL + 2.0
                else:
                    retry_now = 0.5
                try:
                    retry_status = _attempt(coord, _tx("x1", "t0", "p0"), "none", now=retry_now)
                except LedgerError as exc:
                    retry_status = f"refused:{str(exc)[:22]}"
                if retry_status == "answered":
                    answered += 1
            row = _row(
                "matrix",
                f"{fault}/{retry}" if status == "crashed" else fault,
                coord,
                answered,
                status=status,
                retry=retry_status,
                held_before_tick=held,
                reclaimed_after_ttl=reclaimed,
            )
            rows.append(row)
            print(
                f"matrix {fault:13s} {retry:9s} status {status:8s} retry {retry_status:30s} "
                f"answers {answered} commits {coord.ledger.commits} spent {row['spent_eps']:.3f}",
                flush=True,
            )
    return rows


def crash_sweep() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    per_thread = 200
    for threads in (1, 4):
        for crash_q in (0.0, 0.01, 0.05):
            coord = Coordinator(caps={"s0": SWEEP_CAP}, ttl=TTL)
            counts = {"answered": 0, "crashed": 0, "rejected": 0}
            lock = threading.Lock()

            def worker(w: int) -> None:
                local = random.Random(1000 + w)
                for i in range(per_thread):
                    platform = PLATFORMS[(w + i) % len(PLATFORMS)]
                    now = (w * per_thread + i) * STEP_SECONDS
                    fault = (
                        local.choice(("after_reserve", "after_execute", "after_commit"))
                        if local.random() < crash_q
                        else "none"
                    )
                    try:
                        status = _attempt(coord, _tx(f"t{w}-{i}", f"ten{w}", platform), fault, now=now)
                    except LedgerError:
                        status = "rejected"
                    coord.tick(now)
                    with lock:
                        counts[status] += 1

            workers = [threading.Thread(target=worker, args=(w,)) for w in range(threads)]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join()
            frozen = coord.ledger.reserved_eps("s0")
            spent = coord.ledger.committed_eps("s0")
            row = {
                "part": "sweep",
                "fault": f"q={crash_q}",
                "threads": float(threads),
                "attempts": float(threads * per_thread),
                "answers": float(counts["answered"]),
                "commits": float(coord.ledger.commits),
                "answers_without_charge": float(max(0, counts["answered"] - coord.ledger.commits)),
                "duplicate_commits": float(coord.ledger.duplicate_commits),
                "spent_eps": spent,
                "cap_violations": float(spent > SWEEP_CAP + 1e-12),
                "crashed": float(counts["crashed"]),
                "rejected": float(counts["rejected"]),
                "frozen_at_end": frozen,
            }
            rows.append(row)
            print(
                f"sweep threads {threads} q {crash_q:.2f}: answered {counts['answered']} "
                f"crashed {counts['crashed']} rejected {counts['rejected']} "
                f"spent {spent:.2f}/{SWEEP_CAP} viol {int(row['cap_violations'])}",
                flush=True,
            )
    return rows


def local_ledgers() -> list[dict[str, Any]]:
    """Control: one ledger per platform instead of one shared coordinator."""
    ledgers = {p: Coordinator(caps={"s0": CAP}, ttl=TTL) for p in PLATFORMS}
    answered = 0
    for i in range(200):
        platform = PLATFORMS[i % len(PLATFORMS)]
        status = _attempt(ledgers[platform], _tx(f"l{i}", "t0", platform), "none", now=float(i))
        if status == "answered":
            answered += 1
    spent = sum(ledger.ledger.committed_eps("s0") for ledger in ledgers.values())
    row = {
        "part": "control",
        "fault": "local_ledgers",
        "answers": float(answered),
        "commits": float(sum(ledger.ledger.commits for ledger in ledgers.values())),
        "answers_without_charge": 0.0,
        "duplicate_commits": 0.0,
        "spent_eps": spent,
        "cap_violations": float(spent > CAP + 1e-12),
    }
    print(f"control local-ledgers answered {answered} spent {spent:.3f} (cap {CAP})", flush=True)
    return [row]


def run() -> list[dict[str, Any]]:
    rows = fault_matrix() + crash_sweep() + local_ledgers()
    write_csv("e19_faults", rows)
    write_json(
        "e19_faults_meta",
        {
            "cap_matrix": CAP,
            "cap_sweep": SWEEP_CAP,
            "unit_eps": UNIT_EPS,
            "ttl": TTL,
            "step_seconds": STEP_SECONDS,
            "attempts_per_thread": 200,
            "subjects": list(SUBJECTS),
            "platforms": list(PLATFORMS),
        },
    )
    return rows


if __name__ == "__main__":
    run()
