"""Hysteresis circuit breaker.

Escalation is immediate; de-escalation requires the pressure to fall below the
triggering threshold by a margin and to stay there for ``dwell`` consecutive
evaluations.  The margin is what prevents the breaker from oscillating when the
arrival process hovers around a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class BreakerLevel(IntEnum):
    NORMAL = 0
    THROTTLE = 1
    REJECT = 2
    FREEZE = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class BreakerConfig:
    throttle_ratio: float = 0.60
    reject_ratio: float = 0.85
    freeze_ratio: float = 1.00
    hysteresis: float = 0.05
    dwell: int = 3

    def __post_init__(self) -> None:
        if not (0 < self.throttle_ratio < self.reject_ratio <= self.freeze_ratio):
            raise ValueError("thresholds must be strictly increasing")
        if self.hysteresis < 0:
            raise ValueError("hysteresis must be non-negative")
        if self.dwell < 1:
            raise ValueError("dwell must be at least 1")


@dataclass
class BreakerState:
    level: BreakerLevel = BreakerLevel.NORMAL
    dwell_count: int = 0
    escalations: int = 0
    deescalations: int = 0
    freezes: int = 0
    last_pressure: float = 0.0

    @property
    def flaps(self) -> int:
        return self.deescalations


class BreakerController:
    """Per-key breaker state machine with hysteresis and dwell."""

    def __init__(self, config: BreakerConfig | None = None) -> None:
        self.config = config or BreakerConfig()
        self._states: dict[str, BreakerState] = {}

    def state(self, key: str) -> BreakerState:
        return self._states.setdefault(key, BreakerState())

    def threshold(self, level: BreakerLevel) -> float:
        cfg = self.config
        return {
            BreakerLevel.NORMAL: 0.0,
            BreakerLevel.THROTTLE: cfg.throttle_ratio,
            BreakerLevel.REJECT: cfg.reject_ratio,
            BreakerLevel.FREEZE: cfg.freeze_ratio,
        }[level]

    def target_level(self, pressure: float) -> BreakerLevel:
        cfg = self.config
        if pressure >= cfg.freeze_ratio:
            return BreakerLevel.FREEZE
        if pressure >= cfg.reject_ratio:
            return BreakerLevel.REJECT
        if pressure >= cfg.throttle_ratio:
            return BreakerLevel.THROTTLE
        return BreakerLevel.NORMAL

    def update(self, key: str, pressure: float) -> BreakerLevel:
        cfg = self.config
        st = self.state(key)
        st.last_pressure = pressure
        target = self.target_level(pressure)

        if target > st.level:
            if target >= BreakerLevel.FREEZE:
                st.freezes += 1
            st.level = target
            st.escalations += 1
            st.dwell_count = 0
            return st.level

        if target < st.level:
            release = self.threshold(st.level) - cfg.hysteresis
            if pressure < release:
                st.dwell_count += 1
                if st.dwell_count >= cfg.dwell:
                    st.level = BreakerLevel(st.level - 1)
                    st.deescalations += 1
                    st.dwell_count = 0
            else:
                st.dwell_count = 0
            return st.level

        st.dwell_count = 0
        return st.level

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {
            key: {
                "level": float(st.level),
                "escalations": float(st.escalations),
                "deescalations": float(st.deescalations),
                "freezes": float(st.freezes),
                "last_pressure": st.last_pressure,
            }
            for key, st in self._states.items()
        }

    def total_flaps(self) -> int:
        return sum(st.flaps for st in self._states.values())
