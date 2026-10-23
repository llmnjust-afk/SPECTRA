import random

from privfuse.dp.cost import CostVector
from privfuse.sketch.countmin import CountMinSketch, SpaceSaving
from privfuse.sketch.costsketch import CostSketch, HotTable


def test_countmin_never_underestimates():
    rng = random.Random(0)
    sketch = CountMinSketch(width=64, depth=3, seed=1)
    truth: dict[str, float] = {}
    for _ in range(3000):
        key = f"k{rng.randrange(50)}"
        value = rng.random()
        sketch.add(key, value)
        truth[key] = truth.get(key, 0.0) + value
    for key, value in truth.items():
        assert sketch.estimate(key) >= value - 1e-9


def test_countmin_error_bound_holds():
    rng = random.Random(1)
    sketch = CountMinSketch(width=128, depth=4, seed=2)
    truth: dict[str, float] = {}
    for _ in range(5000):
        key = f"k{rng.randrange(200)}"
        value = rng.random()
        sketch.add(key, value)
        truth[key] = truth.get(key, 0.0) + value
    for key, value in truth.items():
        assert sketch.estimate(key) - value <= sketch.error_bound() + 1e-9


def test_negative_updates_rejected():
    sketch = CountMinSketch(width=16, depth=2)
    try:
        sketch.add("k", -1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("negative update should be rejected")


def test_spacesaving_tracks_heavy_hitter():
    summary = SpaceSaving(capacity=8)
    for _ in range(100):
        summary.add("hot", 1.0)
    for i in range(40):
        summary.add(f"cold{i}", 1.0)
    assert summary.contains("hot")
    assert summary.estimate("hot") >= 100.0


def test_spacesaving_returns_eviction():
    summary = SpaceSaving(capacity=2)
    summary.add("a", 5.0)
    summary.add("b", 4.0)
    evicted = summary.add("c", 1.0)
    assert evicted in {"a", "b"}


def test_hot_table_is_exact_when_tracked():
    table = HotTable(capacity=4)
    cost = CostVector(eps_pure=0.1, rho=0.01)
    for _ in range(5):
        table.add("subject", cost)
    stored = table.estimate("subject")
    assert stored is not None
    assert stored.eps_pure == pytest.approx(0.5)


def test_costsketch_upper_bound_contains_estimate():
    sketch = CostSketch(width=256, depth=3, hot_capacity=16)
    cost = CostVector(eps_pure=0.01, rho=1e-4)
    for i in range(50):
        sketch.add(f"s{i%5}", cost)
    for i in range(5):
        subject = f"s{i}"
        assert sketch.upper_bound(subject).eps() >= sketch.estimate(subject).eps()


import pytest
