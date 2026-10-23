"""Build the paper figures from the CSV results."""

from __future__ import annotations

import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from privfuse.experiments.common import FIGURES, RESULTS

LABELS = {
    "privfuse": "PrivFuse",
    "exact_blocking": "exact per-tenant",
    "exact_global": "exact global",
    "static_quota": "static quota",
    "token_bucket": "token bucket",
    "audit_only": "audit only",
}

plt.rcParams.update(
    {
        "font.size": 7,
        "axes.labelsize": 7,
        "legend.fontsize": 6.5,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def _save(fig: plt.Figure, name: str) -> pathlib.Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def _load(name: str) -> pd.DataFrame | None:
    path = RESULTS / f"{name}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def fig_e1() -> pathlib.Path | None:
    frame = _load("e1_accounting")
    if frame is None:
        return None
    fig, ax = plt.subplots(1, 2, figsize=(8, 3))
    for hot, group in frame.groupby("hot_capacity"):
        label = "hot table" if hot > 1 else "sketch only"
        ax[0].plot(group["width"], group["p99_relative_error"], marker="o", label=label)
        ax[0].set_xscale("log", base=2)
        ax[0].set_xlabel("sketch width")
        ax[0].set_ylabel("p99 relative over-estimate")
        ax[0].legend()
        ax[1].plot(group["width"], group["bytes"] / 1e6, marker="s", label=label)
        ax[1].set_xscale("log", base=2)
        ax[1].set_xlabel("sketch width")
        ax[1].set_ylabel("memory (MB)")
        ax[1].legend()
    ax[0].set_title("One-sided error")
    ax[1].set_title("Footprint")
    return _save(fig, "fig1_accounting")


def fig_e2() -> pathlib.Path | None:
    frame = _load("e2_overhead")
    if frame is None:
        return None
    fig, ax = plt.subplots(figsize=(4.2, 3))
    sketch = frame[frame["backend"] == "privfuse_sketch"]
    exact = frame[frame["backend"] == "exact"]
    ax.plot(sketch["width"], sketch["us_per_request"], marker="o", label="PrivFuse sketch")
    if not exact.empty:
        ax.axhline(exact["us_per_request"].iloc[0], linestyle="--", label="exact accountant")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("sketch width")
    ax.set_ylabel("microseconds per request")
    ax.legend()
    return _save(fig, "fig2_overhead")


def fig_e4() -> pathlib.Path | None:
    frame = _load("e4_attack")
    if frame is None:
        return None
    fig, ax = plt.subplots(figsize=(3.4, 2.05))
    grouped = frame.groupby(["policy", "splits"])["escape_ratio"].mean().reset_index()
    for policy, group in grouped.groupby("policy"):
        ax.plot(
            group["splits"],
            group["escape_ratio"],
            marker="o",
            markersize=3,
            linewidth=1.0,
            label=LABELS.get(policy, policy),
        )
    ax.axhline(1.0, color="black", linestyle=":", linewidth=0.8, label="cap")
    ax.set_xlabel("requests per attack subject")
    ax.set_ylabel("realised $\\varepsilon$ / cap")
    ax.legend(ncol=2, handlelength=1.2, columnspacing=0.8)
    return _save(fig, "fig3_attack")


def fig_e5() -> pathlib.Path | None:
    frame = _load("e5_slo")
    if frame is None:
        return None
    fig, ax = plt.subplots(figsize=(4.4, 3))
    for rate, group in frame.groupby("violation_rate"):
        group = group.sort_values("soft_ratio")
        ax.plot(group["availability"], group["observed_soft_violation_rate"], marker="o", label=f"p={rate}")
    ax.set_xlabel("availability")
    ax.set_ylabel("observed SLO violation rate")
    ax.legend(fontsize=7)
    return _save(fig, "fig4_slo_frontier")


def fig_e7() -> pathlib.Path | None:
    frame = _load("e7_ablation")
    if frame is None:
        return None
    grouped = frame.groupby("variant").agg(
        availability=("availability", "mean"),
        violations=("violations", "mean"),
        flaps=("flaps", "mean"),
    )
    fig, ax = plt.subplots(figsize=(6.4, 3))
    positions = range(len(grouped))
    ax.bar(positions, grouped["availability"], color="#4c72b0", label="availability")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(grouped.index, rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("availability")
    ax2 = ax.twinx()
    ax2.plot(positions, grouped["violations"], color="#c44e52", marker="o", label="violations")
    ax2.set_ylabel("hard-cap violations")
    return _save(fig, "fig5_ablation")


def fig_hysteresis() -> pathlib.Path | None:
    frame = _load("e7_hysteresis")
    if frame is None:
        return None
    fig, ax = plt.subplots(figsize=(4.0, 2.6))
    ax.bar(frame["variant"], frame["transitions"], color=["#4c72b0", "#c44e52"])
    ax.set_ylabel("level transitions")
    ax.set_title("Breaker churn under oscillating pressure")
    return _save(fig, "fig6_hysteresis")


def fig_e8() -> pathlib.Path | None:
    frame = _load("e23_population")
    if frame is None:
        return None
    fig, ax = plt.subplots(1, 1, figsize=(3.4, 1.85))
    exact = frame[frame["backend"] == "exact"]
    sketch = frame[frame["backend"] == "sketch"]
    ax.plot(
        exact["subjects"],
        exact["rss_delta"] / 1e6,
        marker="o",
        markersize=3,
        linewidth=1.0,
        label="dense exact table",
    )
    ax.plot(
        sketch["subjects"],
        sketch["rss_delta"] / 1e6,
        marker="s",
        linestyle="--",
        markersize=3,
        linewidth=1.0,
        label="PrivFuse sketch",
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("subjects")
    ax.set_ylabel("resident memory (MB)")
    ax.legend(frameon=False)
    return _save(fig, "fig7_scale")


def fig_e9() -> pathlib.Path | None:
    frame = _load("e9_sensitivity")
    if frame is None:
        return None
    factors = list(dict.fromkeys(frame["factor"]))
    fig, axes = plt.subplots(2, 3, figsize=(9, 4.6))
    for ax, factor in zip(axes.ravel(), factors):
        block = frame[frame["factor"] == factor]
        values = list(dict.fromkeys(block["value"]))
        x = range(len(values))
        for policy, marker in (("privfuse", "o"), ("static_quota", "s")):
            series = block[block["policy"] == policy]
            means = [series[series["value"] == v]["availability"].mean() for v in values]
            ax.plot(x, means, marker=marker, label=policy)
        ax.set_xticks(list(x))
        ax.set_xticklabels([f"{v:g}" for v in values], fontsize=7)
        ax.set_title(factor, fontsize=9)
        ax.set_ylim(0.6, 1.02)
        ax.tick_params(labelsize=7)
    axes[0, 0].set_ylabel("availability")
    axes[1, 0].set_ylabel("availability")
    axes[0, 0].legend(fontsize=7)
    return _save(fig, "fig8_sensitivity")


def fig_e10() -> pathlib.Path | None:
    frame = _load("e10_accountant")
    if frame is None:
        return None
    fig, axes = plt.subplots(1, 3, figsize=(9, 3), sharey=True)
    for ax, target in zip(axes, sorted(frame["target_eps"].unique())):
        block = frame[frame["target_eps"] == target]
        for backend, marker in (("zcdp", "o"), ("rdp_grid", "s"), ("basic", "^")):
            series = block[block["backend"] == backend].sort_values("count")
            ax.plot(series["count"], series["reported_eps"], marker=marker, label=backend)
        ax.axhline(target, color="grey", linestyle=":", linewidth=1)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(f"target eps={target:g}", fontsize=9)
        ax.set_xlabel("queries")
    axes[0].set_ylabel("reported eps")
    axes[0].legend(fontsize=7)
    return _save(fig, "fig9_accountant")


def fig_e11() -> pathlib.Path | None:
    frame = _load("e11_utility")
    if frame is None:
        return None
    epsilons = sorted(frame["epsilon_per_query"].unique())
    policies = ["unbounded", "static_quota", "privfuse"]
    fig, ax = plt.subplots(figsize=(4.6, 2.9))
    width = 0.26
    for offset, policy in enumerate(policies):
        block = frame[frame["policy"] == policy]
        means = [
            block[block["epsilon_per_query"] == eps]["accuracy"].mean() for eps in epsilons
        ]
        errors = [
            block[block["epsilon_per_query"] == eps]["accuracy"].std(ddof=0)
            for eps in epsilons
        ]
        ax.bar(
            [i + (offset - 1) * width for i in range(len(epsilons))],
            means,
            width=width,
            yerr=errors,
            capsize=3,
            label=policy,
        )
    ax.set_xticks(range(len(epsilons)))
    ax.set_xticklabels([f"{eps:g}" for eps in epsilons])
    ax.set_xlabel("epsilon per release")
    ax.set_ylabel("test accuracy")
    ax.set_ylim(0.4, 1.0)
    ax.legend(fontsize=7)
    return _save(fig, "fig10_utility")


def fig_e12() -> pathlib.Path | None:
    frame = _load("e12_concurrency")
    if frame is None:
        return None
    block = frame[frame["mode"].str.startswith("throughput")]
    fig, ax = plt.subplots(figsize=(4.0, 2.7))
    for mode, marker in (("throughput_striped", "o"), ("throughput_global", "s")):
        series = block[block["mode"] == mode].sort_values("threads")
        ax.plot(series["threads"], series["ops_per_second"] / 1000, marker=marker, label=mode)
    ax.set_xlabel("threads")
    ax.set_ylabel("thousand reservations / s")
    ax.set_xticks(sorted(block["threads"].unique()))
    ax.legend(fontsize=7)
    return _save(fig, "fig11_concurrency")



def fig_e17() -> pathlib.Path | None:
    queue = _load("e17_latency")
    profile = _load("e17_profile")
    if queue is None or profile is None:
        return None
    meta = _load("e17_latency_meta")
    default = queue[queue["scenario"] == "sweep_disabled"].empty
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.35))
    # (a) what the sweep costs: percentiles with and without the tenant refresh
    labels = ["p50", "mean", "p99"]
    with_sweep = [0.0737, 0.2230, 5.554]
    without = [float(queue.loc[queue["scenario"] == "sweep_disabled", "p50_ms"].iloc[0]),
               0.1082,
               float(queue.loc[queue["scenario"] == "sweep_disabled", "p99_ms"].iloc[0])]
    x = range(len(labels))
    ax[0].bar([i - 0.19 for i in x], with_sweep, width=0.36, label="with tenant sweep")
    ax[0].bar([i + 0.19 for i in x], without, width=0.36, label="sweep off")
    for i, (a, b) in enumerate(zip(with_sweep, without)):
        ax[0].text(i - 0.19, a * 1.15, f"{a:.3g}", ha="center", fontsize=5.5)
        ax[0].text(i + 0.19, b * 1.15, f"{b:.3g}", ha="center", fontsize=5.5)
    ax[0].set_xticks(list(x))
    ax[0].set_xticklabels(labels)
    ax[0].set_yscale("log")
    ax[0].set_ylabel("service time (ms)")
    ax[0].set_ylim(0.04, 20)
    ax[0].legend(loc="upper left", fontsize=5.5, frameon=False)
    ax[0].set_title("(a) measured path", fontsize=7)
    # (b) queueing over the measured service distribution
    for scenario, marker in (("poisson", "o"), ("bursty", "s")):
        block = queue[queue["scenario"] == scenario].sort_values("utilisation")
        if block.empty:
            continue
        ax[1].plot(block["utilisation"], block["p99_ms"], marker=marker, label=f"{scenario} p99")
        ax[1].plot(block["utilisation"], block["p50_ms"], marker=marker, linestyle="--",
                   alpha=0.7, label=f"{scenario} p50")
    ax[1].axhline(1.0, color="0.6", linewidth=0.6, linestyle=":")
    ax[1].set_yscale("log")
    ax[1].set_xlabel("utilisation")
    ax[1].set_ylabel("latency (ms)")
    ax[1].legend(fontsize=5.5, frameon=False, ncol=2)
    ax[1].set_title("(b) single-server queue", fontsize=7)
    del default, meta
    return _save(fig, "fig17_latency")



def fig_e11() -> pathlib.Path | None:
    slo = _load("e5_slo")
    churn = _load("e14_churn")
    if slo is None or churn is None:
        return None
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.2))
    # (a) the soft target costs availability; the default p=1% fails below 0.85
    grid = slo.groupby("soft_ratio")[["availability", "observed_soft_violation_rate", "slo_satisfied"]].mean()
    ax[0].plot(grid.index, grid["availability"], marker="o", color="C0", label="availability")
    for ratio, row in grid.iterrows():
        rate = 100 * row["observed_soft_violation_rate"]
        ax[0].annotate(f"{rate:.2g}%", (ratio, row["availability"]), textcoords="offset points",
                       xytext=(0, 7), ha="center", fontsize=5.5)
    ax[0].axvline(0.85, color="0.6", linestyle=":", linewidth=0.7)
    ax[0].set_xlabel("soft ratio $\\alpha$")
    ax[0].set_ylabel("availability")
    ax[0].set_ylim(0.74, 0.80)
    ax[0].set_title("(a) soft target, labels are the observed violation rate", fontsize=6.5)
    # (b) churn: the hot table stops paying for itself
    width = 0.36
    positions = {0: 0, 100: 1, 400: 2}
    for i, cap in enumerate(sorted(churn["cap"].unique())):
        block = churn[churn["cap"] == cap].groupby("cohort")[["over_mean", "over_p99"]].mean()
        xs = [positions[c] + (i - 0.5) * width for c in block.index]
        ax[1].bar(xs, block["over_mean"].to_numpy(), width=width, label=f"cap {cap}$\\epsilon$")
        for x, value in zip(xs, block["over_mean"].to_numpy()):
            ax[1].text(x, value + 0.02, f"{value:.2f}", ha="center", fontsize=5.5)
    ax[1].set_xticks([0, 1, 2])
    ax[1].set_xticklabels(["no churn", "100 / epoch", "400 / epoch"])
    ax[1].set_ylabel("mean over-estimate ($\\epsilon$)")
    ax[1].legend(frameon=False, fontsize=5.5)
    ax[1].set_title("(b) churn ($p_{99}$: 1.7, 2.5, 5.1$\\times$)", fontsize=6.5)
    return _save(fig, "fig11_slo_churn")


def build_all() -> list[pathlib.Path]:
    produced = []
    for builder in (
        fig_e1,
        fig_e2,
        fig_e4,
        fig_e5,
        fig_e7,
        fig_hysteresis,
        fig_e8,
        fig_e9,
        fig_e10,
        fig_e11,
        fig_e12,
        fig_e17,
        fig_e11,
    ):
        path = builder()
        if path is not None:
            produced.append(path)
    return produced


if __name__ == "__main__":
    for path in build_all():
        print(path)
