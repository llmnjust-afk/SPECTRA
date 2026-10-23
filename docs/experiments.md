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
| E9 | Does the result survive one-factor perturbation? | `e9_sensitivity` |
| E10 | What does the composition backend cost? | `e10_accountant` |
| E11 | What does the cap cost in downstream accuracy? | `e11_utility` |
| E12 | Is settlement atomic under concurrent platforms? | `e12_concurrency` |

## Common setup

Traces are heavy-tailed: subject demand follows a truncated Zipf law over ranks
(sampled by inverse CDF, not by reducing `numpy.random.zipf` modulo the
population, which flattens the tail into uniform noise), per-query epsilon is
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

## E9 — sensitivity

One factor moves per row; everything else is the default trace with 6,000
requests. Factors: `delta`, `hot_capacity`, `n_platforms`, `crash_probability`,
`zipf_alpha`, `n_tenants`. PrivFuse is compared against static quota at every
point. The point of the sweep is not a new optimum but whether the qualitative
claim (zero violations, bounded availability cost) survives.

## E10 — composition backend

Three accountants on the same Gaussian charges: zCDP, a Rényi-DP accountant over
128 log-spaced orders (2 to 512), and basic composition. Sigma is calibrated by
bisection for each backend and the calibration is checked: a grid whose floor
`log(1/delta)/(alpha_max-1)` exceeds the target cannot reach it, and the run is
flagged rather than silently accepted. Report the reported epsilon at 1, 10 and
100 charges, plus the sigma ratio against zCDP.

## E11 — utility

`sklearn.datasets.load_breast_cancer`, 70/30 stratified split, features min-max
scaled to the unit interval. A release is four Gaussian mechanisms (class-mean
and class-second-moment vectors, L2 sensitivity `sqrt(d)/n`); the tenant repeats
the release and averages the answers, which is the classic
reconstruction-by-averaging pattern. The downstream model is Gaussian naive
Bayes fitted to the noisy statistics, so accuracy is a real number.

Simplifications are stated in the module: class counts are public, the four
mechanisms split the per-release epsilon by basic composition, and totals are
therefore conservative.

## E12 — concurrency

Two measurements. Atomicity: 2 to 16 threads, 200 reservations each, one subject,
one cap; the number admitted must equal `cap / cost` exactly. Throughput: 4,000
disjoint reservations per thread at 1, 2 and 4 threads, with striped per-subject
locks versus a single global lock.

## E13 — settlement scaling

Two measurements of where the settlement path serialises. (a) Disjoint-subject
throughput in one CPython process: 20 000 reservations at 1, 2 and 4 threads, each
subject either shared by every thread or private to one, with striped versus global
locking, repeated three times and reported as the median. (b) Cross-process
settlement: the same coordinator served over loopback TCP and driven by 1, 2 and 4
client processes, recording throughput and the per-operation reserve+commit round
trip (p50, p99).

Part (b) is a two-process loopback measurement, not a multi-node deployment: there
is no consensus, no replication and no persistent ledger backend. The numbers bound
the cost of a remote settlement round trip, nothing more.

## E14 — hot-table churn

The hot table is exact for the subjects it holds, so its accuracy depends on the
traffic staying put. This experiment forces turnover: four epochs, each admitting a
fresh cohort of heavy subjects (0, 100 or 400 per epoch, 40 queries each), against
table capacities 256, 32 and 1 (the last is the sketch-only control). Three seeds,
two caps (1.0 and 0.15 epsilon).

Reported: availability over all decisions, availability over the unchurned base
requests only (the churn requests add load, so the two differ), hard-cap
violations, and the relative over-estimate of the accountant's upper bound against
exact truth, per subject, summarised as mean, p99 and the fraction above 50%.

The expected result is that churn costs accuracy, not safety: an evicted subject is
re-seeded from the sketch upper bound, so its counter over-estimates but never
under-estimates. If a churn row ever shows a violation, the re-seeding path is
wrong.

## E15 — twelve-seed replication

The cap sweep rerun on twelve seeds instead of three, with the same traces for every
policy so the comparison is paired. Reports mean, sample standard deviation and a
95% Student-t interval per policy and cap, plus the paired availability difference
against PrivFuse. The summary is derived from the raw per-seed rows; nothing is
smoothed or dropped.

## E16 — exact windowed accountant

An exact per-subject event log with a sliding window, used as the strong baseline
that Section VII-E used to claim was impossible. It enforces the same hard cap and
soft budget inside the window, so its estimate is exact and its memory grows with
events in the window rather than with the population.

Reported per policy: availability, cumulative violations against exact truth,
windowed peak spend and the number of subjects whose windowed spend crosses the cap
(a two-pointer scan over allowed events), memory and microseconds per request. The
two violation columns are deliberately separate: windowed enforcement bounds a
window, not a lifetime, and the experiment shows exactly that.

## E17 — latency breakdown and load

Part A profiles a full run with `cProfile` and aggregates self time by module, so
the sketch, the accountant, the breaker, the coordinator and the market harness can
be separated. Profiling inflates absolute cost, so only the shares are read from it.

Part B times `begin` and `finish` separately for every request, over three trials,
keeping the trial with the median mean service time (the host is shared, so a
scheduler pause must not decide the reported tail). The empirical service-time
distribution is then fed to two single-server FCFS queues: Poisson arrivals at
utilisation 0.5 to 0.95, and an alternating burst pattern whose time-average rate
matches the requested utilisation. Each point is the median of five replicates,
because a single replicate's p99 moves by tens of milliseconds.

A third row disables the tenant-pressure sweep (`_tenant_refresh = 10**9`) to show
what the periodic O(hot-table) scan costs. This is the ablation behind the paper's
claim that one function owns the tail; it changes admission behaviour, so it is a
diagnostic, not a configuration we recommend.

Latency from the queue model is queueing plus service for one coordinator thread.
It excludes network, client time and any second server.

## E18 — closed-loop attacker

E4 and E15 attack with a fixed plan. A tenant that sees admission decisions can do
better, so E18 hands the attacker the decision stream. Three strategies share one
budget of 1,200 attempts, one target subject and a cap of one epsilon:

* `round_robin` cycles forty tenants and three platforms (the open-loop baseline);
* `probe` halves the fragment after a refusal, grows it by 10% after an admission,
  and retires an identity after three consecutive refusals;
* `cooling` always uses the identity that has been idle longest.

The measured quantity is the composed loss actually charged, converted to epsilon at
the run's delta and divided by the cap. Summing marginal epsilons would overstate the
loss, since ten fragments of 0.3 eps compose to 0.80, not 3.0.

Results: probing raises PrivFuse from 0.80 to 0.85 of the cap (the soft budget is
0.8, the hard cap 1.0) but raises static quota from 1.30 to 1.74 and exact blocking
from 1.69 to 1.76, because a cheaper request slips under a quota that refused the
full fragment. `cooling` is indistinguishable from `round_robin` for every policy:
dispersion across identities buys nothing when the identity is not the key. Runs are
deterministic, so the three seeds coincide.

## E19 — settlement under injected faults

E12 crashes the client at a random point; E19 places the crash at a named step so each
clause of Proposition 2 has a row: after the reservation (nothing executed), after
execution (answer withheld), after commit (answer withheld, charge kept), and a client
retry with the same transaction id, either immediately or after the TTL has released
the hold.

The invariants are read off the ledger: answers minus commits is the count of answers
delivered without a charge, `duplicate_commits` and the committed total catch double
charging, and in-flight spend (committed plus reserved) is checked against the cap.
Rows for four crash points and two retry timings are printed by the experiment and
stored in `results/e19_faults.csv`.

Part B sweeps the crash rate (0, 1, 5%) over one and four threads at a cap of 50 eps
with a 5 s TTL, so the cost of a crash shows up as availability rather than as an
invariant failure. Part C is the control: three platform-local ledgers instead of the
shared coordinator, which spend three caps on one subject.

Two properties are worth restating, because they are what the numbers buy: a retry
before the TTL reuses the reservation and charges once, and a crash after commit keeps
the charge while withholding the answer (the safe direction). A retry after the TTL is
refused, and the hold returns to the pool.

## E20: an equi-functional exact baseline

The exact baselines in E4 and E16 also lack the window, the breaker and the
coordinator, so a difference against them cannot be attributed to approximation.
E20 removes the confound: `build_privfuse(..., PrivFuseConfig(exact=True))` swaps
the Count-Min sketch for a dense per-subject table (`privfuse/sketch/exact.py`)
behind the *same* accountant ring, SLO predicate, breaker, admission controller
and two-phase coordinator.

At the population where a dense table fits (1,500 subjects, 12,000 requests, caps
1.0 and 0.5, three seeds) the two policies make **identical** admission decisions:
availability and windowed peak match exactly (maximum per-seed difference 0.0000),
both have zero hard-cap violations. The exact version is 1.5x faster on average
(233 against 156 us per request, 1.3-2.4x across runs) and holds 0.37 MB against
5.01 MB.

The result is deliberately unflattering and bounds the claim: at 10^3 subjects the
sketch buys nothing but the slope. That slope is the point, and E23 measures it
rather than extrapolating it: 553 MB resident at 10^6 subjects against 5.8 MB for
the sketch, whose footprint does not move across four orders of magnitude. An equi-functional exact design
is therefore the right choice below the crossover and the wrong one above it, and
the paper should be read as locating that crossover rather than as claiming
approximation is free.

`results/e20_equiv.csv` holds the rows; `results/e20_equiv_meta.json` records that
the only difference between the two policies is the accountant store.

## E21: killing the coordinator

E19 injects faults inside one process and keeps the ledger alive, so it cannot
show what a restart does to committed charges. E21 removes that assumption. A
worker process (`privfuse/experiments/_e21_worker.py`) runs the reservation and
commit path and kills itself with `SIGKILL` at a chosen step: before the
reservation, after it, after the commit, or after the answer has been written to
the client's log. A fresh process then replays the log and continues. Six kills
are spread over a 600-request trace, followed by an uninterrupted run.

Two arms run the identical schedule:

* `durable` uses `DurableLedger` (`privfuse/ledger/durable.py`), which appends
  every transition to a log, `fsync`s it, and replays it on open. A partial
  trailing line from a kill mid-write is truncated, because a record that was
  never fully written was also never acknowledged.
* `volatile` keeps the ledger in memory, which is what the system did before
  this experiment.

Both arms are scored on the client side - the answers the tenant actually holds -
because that is the information that left the building and it does not depend on
what the ledger believes about itself.

| arm | answers | uncharged | worst client eps | subjects over cap |
|---|---|---|---|---|
| durable | 389 | 0 | 0.191 (cap 0.2) | 0 of 10 |
| volatile | 571 | - | 0.418 (2.1x cap) | 5 of 10 |

The volatile arm is the failure mode: every restart resets the budget, so the
hottest subject is served 2.1 times its cap. The durable arm pays for its
correctness in availability (389 against 571 answers at the same cap) and in
latency: `e21_cost.csv` measures 76 us per reserve-and-commit against 7.5 us in
memory, because each transition is an fsync. Group commit would amortise that and
is not implemented.

## E22 — three platform processes and a coordinator that dies

`e22_deploy` starts a coordinator process with a write-ahead log, then three
platform processes that read the trace for their own platform and settle over a
line protocol on loopback. When 300 answers have been handed back it sends
`SIGKILL` to the coordinator, restarts it from the log on the same port, and the
platforms retry the transaction they were in (reserve is idempotent for a
committed or reserved id, so a lost reply cannot double-charge).

Only single-subject requests are run, because the line protocol prices one
subject per reservation; 760 of 900 requests qualify. Two modes are reported:
`durable+restart` and `durable` (same code, no kill).

| mode | answers | uncharged | worst client ε (cap 0.5) | downtime | steady ans/s |
|---|---|---|---|---|---|
| durable+restart | 760 | 0 | 0.380 | 1.05 s | 221 |
| durable | 760 | 0 | 0.380 | — | 237 |

The restart costs about 1 s of unavailability and 7% of steady-state
throughput; no answer is delivered without a committed charge and no subject is
charged twice. `reconnect_attempts` counts the retries the three platforms made
while the coordinator was down.

What this is not: one host, two vCPUs, loopback TCP, no consensus, no
replication, no network partition. The honest comparison for throughput is E13b
(1.9k pairs/s), which runs an in-memory ledger and no answer-log fsync; the
difference is the price of durability, not of distribution.

## E23 — the dense table at four populations

E20's exact control holds one table per live epoch, so its per-subject cost is the
number the crossover argument depends on. `e23_population` measures it at 10^3,
10^4, 10^5 and 10^6 subjects, each (backend, population) pair in its own process so
the resident set is not contaminated by an earlier run. The traffic shape is E8's:
1000 hot subjects with eight requests each, every other subject once.

| backend | subjects | nbytes | resident | us/request |
|---|---|---|---|---|
| sketch | 10^3 | 2.77 MB | 5.53 MB | 32.0 |
| sketch | 10^4 | 2.79 MB | 5.75 MB | 54.9 |
| sketch | 10^5 | 2.79 MB | 5.88 MB | 54.0 |
| sketch | 10^6 | 2.79 MB | 5.75 MB | 45.7 |
| exact | 10^3 | 0.26 MB | 1.05 MB | 6.6 |
| exact | 10^4 | 2.56 MB | 5.81 MB | 8.3 |
| exact | 10^5 | 25.6 MB | 58.4 MB | 10.8 |
| exact | 10^6 | 256.0 MB | 552.6 MB | 14.5 |

Two things worth stating in the paper and one that is not.

1. The sketch is flat: 5.5-5.9 MB at every population. This is the claim the paper
   makes, now measured at 10^6 rather than inferred from 1,500.
2. The exact store's own `nbytes` understates what it occupies by 2.2x, because it
   reports `128 * len(costs)` and ignores the dict, the key strings and the
   `CostVector` objects. The paper quotes the resident number for the slope and the
   `nbytes` number for the 1,500-subject comparison, and says which is which.
3. Per-request cost also rises, 6.6 to 14.5 us, as the dict outgrows cache; that is
   a secondary effect and the paper only mentions it in passing.

`results/e23_population.csv` holds the rows.
## Reading the numbers

* Violation counts are the load-bearing result; wall-clock numbers are
  machine-dependent.
* Availability differences of a few points are the *price* of soundness, not a
  defect. A policy that never rejects will always look better on availability
  and worse on violations.
* E1's mean absolute error is expressed in epsilon units; divide by the cap to
  read it as a fraction of the budget.
