import pytest

from privfuse.dp.cost import CostVector
from privfuse.ledger.ledger import Coordinator, LedgerError, SettlementLedger, State

COST = CostVector(eps_pure=0.1)


def test_commit_is_idempotent():
    ledger = SettlementLedger(ttl=10.0)
    ledger.reserve("tx", "t", {"s": COST})
    ledger.commit("tx")
    ledger.commit("tx")
    assert ledger.duplicate_commits == 1
    assert ledger.committed_eps("s") == pytest.approx(0.1)


def test_release_returns_budget():
    ledger = SettlementLedger(ttl=10.0)
    ledger.reserve("tx", "t", {"s": COST})
    assert ledger.reserved_eps("s") == pytest.approx(0.1)
    ledger.release("tx")
    assert ledger.reserved_eps("s") == pytest.approx(0.0)


def test_timeout_expires_reservations():
    ledger = SettlementLedger(ttl=5.0)
    ledger.reserve("tx", "t", {"s": COST}, now=0.0)
    assert ledger.tick(6.0) == 1
    assert ledger.state("tx") is State.EXPIRED


def test_transaction_id_cannot_be_hijacked():
    ledger = SettlementLedger(ttl=10.0)
    ledger.reserve("tx", "t1", {"s": COST})
    with pytest.raises(LedgerError):
        ledger.reserve("tx", "t2", {"s": COST})


def test_coordinator_blocks_cross_platform_splitting():
    coordinator = Coordinator(caps={"s": 1.0}, ttl=10.0)
    ok, _ = coordinator.try_reserve("a", "t", "p0", {"s": CostVector(eps_pure=0.6)})
    assert ok
    ok, _ = coordinator.try_reserve("b", "t", "p1", {"s": CostVector(eps_pure=0.6)})
    assert not ok


def test_coordinator_allows_within_cap():
    coordinator = Coordinator(caps={"s": 1.0}, ttl=10.0)
    for i in range(5):
        ok, _ = coordinator.try_reserve(f"tx{i}", "t", f"p{i%3}", {"s": CostVector(eps_pure=0.1)})
        assert ok
        coordinator.commit(f"tx{i}")
