"""Receipt-bound device export, mesh comparison and shared optimization steps."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from ..exceptions import InvalidInputError
from ..lumerical_exchange import export_lumerical_sparameters, normalize_lumerical_sparameters
from ..models import OptimizationSpec, OptimizationTrial
from ..models.io import atomic_create_text, atomic_write_text, load_contract, write_contract
from ..native_devices import load_native_json
from ..optimization import spec_fingerprint, suggest_candidate


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_device_run(receipt_file: Path, *, require_diagnostics: bool = False) -> dict[str, Any]:
    """Verify every recorded artifact and complete common-basis source data."""
    receipt_file = Path(receipt_file).resolve()
    root = receipt_file.parent
    receipt = load_native_json(receipt_file)
    result = receipt.get("result", {})
    if (receipt.get("operation") != "fdtd-device" or receipt.get("status") != "completed"
            or receipt.get("native_execution") is not True or receipt.get("solve_completed") is not True):
        raise InvalidInputError("A completed native fdtd-device receipt is required")
    if not isinstance(result, dict):
        raise InvalidInputError("Device result must be an object")
    if result.get("matrix_complete") is not True or result.get("basis_consistent") is not True:
        raise InvalidInputError("Device data needs complete columns in a verified common modal basis")
    if require_diagnostics and result.get("diagnostic_passed") is not True:
        raise InvalidInputError("Device diagnostics failed; this result cannot train optimization")
    artifacts = receipt.get("artifacts", {})
    if (not isinstance(artifacts, dict)
            or not {"request.json", "geometry.json", "source_dataset.json", "raw.npz"} <= artifacts.keys()):
        raise InvalidInputError("Device receipt does not bind the required raw artifacts")
    for name, item in artifacts.items():
        if not isinstance(name, str) or not isinstance(item, dict) or not {"bytes", "sha256"} <= item.keys():
            raise InvalidInputError("Malformed device artifact record")
        if (isinstance(item["bytes"], bool) or not isinstance(item["bytes"], int) or item["bytes"] < 0
                or not isinstance(item["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise InvalidInputError("Malformed device artifact size or SHA-256")
        path = root / name
        if Path(name).is_absolute() or not path.resolve().is_relative_to(root) or path.is_symlink():
            raise InvalidInputError("Invalid device receipt artifact path")
        if not path.is_file() or path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
            raise InvalidInputError(f"Device artifact changed or missing: {name}")
    data = normalize_lumerical_sparameters(load_native_json(root / "source_dataset.json"))
    columns = result.get("source_columns", [])
    if not isinstance(columns, list) or any(not isinstance(row, dict) for row in columns):
        raise InvalidInputError("Device source columns must be an array of objects")
    if [row.get("source_port") for row in columns] != data["port_order"]:
        raise InvalidInputError("Actual source-column identities do not match the exported channel order")
    if (any(isinstance(row.get("source_index"), bool) or not isinstance(row.get("source_index"), int)
            for row in columns)
            or [row.get("source_index") for row in columns] != list(range(len(data["port_order"])))):
        raise InvalidInputError("Source-column indices are missing or duplicated")
    for row in columns:
        if row.get("source_port_readback") != row["source_port"] or row.get("source_mode_readback") != "mode 1":
            raise InvalidInputError("Source group readback does not identify the declared selected input")
        if any(not isinstance(row.get(key), str) or row[key] not in artifacts for key in ("source_model", "raw")):
            raise InvalidInputError("Each source column must retain its native model and raw arrays")
    from .runtime import validate_request

    request = validate_request(load_native_json(root / "request.json"))
    if request["operation"] != "fdtd-device" or request["parameters"]["family"] != result.get("family"):
        raise InvalidInputError("Request and actual device family differ")
    expected_level = ("2d-scalar-index-surrogate" if request["parameters"]["model_dimension"] == "2d"
                      else "full-wave-3d")
    if data["model_level"] != expected_level or result.get("model_level") != expected_level:
        raise InvalidInputError("Requested and exported model levels differ")
    if (data["producer"]["product"] != "FDTD" or data["conventions"]["time_dependence"] != "exp(-iwt)"
            or any(channel["mode"] != request["parameters"]["mode_selection"] for channel in data["channels"])):
        raise InvalidInputError("Exported native product, phasor convention or selected mode differs from the request")
    try:
        with np.load(root / "raw.npz", allow_pickle=False) as raw:
            frequency = np.asarray(raw["frequency_hz"])
            matrix = np.asarray(raw["s_matrix"])
    except (OSError, ValueError, KeyError) as exc:
        raise InvalidInputError("Native raw artifact must contain numeric frequency_hz and s_matrix arrays") from exc
    count = len(data["port_order"])
    if (frequency.dtype.kind not in "fiu" or frequency.ndim != 1 or not frequency.size
            or not np.isfinite(frequency).all() or np.any(frequency <= 0)
            or len(np.unique(frequency)) != frequency.size
            or matrix.dtype.kind not in "fc" or matrix.shape != (frequency.size, count, count)
            or not np.isfinite(matrix).all()):
        raise InvalidInputError("Native raw spectral axis or complete matrix has invalid shape or values")
    order = np.argsort(299792458e9 / frequency)
    if not np.array_equal(matrix[order], _matrix(data)) or not np.allclose(
        299792458e9 / frequency[order], data["wavelengths_nm"], rtol=1e-14, atol=0,
    ):
        raise InvalidInputError("Exported matrix differs from its raw source-bound native array")
    return {"receipt": receipt, "receipt_sha256": _sha(receipt_file), "root": root,
            "request": request, "data": data}


def _matrix(data: dict[str, Any]) -> np.ndarray:
    values = np.asarray(data["s_matrices"], dtype=float)
    return values[..., 0] + 1j * values[..., 1]


def export_device_run(receipt_file: Path, output: Path, *, project_root: Path,
                      passivity_tolerance: float | None = None) -> dict[str, Any]:
    if passivity_tolerance is not None and (isinstance(passivity_tolerance, bool)
        or not isinstance(passivity_tolerance, int | float) or not math.isfinite(passivity_tolerance)
        or not 0 <= passivity_tolerance <= 0.05):
        raise InvalidInputError("Explicit circuit passivity_tolerance must be in [0, 0.05]")
    run = load_device_run(receipt_file)
    receipt = export_lumerical_sparameters(run["root"] / "source_dataset.json", output, project_root=project_root)
    if passivity_tolerance is not None:
        receipt["component"]["passivity_tolerance"] = passivity_tolerance
        metadata_path = project_root.resolve() / receipt["metadata_path"]
        metadata = load_native_json(metadata_path)
        metadata["component"] = receipt["component"]
        metadata["numerical_acceptance"] = {
            "passivity_tolerance": passivity_tolerance, "source": "explicit export argument",
            "data_modified": False, "scope": "circuit input validation only; not physical device acceptance",
        }
        atomic_write_text(metadata_path, json.dumps(metadata, indent=2, allow_nan=False))
        receipt["metadata_sha256"] = _sha(metadata_path)
    result = run["receipt"]["result"]
    return {**receipt, "native_receipt_sha256": run["receipt_sha256"],
            "native_diagnostic_passed": result.get("diagnostic_passed") is True,
            "native_diagnostic_checks": copy.deepcopy(result.get("diagnostic_checks", {})),
            "physics_accepted": False}


def compare_device_runs(coarse: Path, fine: Path) -> dict[str, Any]:
    left, right = load_device_run(coarse), load_device_run(fine)
    a, b = copy.deepcopy(left["request"]), copy.deepcopy(right["request"])
    for request in (a, b):
        for key in ("mesh_accuracy", "simulation_time_s", "auto_shutoff_min", "port_buffer_m"):
            request["parameters"].pop(key, None)
    if a != b:
        raise InvalidInputError("Mesh/PML comparison needs matching geometry, materials, modes and spectral settings")
    plane_roundoff = _channel_plane_roundoff(left["data"]["channels"], right["data"]["channels"])
    for key in ("wavelengths_nm", "conventions", "model_level"):
        if left["data"][key] != right["data"][key]:
            raise InvalidInputError(f"Cross-run {key} differs; no implicit alignment is performed")
    difference = np.abs(np.abs(_matrix(left["data"])) ** 2 - np.abs(_matrix(right["data"])) ** 2)
    return {"max_absolute_power_change": float(difference.max()),
            "per_wavelength_max_power_change": difference.max(axis=(1, 2)).tolist(),
            "complex_phase_convergence": "not asserted; independent-run modal gauge alignment is separate",
            "max_reference_plane_roundoff_m": plane_roundoff,
            "reference_plane_roundoff_tolerance_m": 1e-15,
            "receipt_sha256": [left["receipt_sha256"], right["receipt_sha256"]], "physics_accepted": False}


def _channel_plane_roundoff(left: list[dict[str, str]], right: list[dict[str, str]]) -> float:
    """Allow only machine roundoff in native plane coordinates; never shift data."""
    if len(left) != len(right):
        raise InvalidInputError("Cross-run channels differ; no implicit alignment is performed")
    maximum = 0.0
    pattern = re.compile(r"([xy])=([+-]?[\d.]+(?:[eE][+-]?\d+)?) m; native port E dataset")
    for a, b in zip(left, right, strict=True):
        fields_a = {key: value for key, value in a.items() if key != "reference_plane"}
        fields_b = {key: value for key, value in b.items() if key != "reference_plane"}
        if fields_a != fields_b:
            raise InvalidInputError("Cross-run channels differ; no implicit alignment is performed")
        if a["reference_plane"] == b["reference_plane"]:
            continue
        first, second = (pattern.fullmatch(item["reference_plane"]) for item in (a, b))
        if first is None or second is None or first[1] != second[1]:
            raise InvalidInputError("Cross-run channels differ; reference planes cannot be aligned implicitly")
        difference = abs(float(first[2]) - float(second[2]))
        if not math.isfinite(difference) or difference > 1e-15:
            raise InvalidInputError("Cross-run channels differ beyond reference-plane roundoff tolerance")
        maximum = max(maximum, difference)
    return maximum


def objective_value(data: dict[str, Any], objective: dict[str, Any]) -> float:
    if set(objective) != {"name", "out_port", "in_port", "statistic"}:
        raise InvalidInputError("objective needs name, out_port, in_port and statistic")
    try:
        row, column = (data["port_order"].index(objective[key]) for key in ("out_port", "in_port"))
    except ValueError as exc:
        raise InvalidInputError("Objective channel is not in the complete native matrix") from exc
    power = np.abs(_matrix(data)[:, row, column]) ** 2
    statistic = objective["statistic"]
    if statistic == "mean_power":
        return float(power.mean())
    if statistic == "min_power":
        return float(power.min())
    if statistic == "max_power":
        return float(power.max())
    if statistic == "mean_insertion_loss_db" and np.all(power > 0):
        return float((-10 * np.log10(power)).mean())
    raise InvalidInputError("Unsupported objective statistic or undefined zero-power insertion loss")


def _constraints(data: dict[str, Any]) -> dict[str, float]:
    matrix = _matrix(data)
    return {"max_reflection_power": float((np.abs(np.diagonal(matrix, axis1=1, axis2=2)) ** 2).max()),
            "max_singular_value": float(np.linalg.svd(matrix, compute_uv=False).max()),
            "max_reciprocity_error": float(np.abs(matrix - matrix.transpose(0, 2, 1)).max())}


def optimize_step(config_file: Path, output: Path, *, execute: bool = False, install_root: Path | None = None,
                  local_license: bool = False, license_server: str | None = None, threads: int = 2) -> dict[str, Any]:
    """One budgeted ask/evaluate/tell step using the unchanged shared proposer."""
    from .runtime import _check_output, run_request, validate_request

    config_file = Path(config_file).resolve()
    config = load_native_json(config_file)
    if set(config) != {"schema_version", "spec_file", "base_request", "trials_dir", "objective", "parameter_map"}:
        raise InvalidInputError("Optimization config fields differ from the fixed workflow schema")
    if config["schema_version"] != "1.0":
        raise InvalidInputError("Optimization config schema_version must be 1.0")
    spec = load_contract(config_file.parent / config["spec_file"], "OptimizationSpec")
    if not isinstance(spec, OptimizationSpec) or spec.solver_backend != "lumerical-fdtd-device":
        raise InvalidInputError("OptimizationSpec must explicitly select lumerical-fdtd-device")
    base = validate_request(load_native_json(config_file.parent / config["base_request"]))
    if base["operation"] != "fdtd-device":
        raise InvalidInputError("Optimization base request must be fdtd-device")
    expected_fidelity = "full-wave-2d-scalar" if base["parameters"]["model_dimension"] == "2d" else "full-wave-3d"
    if spec.fidelity.value != expected_fidelity:
        raise InvalidInputError("Optimization fidelity must match the actual device model dimension")
    mapping = config["parameter_map"]
    if not isinstance(mapping, dict) or set(mapping) != {item["name"] for item in spec.variables}:
        raise InvalidInputError("parameter_map must bind exactly the optimization variables")
    for value in mapping.values():
        if not isinstance(value, str) or len(value.split(".")) != 2 or not value.startswith("geometry_parameters."):
            raise InvalidInputError("Only explicit geometry_parameters.FIELD mappings are supported")
    if len(set(mapping.values())) != len(mapping):
        raise InvalidInputError("Optimization variables cannot target the same geometry parameter")
    if (not isinstance(config["objective"], dict) or len(spec.objectives) != 1
            or config["objective"].get("name") != spec.objectives[0]["name"]):
        raise InvalidInputError("Workflow objective must match the single frozen specification objective")
    objective = config["objective"]
    if set(objective) != {"name", "out_port", "in_port", "statistic"} or objective["statistic"] not in {
        "mean_power", "min_power", "max_power", "mean_insertion_loss_db",
    }:
        raise InvalidInputError("Objective needs explicit channels and a supported power or insertion-loss statistic")
    from .device_geometry import build_device_geometry

    ports = [port["name"] for port in build_device_geometry(
        base["parameters"]["family"], base["parameters"]["geometry_parameters"])["ports"]]
    for variable in spec.variables:
        target = mapping[variable["name"]].split(".")[1]
        if not target.endswith("_um") or variable["unit"] != "um":
            raise InvalidInputError("Continuous native geometry optimization requires an explicit um parameter/unit")
    if objective["out_port"] not in ports or objective["in_port"] not in ports:
        raise InvalidInputError("Objective ports are absent from the shared device geometry")
    allowed_constraints = {"max_reflection_power", "max_singular_value", "max_reciprocity_error"}
    if any(item["name"] not in allowed_constraints for item in spec.constraints):
        raise InvalidInputError("Unknown constraint metric for native FDTD evaluator")
    binding = {"base": base, "parameter_map": mapping, "objective": config["objective"]}
    marker = "lumerical-workflow-sha256:" + hashlib.sha256(
        json.dumps(binding, sort_keys=True, allow_nan=False).encode()).hexdigest()
    trial_root = (config_file.parent / config["trials_dir"]).resolve()
    history = []
    trial_files = sorted(trial_root.glob("*.json"))
    if len(trial_files) > 512:
        raise InvalidInputError("Optimization reads at most 512 trial files")
    for path in trial_files:
        item = load_contract(path, "OptimizationTrial")
        if not isinstance(item, OptimizationTrial) or marker not in item.provenance:
            raise InvalidInputError("Optimization history belongs to a different frozen workflow")
        history.append(item)
    proposal = suggest_candidate(spec, history)
    if proposal["action"] != "evaluate_candidate":
        return {"status": "stopped", "proposal": proposal, "will_execute": False, "physics_accepted": False}
    candidate = copy.deepcopy(base)
    for name, target in mapping.items():
        candidate["parameters"]["geometry_parameters"][target.split(".")[1]] = proposal["parameters"][name]
    candidate = validate_request(candidate)
    folder = _check_output(Path(output))
    folder.mkdir(parents=True)
    atomic_create_text(folder / "candidate.json", json.dumps(candidate, indent=2, allow_nan=False))
    plan = {"status": "planned", "will_execute": execute, "proposal": proposal,
            "candidate": candidate, "workflow_provenance_marker": marker, "physics_accepted": False}
    atomic_create_text(folder / "plan.json", json.dumps(plan, indent=2, allow_nan=False))
    if not execute:
        return plan
    trial_root.mkdir(parents=True, exist_ok=True)
    index = len(history)
    trial = OptimizationTrial(
        stable_id=f"trial:lumerical-{index:04d}", name=f"Lumerical device trial {index}",
        source="receipt-bound native FDTD evaluation", optimization_spec_id=spec.stable_id,
        run_id=f"run:lumerical-{index:04d}", parameters=proposal["parameters"], status="running",
        provenance=["optimization-spec-sha256:" + spec_fingerprint(spec), marker],
    )
    trial_file = trial_root / f"trial-{index:04d}.json"
    if trial_file.exists():
        raise InvalidInputError("Optimization trial identity collision")
    # The pending record blocks another shared-proposer ask while this solve runs.
    atomic_create_text(trial_file, json.dumps({"contract_type": "OptimizationTrial", **trial.model_dump(mode="json")},
                                             indent=2, allow_nan=False))
    try:
        receipt = run_request(candidate, folder / "native", install_root=install_root, timeout_s=spec.timeout_s,
                              threads=threads, local_license=local_license, license_server=license_server)
        if receipt["status"] != "completed":
            raise InvalidInputError("Native device execution failed: " + receipt["status"])
        run = load_device_run(folder / "native/receipt.json", require_diagnostics=True)
        trial.objectives = {config["objective"]["name"]: objective_value(run["data"], config["objective"])}
        constraints = _constraints(run["data"])
        names = {item["name"] for item in spec.constraints}
        if not names <= constraints.keys():
            raise InvalidInputError("Unknown constraint metric for native FDTD evaluator")
        trial.constraint_results = {name: constraints[name] for name in names}
        trial.provenance.append("native-receipt-sha256:" + run["receipt_sha256"])
        trial.status = "succeeded"
    except Exception as error:
        trial.status, trial.failure = "failed", type(error).__name__
        plan["error"] = str(error)
    write_contract(trial_file, trial)
    write_contract(folder / "trial.json", trial)
    return {**plan, "status": trial.status, "trial": trial.model_dump(mode="json"), "trial_file": str(trial_file)}
