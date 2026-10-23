"""E17: where the admission path spends its time, and what that does to tails.

Section VII-C reports one number, microseconds per request, and one number is not
an explanation. This experiment has two parts.

Part A profiles a full run with cProfile and aggregates self time by module, so
the sketch, the accountant, the breaker, the coordinator and the market harness
can be separated. Profiling inflates absolute costs, so the shares are the result
and the unprofiled run supplies the mean.

Part B measures the service-time distribution of the admission path and feeds it
to a single-server queue, which is the smallest model that turns a service time
into a latency. Arrivals are Poisson at a chosen utilisation, and a second
scenario alternates a fast and a slow phase so that bursts are not averaged away.
Latency here is queueing latency plus service, for one coordinator thread and
FCFS order; it is a model driven by measured service times, not a deployment
measurement, and it says nothing about network or client-side time.
"""

from __future__ import annotations

import cProfile
import io
import pstats
import time
from typing import Any

import numpy as np

from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.factory import build_privfuse
from privfuse.platform.runtime import Market
from privfuse.trace.generator import EPS_DELTA

N_REQUESTS = 12000
N_SUBJECTS = 1500
SEED = 5
UTILISATIONS = (0.5, 0.8, 0.9, 0.95)
MODULES = (
    "privfuse.sketch",
    "privfuse.accounting",
    "privfuse.control",
    "privfuse.ledger",
    "privfuse.slo",
    "privfuse.platform",
    "privfuse.dp",
    "privfuse.trace",
)


class _Timed:
    """Policy proxy that records begin and finish separately."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.begin_s: list[float] = []
        self.finish_s: list[float] = []

    def begin(self, request: Any) -> Any:
        started = time.perf_counter()
        decision = self.inner.begin(request)
        self.begin_s.append(time.perf_counter() - started)
        return decision

    def finish(self, decision: Any, now: float) -> None:
        started = time.perf_counter()
        self.inner.finish(decision, now)
        self.finish_s.append(time.perf_counter() - started)

    def abort(self, decision: Any, now: float) -> None:
        self.inner.abort(decision, now)

    def tick(self, now: float) -> None:
        self.inner.tick(now)

    def stats(self) -> dict[str, float]:
        return self.inner.stats()


TRIALS = 3


def _median_run() -> tuple[_Timed, Market, Any]:
    """Run three times and keep the trial with the median mean service time, so a
    scheduler pause on the shared host cannot decide the reported percentiles."""
    runs = [_run() for _ in range(TRIALS)]
    returns = [float(np.mean(np.asarray(w.begin_s) + np.asarray(w.finish_s))) for w, _m, _t in runs]
    return runs[int(np.argsort(returns)[len(returns) // 2])]


def _run(disable_sweep: bool = False) -> tuple[_Timed, Market, Any]:
    trace = default_trace(n_requests=N_REQUESTS, n_subjects=N_SUBJECTS, cap_eps=1.0, seed=SEED)
    policy = build_privfuse(trace)
    if disable_sweep:
        policy.controller._tenant_refresh = 10**9
    wrapped = _Timed(policy)
    market = Market(
        policy=wrapped,
        caps=trace.caps,
        platforms=tuple(f"p{i}" for i in range(trace.config.n_platforms)),
        delta=EPS_DELTA,
    )
    market.run(trace.requests)
    return wrapped, market, trace


def _profile() -> list[dict[str, Any]]:
    trace = default_trace(n_requests=6000, n_subjects=1200, cap_eps=1.0, seed=SEED)
    policy = build_privfuse(trace)
    market = Market(policy=policy, caps=trace.caps, delta=EPS_DELTA)
    profiler = cProfile.Profile()
    profiler.enable()
    market.run(trace.requests)
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("tottime")
    stats.print_stats(18)
    text = stream.getvalue()

    rows: list[dict[str, Any]] = []
    total = 0.0
    for func, (_cc, _nc, tt, _ct, _callers) in stats.stats.items():
        total += tt
    for func, (_cc, _nc, tt, _ct, _callers) in stats.stats.items():
        path = func[0] or ""
        module = next((m for m in MODULES if path.startswith(m.replace(".", "/"))), None)
        if module is None:
            module = next((m for m in MODULES if m.split(".")[-1] in path), "other")
        rows.append(
            {
                "function": f"{path.rsplit('/', 1)[-1]}:{func[1]}:{func[2]}",
                "module": module,
                "self_s": tt,
                "share": tt / total if total else 0.0,
            }
        )
    rows.sort(key=lambda r: r["self_s"], reverse=True)
    (write_csv("e17_profile", rows[:40]))
    _top = "\n".join(text.splitlines()[5:18])
    write_json("e17_profile_top", {"top": _top, "requests": len(trace.requests)})
    agg: dict[str, float] = {}
    for row in rows:
        agg[row["module"]] = agg.get(row["module"], 0.0) + row["self_s"]
    print("module shares:")
    for module, value in sorted(agg.items(), key=lambda kv: -kv[1]):
        print(f"  {module:24s} {value / total * 100:5.1f}%")
    return rows


def _latencies(
    service: np.ndarray, utilisation: float, horizon: int, seed: int = 7
) -> np.ndarray:
    """FCFS single-server latency with Poisson arrivals at a given utilisation."""
    rng = np.random.default_rng(seed)
    mean = float(service.mean())
    rate = utilisation / mean
    gaps = rng.exponential(1.0 / rate, size=horizon)
    arrivals = np.cumsum(gaps)
    picks = rng.integers(0, len(service), size=horizon)
    out = np.empty(horizon)
    free = 0.0
    for i in range(horizon):
        start = max(arrivals[i], free)
        free = start + service[picks[i]]
        out[i] = free - arrivals[i]
    return out


def _bursty(
    service: np.ndarray, utilisation: float, horizon: int, seed: int = 11
) -> np.ndarray:
    """Alternating fast and slow phases, with the same average utilisation."""
    rng = np.random.default_rng(seed)
    mean = float(service.mean())
    # a 0.5 s burst followed by 4.5 s of silence; the burst rate is set so the
    # time-average rate equals the requested utilisation
    burst, calm = 10.0 * utilisation / mean, 0.0
    out: list[float] = []
    free = 0.0
    now = 0.0
    fast = True
    while len(out) < horizon:
        rate = burst if fast else calm
        length = 0.5 if fast else 4.5
        until = now + length
        while now < until and len(out) < horizon:
            if rate <= 0.0:
                now = until
                break
            now += rng.exponential(1.0 / rate)
            start = max(now, free)
            free = start + service[rng.integers(0, len(service))]
            out.append(free - now)
        fast = not fast
    return np.asarray(out)


def run() -> list[dict[str, Any]]:
    _profile()

    wrapped, market, trace = _median_run()
    service = np.asarray(wrapped.begin_s) + np.asarray(wrapped.finish_s[: len(wrapped.begin_s)])
    mean_us = float(service.mean() * 1e6)
    print(
        f"service: mean {mean_us:.1f} us  p50 {np.percentile(service, 50) * 1e6:.1f}  "
        f"p99 {np.percentile(service, 99) * 1e6:.1f}",
        flush=True,
    )

    plain, _pm, _pt = _run(disable_sweep=True)
    ablated = np.asarray(plain.begin_s) + np.asarray(plain.finish_s)
    print(
        f"sweep disabled: mean {ablated.mean() * 1e6:.1f} us  "
        f"p99 {np.percentile(ablated, 99) * 1e6:.1f} us",
        flush=True,
    )

    def _quantiles(reps: list[np.ndarray]) -> dict[str, float]:
        """Median across replicates of each percentile: the tail is unstable in a
        single replicate, so one draw would be a number without an error bar."""
        return {
            "p50_ms": float(np.median([np.percentile(r, 50) for r in reps]) * 1e3),
            "p99_ms": float(np.median([np.percentile(r, 99) for r in reps]) * 1e3),
            "p999_ms": float(np.median([np.percentile(r, 99.9) for r in reps]) * 1e3),
            "max_ms": float(np.median([r.max() for r in reps]) * 1e3),
        }

    rows: list[dict[str, Any]] = []
    for utilisation in UTILISATIONS:
        reps = [_latencies(service, utilisation, 100000, seed=100 + i) for i in range(5)]
        row: dict[str, Any] = {
            "scenario": "poisson",
            "utilisation": utilisation,
            "offered_rps": utilisation / float(service.mean()),
        }
        row.update(_quantiles(reps))
        rows.append(row)
    for utilisation in (0.5, 0.8):
        reps = [_bursty(service, utilisation, 60000, seed=200 + i) for i in range(5)]
        row = {
            "scenario": "bursty",
            "utilisation": utilisation,
            "offered_rps": utilisation / float(service.mean()),
        }
        row.update(_quantiles(reps))
        rows.append(row)
    rows.append(
        {
            "scenario": "sweep_disabled",
            "utilisation": 0.0,
            "offered_rps": 0.0,
            "p50_ms": float(np.percentile(ablated, 50) * 1e3),
            "p99_ms": float(np.percentile(ablated, 99) * 1e3),
            "p999_ms": float(np.percentile(ablated, 99.9) * 1e3),
            "max_ms": float(ablated.max() * 1e3),
        }
    )
    write_csv("e17_latency", rows)
    write_json(
        "e17_latency_meta",
        {
            "requests": len(wrapped.begin_s),
            "service_mean_us": mean_us,
            "service_p50_us": float(np.percentile(service, 50) * 1e6),
            "service_p99_us": float(np.percentile(service, 99) * 1e6),
            "service_p999_us": float(np.percentile(service, 99.9) * 1e6),
            "sweep_disabled_mean_us": float(ablated.mean() * 1e6),
            "sweep_disabled_p99_us": float(np.percentile(ablated, 99) * 1e6),
            "trials": TRIALS,
            "seed": SEED,
            "n_subjects": N_SUBJECTS,
            "model": "single server, FCFS, measured service times, synthetic arrivals",
        },
    )
    for row in rows:
        print(
            f"{row['scenario']} rho={row['utilisation']:.2f}: "
            f"p50 {row['p50_ms']:.2f} ms p99 {row['p99_ms']:.2f} ms",
            flush=True,
        )
    return rows


if __name__ == "__main__":
    run()
