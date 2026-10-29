"""Shared native device footprints and explicit Lumerical geometry readback.

Coordinates in the reusable footprint stay in micrometres. Only the vendor CAD
boundary converts to metres; curves and ring annuli are not reconstructed.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np

from ..exceptions import InvalidInputError
from ..native_geometry import build_geometry
from ..ring_modulator import build_ring_geometry

FAMILIES = ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch", "ring", "ring-modulator")
_DIELECTRIC = "<Object defined dielectric>"


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInputError(f"{label} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InvalidInputError(f"{label} must be finite") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise InvalidInputError(f"{label} must be {'positive and ' if positive else ''}finite")
    return result


def build_device_geometry(family: str, geometry_parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reuse the exact native geometry and source order, including exact rings."""
    if family not in FAMILIES:
        raise InvalidInputError(f"Unsupported Lumerical device family: {family!r}")
    if family in {"ring", "ring-modulator"}:
        result = build_ring_geometry(geometry_parameters)
        result["family"] = family
        if family == "ring-modulator":
            result["limitations"].append(
                "Optical ring footprint only; no electrical PN domains or carrier-dependent material is inferred."
            )
    else:
        result = build_geometry(family, geometry_parameters)
    return copy.deepcopy(result)


def _properties(primitive: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    kind = primitive["type"]
    if kind == "rectangle":
        x, y, width, height = [primitive[key] * 1e-6 for key in ("x", "y", "width", "height")]
        return "addrect", {"x min": x, "x max": x + width, "y min": y, "y max": y + height}
    if kind == "polygon":
        return "addpoly", {"x": 0.0, "y": 0.0, "vertices": np.asarray(primitive["points"], dtype=float) * 1e-6}
    if kind == "ring":
        return "addring", {
            "x": primitive["cx"] * 1e-6, "y": primitive["cy"] * 1e-6,
            "inner radius": primitive["inner_radius"] * 1e-6,
            "outer radius": primitive["outer_radius"] * 1e-6,
            "theta start": 0.0, "theta stop": 360.0,
        }
    raise InvalidInputError(f"Unsupported native primitive type: {kind!r}")


def _lead_properties(port: dict[str, Any], bounds: list[float], buffer: float) -> dict[str, float]:
    x, y = port["center_m"]
    width = port["width_m"]
    overlap = min(1e-9, width / 10)
    side = port["side"]
    if side == "left":
        return {"x min": bounds[0] - buffer, "x max": x + overlap,
                "y min": y - width / 2, "y max": y + width / 2}
    if side == "right":
        return {"x min": x - overlap, "x max": bounds[1] + buffer,
                "y min": y - width / 2, "y max": y + width / 2}
    if side == "bottom":
        return {"y min": bounds[2] - buffer, "y max": y + overlap,
                "x min": x - width / 2, "x max": x + width / 2}
    if side == "top":
        return {"y min": y - overlap, "y max": bounds[3] + buffer,
                "x min": x - width / 2, "x max": x + width / 2}
    raise InvalidInputError(f"Unsupported port side: {side!r}")


def apply_device_geometry(
    session: Any, geometry: dict[str, Any], *, height_m: float, core_index: float,
    clad_index: float, model_dimension: str, port_buffer_m: float,
) -> dict[str, Any]:
    """Apply fixed CAD operations and read every geometry/material assignment.

    Ports retain the original native exterior reference planes. Added uniform
    leads overlap the native core by 1 nm and extend beyond the expanded FDTD
    bounds, so the solver's PML cuts through continuing core rather than an end.
    This creates no solver region or port objects; callers build those next.
    """
    if model_dimension not in {"2d", "3d"}:
        raise InvalidInputError("model_dimension must be 2d or 3d")
    height = _number(height_m, "height_m", positive=True)
    core = _number(core_index, "core_index", positive=True)
    clad = _number(clad_index, "clad_index", positive=True)
    buffer = _number(port_buffer_m, "port_buffer_m", positive=True)
    if core <= clad or clad < 1:
        raise InvalidInputError("device requires core_index > clad_index >= 1")
    # Reconstruct the known family from its declared parameters so modified
    # primitive dictionaries cannot silently diverge from the original builder.
    canonical = build_device_geometry(geometry["family"], geometry["parameters"])
    if geometry != canonical:
        raise InvalidInputError("Geometry does not match its declared shared native builder")
    bounds = [value * 1e-6 for value in geometry["bbox_um"]]
    bounds = [bounds[0] - buffer, bounds[1] + buffer, bounds[2] - buffer, bounds[3] + buffer]
    ports = [{
        "name": port["name"], "side": port["side"],
        "center_m": [coordinate * 1e-6 for coordinate in port["center_um"]],
        "width_m": port["width_um"] * 1e-6, "window_m": port["window_um"] * 1e-6,
    } for port in geometry["ports"]]
    objects = [("device_" + primitive["tag"], *_properties(primitive), False)
               for primitive in geometry["primitives"]]
    objects.extend(("lead_" + port["name"], "addrect", _lead_properties(port, bounds, buffer), True) for port in ports)
    readbacks = []
    for name, command, properties, extension in objects:
        getattr(session, command)()
        actual_properties = {"name": name, **properties, "z min": -height / 2, "z max": height / 2,
                             "material": _DIELECTRIC, "index": core,
                             "override mesh order from material database": 1, "mesh order": 2}
        for key, value in actual_properties.items():
            session.set(key, value)
        observed: dict[str, Any] = {"name": name, "lead_extension": extension, "command": command}
        checks = {}
        for key, expected in actual_properties.items():
            actual = session.getnamed(name, key)
            if isinstance(expected, str):
                observed[key] = str(actual)
                checks[key] = str(actual) == expected
            else:
                numeric = np.asarray(actual, dtype=float)
                observed[key] = numeric.tolist()
                checks[key] = bool(np.isfinite(numeric).all() and np.allclose(numeric, expected, rtol=0, atol=1e-15))
        observed["checks"] = checks
        observed["all_matched"] = all(checks.values())
        readbacks.append(observed)
    return {
        "solver_bounds_m": bounds, "ports": ports,
        "geometry_readback": {"objects": readbacks, "all_matched": all(item["all_matched"] for item in readbacks)},
        "source_geometry": geometry, "core_index": core, "clad_index": clad,
        "height_m": height, "model_dimension": model_dimension,
        "model_level": "2d-scalar-index-surrogate" if model_dimension == "2d" else "3d-vector-constant-index",
        "original_core_area_um2": geometry["expected_core_area_um2"],
        "lead_extension_count": len(ports), "port_reference_planes": "original shared native geometry exterior planes",
        "physics_accepted": False,
        "limitations": geometry["limitations"] + [
            "Native CAD property readback does not establish Boolean topology, mesh area or field convergence.",
            "Cladding is the caller's declared FDTD background; this routine creates core and continuing leads.",
            "3D extrusion changes the model level; it is not asserted equivalent to the native 2D scalar model.",
        ],
    }


__all__ = ["FAMILIES", "apply_device_geometry", "build_device_geometry"]
