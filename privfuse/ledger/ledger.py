"""Two-phase settlement ledger.

Budget must be reserved *before* a query executes.  Executing first and
deducting afterwards is the accounting equivalent of writing a cheque after
spending the money: it lets a tenant race past the cap and only discover the
overdraft once the data has left the platform.

Caps are expressed as a single epsilon value at a fixed delta, which is the
quantity a regulator actually publishes.  Reservations and commits are therefore
tracked as epsilon balances, while committed costs keep their full composition
vector for reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from privfuse.dp.cost import CostVector


class LedgerError(RuntimeError):
    pass


class State(str, Enum):
    RESERVED = "reserved"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass
class Reservation:
    tx_id: str
    tenant: str
    platform: str
    costs: dict[str, CostVector]
    created: float
    expires: float
    state: State = State.RESERVED
    committed_at: float | None = None


class SettlementLedger:
    """Reserve / commit / release with idempotent transaction identifiers."""

    def __init__(self, ttl: float = 30.0, delta: float = 1e-5) -> None:
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        if not (0 < delta < 1):
            raise ValueError("delta must lie in (0, 1)")
        self.ttl = float(ttl)
        self.delta = float(delta)
        self._reservations: dict[str, Reservation] = {}
        self._committed: dict[str, CostVector] = {}
        self._reserved_eps: dict[str, float] = {}
        self.duplicate_commits = 0
        self.expired = 0
        self.commits = 0
        self.releases = 0

    def reserve(
        self,
        tx_id: str,
        tenant: str,
        costs: dict[str, CostVector],
        now: float = 0.0,
        platform: str = "local",
    ) -> Reservation:
        existing = self._reservations.get(tx_id)
        if existing is not None:
            if existing.tenant != tenant or existing.platform != platform:
                raise LedgerError(f"transaction id {tx_id!r} reused by another tenant")
            if existing.state is State.RESERVED:
                return existing
            raise LedgerError(f"transaction {tx_id!r} already {existing.state.value}")
        res = Reservation(
            tx_id=tx_id,
            tenant=tenant,
            platform=platform,
            costs=dict(costs),
            created=now,
            expires=now + self.ttl,
        )
        self._reservations[tx_id] = res
        for subject, cost in costs.items():
            self._reserved_eps[subject] = self._reserved_eps.get(subject, 0.0) + cost.eps(
                self.delta
            )
        return res

    def commit(self, tx_id: str, now: float = 0.0) -> Reservation:
        res = self._reservations.get(tx_id)
        if res is None:
            raise LedgerError(f"unknown transaction {tx_id!r}")
        if res.state is State.COMMITTED:
            self.duplicate_commits += 1
            return res
        if res.state is not State.RESERVED:
            raise LedgerError(f"cannot commit {res.state.value} transaction {tx_id!r}")
        for subject, cost in res.costs.items():
            self._reserved_eps[subject] = max(
                0.0, self._reserved_eps.get(subject, 0.0) - cost.eps(self.delta)
            )
            self._committed[subject] = self._committed.get(
                subject, CostVector.zero()
            ) + cost
        res.state = State.COMMITTED
        res.committed_at = now
        self.commits += 1
        return res

    def release(self, tx_id: str, now: float = 0.0, reason: State = State.RELEASED) -> Reservation:
        res = self._reservations.get(tx_id)
        if res is None:
            raise LedgerError(f"unknown transaction {tx_id!r}")
        if res.state is not State.RESERVED:
            return res
        for subject, cost in res.costs.items():
            self._reserved_eps[subject] = max(
                0.0, self._reserved_eps.get(subject, 0.0) - cost.eps(self.delta)
            )
        res.state = reason
        self.releases += 1
        return res

    def tick(self, now: float) -> int:
        expired = 0
        for res in list(self._reservations.values()):
            if res.state is State.RESERVED and now >= res.expires:
                self.release(res.tx_id, now=now, reason=State.EXPIRED)
                expired += 1
        self.expired += expired
        return expired

    def committed_eps(self, subject: str) -> float:
        cost = self._committed.get(subject)
        return 0.0 if cost is None else cost.eps(self.delta)

    def committed(self, subject: str) -> CostVector:
        return self._committed.get(subject, CostVector.zero())

    def reserved_eps(self, subject: str) -> float:
        return self._reserved_eps.get(subject, 0.0)

    def in_flight_eps(self, subject: str) -> float:
        return self.committed_eps(subject) + self.reserved_eps(subject)

    def remaining_eps(self, subject: str, cap_eps: float) -> float:
        return cap_eps - self.in_flight_eps(subject)

    def state(self, tx_id: str) -> State | None:
        res = self._reservations.get(tx_id)
        return None if res is None else res.state

    def stats(self) -> dict[str, float]:
        counts = {s.value: 0 for s in State}
        for res in self._reservations.values():
            counts[res.state.value] += 1
        return {
            "reservations": float(len(self._reservations)),
            "reserved_open": float(counts["reserved"]),
            "committed_tx": float(counts["committed"]),
            "released_tx": float(counts["released"]),
            "expired_tx": float(counts["expired"]),
            "duplicate_commits": float(self.duplicate_commits),
        }


class Coordinator:
    """Shared budget root across platforms.

    Each platform holds a local ledger for fast admission, but every reservation
    is also applied to this coordinator, which is the single source of truth for
    cross-platform budget.  A reservation that would push a subject past its cap
    is rejected here regardless of which platform issued it, which is what
    defeats budget splitting across platforms.
    """

    def __init__(self, caps: dict[str, float], ttl: float = 30.0, delta: float = 1e-5) -> None:
        self.caps = dict(caps)
        self.delta = float(delta)
        self.ledger = SettlementLedger(ttl=ttl, delta=delta)
        self.rejections = 0

    def cap_for(self, subject: str) -> float:
        if subject not in self.caps:
            raise KeyError(f"unknown subject {subject!r}")
        return self.caps[subject]

    def try_reserve(
        self,
        tx_id: str,
        tenant: str,
        platform: str,
        costs: dict[str, CostVector],
        now: float = 0.0,
    ) -> tuple[bool, str]:
        for subject, cost in costs.items():
            remaining = self.ledger.remaining_eps(subject, self.cap_for(subject))
            if cost.eps(self.delta) > remaining + 1e-12:
                self.rejections += 1
                return False, f"insufficient budget for subject {subject}"
        self.ledger.reserve(tx_id, tenant, costs, now=now, platform=platform)
        return True, "reserved"

    def commit(self, tx_id: str, now: float = 0.0) -> None:
        self.ledger.commit(tx_id, now=now)

    def release(self, tx_id: str, now: float = 0.0) -> None:
        self.ledger.release(tx_id, now=now)

    def tick(self, now: float) -> int:
        return self.ledger.tick(now)

    def stats(self) -> dict[str, float]:
        stats = self.ledger.stats()
        stats["coordinator_rejections"] = float(self.rejections)
        return stats
