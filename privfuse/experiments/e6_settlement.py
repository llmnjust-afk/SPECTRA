"""E6: settlement safety under crashes, retries and timeouts."""

from __future__ import annotations

from typing import Any

from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.factory import build_privfuse
from privfuse.ledger.ledger import LedgerError, SettlementLedger, State
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA


def ledger_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    source = default_trace(n_requests=10, n_subjects=5, seed=3)
    cost = source.requests[0].cost
    subject = source.subjects[0]

    ledger = SettlementLedger(ttl=10.0, delta=EPS_DELTA)
    ledger.reserve("tx1", "t1", {subject: cost}, now=0.0)
    ledger.commit("tx1", now=1.0)
    ledger.commit("tx1", now=2.0)
    checks.append(
        {
            "check": "idempotent_commit",
            "passed": ledger.duplicate_commits == 1
            and ledger.state("tx1") is State.COMMITTED
            and abs(ledger.committed_eps(subject) - cost.eps(EPS_DELTA)) < 1e-12,
        }
    )

    ledger2 = SettlementLedger(ttl=5.0, delta=EPS_DELTA)
    ledger2.reserve("tx2", "t1", {subject: cost}, now=0.0)
    ledger2.tick(6.0)
    checks.append(
        {
            "check": "timeout_releases",
            "passed": ledger2.state("tx2") is State.EXPIRED
            and abs(ledger2.reserved_eps(subject)) < 1e-12,
        }
    )

    ledger3 = SettlementLedger(ttl=5.0, delta=EPS_DELTA)
    first = ledger3.reserve("tx3", "t1", {subject: cost}, now=0.0)
    second = ledger3.reserve("tx3", "t1", {subject: cost}, now=0.0)
    try:
        ledger3.reserve("tx3", "t2", {subject: cost}, now=0.0)
        hijack = False
    except LedgerError:
        hijack = True
    checks.append(
        {
            "check": "idempotent_reserve_and_tenant_binding",
            "passed": first is second and hijack,
        }
    )
    return checks


def run() -> dict[str, Any]:
    trace = default_trace(n_requests=5000, n_subjects=1000, cap_eps=1.0, seed=9)
    policy = build_privfuse(trace)
    market = Market(policy=policy, caps=trace.caps, delta=EPS_DELTA)
    market.platforms["p1"].crash_after_reserve = True
    result = market.run(trace.requests, tick_every=64)
    checks = ledger_checks()
    stats = result.summary()
    checks.append(
        {
            "check": "crash_leaves_no_double_spend",
            "passed": result.crashes == 1
            and result.ground_truth["violations"] == 0
            and stats.get("duplicate_commits", 0.0) == 0.0,
        }
    )
    checks.append(
        {
            "check": "expired_reservation_recovered",
            "passed": stats.get("expired_tx", 0.0) >= 1.0,
        }
    )
    write_csv("e6_settlement", checks)
    write_json(
        "e6_settlement_meta",
        {
            "all_passed": all(c["passed"] for c in checks),
            "crashes": result.crashes,
            "violations": result.ground_truth["violations"],
            "expired": stats.get("expired_tx", 0.0),
        },
    )
    return {"checks": checks, "summary": stats}


if __name__ == "__main__":
    out = run()
    for check in out["checks"]:
        print(check)
