import pytest

from privfuse.accounting.online import OnlineAccountant, OnlineAccountantConfig
from privfuse.dp.accountant import ExactAccountant
from privfuse.dp.mechanisms import gaussian_cost


def _feed(accountant, exact, cost, subject="s1", n=20, step=5.0):
    for i in range(n):
        now = i * step
        accountant.observe(subject, cost, now=now)
        exact.add(subject, cost, timestamp=now)


def test_online_never_underestimates_cumulative():
    cost = gaussian_cost(0.05, 1e-5, 1.0)
    accountant = OnlineAccountant(OnlineAccountantConfig(width=256, depth=3, hot_capacity=8))
    exact = ExactAccountant()
    _feed(accountant, exact, cost)
    assert accountant.upper_bound_eps("s1", 1e-5) >= exact.get("s1").eps(1e-5) - 1e-9


def test_window_excludes_old_events():
    cost = gaussian_cost(0.05, 1e-5, 1.0)
    cfg = OnlineAccountantConfig(width=256, depth=3, epoch_seconds=10.0, ring_size=2)
    accountant = OnlineAccountant(cfg)
    accountant.observe("s1", cost, now=0.0)
    accountant.observe("s1", cost, now=100.0)
    windowed = accountant.estimate("s1", now=100.0, window=10.0)
    cumulative = accountant.estimate("s1", now=100.0, window=None)
    assert windowed.eps(1e-5) < cumulative.eps(1e-5)


def test_window_larger_than_ring_rejected():
    accountant = OnlineAccountant(OnlineAccountantConfig(epoch_seconds=10.0, ring_size=2))
    with pytest.raises(ValueError):
        accountant.estimate("s1", now=0.0, window=1000.0)


def test_stats_report_events():
    accountant = OnlineAccountant()
    accountant.observe("s1", gaussian_cost(0.01, 1e-5, 1.0), now=0.0)
    assert accountant.stats()["events_cumulative"] == 1.0
