# Design notes

This document states the model precisely and points at the code that implements
each piece. It is meant to be the bridge between the paper's propositions and
the repository.

## 1. Cost algebra

A transaction `j` produces a cost vector

```
c_j = (eps_pure, rho, delta)
```

where `eps_pure` is pure `(eps, 0)`-DP mass and `rho` is zCDP concentration.
Composition is componentwise addition (`CostVector.__add__`), and conversion to a
`(eps, delta)` guarantee is

```
eps(c) = c.eps_pure + c.rho + 2 * sqrt(c.rho * log(1/delta))
```

`CostVector.eps` returns `eps_pure` unchanged when `rho = 0`, which is what makes
mixed Laplace/Gaussian streams sound: the pure part never gets folded into a
concentration bound it does not satisfy.

Calibration (`privfuse/dp/mechanisms.py`) inverts the conversion in closed form:

```
u = sqrt(log(1/delta));  rho = (sqrt(u^2 + eps) - u)^2
sigma = sensitivity / sqrt(2 rho)
```

so `gaussian_cost(e, d, s).eps(d) == e` to machine precision.

## 2. Accounting

Let `E_d(t)` be subject `d`'s true cumulative cost at time `t`. The accountant
maintains two estimators, both over Count-Min sketches:

* `Ehat_d^cum` — cumulative, never reset, backs the hard cap;
* `Ehat_d^win` — sum over the epoch ring, backs the windowed SLO.

The ring must cover the window. A window of length `w` touches
`ceil(w / epoch) + 1` epochs, so a ring of `k` epochs only guarantees coverage of
`(k - 1) * epoch`; `OnlineAccountantConfig.max_window` reports that smaller
number, and the factory sizes the ring with `ring_epochs_for` instead of trusting
the configured value. Without this, a 600 s window over 300 s epochs silently
drops the oldest epoch and the windowed estimate under-counts — the one failure
direction the design forbids.

Sketches are additive and their updates are non-negative, so

> **P1 (one-sidedness).** For every subject, every view (cumulative or any fully
> covered window), and every time, `Ehat_d >= E_d`.

The proof is the standard Count-Min argument, the ring-coverage invariant above,
and the observation that the conversion `rho -> eps` is monotone. The update rule in
`CountMinSketch.add` raises every cell below `min + value` to `min + value`.
The textbook conservative update only raises cells *equal* to the minimum, which
is equivalent for unit increments but can leave a collision cell just below the
new minimum for real-valued weights, producing an under-estimate. The test
`test_countmin_never_underestimates` pins this down.

Because P1 holds, a breaker that trips on `Ehat_d >= cap` never admits a set of
transactions whose true composition exceeds the cap:

> **P2 (breaker safety).** If every admitted transaction carries a certified
> cost and the breaker admits only while `Ehat_d < cap`, no subject's true
> cumulative cost exceeds `cap`.

P2 is conditional on the costs being certified. That is the honest boundary of
the contribution: PrivFuse does not verify that a query engine injected the noise
it claimed to; it verifies that the *accounting* of claimed costs is sound.

## 3. SLO

An SLO is `(E, p, W)`:

```
Pr[ eps_d(W) > E ] <= p        for d drawn from the subject population
```

`SLOSpec` holds the triple; `evaluate_slo` computes the observed rate over the
hot table. The hard cap is separate and cumulative, because a regulator
publishes a lifetime cap, not a per-window one. Conflating the two is a common
modelling error: a per-window cap can be reset by waiting.

## 4. Breaker

`BreakerController.update` is a per-key automaton with

* immediate escalation at `throttle_ratio`, `reject_ratio`, `freeze_ratio`;
* de-escalation only when pressure falls below `threshold - hysteresis` for
  `dwell` consecutive evaluations.

> **P3 (no churn).** For pressure confined to
> `[threshold - hysteresis + eta, threshold + eta]` with `eta < hysteresis`, the
> breaker changes level at most once.

The proof is immediate from the release condition: the release threshold is
never crossed, so no de-escalation can fire.

Subject-level pressure is monotone (budgets only accumulate), so P3 matters at
tenant granularity, where the windowed violation rate can fall. The
`hysteresis_micro` experiment measures 26 transitions without hysteresis and 0
with it.

## 5. Settlement

`SettlementLedger` implements reserve / commit / release with idempotent
transaction identifiers. `Coordinator` applies every reservation to one shared
balance, which is the stand-in for a cross-chain budget root.

> **P4 (no double spend).** If commit and release are idempotent and an expired
> reservation is released exactly once, the sum of committed costs for a subject
> never exceeds the sum of its reservations, and reservations never exceed the
> cap.

The expiry sweep (`SettlementLedger.tick`) is what makes a crashed platform
recoverable: the reservation dies on its own and the budget returns. E6 injects
a crash between reserve and commit and checks that no double spend occurs and
that the expired reservation is recovered.

## 6. What the sketch buys, and what it costs

The sketch is not a memory optimisation at small scale — at 1,000 subjects an
exact dictionary is smaller. What it buys is:

1. **Bounded identifier footprint.** The accountant stores `width * depth` cells
   plus at most `hot_capacity` identifiers, independent of the population. An
   exact accountant stores every subject identifier, which is itself a privacy
   and compliance liability for the accounting layer.
2. **Bounded per-request cost.** `O(depth)` hashes regardless of how many
   subjects exist.
3. **A conservative failure direction.** Every error makes the breaker trip
   earlier, never later.

The hot table is bounded, so a subject that is evicted and returns cannot recover
its history from the table. It is seeded instead with the sketch's upper bound
for the past and then accumulates exactly, which keeps the value an upper bound
while staying exact for subjects tracked from their first request. The price is
the 5x per-request overhead measured in E2 and the availability loss in E3 —
both of which are reported rather than hidden.
