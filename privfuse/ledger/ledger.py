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

import hashlib
import json
import threading
import zlib
from contextlib import contextmanager

from dataclasses import dataclass
from typing import Iterable
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
    fingerprint: str = ""


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

    @staticmethod
    def fingerprint(tenant: str, platform: str, costs: dict[str, CostVector]) -> str:
        """Canonical hash of everything a transaction commits to.

        Retrying with the same identifier is legal only if the payload is the
        same; otherwise a caller could reserve against one subject and execute
        another under the same charge.
        """
        payload = {
            "tenant": tenant,
            "platform": platform,
            "costs": {
                subject: [cost.eps_pure, cost.rho, cost.delta]
                for subject, cost in sorted(costs.items())
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

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
            if existing.fingerprint != self.fingerprint(tenant, platform, costs):
                raise LedgerError(
                    f"transaction id {tx_id!r} reused with a different charge"
                )
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
            fingerprint=self.fingerprint(tenant, platform, costs),
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

    def committed_reservations(self) -> list[Reservation]:
        """Committed transactions in commit order, for estimator replay."""
        return sorted(
            (r for r in self._reservations.values() if r.state is State.COMMITTED),
            key=lambda r: (r.committed_at is None, r.committed_at or 0.0),
        )

    def get(self, tx_id: str) -> Reservation | None:
        return self._reservations.get(tx_id)

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

    STRIPES = 64

    def __init__(
        self,
        caps: dict[str, float],
        ttl: float = 30.0,
        delta: float = 1e-5,
        striped: bool = True,
        ledger: SettlementLedger | None = None,
    ) -> None:
        self.caps = dict(caps)
        self.delta = float(delta)
        self.ledger = ledger if ledger is not None else SettlementLedger(ttl=ttl, delta=delta)
        self.rejections = 0
        self.striped = bool(striped)
        self._global = threading.RLock()
        self._stripes = [threading.Lock() for _ in range(self.STRIPES)]

    def _index(self, subject: str) -> int:
        return zlib.crc32(subject.encode("utf-8")) % self.STRIPES

    @contextmanager
    def _guard(self, subjects: Iterable[str]):
        if not self.striped:
            with self._global:
                yield
            return
        indices = sorted({self._index(subject) for subject in subjects})
        for index in indices:
            self._stripes[index].acquire()
        try:
            yield
        finally:
            for index in reversed(indices):
                self._stripes[index].release()

    @contextmanager
    def _guard_all(self):
        if not self.striped:
            with self._global:
                yield
            return
        for lock in self._stripes:
            lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(self._stripes):
                lock.release()

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
        with self._guard(costs):
            for subject, cost in costs.items():
                remaining = self.ledger.remaining_eps(subject, self.cap_for(subject))
                if cost.eps(self.delta) > remaining + 1e-12:
                    self.rejections += 1
                    return False, f"insufficient budget for subject {subject}"
            self.ledger.reserve(tx_id, tenant, costs, now=now, platform=platform)
            return True, "reserved"

    def commit(self, tx_id: str, now: float = 0.0) -> None:
        reservation = self.ledger.get(tx_id)
        subjects = list(reservation.costs) if reservation is not None else []
        with self._guard(subjects):
            self.ledger.commit(tx_id, now=now)

    def release(self, tx_id: str, now: float = 0.0) -> None:
        reservation = self.ledger.get(tx_id)
        subjects = list(reservation.costs) if reservation is not None else []
        with self._guard(subjects):
            self.ledger.release(tx_id, now=now)

    def tick(self, now: float) -> int:
        with self._guard_all():
            return self.ledger.tick(now)

    def stats(self) -> dict[str, float]:
        with self._guard_all():
            stats = self.ledger.stats()
            stats["coordinator_rejections"] = float(self.rejections)
            return stats
