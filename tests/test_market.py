from privfuse.experiments.common import compare_policies, default_trace
from privfuse.trace.generator import TraceConfig


def _trace():
    return default_trace(
        n_requests=1500,
        n_subjects=300,
        cap_eps=0.6,
        seed=3,
        attack="split",
        attack_splits=30,
        attack_epsilon=0.25,
    )


def test_privfuse_never_violates_the_cap():
    rows = compare_policies(_trace(), names=["privfuse"])
    assert rows[0]["hard_cap_violations"] == 0


def test_platform_local_quota_is_defeated_by_splitting():
    rows = compare_policies(_trace(), names=["static_quota"])
    assert rows[0]["hard_cap_violations"] > 0


def test_privfuse_keeps_more_availability_than_a_hard_freeze():
    rows = compare_policies(_trace(), names=["privfuse", "exact_blocking"])
    assert rows[0]["availability"] > 0.0
    assert rows[0]["hard_cap_violations"] == 0
