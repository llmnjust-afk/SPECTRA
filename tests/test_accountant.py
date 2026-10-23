import pytest

from privfuse.accounting.online import (
    OnlineAccountant,
    OnlineAccountantConfig,
    ring_epochs_for,
)
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


def test_ring_covers_the_requested_window():
    cost = gaussian_cost(0.05, 1e-5, 1.0)
    epoch, window = 10.0, 20.0
    ring = ring_epochs_for(window, epoch)
    assert ring == 3
    accountant = OnlineAccountant(
        OnlineAccountantConfig(width=256, depth=3, epoch_seconds=epoch, ring_size=ring)
    )
    exact = ExactAccountant()
    for now in (0.0, 10.0, 20.0):
        accountant.observe("s1", cost, now=now)
        exact.add("s1", cost, timestamp=now)
    windowed = accountant.estimate("s1", now=20.0, window=window)
    assert windowed.eps(1e-5) >= exact.get("s1").eps(1e-5) - 1e-9


def test_max_window_leaves_room_for_the_boundary_epoch():
    cfg = OnlineAccountantConfig(epoch_seconds=300.0, ring_size=2)
    assert cfg.max_window == 300.0
    assert ring_epochs_for(600.0, 300.0) == 3


def test_factory_sizes_ring_for_its_window():
    from privfuse.factory import PrivFuseConfig, build_privfuse
    from privfuse.trace.generator import TraceConfig, generate_trace

    trace = generate_trace(TraceConfig(n_requests=40, n_subjects=5))
    policy = build_privfuse(
        trace, PrivFuseConfig(epoch_seconds=300.0, ring_size=2, window=600.0)
    )
    assert policy.controller.accountant.config.ring_size == 3
