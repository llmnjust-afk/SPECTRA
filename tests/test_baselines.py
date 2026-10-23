"""Tests for the exact windowed baseline.

The baseline composes costs with the same vector algebra as PrivFuse, so its
epsilon per request is sublinear in the number of requests and the thresholds
have to be derived from the mechanism rather than assumed additive.
"""

import pytest

from privfuse.baselines import ExactWindowedPolicy
from privfuse.control.admission import QueryRequest
from privfuse.dp.mechanisms import gaussian_cost
from privfuse.trace.generator import EPS_DELTA

UNIT = gaussian_cost(0.4, EPS_DELTA, 1.0)
EPS_2 = (UNIT + UNIT).eps(EPS_DELTA)
EPS_3 = (UNIT + UNIT + UNIT).eps(EPS_DELTA)


def _request(i: int, timestamp: float) -> QueryRequest:
    return QueryRequest(
        request_id=f"r{i}",
        tenant="t0",
        platform="p0",
        subjects=("s0",),
        cost=UNIT,
        timestamp=timestamp,
    )


def _policy(cap: float, window: float = 10.0) -> ExactWindowedPolicy:
    return ExactWindowedPolicy(caps={"s0": cap}, window=window)


def test_windowed_cap_refuses_the_request_that_would_cross_it():
    policy = _policy(cap=0.5 * (EPS_2 + EPS_3))
    admitted = 0
    for i, t in enumerate((0.0, 1.0, 2.0)):
        decision = policy.begin(_request(i, t))
        if decision.allowed:
            admitted += 1
            policy.finish(decision, t)
    assert admitted == 2
    assert not policy.begin(_request(3, 3.0)).allowed


def test_spend_returns_after_the_window_slides_past():
    policy = _policy(cap=0.5 * (EPS_2 + EPS_3))
    for i, t in enumerate((0.0, 1.0)):
        decision = policy.begin(_request(i, t))
        assert decision.allowed
        policy.finish(decision, t)
    assert not policy.begin(_request(2, 2.0)).allowed
    later = policy.begin(_request(3, 25.0))
    assert later.allowed
    assert later.reason == "exact_windowed_ok"


def test_soft_budget_degrades_instead_of_refusing():
    policy = _policy(cap=1.05 * EPS_3)
    for i, t in enumerate((0.0, 1.0)):
        decision = policy.begin(_request(i, t))
        assert decision.allowed
        policy.finish(decision, t)
    third = policy.begin(_request(2, 2.0))
    assert third.allowed
    assert third.reason == "exact_windowed_degraded"
    # degradation scales the cost vector, and epsilon is nonlinear in it, so the
    # charged epsilon is not half of the unit epsilon.
    assert third.charged.eps(EPS_DELTA) == pytest.approx(
        UNIT.scale(0.5).eps(EPS_DELTA), rel=1e-9
    )
    assert third.charged.eps(EPS_DELTA) > 0.5 * UNIT.eps(EPS_DELTA)
    assert third.utility_loss > 0.0
    policy.finish(third, 2.0)
    # two full charges plus one halved charge leave less than one more full headroom
    assert not policy.begin(_request(3, 3.0)).allowed
