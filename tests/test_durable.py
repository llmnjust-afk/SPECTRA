from privfuse.dp.cost import CostVector
from privfuse.ledger.durable import DurableLedger
from privfuse.ledger.ledger import State


def _costs():
    return {"a": CostVector.from_gaussian(100.0, 1.0)}


def test_commit_survives_replay(tmp_path):
    path = tmp_path / "settlement.wal"
    ledger = DurableLedger(path)
    ledger.reserve("t1", "ten", _costs(), now=1.0, platform="p0")
    ledger.commit("t1", now=1.1)
    ledger.close()

    replayed = DurableLedger(path)
    assert replayed.state("t1") is State.COMMITTED
    assert replayed.committed_eps("a") > 0.0
    assert replayed.torn_records == 0
    replayed.commit("t1", now=2.0)
    assert replayed.duplicate_commits == 1
    replayed.close()
    assert path.read_text().count("\n") == 2


def test_reservation_survives_replay_for_retry(tmp_path):
    path = tmp_path / "settlement.wal"
    ledger = DurableLedger(path)
    ledger.reserve("t7", "ten", _costs(), now=5.0, platform="p0")
    ledger.close()

    replayed = DurableLedger(path)
    assert replayed.state("t7") is State.RESERVED
    again = replayed.reserve("t7", "ten", _costs(), now=6.0, platform="p0")
    assert again.created == 5.0
    assert replayed.reserved_eps("a") == again.costs["a"].eps(replayed.delta)
    replayed.close()


def test_torn_tail_is_truncated_not_fatal(tmp_path):
    path = tmp_path / "settlement.wal"
    ledger = DurableLedger(path)
    ledger.reserve("t1", "ten", _costs(), now=1.0, platform="p0")
    ledger.commit("t1", now=1.1)
    ledger.close()

    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"op": "commit", "tx": "t1"')

    replayed = DurableLedger(path)
    assert replayed.torn_records == 1
    assert replayed.state("t1") is State.COMMITTED
    replayed.reserve("t2", "ten", _costs(), now=3.0, platform="p0")
    replayed.close()

    final = DurableLedger(path)
    assert final.state("t2") is State.RESERVED
    assert final.torn_records == 0
    final.close()


def test_estimator_rebuilds_from_committed_charges(tmp_path) -> None:
    """A restart must not leave the windowed estimator empty."""
    from privfuse.accounting.online import OnlineAccountant, OnlineAccountantConfig
    from privfuse.ledger.ledger import Coordinator
    from privfuse.ledger.recovery import rebuild_estimator

    path = str(tmp_path / "wal.log")
    cost = CostVector(eps_pure=0.1, rho=0.0, delta=0.0)
    first = Coordinator(caps={"s": 5.0}, ttl=30.0, ledger=DurableLedger(path, ttl=30.0))
    for index in range(4):
        first.try_reserve(f"tx{index}", "t", "p0", {"s": cost}, now=float(index))
        first.commit(f"tx{index}", now=float(index))
    first.ledger.close()

    second = Coordinator(caps={"s": 5.0}, ttl=30.0, ledger=DurableLedger(path, ttl=30.0))
    accountant = OnlineAccountant(OnlineAccountantConfig(epoch_seconds=1.0, ring_size=8))
    restored = rebuild_estimator(accountant, second.ledger)
    assert restored == 4
    assert accountant.estimate("s").eps(1e-5) >= 0.4 - 1e-9
    assert accountant.upper_bound("s").eps(1e-5) >= 0.4 - 1e-9
    second.ledger.close()
