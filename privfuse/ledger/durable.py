"""Settlement ledger with a write-ahead log.

The in-memory ledger loses every committed charge when the coordinator process
dies, which turns a crash into free answers: the restarted coordinator believes
the subject is unspent and admits the next queries against a budget that has
already been consumed.  This module writes each state transition to an
append-only log and replays it on open, so a restart resumes from the charges
that were acknowledged before the crash.

Two details matter for the guarantee.

* The record is flushed and ``fsync``-ed *before* the caller is told the
  transition happened.  A platform commits before it returns an answer, so an
  answer that left the building has a durable charge behind it.
* A kill in the middle of an append can leave a partial trailing line.  Replay
  truncates it instead of failing: a record that was never fully written was
  also never acknowledged, so discarding it cannot drop a committed charge.

The log is a sequence of JSON objects, one per transition, replayed in order
through the same code path that produced them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from privfuse.dp.cost import CostVector
from privfuse.ledger.ledger import LedgerError, Reservation, SettlementLedger, State


class DurableLedger(SettlementLedger):
    """``SettlementLedger`` backed by an fsync-ed append-only log."""

    def __init__(self, path: str | Path, ttl: float = 30.0, delta: float = 1e-5) -> None:
        super().__init__(ttl=ttl, delta=delta)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.replayed = 0
        self.torn_records = 0
        self.appended = 0
        self._replaying = True
        try:
            self._replay()
        finally:
            self._replaying = False
        self._handle = open(self.path, "a", encoding="utf-8")

    def _replay(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        if not raw:
            return
        good = 0
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b"\n"):
                self.torn_records += 1
                break
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.torn_records += 1
                break
            self._apply(record)
            self.replayed += 1
            good += len(line)
        if good != len(raw):
            with open(self.path, "r+b") as handle:
                handle.truncate(good)

    def _apply(self, record: dict) -> None:
        op = record["op"]
        try:
            if op == "reserve":
                costs = {
                    subject: CostVector(*value)
                    for subject, value in record["costs"].items()
                }
                super().reserve(
                    record["tx"],
                    record["tenant"],
                    costs,
                    now=record["created"],
                    platform=record.get("platform", "local"),
                    query_digest=record.get("query", ""),
                    mechanism=record.get("mechanism", ""),
                    policy_version=record.get("policy", ""),
                )
            elif op == "commit":
                super().commit(
                    record["tx"], now=record["now"], receipt=record.get("receipt")
                )
            elif op == "release":
                super().release(
                    record["tx"],
                    now=record["now"],
                    reason=State(record.get("reason", State.RELEASED.value)),
                )
            else:
                raise LedgerError(f"unknown WAL operation {op!r}")
        except LedgerError:
            # A duplicate transition is already reflected by the replayed state.
            pass

    def _append(self, record: dict) -> None:
        if self._replaying:
            return
        self._handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.appended += 1

    def reserve(
        self,
        tx_id: str,
        tenant: str,
        costs: dict[str, CostVector],
        now: float = 0.0,
        platform: str = "local",
        query_digest: str = "",
        mechanism: str = "",
        policy_version: str = "",
    ) -> Reservation:
        existing = self.get(tx_id)
        reservation = super().reserve(
            tx_id,
            tenant,
            costs,
            now=now,
            platform=platform,
            query_digest=query_digest,
            mechanism=mechanism,
            policy_version=policy_version,
        )
        if existing is None:
            self._append(
                {
                    "op": "reserve",
                    "tx": tx_id,
                    "tenant": tenant,
                    "platform": platform,
                    "query": query_digest,
                    "mechanism": mechanism,
                    "policy": policy_version,
                    "costs": {
                        subject: [cost.eps_pure, cost.rho, cost.delta]
                        for subject, cost in costs.items()
                    },
                    "created": reservation.created,
                    "expires": reservation.expires,
                }
            )
        return reservation

    def commit(self, tx_id: str, now: float = 0.0, receipt: str | None = None) -> Reservation:
        before = self.state(tx_id)
        reservation = super().commit(tx_id, now=now, receipt=receipt)
        if before is State.RESERVED:
            self._append(
                {"op": "commit", "tx": tx_id, "now": now, "receipt": receipt}
            )
        return reservation

    def release(
        self,
        tx_id: str,
        now: float = 0.0,
        reason: State = State.RELEASED,
    ) -> Reservation:
        before = self.state(tx_id)
        reservation = super().release(tx_id, now=now, reason=reason)
        if before is State.RESERVED and reservation.state is not State.RESERVED:
            self._append(
                {"op": "release", "tx": tx_id, "now": now, "reason": reservation.state.value}
            )
        return reservation

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> "DurableLedger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
