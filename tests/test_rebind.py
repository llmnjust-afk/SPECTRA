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
    with pytest.raises(LedgerError, match="different charge"):
        coordinator.try_reserve("tx", "t", "p0", {"bob": CostVector(eps_pure=0.9, rho=0.0, delta=0.0)})
    assert coordinator.ledger.committed_eps("bob") == 0.0


def test_rebinding_the_cost_is_rejected() -> None:
    coordinator = _coordinator()
    coordinator.try_reserve("tx", "t", "p0", {"alice": CostVector(eps_pure=0.1, rho=0.0, delta=0.0)})
    with pytest.raises(LedgerError, match="different charge"):
        coordinator.try_reserve("tx", "t", "p0", {"alice": CostVector(eps_pure=0.9, rho=0.0, delta=0.0)})


def test_released_and_committed_states_are_terminal() -> None:
    coordinator = _coordinator()
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    coordinator.try_reserve("tx", "t", "p0", {"alice": cost})
    coordinator.release("tx")
    assert coordinator.ledger.state("tx") is State.RELEASED
    with pytest.raises(LedgerError, match="already released"):
        coordinator.try_reserve("tx", "t", "p0", {"alice": cost})

    coordinator.try_reserve("ty", "t", "p0", {"alice": cost})
    coordinator.commit("ty")
    with pytest.raises(LedgerError, match="already committed"):
        coordinator.try_reserve("ty", "t", "p0", {"alice": cost})
