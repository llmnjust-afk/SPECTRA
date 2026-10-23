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


def build_all() -> list[pathlib.Path]:
    produced = []
    for builder in (fig_e1, fig_e2, fig_e4, fig_e5, fig_e7, fig_hysteresis, fig_e8):
        path = builder()
        if path is not None:
            produced.append(path)
    return produced


if __name__ == "__main__":
    for path in build_all():
        print(path)
