"""Reproducible experiment runners."""

EXPERIMENTS = {
    "e1": "privfuse.experiments.e1_accounting",
    "e2": "privfuse.experiments.e2_overhead",
    "e3": "privfuse.experiments.e3_breaker",
    "e4": "privfuse.experiments.e4_attack",
    "e5": "privfuse.experiments.e5_slo",
    "e6": "privfuse.experiments.e6_settlement",
    "e7": "privfuse.experiments.e7_ablation",
    "e8": "privfuse.experiments.e8_scale",
}

DEFAULT = [name for name in EXPERIMENTS if name != "e8"]

__all__ = ["DEFAULT", "EXPERIMENTS"]
