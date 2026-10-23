"""Rebuild the estimator from committed charges after a restart.

The ledger is durable; the sketch, ring and hot table are not.  Without this
replay a restarted coordinator would admit against an empty estimator, which is
safe for the hard cap (the ledger is exact) but blind for the windowed SLO until
the traffic refills it.
"""

from __future__ import annotations

from privfuse.accounting.online import OnlineAccountant
from privfuse.ledger.ledger import SettlementLedger


def rebuild_estimator(accountant: OnlineAccountant, ledger: SettlementLedger) -> int:
    """Replay committed charges in commit order; return how many transactions."""
    restored = 0
    for reservation in ledger.committed_reservations():
        now = reservation.committed_at if reservation.committed_at is not None else 0.0
        for subject, cost in reservation.costs.items():
            accountant.observe(subject, cost, now=now)
        restored += 1
    return restored
