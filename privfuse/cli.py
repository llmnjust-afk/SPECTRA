"""Command line entry point."""

from __future__ import annotations

import argparse
import json

from privfuse.experiments import EXPERIMENTS
from privfuse.experiments import figures
from privfuse.experiments.run_all import main as run_all


def main() -> None:
    parser = argparse.ArgumentParser(prog="privfuse", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one or more experiments")
    run.add_argument("names", nargs="*", choices=sorted(EXPERIMENTS), default=None)
    run.add_argument("--figures", action="store_true", help="rebuild figures afterwards")

    sub.add_parser("figures", help="rebuild figures from results")

    demo = sub.add_parser("demo", help="run a small end-to-end market simulation")
    demo.add_argument("--requests", type=int, default=2000)

    args = parser.parse_args()
    if args.command == "run":
        run_all(args.names or None)
    elif args.command == "figures":
        figures.build_all()
    else:
        from privfuse.experiments.common import compare_policies, default_trace

        trace = default_trace(n_requests=args.requests, attack="split")
        for row in compare_policies(trace):
            print(json.dumps({k: round(v, 4) for k, v in row.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
