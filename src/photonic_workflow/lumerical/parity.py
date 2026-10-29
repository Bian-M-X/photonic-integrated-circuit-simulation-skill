"""Receipt-bound, power-only comparison of matched COMSOL/FDTD scalar models.

This compares approximations to the same declared interior wave problem. The
two solvers retain different open-boundary and discretization implementations;
agreement is a diagnostic and never grants a device or solver-adoption gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from ..exceptions import InvalidInputError
from ..native_backend import verify_native_bundle
from ..native_devices import calibrate_native_run, load_native_json, native_request
from .device_geometry import build_device_geometry
from .runtime import validate_request
from .workflow import load_device_run

_GEOMETRY_KEYS = ("family", "parameters", "bbox_um", "primitives", "ports", "model_level")
_PLANE = re.compile(r"([xy])=([+-]?[\d.]+(?:[eE][+-]?\d+)?) m; native port E dataset")
# COMSOL's recorded rendering bounds are float-quantized (about 0.03 pm
# transverse center roundoff in the native coupler). This is not a tolerance
# on the longitudinal reference-plane comparison or on S/power agreement.
_COMSOL_TRANSVERSE_BBOX_TOLERANCE_UM = 1e-6


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _budget(value: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, int | float)
            or not math.isfinite(value) or not 0 < value <= 0.2):
        raise InvalidInputError("power_tolerance must be an explicit finite power fraction in (0, 0.2]")
    return float(value)


def make_benchmark_plan(family: str, *, power_tolerance: float = 0.03) -> dict[str, Any]:
    """Freeze two scalar controls, exact common spectral samples and a budget.

    This is a plan, not a solver call. The default 0.03 is a screening allowance
    of three absolute power percentage points, not a production specification.
    """
    if family not in {"straight", "directional-coupler"}:
        raise InvalidInputError("The paired benchmark supports straight and directional-coupler controls")
    tolerance = _budget(power_tolerance)
    fdtd = validate_request({"schema_version": "1.0", "operation": "fdtd-device", "parameters": {
        "family": family, "model_dimension": "2d", "core_index": 2.6, "clad_index": 1.45,
        "mesh_accuracy": 5, "frequency_points": 5,
        "wavelength_start_m": 1.5e-6, "wavelength_stop_m": 1.6e-6,
    }})
    p = fdtd["parameters"]
    frequency = np.linspace(299792458 / p["wavelength_stop_m"], 299792458 / p["wavelength_start_m"],
                            p["frequency_points"])
    waves = sorted((299792458e9 / frequency).tolist())
    comsol = {"schema_version": "1.0", "family": family, "parameters": p["geometry_parameters"],
              "wavelengths_nm": waves, "materials": {"core_index": 2.6, "cladding_index": 1.45},
              "mesh": {"core_mesh_um": 0.04, "cladding_mesh_um": 0.14, "port_mesh_um": 0.02},
              "stage": "solve", "export_fields": False}
    geometry, _ = native_request(comsol)
    target = build_device_geometry(family, p["geometry_parameters"])
    if any(geometry[key] != target[key] for key in _GEOMETRY_KEYS):
        raise InvalidInputError("Shared benchmark builders produced different geometry")
    return {"schema_version": "1.0", "family": family, "model_level": "2d-scalar-index-surrogate",
            "comsol_request": comsol, "lumerical_request": fdtd,
            "power_tolerance": tolerance, "comparison": "complete selected-mode powers only",
            "geometry_sha256": hashlib.sha256(_canonical({key: geometry[key] for key in _GEOMETRY_KEYS})).hexdigest(),
            "refinement": {"comsol_mesh": {"core_mesh_um": 0.025, "cladding_mesh_um": 0.10,
                                             "port_mesh_um": 0.01}, "lumerical_mesh_accuracy": 6},
            "boundaries": {"comsol": "finite exterior modal windows and scattering boundary",
                           "lumerical": "interior modal planes, extended leads and PML"},
            "will_execute": False, "physics_accepted": False,
            "limits": ["No native mode-gauge alignment or complex-phase parity is supplied.",
                       "Use each backend's mesh/boundary/time refinement before interpreting agreement.",
                       "The 2D scalar index problem is not a calibrated 3D waveguide stack."]}


def _comsol_planes(console: str, ports: list[dict[str, Any]]) -> list[tuple[str, float]]:
    records = {}
    for line in console.splitlines():
        if not line.startswith("PIC PORT_GEOMETRY "):
            continue
        fields = line.split()
        try:
            if len(fields) != 8:
                raise ValueError("arity")
            index = int(fields[2])
            values = [float(value) for value in fields[3:]]
            if index in records or not all(math.isfinite(value) for value in values):
                raise ValueError("duplicate or nonfinite port geometry")
            records[index] = values
        except (ValueError, OverflowError) as exc:
            raise InvalidInputError("Invalid actual COMSOL port-geometry record") from exc
    if set(records) != set(range(1, len(ports) + 1)):
        raise InvalidInputError("Actual COMSOL reference-plane records are incomplete")
    result = []
    for index, port in enumerate(ports, 1):
        length, xmin, xmax, ymin, ymax = records[index]
        axis = "x" if port["side"] in {"left", "right"} else "y"
        low, high = (xmin, xmax) if axis == "x" else (ymin, ymax)
        center = port["center_um"][0 if axis == "x" else 1]
        cross_low, cross_high = (ymin, ymax) if axis == "x" else (xmin, xmax)
        cross_center = port["center_um"][1 if axis == "x" else 0]
        if (abs(high - low) > 1e-8 or abs((high + low) / 2 - center) > 1e-8
                or cross_high < cross_low
                or abs((cross_high + cross_low) / 2 - cross_center) > _COMSOL_TRANSVERSE_BBOX_TOLERANCE_UM
                or abs(cross_high - cross_low - port["window_um"]) > 1e-5
                or abs(length - port["window_um"]) > 1e-5):
            raise InvalidInputError("Actual COMSOL port plane/window differs from shared geometry")
        result.append((axis, (high + low) * 0.5e-6))
    return result


def _load_comsol(receipt_path: Path) -> dict[str, Any]:
    receipt = load_native_json(receipt_path)
    if receipt.get("status") != "completed" or receipt.get("stage") != "solve":
        raise InvalidInputError("Comparison requires a completed COMSOL driven receipt")
    # Calibrate first: this binds generated source, executable, raw console and bundle.
    result = calibrate_native_run(receipt_path)
    bundle = verify_native_bundle(receipt["bundle"])
    root = receipt_path.resolve().parent
    return {"result": result, "geometry": bundle["geometry"], "config": bundle["config"],
            "planes": _comsol_planes((root / "console.log").read_text(encoding="utf-8", errors="replace"),
                                     bundle["geometry"]["ports"]),
            "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()}


def _matrix(value: Any, count: int, spectral_count: int) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidInputError("Comparison needs complete finite complex matrices") from exc
    if array.shape != (spectral_count, count, count, 2) or not np.isfinite(array).all():
        raise InvalidInputError("Comparison needs complete finite complex matrices")
    return array[..., 0] + 1j * array[..., 1]


def compare_solver_runs(comsol_receipt: Path, lumerical_receipt: Path, *, power_tolerance: float) -> dict[str, Any]:
    """Compare all powers from matched, receipt-bound native scalar experiments.

    Every sample/channel is used. There is no interpolation, channel remapping,
    phase fit, reference-plane translation, conjugation or matrix correction.
    """
    tolerance = _budget(power_tolerance)
    comsol = _load_comsol(Path(comsol_receipt))
    fdtd = load_device_run(Path(lumerical_receipt))
    p, geometry, config = fdtd["request"]["parameters"], comsol["geometry"], comsol["config"]
    data, result = fdtd["data"], comsol["result"]
    if (geometry["family"] not in {"straight", "directional-coupler"}
            or p["model_dimension"] != "2d" or p["mode_selection"] != "fundamental TM mode"
            or data["model_level"] != "2d-scalar-index-surrogate"
            or result["model_level"] != "2d-scalar-index-surrogate"):
        raise InvalidInputError("Paired comparison requires the same supported scalar-Ez model level")
    other = load_native_json(fdtd["root"] / "geometry.json")["source"]
    if any(geometry[key] != other.get(key) for key in _GEOMETRY_KEYS):
        raise InvalidInputError("Cross-solver geometry or semantic ports differ")
    if (p["core_material_model"] is not None or p["clad_material_model"] is not None
            or p["core_index"] != config["core_index"] or p["clad_index"] != config["cladding_index"]
            or config["active_index"] != config["core_index"] or config["active_extinction"] != 0):
        raise InvalidInputError("Paired comparison requires matching constant, lossless scalar materials")
    ports = [port["name"] for port in geometry["ports"]]
    if ports != result["port_order"] or ports != data["port_order"]:
        raise InvalidInputError("Cross-solver port/source order differs")
    waves = np.asarray(result["wavelengths_nm"], dtype=float)
    other_waves = np.asarray(data["wavelengths_nm"], dtype=float)
    if (waves.ndim != 1 or waves.shape != other_waves.shape or not waves.size or not np.isfinite(waves).all()
            or np.any(np.diff(waves) <= 0) or not np.allclose(waves, other_waves, rtol=1e-13, atol=1e-9)):
        raise InvalidInputError("Cross-solver spectral grids differ; no interpolation is performed")
    maximum_plane_difference = 0.0
    for port, (axis, position), channel in zip(geometry["ports"], comsol["planes"], data["channels"], strict=True):
        match = _PLANE.fullmatch(channel["reference_plane"])
        incoming = ("+" if port["side"] in {"left", "bottom"} else "-") + axis
        if match is None or match[1] != axis or channel["incoming_direction"] != incoming:
            raise InvalidInputError("Cross-solver actual port plane/direction is incompatible")
        difference = abs(float(match[2]) - position)
        if not math.isfinite(difference) or difference > 1e-15:
            raise InvalidInputError("Cross-solver reference planes differ beyond coordinate roundoff")
        maximum_plane_difference = max(maximum_plane_difference, difference)
    a, b = (_matrix(item, len(ports), len(waves)) for item in (result["s_matrices"], data["s_matrices"]))
    difference = np.abs(np.abs(a) ** 2 - np.abs(b) ** 2)
    maximum = float(difference.max())
    passed = bool(maximum <= tolerance)
    return {
        "schema_version": "1.0", "family": geometry["family"], "model_level": data["model_level"],
        "status": "within_declared_power_tolerance" if passed else "outside_declared_power_tolerance",
        "power_agreement_passed": passed, "power_tolerance": tolerance,
        "max_absolute_power_change": maximum,
        "rms_absolute_power_change": float(np.sqrt(np.mean(difference ** 2))),
        "per_wavelength_max_power_change": difference.max(axis=(1, 2)).tolist(),
        "wavelengths_nm": waves.tolist(), "port_order": ports, "matrix_element_count": int(difference.size),
        "comsol_guided_power_per_source": np.sum(np.abs(a) ** 2, axis=1).tolist(),
        "lumerical_guided_power_per_source": np.sum(np.abs(b) ** 2, axis=1).tolist(),
        "max_reference_plane_roundoff_m": maximum_plane_difference,
        "reference_plane_roundoff_tolerance_m": 1e-15,
        "comsol_transverse_bbox_tolerance_m": _COMSOL_TRANSVERSE_BBOX_TOLERANCE_UM * 1e-6,
        "geometry_sha256": hashlib.sha256(_canonical({key: geometry[key] for key in _GEOMETRY_KEYS})).hexdigest(),
        "receipt_sha256": {"comsol": comsol["receipt_sha256"], "lumerical": fdtd["receipt_sha256"]},
        "lumerical_diagnostic_passed": fdtd["receipt"]["result"].get("diagnostic_passed") is True,
        "complex_phase_comparable": False,
        "complex_phase_comparison": "not asserted; independent native modal gauges are not aligned",
        "boundary_implementations": {"comsol": "finite exterior scattering boundary",
                                     "lumerical": "extended waveguide/PML backing"},
        "transformations_applied": [], "physics_accepted": False,
        "limits": ["Agreement is restricted to declared selected-mode powers and the tested samples.",
                   "Boundary, modal truncation, mesh and finite-time errors require independent budgets.",
                   "No claim of equal complex phase, group delay, runtime or production qualification."]}
