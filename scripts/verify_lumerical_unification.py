"""Recompute the retained matched-solver comparisons and compact public record.

Only reads saved artifacts; does not import a vendor API or start a solver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from photonic_workflow.lumerical.parity import compare_solver_runs


def one_receipt(bundle: Path) -> Path:
    candidates = list(bundle.glob("run-*/receipt.json"))
    if len(candidates) != 1:
        raise RuntimeError("Expected one identified COMSOL run per retained benchmark bundle")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--device-runs", type=Path, required=True)
    parser.add_argument("--installed-smoke", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, earlier = args.runs.resolve(), args.device_runs.resolve()
    pairs = {
        "straight": (root / "straight/bundle", earlier / "straight-m5"),
        "coupler_baseline": (root / "directional-coupler/bundle", earlier / "coupler-m5"),
        "coupler_fine": (root / "coupler-refined-comsol", root / "coupler-refined-fdtd"),
        "coupler_expanded": (root / "coupler-window4-comsol", root / "coupler-window4-fdtd"),
    }
    comparisons = {name: compare_solver_runs(one_receipt(bundle), fdtd / "receipt.json", power_tolerance=.03)
                   for name, (bundle, fdtd) in pairs.items()}
    cad_root = root / "recipe-native"
    cad = json.loads((cad_root / "summary.json").read_text())
    checks = []
    for name, case in cad["cases"].items():
        path = cad_root / name / "readback.json"
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["readback_sha256"]:
            raise RuntimeError("Native CAD readback differs from its recorded hash")
        data = json.loads(path.read_text())
        for key, objects in data.items():
            if key.startswith("objects_after_"):
                checks.extend(prop for obj in objects for prop in obj["properties"])
    if not checks or not all(check["matched"] is True for check in checks):
        raise RuntimeError("Native recipe properties failed")
    log = (root / "pytest-full.log").read_text(encoding="utf-8", errors="replace")
    tests = re.search(r"(\d+) passed, (\d+) skipped in ([\d.]+)s", log)
    if tests is None:
        raise RuntimeError("Completed full regression record required")
    installed = (json.loads(args.installed_smoke.read_text()) if args.installed_smoke
                 else {"status": "not_recorded"})
    result = {
        "schema_version": "1.0", "validation_date": "2026-10-30", "package_version": "0.8.0",
        "development_surface": {"mcp_tools": 18, "mcp_resources": 43, "lumerical_cli_commands": 11,
                                "canonical_recipes": 6, "lumerical_geometry_recipes": 2},
        "native_recipe_cad": {"status": cad["status"], "case_count": len(cad["cases"]),
            "primitive_count": sum(item["primitive_count"] for item in cad["cases"].values()),
            "property_checks": len(checks),
            "max_absolute_property_error": max(item["max_absolute_error"] for item in checks),
            "solve_invoked": cad["solve_invoked"], "session_closed": cad["session_closed"],
            "owned_license_processes_exited": cad["local_license"]["owned_processes_exited"]},
        "matched_solver_comparisons": comparisons,
        "retained_negative_configurations": [name for name, item in comparisons.items()
                                             if not item["power_agreement_passed"]],
        "tested_final_control_powers_within_budget": bool(comparisons["straight"]["power_agreement_passed"]
                                                         and comparisons["coupler_expanded"]["power_agreement_passed"]),
        "offline_regression": {"passed": int(tests[1]), "skipped": int(tests[2]), "seconds": float(tests[3]),
                               "skip_reason": "Windows symlink privilege"},
        "installed_stdio_smoke": installed,
        "physics_accepted": False,
        "limits": ["Selected-mode powers only; no independent modal-phase alignment.",
                   "Expanded-window pass is not full boundary/mesh/time convergence.",
                   "No general superiority in accuracy, speed, 3D or multiphysics is claimed.",
                   "MCP and generic adapter are nonexecuting; explicit CLI owns native execution."],
    }
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"regression": result["offline_regression"],
                      "native_cad_checks": len(checks), "retained_negative": result["retained_negative_configurations"],
                      "tested_final_controls_passed": result["tested_final_control_powers_within_budget"],
                      "installed_stdio_status": installed["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
