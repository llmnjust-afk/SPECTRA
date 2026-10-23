# PrivFuse

**Runtime privacy SLOs for multi-tenant data trading systems.**

Data marketplaces check privacy *after* the fact: a query is executed, the result
leaves the platform, and an auditor later discovers that some subject's budget was
overshot. PrivFuse moves the check to admission time. Every request is priced,
checked against a per-subject budget that is shared across platforms, and either
admitted, degraded, or rejected *before* it touches data.

The technical enabler is a small observation: privacy composition is additive in
its accounting domain, and the Count-Min sketch's error is one-sided. Those two
facts line up. A sketch that only ever over-estimates cannot hide an overdraft —
it can only make the breaker more conservative.

This repository is a reference implementation, a simulator, and the experiment
suite behind the paper. Everything runs on CPU; no GPU is required.

## Status

| Item | State |
|---|---|
| zCDP cost algebra + composition | implemented, tested |
| One-sided streaming accountant | implemented, tested |
| SLO specification and evaluation | implemented, tested |
| Hysteresis circuit breaker | implemented, tested |
| Two-phase settlement ledger + cross-platform coordinator | implemented, tested |
| Market simulator and baselines | implemented, tested |
| Experiments E1–E12 + figures | implemented, reproducible |
| Thread-safe settlement | implemented, tested |
| Hyperledger Fabric chaincode | interface defined, not implemented |
| TEE execution layer | interface defined, not implemented |
| zkSNARK compliance proofs | interface defined, not implemented |

37 unit and property tests pass. The core suite E1–E7 and E9–E12 runs in about four minutes on two cores;
the scale sweep to one million subjects (E8) takes another 90 seconds.

## Quickstart

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
python3 -m privfuse.cli demo --requests 2000
python3 -m privfuse.experiments.run_all
python3 -m privfuse.experiments.e8_scale     # the long sweep, ~90 s
```

`run_all` writes `results/*.csv`, `results/*.json` and `results/figures/*.png`.

## How it fits together

```
 request ──► admission ──► breaker ──► reserve ──► execute ──► commit ──► observe
                │            │          │                        │         │
                │            │          │                        │         └─ online accountant
                │            │          │                        └─ ledger (2PC)
                │            │          └─ cross-platform coordinator
                │            └─ per-subject + per-tenant state machine
                └─ cost prediction from sensitivity
```

| Module | Responsibility |
|---|---|
| `privfuse.dp` | `CostVector` (pure ε plus zCDP ρ), Gaussian/Laplace calibration, exact accountant |
| `privfuse.sketch` | additive Count-Min, Space-Saving, vector-valued `CostSketch`, bounded hot table |
| `privfuse.accounting` | cumulative + epoch-ring online accountant |
| `privfuse.slo` | `(E, p, W)` SLO specification and evaluation |
| `privfuse.control` | admission controller, hysteresis breaker, degradation policy |
| `privfuse.ledger` | reserve/commit/release ledger, coordinator, idempotency |
| `privfuse.platform` | trading platform, market harness, ground-truth bookkeeping |
| `privfuse.baselines` | static quota, token bucket, audit-only, exact blocking |
| `privfuse.experiments` | E1–E7 runners, figure builders |
| `privfuse.trace` | heavy-tailed synthetic request traces |

## Why zCDP rather than a Rényi grid

The accountant needs to compose thousands of small Gaussian charges and convert
back at `delta = 1e-5`. With a fixed grid of Rényi orders, the conversion error
has a floor: the smallest representable epsilon is `log(1/delta)/(alpha_max - 1)`.
For `epsilon = 0.02` that floor sits at 0.0225 with orders up to 512, so every
transaction is silently over-charged and the calibration loop cannot reach its
target.

zCDP removes the floor. `rho = sensitivity^2 / (2 sigma^2)` is additive under
composition and converts with `eps = rho + 2 sqrt(rho log(1/delta))`, which
inverts in closed form. A single Gaussian charge calibrated for `(0.02, 1e-5)`
comes back as exactly 0.02, and a hundred of them compose to 0.2008 rather than
the vacuous 2.0 of basic composition.

## What the experiments show

Every number below is a three-seed mean unless stated otherwise; wall-clock
figures are single-machine and machine-dependent.

**Cross-platform budget splitting (E4).** Twelve subjects are attacked through
42 small requests spread over three platforms. Platform-local policies admit all
of them and reach 2.02x the cap; PrivFuse rejects the excess and stays at 0.82x.

| policy | realised ε / cap (42 splits) | violating subjects |
|---|---|---|
| audit-only | 2.02 | 12.3 |
| token bucket | 2.02 | 12.3 |
| exact per-platform | 1.69 | 12.3 |
| static quota | 1.30 | 12.3 |
| **PrivFuse** | **0.82** | **0** |
| exact global | 0.98 | 0 |

**Accounting accuracy (E1).** Zero false negatives in all 24 configurations.
The top 1 percent of subjects — the only ones that can reach the cap — are off
by 0.02% of the cap with the hot table, against 4.3% without it at width 512.
Mean absolute error over all subjects falls from 0.071 (7.1% of the cap) at
width 512 to zero at width 32768.

**Overhead (E2).** 32 µs per request at width 16384 against 4.6 µs for an exact
dictionary, in pure Python, with 5.6 MB of state for 5,000 subjects.

**Scale (E8).** The point of a sketch is that its state stops growing. Sweeping
the population from one thousand to one million subjects, the exact accountant
grows from 1.1 MB to 264.6 MB while the sketch stays at 4.7 MB (width 4096) or
6.3 MB (width 16384). The crossover is around ten thousand subjects; below it an
exact dictionary is smaller and there is no reason to sketch. Absolute error
stays bounded at about 0.06 in ε across four orders of magnitude, and no subject
is ever under-estimated.

**Price of soundness (E3).** At a cap of 1.0 PrivFuse keeps 93.3% availability
while exact per-platform accounting keeps 97.8% and static quota 95.6%; both
violate on 12.7 of the 12 attacked subjects' cohorts. The gap widens as the cap
tightens: 75.4% against 88.9% at cap 0.5, where the attack has the most room.

**Sensitivity (E9).** Eighteen one-factor perturbations — δ from 1e-6 to 1e-4,
hot capacity 64 to 4096, platforms 1 to 6, crash probability 0 to 5%, Zipf
skew 0.9 to 1.5, tenants 5 to 200 — and PrivFuse violates on none of them. The
single exception in the baseline is instructive: with one platform, static quota
also reaches zero violations, which is exactly what the mechanism predicts,
since there is nowhere to split the budget. Availability falls to 78.3% under
the most concentrated trace (α = 1.5), because a subject that consumes 20% of
all traffic exhausts its cap within the first minutes.

**Composition backend (E10).** Three accountants, same charges:

| target ε | 100 charges: zCDP | RDP grid | basic |
|---|---|---|---|
| 0.02 | 0.2008 | *cannot calibrate* | 2.00 |
| 0.1 | 1.0195 | 1.0194 | 10.00 |
| 0.5 | 5.4783 | 5.4785 | 50.00 |

Where a Rényi grid can represent the budget, it matches zCDP to four decimals;
zCDP is not tighter, it is *calibratable*. The grid's floor is
`log(1/δ)/(α_max-1) = 0.0225` at δ = 1e-5, so a 0.02 target is unreachable: the
calibration loop saturates, picks at least 4x more noise than necessary, and
still cannot certify the target.

**Utility on real data (E11).** Breast-cancer classification from noisy
class-conditional statistics, three seeds. Under a cap of 1.0:

| ε per release | queries admitted | accuracy | unbounded accuracy (ε spent) |
|---|---|---|---|
| 0.25 | 4 | 0.54 | 0.87 (25) |
| 0.5 | 2 | 0.55 | 0.88 (50) |
| 1.0 | 1 | 0.82 | 0.90 (100) |

Splitting a fixed budget into many cheap releases is worse than spending it on
fewer, better-noised ones — the same concavity that makes composition tight.

**Concurrency (E12).** Sixteen threads racing for one subject's budget with 3,200
attempts admit exactly the 100 that fit, at every thread count, with no
overshoot. Throughput is 77k reservations/s single-threaded and falls to 51k at
four threads (98k to 41k with a single global lock): the prototype is bound by
the interpreter, not by the protocol, and the paper reports it as such.

## Scope and non-goals

This is the algorithmic core, not the deployment. Three pieces are deliberately
left as interfaces because they need hardware or a ledger that a laptop cannot
provide:

* **Fabric chaincode** (`privfuse.ledger.backend`) — the ledger semantics are
  implemented and tested in memory; the chaincode wrapper is not.
* **TEE attestation** (`privfuse.platform.attestation`) — the breaker does not
  depend on it, so its absence changes no result in this repository.
* **zkSNARK compliance proofs** — the accounting is checked by re-execution and
  sampling, not by succinct proofs.

Nothing here claims a differential-privacy guarantee for a *query engine*. The
cost vectors are inputs; calibrating a real engine's sensitivity is the caller's
job. What is proven is narrower and honest: given certified per-request costs,
the accountant never under-estimates, so the cap is never silently exceeded.

## Reproducing the paper numbers

```bash
python3 -m privfuse.experiments.run_all          # core suite
python3 -m privfuse.experiments.e8_scale         # scale sweep
python3 -m privfuse.cli run e4 --figures         # one experiment
python3 -m privfuse.cli figures                  # rebuild figures only
```

All randomness is seeded. Wall-clock numbers will differ by machine; the
violation counts and epsilon ratios will not.

## Paper

The manuscript is in `paper/` (IEEEtran conference format, 10 pages of body
plus references). Sources are `paper/main.tex` plus one file per section under
`paper/sections/`, with the bibliography in `paper/refs.bib`.

```bash
cd paper && make pdf        # latexmk -pdf main.tex
```

Numbered claims in the paper map to `results/*.csv` through `docs/experiments.md`.

## License

MIT.
