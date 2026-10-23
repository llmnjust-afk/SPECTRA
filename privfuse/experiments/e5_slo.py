"""E5: the availability / violation frontier of the SLO knob."""

from __future__ import annotations

from typing import Any

from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA


def run(
    soft_ratios: list[float] | None = None,
    violation_rates: list[float] | None = None,
) -> list[dict[str, Any]]:
    soft_ratios = soft_ratios or [0.55, 0.65, 0.75, 0.85, 0.95]
    violation_rates = violation_rates or [0.0, 0.005, 0.01, 0.05]
    trace = default_trace(
        n_requests=14000,
        n_subjects=900,
        cap_eps=0.8,
        seed=5,
        attack="split",
        attack_splits=40,
        attack_epsilon=0.3,
    )
    rows: list[dict[str, Any]] = []
    for soft in soft_ratios:
        for rate in violation_rates:
            config = PrivFuseConfig(soft_ratio=soft, violation_rate=rate)
            policy = build_privfuse(trace, config=config)
            market = Market(policy=policy, caps=trace.caps, delta=EPS_DELTA)
            result = market.run(trace.requests)
            monitored = [
                s for s in market.truth.subjects() if market.truth.get(s).eps(EPS_DELTA) > 0
            ]
            violating = [
                s
                for s in monitored
                if market.truth.get(s).eps(EPS_DELTA) > soft * trace.config.cap_eps
            ]
            observed = len(violating) / max(1, len(monitored))
            rows.append(
                {
                    "soft_ratio": soft,
                    "violation_rate": rate,
                    "availability": result.availability,
                    "utility": result.utility,
                    "hard_cap_violations": result.ground_truth["violations"],
                    "observed_soft_violation_rate": observed,
                    "slo_satisfied": observed <= rate,
                    "max_eps": result.ground_truth["max_eps"],
                    "degraded": float(result.summary().get("degraded", 0.0)),
                }
            )
    write_csv("e5_slo", rows)
    write_json("e5_slo_meta", {"rows": len(rows)})
    return rows


if __name__ == "__main__":
    for row in run():
        print(row["soft_ratio"], row["violation_rate"], round(row["availability"], 3))
