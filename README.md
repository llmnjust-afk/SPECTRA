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
| Experiments E1–E8 + figures | implemented, reproducible |
| Hyperledger Fabric chaincode | interface defined, not implemented |
| TEE execution layer | interface defined, not implemented |
| zkSNARK compliance proofs | interface defined, not implemented |

36 unit and property tests pass. The core suite runs in about 65 seconds on two cores; the scale
sweep to one million subjects (E8) takes another 90 seconds.

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

**Cross-platform budget splitting (E4).** Twelve subjects are attacked through
42 small requests spread over three platforms. Platform-local policies admit all
of them and reach 2.01x the cap; PrivFuse rejects the excess and stays at 0.81x.
Every baseline violates on twelve of twelve attacked subjects; PrivFuse violates
on none, at every split count tested.

| policy | realised ε / cap (42 splits) | violating subjects |
|---|---|---|
| audit-only | 2.01 | 12 |
| token bucket | 2.01 | 12 |
| exact per-platform | 1.69 | 12 |
| static quota | 1.30 | 12 |
| **PrivFuse** | **0.81** | **0** |
| exact global | 0.97 | 0 |

**Accounting accuracy (E1).** Zero false negatives at every sketch width and
every hot-table size. The top 1 percent of subjects — the only ones that can
reach the cap — are off by 0.13% of the cap with the hot table, against 0.76% to
8.1% without it. Mean absolute error over all subjects falls from 0.073 (7.3% of
the cap) at width 512 to below 1e-4 at width 32768.

**Overhead (E2).** 27 µs per request at width 16384 against 4.8 µs for an exact
dictionary, in pure Python, with 5.6 MB of state for 5,000 subjects.

**Scale (E8).** The point of a sketch is that its state stops growing. Sweeping
the population from one thousand to one million subjects, the exact accountant
grows from 1.1 MB to 265 MB while the sketch stays at 4.7 MB (width 4096) or
6.3 MB (width 16384). The crossover is around ten thousand subjects; below it,
an exact dictionary is smaller and there is no reason to sketch. Absolute error
stays bounded at about 0.06 in ε across four orders of magnitude, and no subject
is ever under-estimated.

**Price of soundness (E3).** At a cap of 1.0 PrivFuse keeps 94.2% availability
while local policies keep 97.0% and 97.7% and violate the cap 63 times over the sweep.
The two to three points of availability are what soundness costs; a policy that never
rejects will always look better on that axis.

**SLO frontier (E5).** Raising the soft budget from 0.55 to 0.95 of the cap
moves availability from 82.9% to 88.5% and the soft-violation rate from 1.9% to
zero, with no hard-cap violation at any point.

**Hysteresis (E7).** Under pressure oscillating between 0.59 and 0.67, a breaker
without hysteresis changes level 26 times in 600 evaluations; with a 0.05 margin
and dwell of 3 it changes level zero times.

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

## License

MIT.
