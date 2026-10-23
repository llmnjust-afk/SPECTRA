"""E4: cross-platform budget-splitting attack."""

from __future__ import annotations

from typing import Any

from privfuse.experiments.common import compare_policies, default_trace, write_csv, write_json
from privfuse.trace.generator import TraceConfig


def run(splits: list[int] | None = None, seeds: list[int] | None = None) -> list[dict[str, Any]]:
    splits = splits or [12, 24, 42, 60]
    seeds = seeds or [1, 2, 3]
    rows: list[dict[str, Any]] = []
    for split in splits:
        for seed in seeds:
            trace = default_trace(
                n_requests=5000,
                n_subjects=1000,
                cap_eps=1.0,
                attack="split",
                attack_splits=split,
                attack_epsilon=0.3,
                seed=seed,
            )
            for row in compare_policies(trace):
                row["splits"] = split
                row["seed"] = seed
                row["escape_ratio"] = row["max_eps"] / trace.config.cap_eps
                rows.append(row)
    write_csv("e4_attack", rows)
    write_json(
        "e4_attack_meta",
        {
            "splits": splits,
            "seeds": seeds,
            "privfuse_violations": float(
                sum(r["hard_cap_violations"] for r in rows if r["policy"] == "privfuse")
            ),
            "baseline_violations": float(
                sum(
                    r["hard_cap_violations"]
                    for r in rows
                    if r["policy"] == "static_quota"
                )
            ),
        },
    )
    return rows


if __name__ == "__main__":
    for row in run():
        print(row["policy"], row["splits"], row["seed"], round(row["escape_ratio"], 2))
