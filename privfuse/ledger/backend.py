"""Ledger backend contracts.

The settlement semantics live in :mod:`privfuse.ledger.ledger` and are
independent of where the state is stored. A production deployment puts the
balance and the reservation table in chaincode; this module states the interface
that chaincode has to satisfy so the reference implementation can be swapped
without touching the controller.

Only :class:`InMemoryBackend` is implemented. :class:`FabricGatewayAdapter`
exists to document the shape of the integration and raises on use.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from privfuse.dp.cost import CostVector
from privfuse.ledger.ledger import Reservation, SettlementLedger, State


@runtime_checkable
class ChainBackend(Protocol):
    """Minimal surface a ledger must expose to the coordinator.

    Implementations must be idempotent in ``tx_id`` and must make an expired
    reservation reclaimable without a call from the reserving party. The second
    requirement is what allows a crashed platform to recover its budget.
    """

    def reserve(
        self,
        tx_id: str,
        tenant: str,
        costs: dict[str, CostVector],
        now: float = 0.0,
    ) -> Reservation: ...

    def commit(self, tx_id: str, now: float = 0.0) -> Reservation: ...

    def release(
        self, tx_id: str, now: float = 0.0, reason: State = State.RELEASED
    ) -> Reservation: ...

    def state(self, tx_id: str) -> State | None: ...

    def committed(self, subject: str) -> CostVector: ...

    def tick(self, now: float) -> int: ...


class InMemoryBackend:
    """Adapter over :class:`SettlementLedger` for tests and simulation."""

    def __init__(self, ledger: SettlementLedger | None = None) -> None:
        self.ledger = ledger or SettlementLedger()

    def reserve(
        self,
        tx_id: str,
        tenant: str,
        costs: dict[str, CostVector],
        now: float = 0.0,
    ) -> Reservation:
        return self.ledger.reserve(tx_id, tenant, costs, now=now)

    def commit(self, tx_id: str, now: float = 0.0) -> Reservation:
        return self.ledger.commit(tx_id, now=now)

    def release(
        self, tx_id: str, now: float = 0.0, reason: State = State.RELEASED
    ) -> Reservation:
        return self.ledger.release(tx_id, now=now, reason=reason)

    def state(self, tx_id: str) -> State | None:
        return self.ledger.state(tx_id)

    def committed(self, subject: str) -> CostVector:
        return self.ledger.committed(subject)

    def tick(self, now: float) -> int:
        return self.ledger.tick(now)


class FabricGatewayAdapter:
    """Placeholder for a Hyperledger Fabric gateway.

    A real adapter submits ``Reserve`` / ``Commit`` / ``Release`` transactions to
    a chaincode that stores the reservation table under a composite key of
    ``(subject, tx_id)`` and enforces the cap inside the endorsement policy. The
    ledger invariants are already tested in memory, so the remaining work is
    transport and endorsement, not semantics.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "Fabric integration is out of scope for the reference implementation; "
            "see docs/roadmap.md"
        )
