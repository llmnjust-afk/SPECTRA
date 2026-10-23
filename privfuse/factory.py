"""Assemble a PrivFuse deployment from a trace configuration."""

from __future__ import annotations

from dataclasses import dataclass

from privfuse.accounting.online import (
    OnlineAccountant,
    OnlineAccountantConfig,
    ring_epochs_for,
)
from privfuse.control.admission import AdmissionConfig, AdmissionController
from privfuse.control.breaker import BreakerConfig, BreakerController
from privfuse.ledger.durable import DurableLedger
from privfuse.ledger.ledger import Coordinator
from privfuse.platform.policy import PrivFusePolicy
from privfuse.slo.spec import SLOSpec
from privfuse.trace.generator import EPS_DELTA, Trace


@dataclass
class PrivFuseConfig:
    width: int = 1 << 14
    depth: int = 4
    hot_capacity: int = 1024
    epoch_seconds: float = 300.0
    ring_size: int = 2
    window: float | None = 600.0
    soft_ratio: float = 0.8
    violation_rate: float = 0.01
    throttle_ratio: float = 0.60
    reject_ratio: float = 0.85
    hysteresis: float = 0.05
    dwell: int = 3
    degrade_factor: float = 0.5
    degrade_utility_loss: float = 0.3
    ttl: float = 30.0
    use_hot: bool = True
    exact: bool = False
    wal_path: str | None = None


def build_privfuse(
    trace: Trace,
    config: PrivFuseConfig | None = None,
    delta: float = EPS_DELTA,
) -> PrivFusePolicy:
    cfg = config or PrivFuseConfig()
    cap = float(trace.config.cap_eps)
    spec = SLOSpec(
        name="market",
        hard_cap=cap,
        soft_budget=cfg.soft_ratio * cap,
        violation_rate=cfg.violation_rate,
        window=cfg.window,
        delta=delta,
    )
    ring_size = cfg.ring_size
    if cfg.window is not None:
        ring_size = max(ring_size, ring_epochs_for(cfg.window, cfg.epoch_seconds))
    accountant = OnlineAccountant(
        OnlineAccountantConfig(
            width=cfg.width,
            depth=cfg.depth,
            hot_capacity=cfg.hot_capacity if cfg.use_hot else 1,
            epoch_seconds=cfg.epoch_seconds,
            ring_size=ring_size,
            exact=cfg.exact,
        )
    )
    ledger = (
        DurableLedger(cfg.wal_path, ttl=cfg.ttl, delta=delta)
        if cfg.wal_path
        else None
    )
    coordinator = Coordinator(caps=trace.caps, ttl=cfg.ttl, delta=delta, ledger=ledger)
    breaker = BreakerController(
        BreakerConfig(
            throttle_ratio=cfg.throttle_ratio,
            reject_ratio=cfg.reject_ratio,
            hysteresis=cfg.hysteresis,
            dwell=cfg.dwell,
        )
    )
    controller = AdmissionController(
        accountant=accountant,
        coordinator=coordinator,
        spec=spec,
        breaker=breaker,
        config=AdmissionConfig(
            degrade_factor=cfg.degrade_factor,
            degrade_utility_loss=cfg.degrade_utility_loss,
            window=cfg.window,
        ),
    )
    if cfg.wal_path:
        controller.recover()
    return PrivFusePolicy(controller)
