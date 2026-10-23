"""Reproducible experiment runners."""

EXPERIMENTS = {
    "e1": "privfuse.experiments.e1_accounting",
    "e2": "privfuse.experiments.e2_overhead",
    "e3": "privfuse.experiments.e3_breaker",
    "e4": "privfuse.experiments.e4_attack",
    "e5": "privfuse.experiments.e5_slo",
    "e6": "privfuse.experiments.e6_settlement",
    "e7": "privfuse.experiments.e7_ablation",
}

__all__ = ["EXPERIMENTS"]
