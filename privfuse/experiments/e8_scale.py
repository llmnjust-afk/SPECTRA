"""E8: does the accountant stay bounded as the subject population grows?

The sketch is only worth its per-request overhead if its state stops growing
while an exact accountant keeps growing. This experiment holds the traffic shape
fixed and sweeps the population from one thousand to one million subjects,
measuring traced memory, per-request cost, and whether the estimate ever falls
below the truth.

Truth is computed in closed form: subjects in the hot set receive a known number
of identically priced requests, and cold subjects receive exactly one. That
avoids keeping a second accountant in memory during the measurement.
"""

from __future__ import annotations

import gc
import tracemalloc
from dataclasses import dataclass
from typing import Any, Iterator

from privfuse.accounting.online import (
    OnlineAccountant,
    OnlineAccountantConfig,
    ring_epochs_for,
)
from privfuse.dp.accountant import ExactAccountant
from privfuse.dp.cost import CostVector
from privfuse.dp.mechanisms import gaussian_cost
from privfuse.experiments.common import write_csv, write_json
from privfuse.trace.generator import EPS_DELTA

COLD = gaussian_cost(0.002, EPS_DELTA, 1.0)
HOT = gaussian_cost(0.02, EPS_DELTA, 1.0)
EPOCH = 300.0
WINDOW = 600.0


@dataclass(frozen=True)
class Shape:
    n_subjects: int
    hot: int = 1000
    hot_requests: int = 8

    def __post_init__(self) -> None:
        if self.hot > self.n_subjects:
            object.__setattr__(self, "hot", self.n_subjects)

    @property
    def n_requests(self) -> int:
        return self.n_subjects + self.hot * self.hot_requests

    def events(self) -> Iterator[tuple[str, CostVector]]:
        for i in range(self.n_subjects):
            yield f"s{i:07d}", COLD
        for i in range(self.hot):
            key = f"s{self.n_subjects - 1 - i:07d}"
            for _ in range(self.hot_requests):
                yield key, HOT

    def truth_rho(self, subject: str) -> float:
        index = int(subject[1:])
        repeats = self.hot_requests if index >= self.n_subjects - self.hot else 0
        return COLD.rho + repeats * HOT.rho

    def truth_eps(self, subject: str) -> float:
        return CostVector(eps_pure=0.0, rho=self.truth_rho(subject), delta=0.0).eps(
            EPS_DELTA
        )


def _measure_sketch(shape: Shape, width: int) -> dict[str, Any]:
    config = OnlineAccountantConfig(
        width=width,
        depth=4,
        hot_capacity=2048,
        epoch_seconds=EPOCH,
        ring_size=ring_epochs_for(WINDOW, EPOCH),
    )
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()
    accountant = OnlineAccountant(config)
    for subject, cost in shape.events():
        accountant.observe(subject, cost, now=0.0)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    sample = [f"s{i * 97 % shape.n_subjects:07d}" for i in range(4000)]
    hot_sample = [f"s{shape.n_subjects - 1 - i:07d}" for i in range(shape.hot)]
    underestimated = 0
    absolute: list[float] = []
    for subject in sample + hot_sample:
        estimate = accountant.estimate(subject).eps(EPS_DELTA)
        truth = shape.truth_eps(subject)
        underestimated += estimate < truth - 1e-12
        absolute.append(estimate - truth)
    hot_worst = 0.0
    for subject in hot_sample:
        estimate = accountant.estimate(subject).eps(EPS_DELTA)
        truth = shape.truth_eps(subject)
        if truth > 0:
            hot_worst = max(hot_worst, (estimate - truth) / truth)
    return {
        "backend": "sketch",
        "width": width,
        "bytes": peak,
        "underestimated": underestimated,
        "mean_absolute_error": sum(absolute) / len(absolute),
        "max_absolute_error": max(absolute),
        "hot_max_relative_error": hot_worst,
        "accountant_bytes": accountant.nbytes(),
    }


def _measure_exact(shape: Shape) -> dict[str, Any]:
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()
    accountant = ExactAccountant()
    for subject, cost in shape.events():
        accountant.add(subject, cost, timestamp=0.0)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {
        "backend": "exact",
        "width": 0,
        "bytes": peak,
        "underestimated": 0,
        "mean_absolute_error": 0.0,
        "max_absolute_error": 0.0,
        "hot_max_relative_error": 0.0,
        "accountant_bytes": None,
    }


def _timed(shape: Shape, width: int | None) -> float:
    import time

    gc.collect()
    if width is None:
        accountant: Any = ExactAccountant()
        start = time.perf_counter()
        for subject, cost in shape.events():
            accountant.add(subject, cost, timestamp=0.0)
    else:
        accountant = OnlineAccountant(
            OnlineAccountantConfig(
                width=width,
                depth=4,
                hot_capacity=2048,
                epoch_seconds=EPOCH,
                ring_size=ring_epochs_for(WINDOW, EPOCH),
            )
        )
        start = time.perf_counter()
        for subject, cost in shape.events():
            accountant.observe(subject, cost, now=0.0)
            accountant.upper_bound_eps(subject, EPS_DELTA, now=0.0, window=None)
    return 1e6 * (time.perf_counter() - start) / shape.n_requests


def run(populations: list[int] | None = None, widths: list[int] | None = None) -> list[dict[str, Any]]:
    populations = populations or [1_000, 10_000, 100_000, 1_000_000]
    widths = widths or [1 << 12, 1 << 14]
    rows: list[dict[str, Any]] = []
    for n in populations:
        shape = Shape(n_subjects=n)
        for width in widths:
            row = _measure_sketch(shape, width)
            row.update(
                {
                    "subjects": n,
                    "requests": shape.n_requests,
                    "us_per_request": _timed(shape, width),
                }
            )
            rows.append(row)
        row = _measure_exact(shape)
        row.update(
            {
                "subjects": n,
                "requests": shape.n_requests,
                "us_per_request": _timed(shape, None),
            }
        )
        rows.append(row)
        print(
            f"n={n:>9,}  exact={row['bytes'] / 1e6:.1f}MB "
            f"{row['us_per_request']:.2f}us  "
            + "  ".join(
                f"w{r['width']}={r['bytes'] / 1e6:.1f}MB" for r in rows if r["subjects"] == n and r["width"]
            ),
            flush=True,
        )
    write_csv("e8_scale", rows)
    write_json(
        "e8_scale_meta",
        {
            "populations": populations,
            "widths": widths,
            "hot_subjects": Shape(n_subjects=1).hot,
            "hot_requests": Shape(n_subjects=1).hot_requests,
        },
    )
    return rows


if __name__ == "__main__":
    run()
