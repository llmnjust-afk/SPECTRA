# Roadmap and scope boundary

The paper claims a mechanism and an evaluation of that mechanism. It does not
claim a deployed system. This file records exactly where the line is, so a
reviewer can check the claim against the code.

## Implemented end to end

* cost algebra, calibration, composition
* one-sided streaming accountant with a bounded identifier footprint
* SLO specification and windowed evaluation
* admission control, degradation, rejection, freeze
* hysteresis breaker with dwell and churn bound
* reserve / commit / release settlement with idempotency and expiry
* cross-platform coordinator that defeats budget splitting
* market simulator, five baselines, crash injection
* seven experiments, all reproducible from a seed

## Interface only

### Chaincode (`privfuse.ledger.backend.ChainBackend`)

The in-memory ledger satisfies the same contract a chaincode would. Writing the
chaincode is transport and endorsement work: a composite key on
`(subject, tx_id)`, a range query for the subject's committed total, and the cap
check inside the endorsement policy so that two concurrent reservations cannot
both pass. No new semantics are required, which is why the invariant tests in
`tests/test_ledger.py` are the right artefact to port.

Effort: two to three weeks including a Fabric test network.

### Attestation (`privfuse.platform.attestation.Attester`)

The breaker reads claimed costs only. Binding a claim to an enclave measurement
would close the "the engine lied about its noise" gap, which is orthogonal to the
accounting contribution. `NullAttester` is what the simulator uses, and it is
labelled as such.

Effort: one week on SGX or SEV-SNP hardware, plus the calibration work to make an
enclave's noise generation reproducible enough to certify.

### Compliance proofs

Sampling plus re-execution is what E6 checks. Succinct proofs of "this
transaction's cost was at most `c`" are a research problem in their own right;
the mechanism does not need them, and pretending otherwise would be the kind of
overclaim this repository is trying to avoid.

## Deliberately excluded

* **Query engines.** PrivFuse consumes certified costs. It does not inject noise
  and cannot detect an engine that under-reports its sensitivity.
* **Cryptographic privacy for the accounting layer.** Sketch cells leak aggregate
  information about subject budgets to whoever holds the state. The hot table
  holds at most `hot_capacity` identifiers, which is a mitigation, not a proof.
  A production deployment would combine this with secret sharing.
* **Incentive analysis.** Whether a tenant prefers degradation to rejection is a
  pricing question, not an accounting one. The simulator records utility so the
  question can be studied, but no mechanism design claim is made.

## What would falsify the contribution

If a platform-local policy with the same information could match PrivFuse's
violation count at equal availability, the cross-platform coordination would be
unnecessary. E4 is constructed to test exactly that: platform-local exact
accounting reaches 1.69x the cap while PrivFuse stays at 0.81x. If a future
baseline closes that gap without shared state, the claim fails.
