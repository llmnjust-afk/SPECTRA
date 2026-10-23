"""Privacy service-level objectives.

An SLO is a triple ``(E, p, W)``: at most a ``p`` fraction of a subject
population may exceed ``E`` epsilon within any window of length ``W``.  A hard
cap is a separate, absolute constraint that may never be violated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from privfuse.dp.cost import CostVector


@dataclass(frozen=True)
class SLOSpec:
    name: str = "default"
    hard_cap: float = 10.0
    soft_budget: float = 8.0
    violation_rate: float = 0.01
    window: float | None = None
    delta: float = 1e-5

    def __post_init__(self) -> None:
        if self.hard_cap <= 0:
            raise ValueError("hard_cap must be positive")
        if not (0 < self.soft_budget <= self.hard_cap):
            raise ValueError("soft_budget must lie in (0, hard_cap]")
        if not (0.0 <= self.violation_rate <= 1.0):
            raise ValueError("violation_rate must lie in [0, 1]")

    def ratio(self, cost: CostVector) -> float:
        return cost.eps(self.delta) / self.hard_cap

    def exceeds_hard_cap(self, cost: CostVector) -> bool:
        return cost.eps(self.delta) > self.hard_cap

    def exceeds_soft_budget(self, cost: CostVector) -> bool:
        return cost.eps(self.delta) > self.soft_budget


@dataclass
class SLOResult:
    spec: SLOSpec
    monitored: int
    violating: int
    observed_rate: float
    satisfied: bool
    worst_subject: str | None = None
    worst_eps: float = 0.0

    def as_dict(self) -> dict[str, float | str | bool | None]:
        return {
            "slo": self.spec.name,
            "monitored": self.monitored,
            "violating": self.violating,
            "observed_rate": self.observed_rate,
            "target_rate": self.spec.violation_rate,
            "satisfied": self.satisfied,
            "worst_subject": self.worst_subject,
            "worst_eps": self.worst_eps,
        }


def evaluate_slo(
    spec: SLOSpec,
    estimates: Iterable[tuple[str, CostVector]],
) -> SLOResult:
    monitored = 0
    violating = 0
    worst_subject: str | None = None
    worst_eps = 0.0
    for subject, cost in estimates:
        monitored += 1
        value = cost.eps(spec.delta)
        if value > worst_eps:
            worst_eps, worst_subject = value, subject
        if value > spec.soft_budget:
            violating += 1
    rate = (violating / monitored) if monitored else 0.0
    return SLOResult(
        spec=spec,
        monitored=monitored,
        violating=violating,
        observed_rate=rate,
        satisfied=rate <= spec.violation_rate,
        worst_subject=worst_subject,
        worst_eps=worst_eps,
    )


def hard_cap_violations(
    spec: SLOSpec,
    estimates: Iterable[tuple[str, CostVector]],
) -> int:
    return sum(1 for _, cost in estimates if spec.exceeds_hard_cap(cost))
