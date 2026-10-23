"""Run every experiment and build the figures."""

from __future__ import annotations

import importlib
import time

from privfuse.experiments import EXPERIMENTS
from privfuse.experiments import figures


def main(names: list[str] | None = None) -> None:
    selected = names or list(EXPERIMENTS)
    for name in selected:
        module = importlib.import_module(EXPERIMENTS[name])
        started = time.perf_counter()
        module.run()
        print(f"{name}: {time.perf_counter() - started:.1f}s")
    figures.build_all()


if __name__ == "__main__":
    main()
