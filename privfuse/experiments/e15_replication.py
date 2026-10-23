"""E15: replication of the headline results over twelve seeds.

The published table reports three seeds. Three is enough to see a trend and not
enough to claim a difference, so this experiment reruns the cap sweep with twelve
seeds and reports the mean, the sample standard deviation and a 95% confidence
interval from Student's t. It also reports the paired difference against the
strongest baseline, which is the quantity a reviewer should actually look at:
the two policies see the same traces, so a paired interval is tighter and more
honest than comparing two marginal intervals.

Raw per-seed rows are written unchanged; the summary is derived from them.
"""

from __future__ import annotations

import math
from typing import Any

from privfuse.experiments.common import (
    compare_policies,
    default_trace,
    write_csv,
    write_json,
)

CAPS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
SEEDS = tuple(range(12))
POLICIES = ("privfuse", "exact_blocking", "static_quota")
T975 = {  # two-sided 95% t quantile, df = n-1
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
}


def _summary(values: list[float]) -> dict[str, float]:
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return {"mean": mean, "sd": 0.0, "ci": 0.0, "n": float(n)}
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = math.sqrt(var)
    ci = T975.get(n, 1.96) * sd / math.sqrt(n)
    return {"mean": mean, "sd": sd, "ci": ci, "n": float(n)}


def run() -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for seed in SEEDS:
        for cap in CAPS:
            trace = default_trace(
                n_requests=6000,
                n_subjects=1200,
                cap_eps=cap,
                seed=seed,
                attack="split",
                attack_splits=42,
                attack_epsilon=0.3,
            )
            rows = compare_policies(trace, names=list(POLICIES))
            for row in rows:
                row["cap"] = cap
                row["seed"] = seed
                raw.append(row)
        print(f"seed {seed} done", flush=True)
    write_csv("e15_replication", raw)

    summary: list[dict[str, Any]] = []
    for cap in CAPS:
        block = [r for r in raw if r["cap"] == cap]
        by_policy = {
            name: [r for r in block if r["policy"] == name] for name in POLICIES
        }
        avail = {
            name: _summary([r["availability"] for r in rows])
            for name, rows in by_policy.items()
        }
        viol = {
            name: _summary([r["hard_cap_violations"] for r in rows])
            for name, rows in by_policy.items()
        }
        eps = {
            name: _summary([r["max_eps"] for r in rows])
            for name, rows in by_policy.items()
        }
        for name in POLICIES:
            diff = [
                a["availability"] - b["availability"]
                for a, b in zip(by_policy["privfuse"], by_policy[name])
            ]
            paired = _summary(diff)
            summary.append(
                {
                    "cap": cap,
                    "policy": name,
                    "availability_mean": avail[name]["mean"],
                    "availability_sd": avail[name]["sd"],
                    "availability_ci": avail[name]["ci"],
                    "violations_mean": viol[name]["mean"],
                    "violations_sd": viol[name]["sd"],
                    "violations_ci": viol[name]["ci"],
                    "max_eps_mean": eps[name]["mean"],
                    "max_eps_ci": eps[name]["ci"],
                    "avail_diff_vs_privfuse": paired["mean"],
                    "avail_diff_ci": paired["ci"],
                    "n": float(len(by_policy[name])),
                }
            )
        print(
            f"cap {cap}: "
            + "  ".join(
                f"{name} {avail[name]['mean']:.3f}+-{avail[name]['ci']:.3f} "
                f"viol {viol[name]['mean']:.1f}"
                for name in POLICIES
            ),
            flush=True,
        )
    write_csv("e15_summary", summary)
    write_json(
        "e15_replication_meta",
        {
            "caps": list(CAPS),
            "seeds": list(SEEDS),
            "policies": list(POLICIES),
            "n_seeds": len(SEEDS),
            "base": {"n_requests": 6000, "n_subjects": 1200, "attack_splits": 42},
        },
    )
    return raw


if __name__ == "__main__":
    run()
