"""Complete single-selected-mode FDTD device matrices, one actual solve per source.

All columns use the same constructed model. Native port S results already include
the vendor's power normalization and mesh-dispersion correction; no reciprocity,
symmetry, matrix inversion or power-to-amplitude reconstruction fills missing data.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from ..exceptions import InvalidInputError
from ..lumerical_exchange import dataset_from_arrays

_DEFAULTS = {
    "family": "straight", "geometry_parameters": {}, "model_dimension": "2d",
    "core_index": 2.6, "clad_index": 1.45, "height_m": 0.22e-6,
    "wavelength_start_m": 1.5e-6, "wavelength_stop_m": 1.6e-6,
    "frequency_points": 5, "mesh_accuracy": 3, "simulation_time_s": 1.5e-12,
    "port_buffer_m": 1.2e-6, "cladding_span_z_m": 2.5e-6,
    "mode_selection": "fundamental TM mode", "mode_profile_samples": 3,
    "auto_shutoff_min": 1e-7,
    "core_material_model": None, "clad_material_model": None, "material_fit_tolerance": 0.01,
}
_BOUNDS = {
    "core_index": (1, 5), "clad_index": (1, 4.9), "height_m": (20e-9, 10e-6),
    "wavelength_start_m": (0.4e-6, 5e-6), "wavelength_stop_m": (0.4e-6, 5e-6),
    "frequency_points": (1, 101), "mesh_accuracy": (1, 6), "simulation_time_s": (0.2e-12, 100e-12),
    "port_buffer_m": (0.4e-6, 20e-6), "cladding_span_z_m": (0.4e-6, 30e-6),
    "mode_profile_samples": (1, 25), "auto_shutoff_min": (1e-10, 1e-3),
    "material_fit_tolerance": (1e-6, 0.1),
}
_INTEGERS = {"frequency_points", "mesh_accuracy", "mode_profile_samples"}


def _material_samples(p: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from .materials import sample_material_model

    wavelengths = np.linspace(p["wavelength_start_m"], p["wavelength_stop_m"], 21)
    return {part: sample_material_model(p[part + "_material_model"], wavelengths)
            for part in ("core", "clad") if p[part + "_material_model"] is not None}


def validate_device_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on unsupported fields and model-level changes before launch."""
    if not isinstance(parameters, dict) or set(parameters) - _DEFAULTS.keys():
        raise InvalidInputError("Unknown FDTD device parameter")
    p = {**_DEFAULTS, **parameters}
    if not isinstance(p["model_dimension"], str) or p["model_dimension"] not in {"2d", "3d"}:
        raise InvalidInputError("model_dimension must be 2d or 3d")
    if not isinstance(p["mode_selection"], str) or p["mode_selection"] not in {
        "fundamental TE mode", "fundamental TM mode",
    }:
        raise InvalidInputError("Only one explicit fundamental TE or TM mode is supported per physical port")
    if p["model_dimension"] == "2d" and p["mode_selection"] != "fundamental TM mode":
        raise InvalidInputError("The 2D scalar-Ez model requires fundamental TM mode; use 3d for vector TE")
    for name, (low, high) in _BOUNDS.items():
        value = p[name]
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise InvalidInputError(f"{name} must be finite")
        if not low <= value <= high or (name in _INTEGERS and int(value) != value):
            raise InvalidInputError(f"{name} must be in [{low}, {high}]")
        p[name] = int(value) if name in _INTEGERS else float(value)
    if p["core_index"] <= p["clad_index"]:
        raise InvalidInputError("core_index must exceed clad_index")
    if p["wavelength_stop_m"] <= p["wavelength_start_m"]:
        raise InvalidInputError("wavelength_stop_m must exceed wavelength_start_m")
    if p["cladding_span_z_m"] <= p["height_m"]:
        raise InvalidInputError("cladding_span_z_m must exceed core height")
    from .device_geometry import build_device_geometry

    geometry = build_device_geometry(p["family"], p["geometry_parameters"])
    samples = _material_samples(p)
    wavelength = np.asarray(next(iter(samples.values()))["wavelength_m"]) if samples else np.array([
        p["wavelength_start_m"], p["wavelength_stop_m"],
    ])
    core = np.asarray(samples["core"]["n_real"]) if "core" in samples else np.full(wavelength.size, p["core_index"])
    clad = np.asarray(samples["clad"]["n_real"]) if "clad" in samples else np.full(wavelength.size, p["clad_index"])
    if np.any(core <= clad):
        raise InvalidInputError("Sampled core index must exceed sampled cladding index over the declared band")
    if p["model_dimension"] == "2d":
        cutoff = float(np.min(wavelength / (2 * np.sqrt(core ** 2 - clad ** 2))))
        if any(port["width_um"] * 1e-6 >= cutoff for port in geometry["ports"]):
            raise InvalidInputError("2D port supports additional bound modes; the single-mode contract is insufficient")
    # Preserve a normal JSON object, not caller-owned mutable default state.
    return json.loads(json.dumps(p, allow_nan=False))


def _set(session: Any, properties: dict[str, Any]) -> None:
    for name, value in properties.items():
        session.set(name, value)


def _save_native_dataset(arrays: dict[str, np.ndarray], prefix: str, dataset: dict[str, Any]) -> dict[str, Any]:
    """Archive numeric shapes/dtypes and return a JSON structure of vendor labels."""
    def archive(value, key):
        if isinstance(value, dict):
            return {name: archive(item, key + name + "__") for name, item in value.items()}
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, np.ndarray | float | complex | int | list | tuple):
            try:
                array = np.asarray(value)
            except (TypeError, ValueError):
                array = None
            if array is not None and array.dtype.kind in "bifcu":
                # Remove the structural separator to preserve existing NPZ keys.
                array_key = key.removesuffix("__")
                arrays[array_key] = array
                return {"npz_key": array_key, "dtype": str(array.dtype), "shape": list(array.shape)}
            if isinstance(value, np.ndarray):
                value = value.tolist()
            if isinstance(value, list | tuple):
                return [archive(item, key + str(index) + "__") for index, item in enumerate(value)]
        if isinstance(value, str | bool) or value is None:
            return value
        raise ValueError(f"Unsupported native metadata value: {type(value).__name__}")

    return {name: archive(value, prefix + name + "__") for name, value in dataset.items()}


def _single_mode_s(dataset: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Accept only documented frequency-first, one-mode native port data."""
    if "f" not in dataset or "S" not in dataset:
        raise ValueError("Native port S result must contain explicit f and complex S")
    frequency = np.asarray(dataset["f"], dtype=float).reshape(-1)
    matrix = np.asarray(dataset["S"])
    if not frequency.size or not np.isfinite(frequency).all() or np.any(frequency <= 0):
        raise ValueError("Invalid native port frequency axis")
    if len(np.unique(frequency)) != len(frequency):
        raise ValueError("Duplicate native port frequencies")
    if matrix.ndim == 0 and frequency.size == 1:
        matrix = matrix.reshape(1)
    if matrix.shape[0] != frequency.size or any(size != 1 for size in matrix.shape[1:]):
        raise ValueError("Native S axes must be frequency first followed only by singleton selected-mode axes")
    values = matrix.reshape(len(frequency)).astype(complex)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite native complex S")
    return frequency, values


def _profile_overlap(reference: np.ndarray, current: np.ndarray) -> dict[str, Any]:
    if reference.shape != current.shape or not np.isfinite(current).all():
        return {"same_basis": False, "reason": "mode-profile shape or finite-value mismatch"}
    norm = np.linalg.norm(reference) * np.linalg.norm(current)
    if norm <= 1e-30:
        return {"same_basis": False, "reason": "zero modal field norm"}
    overlap = np.vdot(reference.ravel(), current.ravel()) / norm
    reference_norm = np.linalg.norm(reference)
    norm_ratio = np.linalg.norm(current) / reference_norm
    relative_change = np.linalg.norm(current - reference) / reference_norm
    return {"overlap_abs": float(abs(overlap)), "phase_rad": float(np.angle(overlap)),
            "norm_ratio": float(norm_ratio), "relative_field_change": float(relative_change),
            "same_basis": bool(abs(overlap) > 1 - 1e-8 and abs(np.angle(overlap)) < 1e-6
                               and relative_change < 1e-6)}


def _selected_profile_fields(profiles: dict[str, Any], s_dataset: dict[str, Any]) -> tuple[dict, dict]:
    """Resolve an explicit selected native-mode field pair without axis guessing."""
    if "E" in profiles and "H" in profiles:
        labels = {"E": "E", "H": "H"}
    else:
        pairs = {key[1:] for key in profiles if re.fullmatch(r"E[0-9]+", key) and "H" + key[1:] in profiles}
        declared = np.asarray(s_dataset.get("n", [])).reshape(-1)
        if declared.size == 1 and np.isfinite(declared).all() and float(declared[0]).is_integer():
            mode_id = str(int(declared[0]))
            if mode_id not in pairs:
                raise ValueError("Native S mode id has no matching E/H profile attributes")
        elif len(pairs) == 1:
            mode_id = next(iter(pairs))
        else:
            raise ValueError("Cannot unambiguously bind selected port S mode to its E/H field profiles")
        labels = {"E": "E" + mode_id, "H": "H" + mode_id}
    fields = {field: np.asarray(profiles[key]) for field, key in labels.items()}
    if any(value.ndim < 1 or value.shape[-1] != 3 or not np.isfinite(value).all() for value in fields.values()):
        raise ValueError("Selected native E/H profiles must be finite Cartesian vectors")
    return fields, labels


def _expansion_series(expansion: dict[str, Any], field: str, frequency: np.ndarray) -> np.ndarray:
    values = np.asarray(expansion[field])
    native_frequency = np.asarray(expansion["f"], dtype=float).reshape(-1)
    if not np.array_equal(native_frequency, frequency):
        raise ValueError("Native expansion and S frequency axes differ")
    if values.ndim == 0 and len(frequency) == 1:
        values = values.reshape(1)
    if values.shape[0] != len(frequency) or any(size != 1 for size in values.shape[1:]):
        raise ValueError("Native expansion axes differ from the declared one-mode contract")
    values = values.reshape(len(frequency)).astype(complex)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite native modal expansion result")
    return values


def run_fdtd_device(session: Any, p: dict[str, Any], output: Path, threads: int, engine: Path) -> dict[str, Any]:
    """Construct once, run all source columns, retain native data and export S."""
    from .device_geometry import apply_device_geometry, build_device_geometry
    from .worker import _progress

    p = validate_device_parameters(p)
    geometry = build_device_geometry(p["family"], p["geometry_parameters"])
    session.addfdtd()
    _progress(output, "device-model-build")
    _set(session, {"dimension": 1 if p["model_dimension"] == "2d" else 2,
                   "background index": p["clad_index"], "mesh accuracy": p["mesh_accuracy"],
                   "simulation time": p["simulation_time_s"], "auto shutoff min": p["auto_shutoff_min"],
                   "x min bc": "PML", "x max bc": "PML", "y min bc": "PML", "y max bc": "PML"})
    construction = apply_device_geometry(
        session, geometry, height_m=p["height_m"], core_index=p["core_index"], clad_index=p["clad_index"],
        model_dimension=p["model_dimension"], port_buffer_m=p["port_buffer_m"],
    )
    material_readback = {}
    for part, samples in _material_samples(p).items():
        from .materials import apply_sampled_material

        name = "shared_" + part + "_material"
        fit = apply_sampled_material(session, name, samples)
        if part == "core":
            assignments = {}
            for obj in construction["geometry_readback"]["objects"]:
                session.setnamed(obj["name"], "material", name)
                assignments[obj["name"]] = str(session.getnamed(obj["name"], "material"))
        else:
            session.setnamed("FDTD", "background material", name)
            assignments = {"FDTD background": str(session.getnamed("FDTD", "background material"))}
        material_readback[part] = {**fit, "assignments": assignments,
                                   "assignments_match": all(value == name for value in assignments.values())}
    bounds = construction["solver_bounds_m"]
    session.select("FDTD")
    _set(session, {"x min": bounds[0], "x max": bounds[1], "y min": bounds[2], "y max": bounds[3], "z": 0.0})
    if p["model_dimension"] == "3d":
        _set(session, {"z span": p["cladding_span_z_m"], "z min bc": "PML", "z max bc": "PML"})
    session.setglobalsource("wavelength start", p["wavelength_start_m"])
    session.setglobalsource("wavelength stop", p["wavelength_stop_m"])
    session.setglobalmonitor("frequency points", p["frequency_points"])
    ports = construction["ports"]
    for port in ports:
        side, center = port["side"], port["center_m"]
        axis = "x" if side in {"left", "right"} else "y"
        session.addport()
        props = {"name": port["name"], "injection axis": axis + "-axis",
                 "direction": "Forward" if side in {"left", "bottom"} else "Backward",
                 "x": center[0], "y": center[1], "z": 0.0,
                 "mode selection": p["mode_selection"],
                 "number of field profile samples": p["mode_profile_samples"],
                 "y span" if axis == "x" else "x span": port["window_m"]}
        if p["model_dimension"] == "3d":
            props["z span"] = p["cladding_span_z_m"]
        _set(session, props)
        session.updateportmodes()
    # Preserve actual exported E coordinates. The installed port-group API does
    # not expose the monitor spatial-interpolation property as a setnamed key.
    session.setnamed("FDTD::ports", "monitor frequency points", p["frequency_points"])
    session.save(str(output / "model.fsp"))
    (output / "geometry.json").write_text(json.dumps({"source": geometry, "construction": construction}, indent=2))
    raw: dict[str, np.ndarray] = {}
    matrix = None
    frequencies = None
    basis_reference = {}
    basis_axes = {}
    basis_checks = []
    basis_labels = {}
    columns = []
    actual_planes: dict[str, float] = {}
    incoming_power = None
    modal_power_norms = None
    for source_index, source in enumerate(ports):
        if source_index:
            session.switchtolayout()
        session.setnamed("FDTD::ports", "source port", source["name"])
        session.setnamed("FDTD::ports", "source mode", "mode 1")
        selected_source = str(session.getnamed("FDTD::ports", "source port"))
        selected_mode = str(session.getnamed("FDTD::ports", "source mode"))
        if selected_source != source["name"] or selected_mode != "mode 1":
            raise ValueError("Native source port/mode readback differs from the intended source column")
        source_model = output / f"source-{source_index + 1:02d}.fsp"
        session.save(str(source_model))
        _progress(output, "device-source-solve", solve_invoked=True, source_index=source_index,
                  source_port=source["name"], source_count=len(ports))
        with (output / f"source-{source_index + 1:02d}-engine.log").open("wb") as stream:
            subprocess.run([str(engine), "-t", str(threads), str(source_model)], cwd=output,
                           stdout=stream, stderr=subprocess.STDOUT, check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        session.load(str(source_model))
        if str(session.getnamed("FDTD::ports", "source port")) != source["name"]:
            raise ValueError("Solved native project has an unexpected source port")
        column_arrays = {}
        column_metadata = {}
        for receiver_index, receiver in enumerate(ports):
            path = "FDTD::ports::" + receiver["name"]
            dataset = session.getresult(path, "S")
            frequency, values = _single_mode_s(dataset)
            if frequency.size != p["frequency_points"]:
                raise ValueError("Native port frequency count differs from the declared request")
            if frequencies is None:
                frequencies = frequency
                matrix = np.empty((len(frequency), len(ports), len(ports)), dtype=complex)
                incoming_power = np.empty(matrix.shape, dtype=float)
                modal_power_norms = np.empty(matrix.shape, dtype=complex)
            if not np.array_equal(frequencies, frequency):
                raise ValueError("Port/source frequency axes differ; refusing implicit interpolation")
            matrix[:, receiver_index, source_index] = values
            prefix = f"port{receiver_index + 1}__"
            column_metadata[prefix + "S"] = _save_native_dataset(column_arrays, prefix + "S__", dataset)
            expansion = session.getresult(path, "expansion for port monitor")
            incoming = _expansion_series(expansion, "T_in", frequency)
            if np.any(np.abs(incoming.imag) > 1e-8):
                raise ValueError("Native incoming modal power must be real")
            direction_sign = 1 if receiver["side"] in {"left", "bottom"} else -1
            incoming_power[:, receiver_index, source_index] = direction_sign * incoming.real
            modal_power_norms[:, receiver_index, source_index] = _expansion_series(expansion, "N", frequency)
            column_metadata[prefix + "expansion"] = _save_native_dataset(
                column_arrays, prefix + "expansion__", expansion,
            )
            fields = session.getresult(path, "E")
            column_metadata[prefix + "E"] = _save_native_dataset(column_arrays, prefix + "E__", fields)
            axis = "x" if receiver["side"] in {"left", "right"} else "y"
            plane = np.asarray(fields[axis], dtype=float).reshape(-1)
            if plane.size != 1 or not np.isfinite(plane).all():
                raise ValueError("Port monitor must declare one finite actual reference plane")
            if receiver["name"] in actual_planes and actual_planes[receiver["name"]] != float(plane[0]):
                raise ValueError("Port reference plane changed between source columns")
            actual_planes[receiver["name"]] = float(plane[0])
            profiles = session.getresult(path, "mode profiles")
            column_metadata[prefix + "mode"] = _save_native_dataset(column_arrays, prefix + "mode__", profiles)
            mode_fields, labels = _selected_profile_fields(profiles, dataset)
            profile_axes = {}
            for axis in ("x", "y", "z", "f"):
                values = np.asarray(profiles[axis], dtype=float)
                if not values.size or not np.isfinite(values).all():
                    raise ValueError("Native mode profiles require finite spatial and frequency axes")
                profile_axes[axis] = values
            basis_labels[receiver["name"]] = labels
            if source_index == 0:
                basis_reference[receiver["name"]] = {field: value.copy() for field, value in mode_fields.items()}
                basis_axes[receiver["name"]] = {axis: value.copy() for axis, value in profile_axes.items()}
            else:
                same_axes = all(np.array_equal(value, basis_axes[receiver["name"]][axis])
                                for axis, value in profile_axes.items())
                for field, values in mode_fields.items():
                    basis_checks.append({"source": source["name"], "port": receiver["name"], "field": field,
                                         "same_spatial_frequency_axes": same_axes,
                                         **_profile_overlap(basis_reference[receiver["name"]][field], values)})
                    basis_checks[-1]["same_basis"] = basis_checks[-1]["same_basis"] and same_axes
        np.savez_compressed(output / f"source-{source_index + 1:02d}-raw.npz", **column_arrays)
        (output / f"source-{source_index + 1:02d}-metadata.json").write_text(
            json.dumps(column_metadata, indent=2, allow_nan=False), encoding="utf-8",
        )
        raw.update({f"source{source_index + 1}__{key}": value for key, value in column_arrays.items()})
        columns.append({"source_index": source_index, "source_port": source["name"],
                        "source_port_readback": selected_source, "source_mode_readback": selected_mode,
                        "source_model": source_model.name, "raw": f"source-{source_index + 1:02d}-raw.npz"})
    assert matrix is not None and frequencies is not None
    _progress(output, "device-matrix-export", solve_completed=True, source_columns_completed=len(columns))
    raw.update(s_matrix=matrix, frequency_hz=frequencies,
               direction_adjusted_incoming_power=incoming_power, native_modal_power_N=modal_power_norms)
    np.savez_compressed(output / "raw.npz", **raw)
    channels = []
    for port in ports:
        axis = "x" if port["side"] in {"left", "right"} else "y"
        positive = port["side"] in {"left", "bottom"}
        channels.append({"id": port["name"], "port": port["name"], "mode": p["mode_selection"],
                         "incoming_direction": ("+" if positive else "-") + axis,
                         "outgoing_direction": ("-" if positive else "+") + axis,
                         "reference_plane": f"{axis}={actual_planes[port['name']]:.17g} m; native port E dataset"})
    level = "2d-scalar-index-surrogate" if p["model_dimension"] == "2d" else "full-wave-3d"
    transport = dataset_from_arrays(
        matrix, spectral_axis={"quantity": "frequency", "unit": "Hz", "values": frequencies.tolist()},
        channels=channels, producer={"product": "FDTD", "version": str(session.version())},
        model_level=level, passive=True, time_dependence="exp(-iwt)",
    )
    (output / "source_dataset.json").write_text(json.dumps(transport, indent=2, allow_nan=False), encoding="utf-8")
    powers = np.sum(np.abs(matrix) ** 2, axis=1)
    max_sigma = float(np.max(np.linalg.svd(matrix, compute_uv=False)))
    reciprocity = float(np.max(np.abs(matrix - matrix.transpose(0, 2, 1))))
    source_power = np.diagonal(incoming_power, axis1=1, axis2=2)
    off_diagonal = ~np.eye(len(ports), dtype=bool)
    max_non_source_incoming = float(np.max(np.abs(incoming_power[:, off_diagonal])))
    checks = {
        "geometry_material_readback": bool(construction["geometry_readback"]["all_matched"]),
        "sampled_material_fit_and_assignment": all(
            item["assignments_match"] and item["max_index_fit_error"] <= p["material_fit_tolerance"]
            and item["fitted_minimum_extinction"] >= -1e-7 for item in material_readback.values()
        ),
        "all_source_columns_solved": len(columns) == len(ports),
        "finite_complete_complex_matrix": bool(np.isfinite(matrix).all()),
        "same_modal_basis_across_sources": all(item["same_basis"] for item in basis_checks),
        "source_incoming_power_within_5pct": bool(np.max(np.abs(source_power - 1)) <= 0.05),
        "non_source_incoming_below_1e_3": max_non_source_incoming < 1e-3,
        "positive_finite_modal_power_norms": bool(np.isfinite(modal_power_norms).all()
                                                  and np.all(modal_power_norms.real > 0)),
        "passivity_with_5pct_numeric_budget": max_sigma <= 1.05,
        "reciprocity_with_5pct_amplitude_budget": reciprocity <= 0.05,
    }
    return {
        "model_level": level, "family": p["family"], "port_order": [port["name"] for port in ports],
        "frequency_hz": frequencies.tolist(), "source_columns": columns, "channels": channels,
        "max_singular_value": max_sigma, "max_reciprocity_error": reciprocity,
        "outgoing_guided_power_per_source": powers.tolist(),
        "reflection_power_per_source": (np.abs(np.diagonal(matrix, axis1=1, axis2=2)) ** 2).tolist(),
        "unaccounted_power_per_source": (1 - powers).tolist(),
        "incoming_modal_power": incoming_power.tolist(),
        "source_incoming_power_per_source": source_power.tolist(),
        "max_non_source_incoming_power": max_non_source_incoming,
        "incoming_power_formula": "Re(T_in) times +1 for Forward / -1 for Backward injection direction",
        "incoming_power_policy": "Read-only audit; no incoming-matrix inversion or source renormalization",
        "modal_basis_checks": basis_checks, "construction": construction,
        "native_modal_field_labels": basis_labels,
        "sampled_materials": material_readback,
        "diagnostic_checks": checks, "diagnostic_passed": all(checks.values()), "physics_accepted": False,
        "source_dataset": "source_dataset.json",
        "matrix_complete": len(columns) == len(ports),
        "basis_consistent": all(item["same_basis"] for item in basis_checks),
        "limitations": [
            "Complete for one selected mode per port only; 3D higher-order-mode completeness remains unproved.",
            "Indices are constants or reviewed bulk formulas with measured native fit errors; no foundry stack.",
            "Unaccounted guided power includes radiation, other modes and numerical error; it is not absorption.",
            "Raw vendor port S is retained without symmetry fill, reciprocity enforcement or matrix normalization.",
            "Conditional 5% passivity/reciprocity checks are diagnostics, not device acceptance or convergence.",
        ],
    }
