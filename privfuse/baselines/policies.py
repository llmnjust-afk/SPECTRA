"""Baseline admission policies.

Each baseline is a plausible deployment we might meet in practice:

``static_quota``   per-platform fixed quota, the usual marketplace default
``token_bucket``   rate-limited epsilon budget
``audit_only``     full audit after the fact, no blocking (Burnat-style)
``exact_blocking`` exact per-platform accounting, correct but platform-local
"""

from __future__ import annotations

from dataclasses import dataclass, field

from privfuse.control.admission import Decision, QueryRequest
from privfuse.control.breaker import BreakerLevel
from privfuse.dp.cost import CostVector


def _allow(request: QueryRequest, cost: CostVector, reason: str) -> Decision:
    return Decision(
        request=request,
        allowed=True,
        level=BreakerLevel.NORMAL,
        charged=cost,
        reason=reason,
    )


def _deny(request: QueryRequest, reason: str) -> Decision:
    return Decision(
        request=request,
        allowed=False,
        level=BreakerLevel.REJECT,
        charged=CostVector.zero(),
        reason=reason,
    )


@dataclass
class StaticQuotaPolicy:
    """Fixed per-subject quota, tracked independently on every platform."""

    caps: dict[str, float]
    delta: float = 1e-5
    name: str = "static_quota"

    def __post_init__(self) -> None:
        self._spent: dict[tuple[str, str], CostVector] = {}

    def begin(self, request: QueryRequest) -> Decision:
        for subject in request.subjects:
            key = (request.platform, subject)
            spent = self._spent.get(key, CostVector.zero())
            if spent.eps(self.delta) + request.cost.eps(self.delta) > self.caps[subject]:
                self.rejections = getattr(self, "rejections", 0) + 1
                return _deny(request, "quota_exhausted")
        return _allow(request, request.cost, "quota_ok")

    def finish(self, decision: Decision, now: float) -> None:
        if not decision.allowed:
            return
        for subject in decision.request.subjects:
            key = (decision.request.platform, subject)
            spent = self._spent.get(key, CostVector.zero())
            self._spent[key] = spent + decision.charged

    def abort(self, decision: Decision, now: float) -> None:
        return None

    def tick(self, now: float) -> None:
        return None

    def stats(self) -> dict[str, float]:
        return {"policy_rejections": float(getattr(self, "rejections", 0))}


@dataclass
class TokenBucketPolicy:
    """Epsilon token bucket with lazy refill, per platform and subject."""

    caps: dict[str, float]
    delta: float = 1e-5
    refill_rate: float = 0.05
    name: str = "token_bucket"

    def __post_init__(self) -> None:
        self._level: dict[tuple[str, str], float] = {}
        self._last: dict[tuple[str, str], float] = {}

    def _refill(self, key: tuple[str, str], cap: float, now: float) -> float:
        level = self._level.get(key, cap)
        last = self._last.get(key, now)
        level = min(cap, level + max(0.0, now - last) * self.refill_rate)
        self._level[key] = level
        self._last[key] = now
        return level

    def begin(self, request: QueryRequest) -> Decision:
        cost = request.cost.eps(self.delta)
        for subject in request.subjects:
            key = (request.platform, subject)
            cap = self.caps[subject]
            level = self._refill(key, cap, request.timestamp)
            if level < cost:
                self.rejections = getattr(self, "rejections", 0) + 1
                return _deny(request, "bucket_empty")
        for subject in request.subjects:
            key = (request.platform, subject)
            self._level[key] = self._level[key] - cost
        return _allow(request, request.cost, "tokens_ok")

    def finish(self, decision: Decision, now: float) -> None:
        return None

    def abort(self, decision: Decision, now: float) -> None:
        return None

    def tick(self, now: float) -> None:
        return None

    def stats(self) -> dict[str, float]:
        return {"policy_rejections": float(getattr(self, "rejections", 0))}


@dataclass
class AuditOnlyPolicy:
    """Allow everything; detect violations after the fact."""

    caps: dict[str, float]
    delta: float = 1e-5
    name: str = "audit_only"

    def __post_init__(self) -> None:
        self._spent: dict[tuple[str, str], CostVector] = {}

    def begin(self, request: QueryRequest) -> Decision:
        return _allow(request, request.cost, "unchecked")

    def finish(self, decision: Decision, now: float) -> None:
        if not decision.allowed:
            return
        for subject in decision.request.subjects:
            key = (decision.request.platform, subject)
            spent = self._spent.get(key, CostVector.zero())
            self._spent[key] = spent + decision.charged

    def abort(self, decision: Decision, now: float) -> None:
        return None

    def tick(self, now: float) -> None:
        return None

    def stats(self) -> dict[str, float]:
        flagged = sum(
            1
            for (_, subject), spent in self._spent.items()
            if spent.eps(self.delta) > self.caps[subject]
        )
        return {"audit_flagged_keys": float(flagged)}


@dataclass
class ExactBlockingPolicy:
    """Exact per-platform accounting with blocking at the cap."""

    caps: dict[str, float]
    delta: float = 1e-5
    name: str = "exact_blocking"

    def __post_init__(self) -> None:
        self._spent: dict[tuple[str, str], CostVector] = {}

    def begin(self, request: QueryRequest) -> Decision:
        for subject in request.subjects:
            key = (request.platform, subject)
            spent = self._spent.get(key, CostVector.zero())
            if (spent + request.cost).eps(self.delta) > self.caps[subject] + 1e-12:
                self.rejections = getattr(self, "rejections", 0) + 1
                return _deny(request, "exact_cap")
        return _allow(request, request.cost, "exact_ok")

    def finish(self, decision: Decision, now: float) -> None:
        if not decision.allowed:
            return
        for subject in decision.request.subjects:
            key = (decision.request.platform, subject)
            spent = self._spent.get(key, CostVector.zero())
            self._spent[key] = spent + decision.charged

    def abort(self, decision: Decision, now: float) -> None:
        return None

    def tick(self, now: float) -> None:
        return None

    def stats(self) -> dict[str, float]:
        return {
            "policy_rejections": float(getattr(self, "rejections", 0)),
            "tracked_keys": float(len(self._spent)),
        }


@dataclass
class ExactGlobalPolicy:
    """Exact accounting with a shared cross-platform ledger.

    This is the accuracy ceiling of PrivFuse: it never over-shoots and never
    under-shoots, but it keeps one entry per subject and therefore does not
    scale to the populations a marketplace actually sees.
    """

    caps: dict[str, float]
    delta: float = 1e-5
    name: str = "exact_global"

    def __post_init__(self) -> None:
        self._costs: dict[str, CostVector] = {}
        self.rejections = 0

    def begin(self, request: QueryRequest) -> Decision:
        for subject in request.subjects:
            spent = self._costs.get(subject, CostVector.zero())
            if (spent + request.cost).eps(self.delta) > self.caps[subject] + 1e-12:
                self.rejections += 1
                return _deny(request, "exact_global_cap")
        return _allow(request, request.cost, "exact_global_ok")

    def finish(self, decision: Decision, now: float) -> None:
        if not decision.allowed:
            return
        for subject in decision.request.subjects:
            self._costs[subject] = self._costs.get(subject, CostVector.zero()) + decision.charged

    def abort(self, decision: Decision, now: float) -> None:
        return None

    def tick(self, now: float) -> None:
        return None

    def stats(self) -> dict[str, float]:
        return {
            "policy_rejections": float(self.rejections),
            "tracked_subjects": float(len(self._costs)),
            "bytes": float(256 * len(self._costs)),
        }
