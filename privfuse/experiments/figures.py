"""Build the paper figures from the CSV results."""

from __future__ import annotations

import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from privfuse.experiments.common import FIGURES, RESULTS


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
    fig, ax = plt.subplots(figsize=(5, 3))
    grouped = frame.groupby(["policy", "splits"])["escape_ratio"].mean().reset_index()
    for policy, group in grouped.groupby("policy"):
        ax.plot(group["splits"], group["escape_ratio"], marker="o", label=policy)
    ax.axhline(1.0, color="black", linestyle=":", label="cap")
    ax.set_xlabel("requests per attack subject")
    ax.set_ylabel("realised epsilon / cap")
    ax.legend(fontsize=7, ncol=2)
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
    frame = _load("e8_scale")
    if frame is None:
        return None
    fig, ax = plt.subplots(1, 2, figsize=(8, 3))
    exact = frame[frame["backend"] == "exact"]
    ax[0].plot(exact["subjects"], exact["bytes"] / 1e6, marker="o", label="exact")
    for width, group in frame[frame["backend"] == "sketch"].groupby("width"):
        ax[0].plot(
            group["subjects"],
            group["bytes"] / 1e6,
            marker="s",
            linestyle="--",
            label=f"sketch w={width}",
        )
    ax[0].set_xscale("log")
    ax[0].set_yscale("log")
    ax[0].set_xlabel("subjects")
    ax[0].set_ylabel("peak memory (MB)")
    ax[0].legend(fontsize=7)
    ax[0].set_title("state size")

    for width, group in frame[frame["backend"] == "sketch"].groupby("width"):
        ax[1].plot(group["subjects"], group["us_per_request"], marker="s", label=f"w={width}")
    ax[1].plot(exact["subjects"], exact["us_per_request"], marker="o", label="exact")
    ax[1].set_xscale("log")
    ax[1].set_xlabel("subjects")
    ax[1].set_ylabel("us / request")
    ax[1].legend(fontsize=7)
    ax[1].set_title("per-request cost")
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
    ):
        path = builder()
        if path is not None:
            produced.append(path)
    return produced


if __name__ == "__main__":
    for path in build_all():
        print(path)
