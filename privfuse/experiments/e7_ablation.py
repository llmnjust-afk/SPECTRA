"""E7: contribution of each component."""

from __future__ import annotations

from typing import Any

from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.platform.runtime import Market
from privfuse.baselines import ExactGlobalPolicy
from privfuse.trace.generator import EPS_DELTA


VARIANTS: dict[str, PrivFuseConfig] = {
    "full": PrivFuseConfig(),
    "no_hot_table": PrivFuseConfig(use_hot=False),
    "no_hysteresis": PrivFuseConfig(hysteresis=0.0, dwell=1),
    "no_degradation": PrivFuseConfig(degrade_factor=1.0, degrade_utility_loss=0.0),
    "narrow_sketch": PrivFuseConfig(width=1 << 9),
    "wide_sketch": PrivFuseConfig(width=1 << 16),
}


def run(seeds: list[int] | None = None) -> list[dict[str, Any]]:
    seeds = seeds or [1, 2, 3]
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        trace = default_trace(
            n_requests=5000,
            n_subjects=1000,
            cap_eps=1.0,
            seed=seed,
            attack="split",
            attack_splits=42,
            attack_epsilon=0.3,
        )
        for name, config in VARIANTS.items():
            policy = build_privfuse(trace, config=config)
            result = Market(policy=policy, caps=trace.caps, delta=EPS_DELTA).run(
                trace.requests
            )
            summary = result.summary()
            rows.append(
                {
                    "variant": name,
                    "seed": seed,
                    "availability": result.availability,
                    "utility": result.utility,
                    "violations": result.ground_truth["violations"],
                    "max_eps": result.ground_truth["max_eps"],
                    "flaps": summary.get("flaps", 0.0),
                    "rejected": summary.get("rejected", 0.0),
                    "degraded": summary.get("degraded", 0.0),
                    "bytes": summary.get("bytes", 0.0),
                    "us_per_request": 1e6 * result.elapsed / max(1, len(result.decisions)),
                }
            )
        policy = ExactGlobalPolicy(caps=trace.caps)
        result = Market(policy=policy, caps=trace.caps, delta=EPS_DELTA).run(trace.requests)
        summary = result.summary()
        rows.append(
            {
                "variant": "exact_global",
                "seed": seed,
                "availability": result.availability,
                "utility": result.utility,
                "violations": result.ground_truth["violations"],
                "max_eps": result.ground_truth["max_eps"],
                "flaps": 0.0,
                "rejected": summary.get("policy_rejections", 0.0),
                "degraded": 0.0,
                "bytes": summary.get("bytes", 0.0),
                "us_per_request": 1e6 * result.elapsed / max(1, len(result.decisions)),
            }
        )
    write_csv("e7_ablation", rows)
    write_json("e7_ablation_meta", {"variants": list(VARIANTS) + ["exact_global"]})
    return rows


if __name__ == "__main__":
    for row in run():
        print(row["variant"], row["seed"], round(row["availability"], 3), row["violations"])
    hysteresis_micro()


def hysteresis_micro() -> list[dict[str, Any]]:
    """Drive the breaker with an oscillating pressure and count transitions."""
    from privfuse.control.breaker import BreakerConfig, BreakerController

    import math

    rows: list[dict[str, Any]] = []
    for label, config in (
        ("hysteresis_on", BreakerConfig(hysteresis=0.05, dwell=3)),
        ("hysteresis_off", BreakerConfig(hysteresis=0.0, dwell=1)),
    ):
        breaker = BreakerController(config)
        states = []
        for i in range(600):
            pressure = 0.63 + 0.04 * math.sin(i / 7.0)
            states.append(breaker.update("subject", pressure))
        transitions = sum(1 for a, b in zip(states, states[1:]) if a != b)
        rows.append(
            {
                "variant": label,
                "transitions": float(transitions),
                "flaps": float(breaker.total_flaps()),
                "reject_time": float(sum(1 for s in states if s >= 2)) / len(states),
            }
        )
    write_csv("e7_hysteresis", rows)
    return rows
