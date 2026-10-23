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
