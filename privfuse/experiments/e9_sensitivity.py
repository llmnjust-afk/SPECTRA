"""E9: one-factor sensitivity of the controller.

Every headline number is measured at a single operating point. This experiment
moves one knob at a time and checks that the qualitative result -- PrivFuse never
violates, the platform-local competitor does -- survives the move.

Each point uses a fresh trace and a shortened request count so the whole sweep
stays under a minute. Only one factor changes per row; everything else is the
default configuration.
"""

from __future__ import annotations

import time
from typing import Any

from privfuse.baselines import StaticQuotaPolicy
from privfuse.experiments.common import write_csv, write_json
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA, TraceConfig, generate_trace

BASE = dict(n_requests=6000, n_subjects=1200, attack="split", attack_splits=42)


SWEEPS: dict[str, list[Any]] = {
    "delta": [1e-6, 1e-5, 1e-4],
    "hot_capacity": [64, 256, 1024, 4096],
    "n_platforms": [1, 3, 6],
    "crash_probability": [0.0, 0.01, 0.05],
    "zipf_alpha": [0.9, 1.15, 1.5],
    "n_tenants": [5, 40, 200],
}


def _trace_for(factor: str, value: Any) -> tuple[Any, float, float, int]:
    kwargs = dict(BASE)
    delta = EPS_DELTA
    crash = 0.0
    hot = 1024
    if factor == "delta":
        delta = float(value)
    elif factor == "hot_capacity":
        hot = int(value)
    elif factor == "n_platforms":
        kwargs["n_platforms"] = int(value)
    elif factor == "crash_probability":
        crash = float(value)
    elif factor == "zipf_alpha":
        kwargs["zipf_alpha"] = float(value)
    elif factor == "n_tenants":
        kwargs["n_tenants"] = int(value)
    else:
        raise KeyError(factor)
    kwargs["seed"] = 21
    trace = generate_trace(TraceConfig(**kwargs))
    return trace, delta, crash, hot


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for factor, values in SWEEPS.items():
        for value in values:
            trace, delta, crash, hot = _trace_for(factor, value)
            for policy_name in ("privfuse", "static_quota"):
                if policy_name == "privfuse":
                    policy = build_privfuse(
                        trace, config=PrivFuseConfig(hot_capacity=hot), delta=delta
                    )
                else:
                    policy = StaticQuotaPolicy(caps=trace.caps, delta=delta)
                platforms = tuple(f"p{i}" for i in range(trace.config.n_platforms))
                market = Market(
                    policy=policy,
                    caps=trace.caps,
                    platforms=platforms,
                    delta=delta,
                    crash_probability=crash,
                )
                started = time.perf_counter()
                result = market.run(trace.requests)
                elapsed = time.perf_counter() - started
                row: dict[str, Any] = {
                    "factor": factor,
                    "value": value,
                    "policy": policy_name,
                }
                row.update(result.summary())
                row["us_per_request"] = 1e6 * elapsed / max(1, len(result.decisions))
                rows.append(row)
            print(
                f"{factor}={value}: "
                + "  ".join(
                    f"{r['policy']} viol={int(r['hard_cap_violations'])} "
                    f"avail={r['availability']:.3f}"
                    for r in rows[-2:]
                ),
                flush=True,
            )
    write_csv("e9_sensitivity", rows)
    write_json(
        "e9_sensitivity_meta",
        {"sweeps": {k: list(map(str, v)) for k, v in SWEEPS.items()}, "base": BASE},
    )
    return rows


if __name__ == "__main__":
    run()
