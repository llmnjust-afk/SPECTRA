"""E18: a closed-loop attacker that reacts to the admission decision.

E4 and E15 attack with a fixed plan: k identities, k fragments, no feedback. A
real tenant sees whether a fragment was admitted and can re-plan, so the honest
question is whether observability buys anything. This experiment gives the
attacker the decision stream and three strategies:

``round_robin``  open loop, the E4 baseline: cycle identities, fixed fragment
``probe``        halve the fragment after a refusal, grow it back slowly after an
                 admission, retire an identity after three consecutive refusals
``cooling``      maximise dispersion: always use the identity that has been idle
                 longest, so no identity is charged twice in quick succession

Every strategy attacks one subject whose cap is one epsilon and runs a fixed
number of attempts across all tenants and platforms, since a tenant that can mint
identities is the threat model the paper assumes. The measured quantity is the composed
privacy loss actually charged, converted to epsilon at the run's delta and divided
by the cap, plus the sum of marginal epsilons so the numbers stay comparable with
E4's fragment counts.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from privfuse.baselines import (
    AuditOnlyPolicy,
    ExactBlockingPolicy,
    ExactGlobalPolicy,
    StaticQuotaPolicy,
    TokenBucketPolicy,
)
from privfuse.control.admission import QueryRequest
from privfuse.dp.cost import CostVector
from privfuse.dp.mechanisms import gaussian_cost
from privfuse.experiments.common import write_csv, write_json
from privfuse.factory import build_privfuse
from privfuse.trace.generator import EPS_DELTA

CAP = 1.0
FRAGMENT = 0.30
ATTEMPTS = 1200
SEEDS = (0, 1, 2)
N_TENANTS = 40
PLATFORMS = ("p0", "p1", "p2")
SUBJECT = "attack-subject"
POLICIES = ("privfuse", "exact_blocking", "static_quota", "token_bucket", "audit_only", "exact_global")


def _build(name: str, caps: dict[str, float]) -> Any:
    if name == "privfuse":
        trace = SimpleNamespace(
            caps=caps,
            config=SimpleNamespace(cap_eps=CAP, n_platforms=len(PLATFORMS)),
        )
        return build_privfuse(trace)
    if name == "exact_blocking":
        return ExactBlockingPolicy(caps=caps)
    if name == "static_quota":
        return StaticQuotaPolicy(caps=caps)
    if name == "token_bucket":
        return TokenBucketPolicy(caps=caps)
    if name == "audit_only":
        return AuditOnlyPolicy(caps=caps)
    return ExactGlobalPolicy(caps=caps)


def _request(index: int, tenant: str, platform: str, eps: float, timestamp: float) -> QueryRequest:
    return QueryRequest(
        request_id=f"a{index:06d}",
        tenant=tenant,
        platform=platform,
        subjects=(SUBJECT,),
        cost=gaussian_cost(eps, EPS_DELTA, 1.0),
        purpose="attack",
        timestamp=timestamp,
    )


def _run_attack(policy: Any, strategy: str, seed: int) -> dict[str, float]:
    tenants = [f"t{i:03d}" for i in range(N_TENANTS)]
    composed = CostVector.zero()
    marginal = 0.0
    admitted = 0
    refused = 0
    retirements = 0
    last_used = {t: -1 for t in tenants}
    failures = {t: 0 for t in tenants}
    fragment = {t: FRAGMENT for t in tenants}
    retired: set[str] = set()
    index = 0
    rng_state = seed

    for attempt in range(ATTEMPTS):
        if strategy == "round_robin":
            tenant = tenants[attempt % len(tenants)]
        elif strategy == "cooling":
            tenant = min(tenants, key=lambda t: last_used[t])
        else:
            live = [t for t in tenants if t not in retired]
            if not live:
                break
            rng_state = (1103515245 * rng_state + 12345) % (2**31)
            tenant = live[rng_state % len(live)]

        platform = PLATFORMS[(attempt + seed) % len(PLATFORMS)]
        eps = fragment[tenant] if strategy == "probe" else FRAGMENT
        request = _request(index, tenant, platform, eps, float(attempt))
        index += 1
        decision = policy.begin(request)
        if decision.allowed:
            policy.finish(decision, request.timestamp)
            composed = composed + decision.charged
            marginal += decision.charged.eps(EPS_DELTA)
            admitted += 1
            failures[tenant] = 0
            if strategy == "probe":
                fragment[tenant] = min(FRAGMENT, fragment[tenant] * 1.1)
        else:
            refused += 1
            failures[tenant] += 1
            if strategy == "probe":
                fragment[tenant] = max(FRAGMENT / 64.0, fragment[tenant] / 2.0)
                if failures[tenant] >= 3:
                    retired.add(tenant)
                    retirements += 1
        last_used[tenant] = attempt
        policy.tick(request.timestamp)

    return {
        "seed": float(seed),
        "attempts": float(index),
        "admitted": float(admitted),
        "refused": float(refused),
        "retirements": float(retirements),
        "composed_eps": composed.eps(EPS_DELTA),
        "escape_ratio": composed.eps(EPS_DELTA) / CAP,
        "marginal_eps": marginal,
    }


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy in ("round_robin", "probe", "cooling"):
        for name in POLICIES:
            for seed in SEEDS:
                caps = {SUBJECT: CAP}
                policy = _build(name, caps)
                started = time.perf_counter()
                row = _run_attack(policy, strategy, seed)
                row.update(
                    {
                        "strategy": strategy,
                        "policy": name,
                        "fragment": FRAGMENT,
                        "elapsed": time.perf_counter() - started,
                    }
                )
                rows.append(row)
                print(
                    f"{strategy:11s} {name:15s} seed {seed}: "
                    f"escape {row['escape_ratio']:.3f} admitted {int(row['admitted'])} "
                    f"refused {int(row['refused'])}",
                    flush=True,
                )
    write_csv("e18_adaptive_attack", rows)
    write_json(
        "e18_adaptive_attack_meta",
        {
            "cap": CAP,
            "fragment": FRAGMENT,
            "attempts": ATTEMPTS,
            "seeds": list(SEEDS),
            "tenants": N_TENANTS,
            "platforms": list(PLATFORMS),
            "strategies": ["round_robin", "probe", "cooling"],
            "policies": list(POLICIES),
        },
    )
    return rows


if __name__ == "__main__":
    run()
