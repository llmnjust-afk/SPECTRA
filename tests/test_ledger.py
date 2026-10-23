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


def test_coordinator_reservation_is_atomic():
    import threading

    from privfuse.dp.cost import CostVector
    from privfuse.ledger.ledger import Coordinator

    coordinator = Coordinator(caps={"s1": 1.0}, ttl=1000.0)
    cost = CostVector(eps_pure=0.01, rho=0.0, delta=0.0)
    admitted = []

    def worker(k: int) -> None:
        for i in range(200):
            ok, _ = coordinator.try_reserve(f"t{k}-{i}", "ten", "p0", {"s1": cost})
            if ok:
                admitted.append(i)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert coordinator.ledger.committed("s1").eps(1e-5) <= 1.0 + 1e-9
    assert len(admitted) == 100


def test_crash_before_commit_delivers_nothing_and_retry_charges_once():
    from privfuse.experiments.e19_faults import _attempt, _tx

    coord = Coordinator(caps={"s0": 1.0}, ttl=5.0)
    assert _attempt(coord, _tx("x1", "t0", "p0"), "after_execute", now=0.0) == "crashed"
    assert coord.ledger.commits == 0
    assert _attempt(coord, _tx("x1", "t0", "p0"), "none", now=0.5) == "answered"
    assert coord.ledger.commits == 1
    assert coord.ledger.committed_eps("s0") == pytest.approx(0.05, abs=1e-12)


def test_retry_after_expiry_is_refused_and_the_hold_returns():
    import pytest as _pytest

    from privfuse.experiments.e19_faults import _attempt, _tx

    coord = Coordinator(caps={"s0": 1.0}, ttl=5.0)
    _attempt(coord, _tx("x1", "t0", "p0"), "after_reserve", now=0.0)
    assert coord.ledger.reserved_eps("s0") == _pytest.approx(0.05)
    coord.tick(now=6.0)
    assert coord.ledger.reserved_eps("s0") == 0.0
    assert _attempt(coord, _tx("x1", "t0", "p0"), "none", now=6.5) == "rejected"
    assert coord.ledger.commits == 0
