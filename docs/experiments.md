# Experiment protocol

All experiments are deterministic given their seeds. Results land in
`results/<name>.csv` with a companion `<name>_meta.json`.

| ID | Question | Runner |
|---|---|---|
| E1 | Does the sketch ever under-estimate? How large is the error? | `e1_accounting` |
| E2 | What does accounting cost per request? | `e2_overhead` |
| E3 | What availability does soundness cost? | `e3_breaker` |
| E4 | Can a tenant beat the cap by splitting across platforms? | `e4_attack` |
| E5 | What is the availability / SLO-violation frontier? | `e5_slo` |
| E6 | Does settlement survive crashes and retries? | `e6_settlement` |
| E7 | Which component contributes what? | `e7_ablation` |
| E8 | Does the state stay bounded as the population grows? | `e8_scale` |

## Common setup

Traces are heavy-tailed: subject demand follows a Zipf law, per-query epsilon is
log-normal, and 15% of requests touch up to five subjects. Defaults are 12,000
requests, 1,500 subjects, cap 1.0 at `delta = 1e-5`. The attack mode appends 42
requests per attacked subject, spread across three platforms.

Ground truth is the exact per-subject composition of every admitted request,
computed independently of the policy. A "violation" means the ground-truth
epsilon exceeds the cap. No experiment trusts the policy's own bookkeeping for
this number.

## E1 — accounting accuracy

Sweep sketch width over `2^9 .. 2^15` with the hot table on and off. Report
false negatives (must be zero), mean and p99 absolute error, and the relative
error over the top 1% of subjects by true epsilon — the population that can
actually reach the cap.

## E2 — overhead

Microbenchmark `observe` plus one `upper_bound_eps` against a plain dictionary
for 20,000 operations over 5,000 subjects. Report microseconds per request and
resident bytes.

## E3 — price of soundness

Sweep the cap from 0.5 to 3.0 on a fixed attack trace. Compare PrivFuse, exact
per-platform accounting, and static quota on availability, violations, and the
realised epsilon / cap ratio. The interesting region is where the cap binds.

## E4 — budget splitting

Sweep requests per attacked subject from 12 to 60, over three seeds. Report the
realised epsilon / cap ratio and the number of violating subjects per policy.
`audit_only` and `token_bucket` are the "detect but do not prevent" and
"rate-limit but do not account" controls; `exact_global` is the accuracy ceiling.

## E5 — SLO frontier

Sweep the soft budget ratio and the tolerated violation rate on a high-pressure
trace. Report availability, utility, observed soft-violation rate, and whether
the SLO was met. The soft budget, not the violation rate, is what moves
availability in this workload; the violation rate only binds at 0.05.

## E6 — settlement

Two layers. First, direct ledger checks: idempotent commit, timeout release,
transaction-id binding. Second, a market run in which platform `p1` crashes
between reserve and commit. Assert no double spend, one recovered reservation,
and zero hard-cap violations.

## E7 — ablation

Variants: full system, no hot table, no hysteresis, no degradation, narrow
sketch, wide sketch, and exact global accounting. Report availability, utility,
violations, degraded fraction, memory, and microseconds per request. A separate
micro-benchmark drives the breaker with a sinusoid to isolate hysteresis.

## E8 — scale

Sweep the subject population over 10^3, 10^4, 10^5 and 10^6 while holding the
traffic shape fixed: one thousand heavy subjects with eight requests each, and
every other subject exactly once. Truth is known in closed form, so no second
accountant occupies memory during the measurement. Memory is the peak traced by
`tracemalloc`, not an estimate. Report peak bytes, microseconds per request,
under-estimates (must be zero), and absolute error.

E8 is excluded from `run_all` because the million-subject point takes about a
minute by itself; run it with `make scale`.

## Reading the numbers

* Violation counts are the load-bearing result; wall-clock numbers are
  machine-dependent.
* Availability differences of a few points are the *price* of soundness, not a
  defect. A policy that never rejects will always look better on availability
  and worse on violations.
* E1's mean absolute error is expressed in epsilon units; divide by the cap to
  read it as a fraction of the budget.
