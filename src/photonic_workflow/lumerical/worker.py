"""Isolated vendor session worker. Never used by MCP or arbitrary script inputs."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from .runtime import _json, validate_request


def _progress(output: Path, stage: str, **updates: Any) -> dict[str, Any]:
    path = output / "progress.json"
    state = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else {
            "api_imported": False,
            "session_opened": False,
            "solve_invoked": False,
            "solve_completed": False,
            "license_status": "not_checked",
        }
    )
    state.update(stage=stage, **updates)
    path.write_text(_json(state), encoding="utf-8")
    return state


def _failure(error: Exception, state: dict[str, Any]) -> dict[str, Any]:
    """Categorize vendor availability without returning license configuration."""
    text = str(error).lower()
    license_failure = any(word in text for word in ("license", "licence", "flexnet"))
    if license_failure:
        category, message = "license_unavailable", "Vendor session could not obtain or contact its configured license."
    elif state.get("stage") == "api-import":
        category, message = "api_import_failed", "Selected vendor Python API or native library could not be loaded."
    elif not state.get("session_opened"):
        category, message = "session_start_failed", "Vendor application session could not be opened."
    elif not state.get("solve_invoked"):
        category, message = "model_build_failed", "Vendor session opened but model setup or readback failed."
    else:
        category, message = (
            "solver_or_result_failed",
            "Model setup reached the solver, but solve or result export failed.",
        )
    return {
        **state,
        "completed": False,
        "physics_accepted": False,
        "failure_category": category,
        "error": message,
        "error_type": type(error).__name__,
        "license_status": "unavailable" if license_failure else state.get("license_status", "not_checked"),
        "details_log": "worker.log",
    }


def _set(session: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        session.set(key, value)


def _mode(session: Any, p: dict[str, Any], output: Path) -> dict[str, Any]:
    session.addrect()
    _set(
        session,
        {
            "name": "cladding",
            "x": 0.0,
            "x span": 2e-6,
            "y": 0.0,
            "y span": p["span_y_m"] * 2,
            "z": 0.0,
            "z span": p["span_z_m"] * 2,
            "material": "<Object defined dielectric>",
            "index": p["clad_index"],
            "override mesh order from material database": 1,
            "mesh order": 3,
        },
    )
    session.addrect()
    _set(
        session,
        {
            "name": "core",
            "x": 0.0,
            "x span": 2e-6,
            "y": 0.0,
            "y span": p["width_m"],
            "z": 0.0,
            "z span": p["height_m"],
            "material": "<Object defined dielectric>",
            "index": p["core_index"],
            "override mesh order from material database": 1,
            "mesh order": 2,
        },
    )
    session.addfde()
    _set(
        session,
        {
            "solver type": 1,
            "x": 0.0,
            "y": 0.0,
            "y span": p["span_y_m"],
            "z": 0.0,
            "z span": p["span_z_m"],
            "mesh cells y": p["mesh_cells"],
            "mesh cells z": p["mesh_cells"],
            "y min bc": "PML",
            "y max bc": "PML",
            "z min bc": "PML",
            "z max bc": "PML",
        },
    )
    session.setanalysis("wavelength", p["wavelength_m"])
    session.setanalysis("number of trial modes", p["trial_modes"])
    geometry = {
        "core_y_span_m": float(session.getnamed("core", "y span")),
        "core_z_span_m": float(session.getnamed("core", "z span")),
        "core_index": str(session.getnamed("core", "index")),
        "clad_index": str(session.getnamed("cladding", "index")),
        "core_material": str(session.getnamed("core", "material")),
        "clad_material": str(session.getnamed("cladding", "material")),
    }
    session.save(str(output / "model.lms"))
    _progress(output, "solve", solve_invoked=True)
    count = int(session.findmodes())
    _progress(output, "result-export", solve_completed=True)
    modes, arrays = [], {}
    for index in range(1, count + 1):
        name = f"mode{index}"
        neff = complex(np.asarray(session.getdata(name, "neff")).reshape(-1)[0])
        te_fraction = float(np.real(np.asarray(session.getdata(name, "TE polarization fraction")).reshape(-1)[0]))
        modes.append({"mode": name, "neff_real": neff.real, "neff_imag": neff.imag, "te_fraction": te_fraction})
        arrays[f"{name}_neff"] = np.array([neff])
    if count:
        for key in ("y", "z", "Ex", "Ey", "Ez"):
            arrays[f"mode1_{key}"] = np.asarray(session.getdata("mode1", key))
    np.savez_compressed(output / "raw.npz", **arrays)
    session.save(str(output / "model.lms"))
    guided = [
        m
        for m in modes
        if p["clad_index"] < m["neff_real"] < p["core_index"]
        and np.isfinite(m["neff_real"])
        and abs(m["neff_imag"]) < 1e-3
    ]
    checks = {
        "modes_found": count > 0,
        "guided_mode_index_bounds": bool(guided),
        "finite_mode1_fields": count > 0 and all(np.isfinite(value).all() for value in arrays.values()),
        "core_geometry_readback": abs(geometry["core_y_span_m"] - p["width_m"]) < 1e-15
        and abs(geometry["core_z_span_m"] - p["height_m"]) < 1e-15,
        "material_index_readback": abs(float(geometry["core_index"]) - p["core_index"]) < 1e-12
        and abs(float(geometry["clad_index"]) - p["clad_index"]) < 1e-12
        and geometry["core_material"] == "<Object defined dielectric>"
        and geometry["clad_material"] == "<Object defined dielectric>",
    }
    return {
        "model_level": "vector-2d-cross-section-fde",
        "modes": modes,
        "geometry_readback": geometry,
        "diagnostic_checks": checks,
        "diagnostic_passed": all(checks.values()),
        "limitations": [
            "Constant real-index symmetric cladding; no process material dispersion or substrate stack.",
            "One mesh, one cross-section and wavelength do not establish mode convergence.",
        ],
    }


def _fdtd(session: Any, p: dict[str, Any], output: Path, threads: int, engine: Path) -> dict[str, Any]:
    length, span = p["length_m"], p["span_y_m"]
    session.addfdtd()
    _set(
        session,
        {
            "dimension": 1,
            "x": 0.0,
            "x span": length,
            "y": 0.0,
            "y span": span,
            "z": 0.0,
            "background index": p["background_index"],
            "mesh accuracy": p["mesh_accuracy"],
            "simulation time": p["simulation_time_s"],
            "auto shutoff min": 1e-7,
            "x min bc": "PML",
            "x max bc": "PML",
            "y min bc": "Periodic",
            "y max bc": "Periodic",
        },
    )
    session.addplane()
    _set(
        session,
        {
            "name": "source",
            "injection axis": "x",
            "direction": "Forward",
            "x": -0.3 * length,
            "y": 0.0,
            "y span": span,
            "polarization angle": 0.0,
            "wavelength start": p["wavelength_start_m"],
            "wavelength stop": p["wavelength_stop_m"],
        },
    )
    positions = [-0.1 * length, 0.2 * length]
    for index, position in enumerate(positions, 1):
        session.addpower()
        _set(
            session,
            {
                "name": f"probe{index}",
                "monitor type": "2D X-normal",
                "x": position,
                "y": 0.0,
                "y span": span,
                "override global monitor settings": 1,
                "frequency points": p["frequency_points"],
                "spatial interpolation": "nearest mesh cell",
            },
        )
    # Invoke the documented local engine with an explicit CPU thread budget.
    # The parent supervises this worker and all descendants with one wall budget.
    session.save(str(output / "model.fsp"))
    _progress(output, "solve", solve_invoked=True)
    with (output / "engine.log").open("wb") as stream:
        subprocess.run(
            [str(engine), "-t", str(threads), str(output / "model.fsp")],
            cwd=output,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    session.load(str(output / "model.fsp"))
    _progress(output, "result-export", solve_completed=True)
    fields, arrays = [], {}
    sampled_positions = []
    component = None
    for index in (1, 2):
        result = session.getresult(f"probe{index}", "E")
        electric = np.asarray(result["E"])
        freq = np.asarray(result["f"]).reshape(-1)
        for axis in ("x", "y", "z"):
            coordinates = np.asarray(result[axis], dtype=float).reshape(-1)
            if not coordinates.size or not np.isfinite(coordinates).all():
                raise ValueError(f"Missing or nonfinite monitor {axis} coordinates")
            arrays[f"probe{index}_{axis}"] = coordinates
        if arrays[f"probe{index}_x"].size != 1:
            raise ValueError("X-normal monitor must provide exactly one sampled reference plane")
        sampled_positions.append(float(arrays[f"probe{index}_x"][0]))
        # Rectilinear vector datasets end in frequency and Cartesian component.
        if electric.shape[-1] != 3 or electric.shape[-2] != len(freq):
            raise ValueError("Unexpected E dataset axes; refusing to reinterpret frequency/components")
        if component is None:
            # Select one observed transverse polarization consistently for both
            # monitors; both have identical analytic phase in this uniform medium.
            component = 1 + int(np.argmax([np.sum(np.abs(electric[..., k]) ** 2) for k in (1, 2)]))
        field = np.mean(electric[..., component].reshape(-1, len(freq)), axis=0)
        fields.append(field)
        arrays[f"probe{index}_E"] = electric
        arrays[f"probe{index}_T"] = np.asarray(session.transmission(f"probe{index}")).reshape(-1)
        arrays[f"probe{index}_f"] = freq
    frequency = arrays["probe1_f"]
    if not np.isfinite(fields).all() or np.any(np.abs(fields[0]) < 1e-30):
        raise ValueError("Nonfinite or zero reference field; propagation ratio is undefined")
    if not np.array_equal(arrays["probe1_f"], arrays["probe2_f"]):
        raise ValueError("Monitor frequency grids differ; no implicit interpolation is performed")
    if sampled_positions[1] <= sampled_positions[0]:
        raise ValueError("Sampled monitor reference planes must be ordered along forward propagation")
    ratio = fields[1] / fields[0]
    beta = 2 * np.pi * frequency / 299792458.0 * p["background_index"]
    # Frequency monitors snap to mesh cells with this interpolation policy.
    # The exported E dataset coordinates, rather than requested CAD positions,
    # define the actual phase reference planes. Preserve both for audit.
    expected = np.exp(1j * beta * (sampled_positions[1] - sampled_positions[0]))
    expected_requested = np.exp(1j * beta * (positions[1] - positions[0]))
    phase_error = np.angle(ratio / expected)
    amplitude_error = np.abs(np.abs(ratio) - 1.0)
    arrays.update(
        field_ratio=ratio,
        expected_ratio=expected,
        phase_error_rad=phase_error,
        requested_probe_positions_m=np.array(positions),
        sampled_probe_positions_m=np.array(sampled_positions),
        expected_ratio_requested_planes=expected_requested,
        phase_error_requested_planes_rad=np.angle(ratio / expected_requested),
    )
    np.savez_compressed(output / "raw.npz", **arrays)
    session.save(str(output / "model.fsp"))
    max_phase = float(np.max(np.abs(phase_error)))
    max_amplitude = float(np.max(amplitude_error))
    max_power = float(np.max(np.abs(arrays["probe2_T"] - 1.0)))
    checks = {
        "finite_complex_fields": bool(np.isfinite(ratio).all()),
        "amplitude_error_below_5pct": max_amplitude < 0.05,
        "phase_error_below_0p15rad": max_phase < 0.15,
        "power_error_below_5pct": max_power < 0.05,
    }
    return {
        "model_level": "2d-fdtd-uniform-periodic-plane-wave",
        "frequency_hz": frequency.tolist(),
        "probe_positions_m": sampled_positions,
        "requested_probe_positions_m": positions,
        "monitor_displacements_m": [
            actual - requested for actual, requested in zip(sampled_positions, positions, strict=True)
        ],
        "reference_plane_policy": "E-dataset x coordinates; nearest mesh cell interpolation",
        "background_index": p["background_index"],
        "field_component": ("Ex", "Ey", "Ez")[component],
        "solver_command": [engine.name, "-t", str(threads), "model.fsp"],
        "field_ratio_real": ratio.real.tolist(),
        "field_ratio_imag": ratio.imag.tolist(),
        "max_phase_error_rad": max_phase,
        "max_amplitude_error": max_amplitude,
        "max_power_error": max_power,
        "diagnostic_checks": checks,
        "diagnostic_passed": all(checks.values()),
        "limitations": [
            "Uniform medium and transverse periodic boundary diagnostic; no waveguide or device S matrix.",
            "Analytic phase comparison uses exp(-i omega t), forward exp(+i beta x).",
            "Phase reference planes use exported sampled coordinates; requested CAD positions are retained separately.",
            "Local CPU FDTD engine with explicit thread budget; no MPI or resource-preference edits.",
        ],
    }


def _geometry(session: Any, p: dict[str, Any], output: Path) -> dict[str, Any]:
    from ..lumerical_geometry import migrate_geometry

    bridge = migrate_geometry(p["native_request"], height_um=p["height_um"], core_index=p["core_index"])
    observations = []
    for obj in bridge["objects"]:
        if obj["kind"] in {"rectangle", "rect"}:
            session.addrect()
            props = {
                key.replace("_m", "").replace("_", " "): obj[key]
                for key in ("x_min_m", "x_max_m", "y_min_m", "y_max_m", "z_min_m", "z_max_m")
            }
        elif obj["kind"] in {"polygon", "poly"}:
            session.addpoly()
            props = {"vertices": np.asarray(obj["vertices_m"]), "z min": obj["z_min_m"], "z max": obj["z_max_m"]}
        else:
            raise ValueError("Unsupported migrated object kind")
        _set(session, {"name": obj["name"], **props, "material": "<Object defined dielectric>", "index": obj["index"]})
        observed = {
            "name": obj["name"],
            "kind": obj["kind"],
            "index": str(session.getnamed(obj["name"], "index")),
            "material": str(session.getnamed(obj["name"], "material")),
        }
        observed["index_matches"] = abs(float(observed["index"]) - obj["index"]) < 1e-12
        observed["material_matches"] = observed["material"] == "<Object defined dielectric>"
        for key, expected in props.items():
            actual = np.asarray(session.getnamed(obj["name"], key), dtype=float)
            observed[key] = actual.tolist()
            observed[f"{key}_matches"] = bool(np.allclose(actual, expected, rtol=0.0, atol=1e-15))
        observations.append(observed)
    session.save(str(output / "model.fsp"))
    (output / "geometry.json").write_text(_json(bridge), encoding="utf-8")
    checks = {
        "all_objects_readback": len(observations) == len(bridge["objects"]),
        "geometry_values_match": all(
            value for obj in observations for key, value in obj.items() if key.endswith("_matches")
        ),
    }
    return {
        "model_level": "native-cad-geometry-only",
        "solve_executed": False,
        "object_readback": observations,
        "diagnostic_checks": checks,
        "diagnostic_passed": all(checks.values()),
        "limitations": [
            "Actual CAD readback validates geometry transfer, not fields, material dispersion or device performance."
        ],
    }


def execute(request: dict[str, Any], output: Path, api_path: Path, threads: int) -> dict[str, Any]:
    request = validate_request(request)
    _progress(output, "api-import")
    spec = importlib.util.spec_from_file_location("_photonic_lumerical_vendor_api", api_path)
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load selected local lumapi.py")
    api = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = api
    spec.loader.exec_module(api)
    _progress(output, "session-start", api_imported=True)
    operation, p = request["operation"], request["parameters"]
    product = api.MODE if operation == "mode-waveguide" else api.FDTD
    with product(hide=True, serverArgs={"threads": str(threads)}) as session:
        _progress(output, "model-build", session_opened=True, license_status="session_acquired")
        session.newproject()
        session.cd(str(output))
        version = str(session.version())
        if operation == "mode-waveguide":
            result = _mode(session, p, output)
        elif operation == "fdtd-uniform":
            result = _fdtd(session, p, output, threads, api_path.parents[2] / "bin/fdtd-engine.exe")
        elif operation == "fdtd-device":
            from .device import run_fdtd_device

            _progress(output, "device-model-build")
            result = run_fdtd_device(session, p, output, threads, api_path.parents[2] / "bin/fdtd-engine.exe")
            _progress(output, "result-export", solve_completed=True)
        else:
            result = _geometry(session, p, output)
    progress = _progress(output, "completed", session_closed=True)
    return {**progress, "completed": True, "vendor_version": version, "physics_accepted": False, **result}


def main() -> int:
    request_path, output_path, api_path, threads = sys.argv[1:]
    output = Path(output_path)
    try:
        result = execute(
            json.loads(Path(request_path).read_text(encoding="utf-8")), output, Path(api_path), int(threads)
        )
        code = 0
    except Exception as error:
        traceback.print_exc()
        path = output / "progress.json"
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        result = _failure(error, state)
        code = 1
    (output / "result.json").write_text(_json(result), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
