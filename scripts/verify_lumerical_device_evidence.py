"""Verify the retained 2026-10 native campaign and emit a compact public record.

No solver or license manager is started. Run after both campaign scripts finish.
Raw vendor files remain in the local run directory and are not redistributed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from photonic_workflow.lumerical.workflow import compare_device_runs, load_device_run, objective_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.runs.resolve()
    initial = json.loads((root / "campaign-summary.json").read_text(encoding="utf-8"))
    final = json.loads((root / "final-native-summary.json").read_text(encoding="utf-8"))
    paths = {name: root / name for name in initial if name != "local_license"}
    paths.update({f"ring-adddrop-m{mesh}": root / f"ring-adddrop-m{mesh}" for mesh in (5, 6)})
    paths.update({f"optimization-{index}": root / f"native-optimization/step-{index:02d}/native"
                  for index in range(2)})
    runs = {}
    for name, path in paths.items():
        run = load_device_run(path / "receipt.json")
        receipt, result = run["receipt"], run["receipt"]["result"]
        runs[name] = {
            "directory": str(path.relative_to(root)).replace("\\", "/"),
            "receipt_sha256": run["receipt_sha256"], "artifact_count": len(receipt["artifacts"]),
            "native_execution": receipt["native_execution"], "status": receipt["status"],
            "family": result["family"], "model_level": result["model_level"],
            "source_count": len(result["source_columns"]), "frequency_points": len(result["frequency_hz"]),
            "matrix_complete": result["matrix_complete"], "basis_consistent": result["basis_consistent"],
            "diagnostic_passed": result["diagnostic_passed"], "diagnostic_checks": result["diagnostic_checks"],
            "max_singular_value": result["max_singular_value"],
            "max_reciprocity_error": result["max_reciprocity_error"],
            "mesh_accuracy": run["request"]["parameters"]["mesh_accuracy"],
            "simulation_time_s": run["request"]["parameters"]["simulation_time_s"],
            "vendor_version": result["vendor_version"],
        }
    objective = json.loads((root / "native-optimization/config.json").read_text())["objective"]
    trials = []
    for index in range(2):
        path = root / f"native-optimization/trials/trial-{index:04d}.json"
        trial = json.loads(path.read_text())
        run = load_device_run(paths[f"optimization-{index}"] / "receipt.json", require_diagnostics=True)
        observed = objective_value(run["data"], objective)
        if observed != trial["objectives"][objective["name"]]:
            raise RuntimeError("Stored optimization objective differs from native raw data")
        if "native-receipt-sha256:" + run["receipt_sha256"] not in trial["provenance"]:
            raise RuntimeError("Stored optimization trial is not bound to its native receipt")
        trials.append({"parameters": trial["parameters"], "objectives": trial["objectives"],
                       "constraint_results": trial["constraint_results"], "status": trial["status"],
                       "trial_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    material = load_device_run(paths["straight-dispersive"] / "receipt.json")["receipt"]["result"]
    circuit = json.loads((root / "circuit-verification-final/summary.json").read_text())
    installed = json.loads((root / "installed-lumerical-smoke/summary.json").read_text())
    regression = re.search(r"(\d+) passed, (\d+) skipped in ([\d.]+)s",
                           (root / "pytest-full.log").read_text(encoding="utf-8", errors="replace"))
    if regression is None or installed["status"] != "passed" or circuit["status"] != "passed":
        raise RuntimeError("Complete regression, installation and circuit records are required")
    result = {
        "schema_version": "1.0", "date": "2026-10-29", "native_runs": runs,
        "run_count": len(runs), "solved_source_columns": sum(row["source_count"] for row in runs.values()),
        "diagnostic_pass_count": sum(row["diagnostic_passed"] for row in runs.values()),
        "retained_negative_runs": [name for name, row in runs.items() if not row["diagnostic_passed"]],
        "straight_mesh_power_comparison": compare_device_runs(
            paths["straight-m3"] / "receipt.json", paths["straight-m5"] / "receipt.json"),
        "coupler_mesh_power_comparison": compare_device_runs(
            paths["coupler-m3"] / "receipt.json", paths["coupler-m5"] / "receipt.json"),
        "ring_fine_mesh_power_comparison": compare_device_runs(
            paths["ring-adddrop-m5"] / "receipt.json", paths["ring-adddrop-m6"] / "receipt.json"),
        "native_material_fit_errors": {name: values["max_index_fit_error"]
                                       for name, values in material["sampled_materials"].items()},
        "circuit_integration": {key: circuit[key] for key in (
            "status", "native_source_bytes_preserved", "raw_complex_data_modified",
            "circuit_passivity_tolerance", "max_cascade_absolute_complex_error", "connected_native_modal_basis",
        )},
        "offline_regression": {"passed": int(regression[1]), "skipped": int(regression[2]),
                               "seconds": float(regression[3]), "skip_reason": "Windows symlink privilege"},
        "installed_smoke": {key: installed[key] for key in (
            "status", "native_execution", "device_plan_families", "shared_material_model_loaded",
            "shared_optimization_plan_loaded", "complex_cascade_matches_independent_product",
        )},
        "optimization_trials": trials,
        "resumed_plan": {"executed": final["optimization-resume-plan"]["will_execute"],
                         "history_count": final["optimization-resume-plan"]["proposal"]["successful_observations"],
                         "parameters": final["optimization-resume-plan"]["proposal"]["parameters"]},
        "local_license_managers_cleaned": bool(initial["local_license"]["owned_processes_exited"]
                                              and final["local_license"]["owned_processes_exited"]),
        "physics_accepted": False,
        "limits": ["Selected-mode smoke, not complete device qualification or solver parity.",
                   "2D scalar surrogate except explicit 3D straight.",
                   "Ring modulator optical footprint only, no native electrical/thermal solve.",
                   "Two optimization initialization trials and a resumed plan, not an established optimum.",
                   "Cross-run complex phase and group delay convergence not asserted."],
    }
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("run_count", "solved_source_columns", "diagnostic_pass_count",
                                                "retained_negative_runs", "local_license_managers_cleaned")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
