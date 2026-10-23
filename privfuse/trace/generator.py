"""Synthetic request traces for the market simulator.

Traces are heavy-tailed on purpose: a small set of subjects absorbs most of the
demand, which is exactly the regime where a per-subject cap binds and where an
approximate accountant has to stay conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from privfuse.control.admission import QueryRequest
from privfuse.dp.mechanisms import gaussian_cost

EPS_DELTA = 1e-5


@dataclass
class TraceConfig:
    n_subjects: int = 1500
    n_tenants: int = 40
    n_requests: int = 12000
    duration: float = 3600.0
    zipf_alpha: float = 1.15
    multi_subject_prob: float = 0.15
    max_subjects_per_request: int = 5
    epsilon_mean: float = 0.02
    epsilon_sigma: float = 0.6
    sensitivity: float = 1.0
    cap_eps: float = 1.0
    n_platforms: int = 3
    attack: str | None = None
    attack_subjects: int = 12
    attack_splits: int = 42
    attack_epsilon: float = 0.30
    seed: int = 0


@dataclass
class Trace:
    requests: list[QueryRequest]
    caps: dict[str, float]
    subjects: list[str]
    config: TraceConfig
    attack_subjects: list[str] = field(default_factory=list)


def _subject_names(n: int) -> list[str]:
    return [f"s{i:06d}" for i in range(n)]


def _zipf_subjects(
    rng: np.random.Generator, n_subjects: int, size: int, alpha: float
) -> np.ndarray:
    """Draw subject ranks from a truncated Zipf law over 1..n.

    `numpy.random.zipf` samples the untruncated law, and for alpha below 2 the
    draws overflow into the 10^15 range; reducing those modulo the population
    turns the tail into uniform noise and leaves a single artificial giant at
    rank zero. Sampling the truncated law by inverse CDF keeps the intended
    shape: a smooth head, a long tail, and no rank that dominates by accident.
    """
    ranks = np.arange(1.0, n_subjects + 1.0)
    weights = ranks ** (-alpha)
    cdf = np.cumsum(weights)
    cdf /= cdf[-1]
    u = rng.random(size=size)
    return np.clip(np.searchsorted(cdf, u), 0, n_subjects - 1)


def generate_trace(config: TraceConfig | None = None) -> Trace:
    cfg = config or TraceConfig()
    rng = np.random.default_rng(cfg.seed)
    subjects = _subject_names(cfg.n_subjects)
    caps = {s: float(cfg.cap_eps) for s in subjects}
    platforms = [f"p{i}" for i in range(cfg.n_platforms)]
    tenants = [f"t{i:03d}" for i in range(cfg.n_tenants)]

    index = _zipf_subjects(rng, cfg.n_subjects, cfg.n_requests, cfg.zipf_alpha)
    epsilons = rng.lognormal(
        mean=np.log(cfg.epsilon_mean), sigma=cfg.epsilon_sigma, size=cfg.n_requests
    )
    timestamps = np.sort(rng.uniform(0.0, cfg.duration, size=cfg.n_requests))

    requests: list[QueryRequest] = []
    for i in range(cfg.n_requests):
        primary = subjects[int(index[i])]
        targets = [primary]
        if rng.random() < cfg.multi_subject_prob:
            extra = rng.integers(1, cfg.max_subjects_per_request)
            for _ in range(int(extra)):
                candidate = subjects[int(rng.integers(0, cfg.n_subjects))]
                if candidate not in targets:
                    targets.append(candidate)
        cost = gaussian_cost(
            epsilon=float(epsilons[i]),
            delta=EPS_DELTA,
            sensitivity=cfg.sensitivity,
        )
        requests.append(
            QueryRequest(
                request_id=f"r{i:07d}",
                tenant=tenants[int(rng.integers(0, cfg.n_tenants))],
                platform=platforms[int(rng.integers(0, len(platforms)))],
                subjects=tuple(targets),
                cost=cost,
                timestamp=float(timestamps[i]),
            )
        )

    attack_subjects: list[str] = []
    if cfg.attack == "split":
        attack_subjects = subjects[-cfg.attack_subjects :]
        attack_cost = gaussian_cost(cfg.attack_epsilon, EPS_DELTA, cfg.sensitivity)
        next_id = len(requests)
        attack: list[QueryRequest] = []
        for subject in attack_subjects:
            for k in range(cfg.attack_splits):
                attack.append(
                    QueryRequest(
                        request_id=f"a{next_id:07d}",
                        tenant=tenants[k % len(tenants)],
                        platform=platforms[k % len(platforms)],
                        subjects=(subject,),
                        cost=attack_cost,
                        purpose="attack",
                        timestamp=cfg.duration * 0.5 + k * (cfg.duration * 0.4 / cfg.attack_splits),
                    )
                )
                next_id += 1
        requests.extend(attack)
        requests.sort(key=lambda r: r.timestamp)

    return Trace(
        requests=requests,
        caps=caps,
        subjects=subjects,
        config=cfg,
        attack_subjects=attack_subjects,
    )
