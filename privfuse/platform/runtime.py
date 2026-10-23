"""Reference trading platform and market harness."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from privfuse.control.admission import Decision, QueryRequest
from privfuse.dp.accountant import ExactAccountant
from privfuse.dp.cost import CostVector
from privfuse.platform.policy import Policy


class PlatformCrash(RuntimeError):
    """Raised to simulate a platform dying between reserve and commit."""


@dataclass
class TradingPlatform:
    name: str
    policy: Policy
    crash_after_reserve: bool = False
    crashes: int = 0

    def execute(self, request: QueryRequest) -> Decision:
        decision = self.policy.begin(request)
        try:
            if self.crash_after_reserve and decision.allowed:
                self.crash_after_reserve = False
                self.crashes += 1
                raise PlatformCrash(f"platform {self.name} crashed after reserve")
            self.policy.finish(decision, request.timestamp)
            return decision
        except PlatformCrash:
            raise
        except Exception:
            self.policy.abort(decision, request.timestamp)
            raise


@dataclass
class RunResult:
    decisions: list[Decision]
    stats: dict[str, float]
    ground_truth: dict[str, float]
    elapsed: float
    crashes: int = 0

    @property
    def availability(self) -> float:
        if not self.decisions:
            return 1.0
        return sum(1 for d in self.decisions if d.allowed) / len(self.decisions)

    @property
    def utility(self) -> float:
        if not self.decisions:
            return 0.0
        return sum(
            d.request.utility * (1.0 - d.utility_loss) for d in self.decisions if d.allowed
        )

    def summary(self) -> dict[str, float]:
        out = {
            "requests": float(len(self.decisions)),
            "allowed": float(sum(1 for d in self.decisions if d.allowed)),
            "degraded": float(sum(1 for d in self.decisions if d.degraded)),
            "availability": self.availability,
            "utility": self.utility,
            "elapsed": self.elapsed,
            "crashes": float(self.crashes),
            "hard_cap_violations": float(self.ground_truth["violations"]),
            "max_eps": float(self.ground_truth["max_eps"]),
            "subjects": float(self.ground_truth["subjects"]),
        }
        out.update(self.stats)
        return out


class Market:
    """Runs a request trace against a policy and records ground truth."""

    def __init__(
        self,
        policy: Policy,
        caps: dict[str, float],
        platforms: Sequence[str] = ("p0", "p1", "p2"),
        delta: float = 1e-5,
    ) -> None:
        self.policy = policy
        self.caps = caps
        self.delta = delta
        self.platforms = {
            name: TradingPlatform(name=name, policy=policy) for name in platforms
        }
        self.truth = ExactAccountant()

    def run(self, requests: Iterable[QueryRequest], tick_every: int = 512) -> RunResult:
        started = time.perf_counter()
        decisions: list[Decision] = []
        crashes = 0
        for index, request in enumerate(requests):
            platform = self.platforms.get(request.platform)
            if platform is None:
                platform = self.platforms["p0"]
            try:
                decision = platform.execute(request)
            except PlatformCrash:
                crashes += 1
                continue
            decisions.append(decision)
            if decision.allowed:
                for subject in request.subjects:
                    self.truth.add(subject, decision.charged, timestamp=request.timestamp)
            if index % tick_every == 0:
                self.policy.tick(request.timestamp)
        self.policy.tick(1e12)
        elapsed = time.perf_counter() - started
        truth = self._ground_truth()
        return RunResult(
            decisions=decisions,
            stats=self.policy.stats(),
            ground_truth=truth,
            elapsed=elapsed,
            crashes=crashes,
        )

    def _ground_truth(self) -> dict[str, float]:
        violations = 0
        worst = 0.0
        for subject, cap in self.caps.items():
            value = self.truth.get(subject).eps(self.delta)
            worst = max(worst, value)
            if value > cap + 1e-12:
                violations += 1
        return {
            "violations": float(violations),
            "max_eps": float(worst),
            "subjects": float(len(self.caps)),
        }
