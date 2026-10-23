"""Admission control.

Every request is priced, checked against the subject's remaining budget and the
tenant's SLO state, and only then either admitted, degraded or rejected.  The
decision happens before execution so that rejected work never touches data and
never consumes budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from privfuse.accounting.online import OnlineAccountant
from privfuse.control.breaker import BreakerConfig, BreakerController, BreakerLevel
from privfuse.dp.cost import CostVector
from privfuse.ledger.ledger import Coordinator
from privfuse.slo.spec import SLOSpec


@dataclass(frozen=True)
class QueryRequest:
    request_id: str
    tenant: str
    platform: str
    subjects: tuple[str, ...]
    cost: CostVector
    purpose: str = "analytics"
    timestamp: float = 0.0
    utility: float = 1.0

    def cost_by_subject(self) -> dict[str, CostVector]:
        return {subject: self.cost for subject in self.subjects}


@dataclass
class Decision:
    request: QueryRequest
    allowed: bool
    level: BreakerLevel
    charged: CostVector
    reason: str
    utility_loss: float = 0.0
    pressure: float = 0.0

    @property
    def degraded(self) -> bool:
        return self.allowed and self.utility_loss > 0


@dataclass
class AdmissionConfig:
    degrade_factor: float = 0.5
    degrade_utility_loss: float = 0.3
    window: float | None = None


class CostPredictor:
    """Turns a query plan into a conservative privacy cost.

    The predictor is deliberately simple: it maps a declared sensitivity and a
    target epsilon onto a Gaussian cost.  Over-estimating is safe (it triggers
    the breaker early), under-estimating is not, so callers are expected to pass
    the sensitivity upper bound rather than a point estimate.
    """

    def __init__(self) -> None:
        pass

    def predict(self, sensitivity: float, epsilon: float, delta: float = 1e-5) -> CostVector:
        from privfuse.dp.mechanisms import gaussian_cost

        return gaussian_cost(epsilon=epsilon, delta=delta, sensitivity=sensitivity)


class AdmissionController:
    def __init__(
        self,
        accountant: OnlineAccountant,
        coordinator: Coordinator,
        spec: SLOSpec,
        breaker: BreakerController | None = None,
        config: AdmissionConfig | None = None,
    ) -> None:
        self.accountant = accountant
        self.coordinator = coordinator
        self.spec = spec
        self.breaker = breaker or BreakerController(BreakerConfig())
        self.config = config or AdmissionConfig(window=spec.window)
        self.counters = {
            "admitted": 0,
            "degraded": 0,
            "rejected": 0,
            "frozen": 0,
            "evaluations": 0,
        }
        self._tenant_map: dict[str, float] = {}
        self._tenant_stamp = -10**9
        self._tenant_refresh = 64
        self._subject_tenant: dict[str, str] = {}

    def _subject_pressure(self, subject: str, now: float) -> float:
        """Pressure against the cumulative hard cap.

        The hard cap is cumulative by definition, so this path deliberately
        reads the cumulative sketch rather than the epoch ring.  The windowed
        SLO is evaluated separately, at tenant granularity, because it is a
        rate constraint over a population rather than a per-request bound.
        """
        return (
            self.accountant.upper_bound_eps(subject, self.spec.delta, now=now, window=None)
            / self.spec.hard_cap
        )

    def _refresh_tenant_pressure(self, now: float) -> None:
        evals = self.counters["evaluations"]
        if evals - self._tenant_stamp < self._tenant_refresh:
            return
        self._tenant_stamp = evals
        totals: dict[str, list[int]] = {}
        for subject, cost in self.accountant.hot_estimates(
            now=now, window=self.config.window
        ):
            tenant = self._subject_tenant.get(subject, "*")
            bucket = totals.setdefault(tenant, [0, 0])
            bucket[0] += 1
            if cost.eps(self.spec.delta) > self.spec.soft_budget:
                bucket[1] += 1
        rate = self.spec.violation_rate
        refreshed: dict[str, float] = {}
        for tenant, (total, violating) in totals.items():
            observed = violating / total if total else 0.0
            if rate <= 0:
                refreshed[tenant] = 1.0 if observed > 0 else 0.0
            else:
                refreshed[tenant] = min(1.0, observed / rate)
        refreshed["*"] = max(refreshed.values(), default=0.0)
        self._tenant_map = refreshed

    def _tenant_pressure(self, tenant: str, now: float) -> float:
        self._refresh_tenant_pressure(now)
        return self._tenant_map.get(tenant, self._tenant_map.get("*", 0.0))

    def evaluate(self, request: QueryRequest) -> Decision:
        now = request.timestamp
        self.counters["evaluations"] += 1
        level = BreakerLevel.NORMAL
        pressure = 0.0
        for subject in request.subjects:
            subject_pressure = self._subject_pressure(subject, now)
            pressure = max(pressure, subject_pressure)
            level = max(level, self.breaker.update(subject, subject_pressure))
        tenant_key = f"tenant::{request.tenant}"
        tenant_pressure = self._tenant_pressure(request.tenant, now)
        level = max(level, self.breaker.update(tenant_key, tenant_pressure))

        if level >= BreakerLevel.REJECT:
            if level >= BreakerLevel.FREEZE:
                self.counters["frozen"] += 1
            self.counters["rejected"] += 1
            return Decision(
                request=request,
                allowed=False,
                level=level,
                charged=CostVector.zero(),
                reason=f"breaker_{level.label}",
                pressure=pressure,
            )

        if level is BreakerLevel.THROTTLE:
            charged = request.cost.scale(self.config.degrade_factor)
            ok, reason = self.coordinator.try_reserve(
                request.request_id,
                request.tenant,
                request.platform,
                {subject: charged for subject in request.subjects},
                now=now,
            )
            if not ok:
                self.counters["rejected"] += 1
                return Decision(
                    request=request,
                    allowed=False,
                    level=BreakerLevel.REJECT,
                    charged=CostVector.zero(),
                    reason=reason,
                    pressure=pressure,
                )
            self.counters["degraded"] += 1
            return Decision(
                request=request,
                allowed=True,
                level=level,
                charged=charged,
                reason="degraded",
                utility_loss=self.config.degrade_utility_loss,
                pressure=pressure,
            )

        ok, reason = self.coordinator.try_reserve(
            request.request_id,
            request.tenant,
            request.platform,
            request.cost_by_subject(),
            now=now,
        )
        if not ok:
            self.counters["rejected"] += 1
            return Decision(
                request=request,
                allowed=False,
                level=BreakerLevel.REJECT,
                charged=CostVector.zero(),
                reason=reason,
                pressure=pressure,
            )
        self.counters["admitted"] += 1
        return Decision(
            request=request,
            allowed=True,
            level=level,
            charged=request.cost,
            reason="admitted",
            pressure=pressure,
        )

    def complete(self, decision: Decision, now: float = 0.0) -> None:
        """Commit the reserved budget and publish the cost to the accountant."""
        if not decision.allowed:
            return
        self.coordinator.commit(decision.request.request_id, now=now)
        for subject in decision.request.subjects:
            self.accountant.observe(subject, decision.charged, now=now)
            self._subject_tenant[subject] = decision.request.tenant

    def abort(self, decision: Decision, now: float = 0.0) -> None:
        if decision.allowed:
            self.coordinator.release(decision.request.request_id, now=now)

    def stats(self) -> dict[str, float]:
        merged = {k: float(v) for k, v in self.counters.items()}
        merged["flaps"] = float(self.breaker.total_flaps())
        return merged
