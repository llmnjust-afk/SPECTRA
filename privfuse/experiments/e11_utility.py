"""E11: what does the hard cap cost in downstream accuracy?

The synthetic traces measure availability, not utility. This experiment puts a
real dataset behind the budget. A tenant repeatedly asks a marketplace for the
class-conditional sufficient statistics of a binary classification problem, each
release noised with a Gaussian mechanism. Repeated independent releases can be
averaged, so accuracy improves with the square root of the number of admitted
queries -- which is exactly why an unlimited tenant will happily spend an
unlimited privacy budget.

The classifier is Gaussian naive Bayes fitted to the noisy statistics, so the
accuracy is a genuine downstream number rather than a proxy.

Simplifications, stated rather than hidden: class counts are treated as public,
features are clipped to the public unit interval before release, and the budget
is charged by basic composition (each of the four mechanisms gets a quarter of
the per-release epsilon). The resulting totals are therefore conservative.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split

from privfuse.experiments.common import write_csv, write_json
from privfuse.trace.generator import EPS_DELTA

DELTA_Q = EPS_DELTA
CAP = 1.0
MAX_QUERIES = 100
EPOCH_QUOTA = 20
EPOCHS = 3


def _load() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    data = load_breast_cancer()
    x = data.data.astype(np.float64)
    y = data.target.astype(np.int64)
    x = (x - x.min(axis=0)) / (x.max(axis=0) - x.min(axis=0) + 1e-12)
    return train_test_split(x, y, test_size=0.3, random_state=7, stratify=y)


def _noisy_stats(
    x: np.ndarray, y: np.ndarray, sigma: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Release the mean and second moment of every feature, per class.

    The mechanism is Gaussian on the mean vector with L2 sensitivity
    ``sqrt(d) / n``; the second moment has the same sensitivity because every
    feature is clipped to the unit interval. Noise is added to the mean and to
    the second moment, and the variance is reconstructed from the two.
    """
    classes = np.unique(y)
    means = []
    variances = []
    counts = []
    for label in classes:
        block = x[y == label]
        counts.append(len(block))
        mean = block.mean(axis=0) + rng.normal(0.0, sigma, size=x.shape[1])
        second = (block**2).mean(axis=0) + rng.normal(0.0, sigma, size=x.shape[1])
        variance = np.maximum(second - mean**2, 1e-9)
        means.append(mean)
        variances.append(variance)
    return np.array(means), np.array(variances), np.array(counts)


def _accuracy(
    means: np.ndarray,
    variances: np.ndarray,
    counts: np.ndarray,
    x_test: np.ndarray,
    y_test: np.ndarray,
) -> float:
    log_prior = np.log(counts / counts.sum())
    log_likelihood = np.zeros((x_test.shape[0], len(counts)))
    for index in range(len(counts)):
        var = variances[index]
        diff = x_test - means[index]
        log_likelihood[:, index] = -0.5 * np.sum(np.log(2 * np.pi * var)) - 0.5 * np.sum(
            diff**2 / var, axis=1
        )
    scores = log_likelihood + log_prior
    return float((scores.argmax(axis=1) == y_test).mean())


def _sigma_for(eps_per_release: float, n: int, d: int) -> float:
    """Noise on a mean vector of ``d`` features released with ``eps_per_release``.

    Four mechanisms share the release (two classes times mean and second
    moment), so each gets a quarter of the budget under basic composition. The
    L2 sensitivity of a mean vector over ``n`` clipped records is ``sqrt(d)/n``.
    """
    per_mechanism = eps_per_release / 4.0
    sensitivity = math.sqrt(d) / n
    return sensitivity * math.sqrt(2.0 * math.log(1.25 / DELTA_Q)) / per_mechanism


def run(
    epsilons: list[float] | None = None, seeds: list[int] | None = None
) -> list[dict[str, Any]]:
    epsilons = epsilons or [0.25, 0.5, 1.0]
    seeds = seeds or [1, 2, 3]
    x_train, x_test, y_train, y_test = _load()
    rows: list[dict[str, Any]] = []
    for eps in epsilons:
        sigma = _sigma_for(eps, x_train.shape[0], x_train.shape[1])
        for seed in seeds:
            rng = np.random.default_rng(seed)
            running_sum = None
            running_sq = None
            counts = None
            curve = []
            for k in range(1, MAX_QUERIES + 1):
                means, variances, class_counts = _noisy_stats(
                    x_train, y_train, sigma, rng
                )
                if running_sum is None:
                    running_sum = means
                    running_sq = variances
                    counts = class_counts
                else:
                    running_sum += means
                    running_sq += variances
                averaged_means = running_sum / k
                averaged_var = np.maximum(running_sq / k, 1e-9)
                curve.append(
                    _accuracy(averaged_means, averaged_var, counts, x_test, y_test)
                )

            unbounded = MAX_QUERIES * eps
            quota = EPOCH_QUOTA * EPOCHS * eps
            capped = int(math.floor(CAP / eps + 1e-9))
            points = {
                "unbounded": (MAX_QUERIES, unbounded),
                "static_quota": (EPOCH_QUOTA * EPOCHS, quota),
                "privfuse": (capped, capped * eps),
            }
            for policy, (queries, spent) in points.items():
                rows.append(
                    {
                        "policy": policy,
                        "epsilon_per_query": eps,
                        "seed": seed,
                        "queries": queries,
                        "total_eps": spent,
                        "accuracy": curve[max(0, queries - 1)],
                        "cap": CAP,
                        "violations": int(spent > CAP + 1e-12),
                    }
                )
        print(
            f"eps={eps}: "
            + "  ".join(
                f"{r['policy']} k={r['queries']} acc={r['accuracy']:.3f}"
                for r in rows[-3:]
            ),
            flush=True,
        )
    write_csv("e11_utility", rows)
    write_json(
        "e11_utility_meta",
        {
            "dataset": "sklearn.datasets.load_breast_cancer",
            "cap": CAP,
            "max_queries": MAX_QUERIES,
            "epoch_quota": EPOCH_QUOTA,
            "epochs": EPOCHS,
            "delta": DELTA_Q,
        },
    )
    return rows


if __name__ == "__main__":
    run()
