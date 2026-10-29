"""Freeze paired scalar benchmark requests or compare receipt-bound native powers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from photonic_workflow.lumerical.parity import compare_solver_runs, make_benchmark_plan
from photonic_workflow.models.io import atomic_create_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Create two requests and a declared power budget; no solver.")
    plan.add_argument("--family", choices=["straight", "directional-coupler"], required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--power-tolerance", type=float, default=0.03)
    compare = commands.add_parser("compare", help="Compare all powers without phase alignment or interpolation.")
    compare.add_argument("--comsol-receipt", type=Path, required=True)
    compare.add_argument("--lumerical-receipt", type=Path, required=True)
    compare.add_argument("--power-tolerance", type=float, required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = make_benchmark_plan(args.family, power_tolerance=args.power_tolerance)
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        for name, value in (("benchmark-plan.json", result), ("comsol-request.json", result["comsol_request"]),
                            ("lumerical-request.json", result["lumerical_request"])):
            atomic_create_text(output / name, json.dumps(value, indent=2, allow_nan=False) + "\n")
    else:
        result = compare_solver_runs(args.comsol_receipt, args.lumerical_receipt,
                                     power_tolerance=args.power_tolerance)
        atomic_create_text(args.output, json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
