"""A transaction identifier may be retried, but not re-pointed at a new charge."""

import pytest

from privfuse.dp.cost import CostVector
from privfuse.ledger.ledger import Coordinator, LedgerError, State


def _coordinator() -> Coordinator:
    return Coordinator(caps={"alice": 1.0, "bob": 1.0}, ttl=30.0)


def test_identical_retry_returns_the_same_reservation() -> None:
    coordinator = _coordinator()
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    assert coordinator.try_reserve("tx", "t", "p0", {"alice": cost}) == (True, "reserved")
    assert coordinator.try_reserve("tx", "t", "p0", {"alice": cost}) == (True, "reserved")
    coordinator.commit("tx")
    assert coordinator.ledger.committed_eps("alice") == pytest.approx(0.1)


def test_rebinding_the_subject_is_rejected() -> None:
    coordinator = _coordinator()
    coordinator.try_reserve("tx", "t", "p0", {"alice": CostVector(eps_pure=0.1, rho=0.0, delta=0.0)})
    ok, reason = coordinator.try_reserve(
        "tx", "t", "p0", {"bob": CostVector(eps_pure=0.9, rho=0.0, delta=0.0)}
    )
    assert not ok and "different charge" in reason
    with pytest.raises(LedgerError, match="different charge"):
        coordinator.ledger.reserve(
            "tx", "t", {"bob": CostVector(eps_pure=0.9, rho=0.0, delta=0.0)}, platform="p0"
        )
    assert coordinator.ledger.committed_eps("bob") == 0.0
    assert coordinator.ledger.reserved_eps("bob") == 0.0


def test_rebinding_the_cost_is_rejected() -> None:
    coordinator = _coordinator()
    coordinator.try_reserve("tx", "t", "p0", {"alice": CostVector(eps_pure=0.1, rho=0.0, delta=0.0)})
    ok, reason = coordinator.try_reserve(
        "tx", "t", "p0", {"alice": CostVector(eps_pure=0.9, rho=0.0, delta=0.0)}
    )
    assert not ok and "different charge" in reason


def test_released_and_committed_states_are_terminal() -> None:
    coordinator = _coordinator()
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    coordinator.try_reserve("tx", "t", "p0", {"alice": cost})
    coordinator.release("tx")
    assert coordinator.ledger.state("tx") is State.RELEASED
    ok, reason = coordinator.try_reserve("tx", "t", "p0", {"alice": cost})
    assert not ok and "already released" in reason

    coordinator.try_reserve("ty", "t", "p0", {"alice": cost})
    coordinator.commit("ty")
    ok, reason = coordinator.try_reserve("ty", "t", "p0", {"alice": cost})
    assert not ok and "already committed" in reason


def test_concurrent_update_transactions_with_disjoint_supports() -> None:
    """Two threads, one identifier, disjoint supports: exactly one reservation."""
    import threading

    coordinator = _coordinator()
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def attempt(subject: str) -> None:
        barrier.wait()
        try:
            outcomes.append(coordinator.try_reserve("same", "t", "p0", {subject: cost}))
        except LedgerError as error:
            outcomes.append(error)

    threads = [threading.Thread(target=attempt, args=(s,)) for s in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(coordinator.ledger._reservations) == 1
    assert sum(1 for o in outcomes if o == (True, "reserved")) == 1
    assert sum(1 for o in outcomes if o != (True, "reserved")) == 1


def test_query_and_mechanism_are_part_of_the_fingerprint() -> None:
    coordinator = _coordinator()
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    coordinator.ledger.reserve("tx", "t", {"alice": cost}, platform="p0", query_digest="q1")
    with pytest.raises(LedgerError, match="different charge"):
        coordinator.ledger.reserve(
            "tx", "t", {"alice": cost}, platform="p0", query_digest="q2"
        )


def test_committed_receipt_is_returned_unchanged() -> None:
    coordinator = _coordinator()
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    coordinator.try_reserve("tx", "t", "p0", {"alice": cost})
    coordinator.ledger.commit("tx", receipt="answer-7")
    assert coordinator.ledger.commit("tx", receipt="answer-7").receipt == "answer-7"
    with pytest.raises(LedgerError, match="different receipt"):
        coordinator.ledger.commit("tx", receipt="answer-8")
    assert coordinator.ledger.committed_eps("alice") == pytest.approx(0.1)
