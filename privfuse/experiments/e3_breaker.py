"""E3: breaker behaviour as the hard cap tightens."""

from __future__ import annotations

from typing import Any

from privfuse.experiments.common import compare_policies, default_trace, write_csv, write_json
from privfuse.trace.generator import TraceConfig


def run(caps: list[float] | None = None) -> list[dict[str, Any]]:
    caps = caps or [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    rows: list[dict[str, Any]] = []
    for cap in caps:
        trace = default_trace(
            n_requests=6000,
            n_subjects=1200,
            cap_eps=cap,
            seed=11,
            attack="split",
            attack_splits=42,
            attack_epsilon=0.3,
        )
        for row in compare_policies(
            trace, names=["privfuse", "exact_blocking", "static_quota"]
        ):
            row["cap"] = cap
            rows.append(row)
    write_csv("e3_breaker", rows)
    write_json("e3_breaker_meta", {"caps": caps, "rows": len(rows)})
    return rows


if __name__ == "__main__":
    for row in run():
        print(row["policy"], row["cap"], round(row["availability"], 3), row["hard_cap_violations"])
