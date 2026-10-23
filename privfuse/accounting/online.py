"""Composition-aware online accountant.

The accountant keeps two views:

* a cumulative view, which backs the hard regulatory cap and is never reset;
* an epoch ring, which backs windowed SLOs.

Both views are estimates.  Every estimate is an upper bound on the true
composition, because the underlying Count-Min sketches only ever over-shoot.
The circuit breaker uses ``upper_bound`` -- the point estimate plus the
deterministic sketch error -- so admission decisions do not rely on a
probabilistic argument.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator, Sequence

from privfuse.dp.cost import CostVector
from privfuse.sketch.costsketch import CostSketch


@dataclass
class OnlineAccountantConfig:
    width: int = 1 << 14
    depth: int = 4
    hot_capacity: int = 1024
    epoch_seconds: float = 60.0
    ring_size: int = 8

    @property
    def max_window(self) -> float:
        return self.epoch_seconds * self.ring_size


@dataclass
class Epoch:
    index: int
    start: float
    sketch: CostSketch


class OnlineAccountant:
    """Streaming, one-sided privacy accounting over many subjects."""

    def __init__(self, config: OnlineAccountantConfig | None = None) -> None:
        self.config = config or OnlineAccountantConfig()
        cfg = self.config
        self._cumulative = CostSketch(
            width=cfg.width,
            depth=cfg.depth,
            hot_capacity=cfg.hot_capacity,
            seed=11,
        )
        self._epochs: deque[Epoch] = deque()
        self._next_index = 0

    def _rotate(self, now: float) -> None:
        cfg = self.config
        if not self._epochs:
            self._epochs.append(self._open_epoch(now))
            return
        last = self._epochs[-1]
        while now >= last.start + cfg.epoch_seconds:
            start = last.start + cfg.epoch_seconds
            new_epoch = self._open_epoch(start)
            self._epochs.append(new_epoch)
            last = new_epoch
            while len(self._epochs) > cfg.ring_size:
                self._epochs.popleft()

    def _open_epoch(self, start: float) -> Epoch:
        cfg = self.config
        epoch = Epoch(
            index=self._next_index,
            start=start,
            sketch=CostSketch(
                width=cfg.width,
                depth=cfg.depth,
                hot_capacity=cfg.hot_capacity,
                seed=1000 + self._next_index,
            ),
        )
        self._next_index += 1
        return epoch

    def observe(self, subject: str, cost: CostVector, now: float = 0.0) -> None:
        self._rotate(now)
        self._cumulative.add(subject, cost)
        self._epochs[-1].sketch.add(subject, cost)

    def _window_epochs(self, now: float, window: float) -> list[Epoch]:
        if window > self.config.max_window + 1e-9:
            raise ValueError(
                f"window {window} exceeds max_window {self.config.max_window}"
            )
        cutoff = now - window
        return [e for e in self._epochs if e.start + self.config.epoch_seconds > cutoff]

    def _pair(
        self, subject: str, now: float, window: float | None, upper: bool
    ) -> tuple[float, float]:
        if window is None:
            return self._cumulative.estimate_pair(subject, upper=upper)
        pure = 0.0
        rho = 0.0
        for epoch in self._window_epochs(now, window):
            p, r = epoch.sketch.estimate_pair(subject, upper=upper)
            pure += p
            rho += r
        return pure, rho

    def estimate(self, subject: str, now: float = 0.0, window: float | None = None) -> CostVector:
        pure, rho = self._pair(subject, now, window, upper=False)
        return CostVector(eps_pure=pure, rho=rho, delta=0.0)

    def upper_bound(
        self, subject: str, now: float = 0.0, window: float | None = None
    ) -> CostVector:
        pure, rho = self._pair(subject, now, window, upper=True)
        return CostVector(eps_pure=pure, rho=rho, delta=0.0)

    def upper_bound_eps(
        self,
        subject: str,
        delta: float,
        now: float = 0.0,
        window: float | None = None,
    ) -> float:
        pure, rho = self._pair(subject, now, window, upper=True)
        if rho <= 0.0:
            return pure
        return pure + rho + 2.0 * math.sqrt(rho * math.log(1.0 / delta))

    def mass(self, now: float = 0.0, window: float | None = None) -> float:
        if window is None:
            return self._cumulative.total_mass()
        return sum(e.sketch.total_mass() for e in self._window_epochs(now, window))

    def observed_subjects(self, now: float = 0.0, window: float | None = None) -> Iterator[str]:
        if window is None:
            yield from self._cumulative.hot.keys()
            return
        seen: set[str] = set()
        for epoch in self._window_epochs(now, window):
            for key in epoch.sketch.hot.keys():
                if key not in seen:
                    seen.add(key)
                    yield key

    def hot_estimates(
        self, now: float = 0.0, window: float | None = None
    ) -> list[tuple[str, CostVector]]:
        """Exact costs for the heaviest subjects, used for SLO violation rates."""
        if window is None:
            return list(self._cumulative.hot.items())
        merged: dict[str, CostVector] = {}
        for epoch in self._window_epochs(now, window):
            for subject, cost in epoch.sketch.hot.items():
                merged[subject] = merged.get(subject, CostVector.zero()) + cost
        return list(merged.items())

    def nbytes(self) -> int:
        return self._cumulative.nbytes() + sum(e.sketch.nbytes() for e in self._epochs)

    def stats(self) -> dict[str, float]:
        return {
            "epochs_live": float(len(self._epochs)),
            "events_cumulative": float(self._cumulative.events),
            "mass_cumulative": float(self._cumulative.total_mass()),
            "bytes": float(self.nbytes()),
            "sketch_error": float(self._cumulative.error_bound().eps_pure),
        }
