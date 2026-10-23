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


@dataclass
class ExactWindowedPolicy:
    """Exact per-subject accounting over a sliding window.

    This is the strongest tabulation baseline: it keeps the full event log per
    subject, so its windowed estimate is exact and it can express a windowed
    SLO without a sketch.  It is the honest competitor to a windowed accountant
    at small populations, and the wrong structure at large ones, because its
    memory grows with the number of events inside the window rather than with
    the number of subjects.

    Admission is stateless apart from the log: a request whose projected
    windowed spend would cross the hard cap is refused, and one that would
    cross the soft budget is degraded by the same factor PrivFuse uses.
    """

    caps: dict[str, float]
    window: float = 600.0
    delta: float = 1e-5
    soft_ratio: float = 0.8
    degrade_factor: float = 0.5
    degrade_utility_loss: float = 0.3
    name: str = "exact_windowed"

    def __post_init__(self) -> None:
        self._events: dict[str, list[tuple[float, CostVector]]] = {}
        self.rejections = 0
        self.degraded = 0
        self._bytes_per_event = 256

    def _windowed(self, subject: str, now: float) -> CostVector:
        events = self._events.get(subject)
        if not events:
            return CostVector.zero()
        cut = now - self.window
        keep = [e for e in events if e[0] > cut]
        if len(keep) != len(events):
            self._events[subject] = keep
        total = CostVector.zero()
        for _, cost in keep:
            total = total + cost
        return total

    def begin(self, request: QueryRequest) -> Decision:
        now = request.timestamp
        projections = []
        for subject in request.subjects:
            spent = self._windowed(subject, now)
            hard = self.caps[subject]
            if (spent + request.cost).eps(self.delta) > hard + 1e-12:
                self.rejections += 1
                return _deny(request, "exact_windowed_cap")
            projections.append((spent, hard))
        if any(
            (spent + request.cost).eps(self.delta) > self.soft_ratio * hard
            for spent, hard in projections
        ):
            charged = request.cost.scale(self.degrade_factor)
            self.degraded += 1
            decision = _allow(request, charged, "exact_windowed_degraded")
            decision.utility_loss = self.degrade_utility_loss
            return decision
        return _allow(request, request.cost, "exact_windowed_ok")

    def finish(self, decision: Decision, now: float) -> None:
        if not decision.allowed:
            return
        for subject in decision.request.subjects:
            self._events.setdefault(subject, []).append((now, decision.charged))

    def abort(self, decision: Decision, now: float) -> None:
        return None

    def tick(self, now: float) -> None:
        return None

    def stats(self) -> dict[str, float]:
        events = sum(len(v) for v in self._events.values())
        return {
            "policy_rejections": float(self.rejections),
            "policy_degraded": float(self.degraded),
            "tracked_subjects": float(len(self._events)),
            "window_events": float(events),
            "bytes": float(self._bytes_per_event * events),
        }
