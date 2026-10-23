"""Shared helpers for the experiment runners."""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict
from typing import Any, Callable

import pandas as pd

from privfuse.baselines import (
    AuditOnlyPolicy,
    ExactBlockingPolicy,
    ExactGlobalPolicy,
    ExactWindowedPolicy,
    StaticQuotaPolicy,
    TokenBucketPolicy,
)
from privfuse.factory import PrivFuseConfig, build_privfuse
from privfuse.platform.runtime import Market, RunResult
from privfuse.trace.generator import EPS_DELTA, Trace, generate_trace

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

BASELINES: dict[str, Callable[[Trace], Any]] = {
    "privfuse": lambda trace: build_privfuse(trace),
    "privfuse_exact": lambda trace: build_privfuse(trace, PrivFuseConfig(exact=True)),
    "exact_blocking": lambda trace: ExactBlockingPolicy(caps=trace.caps),
    "static_quota": lambda trace: StaticQuotaPolicy(caps=trace.caps),
    "token_bucket": lambda trace: TokenBucketPolicy(caps=trace.caps),
    "audit_only": lambda trace: AuditOnlyPolicy(caps=trace.caps),
    "exact_global": lambda trace: ExactGlobalPolicy(caps=trace.caps),
    "exact_windowed": lambda trace: ExactWindowedPolicy(caps=trace.caps),
}


def ensure_dirs() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)


def write_json(name: str, payload: dict[str, Any]) -> pathlib.Path:
    ensure_dirs()
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=float))
    return path


def write_csv(name: str, rows: list[dict[str, Any]]) -> pathlib.Path:
    ensure_dirs()
    path = RESULTS / f"{name}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def run_policy(policy: Any, trace: Trace, tick_every: int = 512) -> RunResult:
    market = Market(policy=policy, caps=trace.caps, delta=EPS_DELTA)
    return market.run(trace.requests, tick_every=tick_every)


def compare_policies(
    trace: Trace,
    names: list[str] | None = None,
    config: PrivFuseConfig | None = None,
) -> list[dict[str, Any]]:
    names = names or list(BASELINES)
    rows: list[dict[str, Any]] = []
    for name in names:
        if name == "privfuse":
            policy = build_privfuse(trace, config=config)
        else:
            policy = BASELINES[name](trace)
        result = run_policy(policy, trace)
        row: dict[str, Any] = {"policy": name}
        row.update(result.summary())
        rows.append(row)
    return rows


def default_trace(**overrides: Any) -> Trace:
    from privfuse.trace.generator import TraceConfig

    return generate_trace(TraceConfig(**overrides))
