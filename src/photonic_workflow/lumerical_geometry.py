"""Reuse the existing planar device geometry without reimplementing its curves.

This bridge extrudes the exact existing polygons with an explicitly supplied
height and scalar index. It does not translate a COMSOL mesh, port or study.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .exceptions import InvalidInputError
from .models.io import atomic_create_text
from .native_geometry import build_geometry


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, float | int):
        raise InvalidInputError(f"{name} must be a positive finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InvalidInputError(f"{name} must be finite") from exc
    if not math.isfinite(result) or result <= 0:
        raise InvalidInputError(f"{name} must be a positive finite number")
    return result


def migrate_geometry(request: dict[str, Any], *, height_um: float, core_index: float) -> dict[str, Any]:
    """Map a strict geometry request to SI-valued Lumerical CAD objects.

    Use a geometry-only request {schema_version, family, parameters}. Reject
    physics fields from a native solve request instead of silently losing them.
    """
    if not isinstance(request, dict) or set(request) != {"schema_version", "family", "parameters"}:
        raise InvalidInputError("geometry request needs exactly schema_version, family and parameters")
    if request["schema_version"] != "1.0":
        raise InvalidInputError("geometry schema_version must be '1.0'")
    height = _positive(height_um, "height_um") * 1e-6
    index = _positive(core_index, "core_index")
    geometry = build_geometry(request["family"], request["parameters"])
    objects = []
    for primitive in geometry["primitives"]:
        item = {
            "name": "migrated_" + primitive["tag"],
            "kind": primitive["type"],
            "z_min_m": -height / 2,
            "z_max_m": height / 2,
            "index": index,
        }
        if primitive["type"] == "rectangle":
            item.update({
                "x_min_m": primitive["x"] * 1e-6,
                "x_max_m": (primitive["x"] + primitive["width"]) * 1e-6,
                "y_min_m": primitive["y"] * 1e-6,
                "y_max_m": (primitive["y"] + primitive["height"]) * 1e-6,
            })
        else:
            item["vertices_m"] = [[x * 1e-6, y * 1e-6] for x, y in primitive["points"]]
        objects.append(item)
    return {
        "schema_version": "1.0",
        "source_geometry": geometry,
        "objects": objects,
        "extrusion_height_m": height,
        "core_index": index,
        "physics_accepted": False,
        "limitations": geometry["limitations"] + [
            "Explicit vertical extrusion and constant scalar index; no 3D equivalence to the 2D source is inferred.",
            "Port names/planes are retained as metadata; ports, sources, cladding and boundaries are not created.",
        ],
    }


def geometry_script(model: dict[str, Any]) -> str:
    """Render only fixed addrect/addpoly operations with numeric geometry."""
    lines = ["# Generated geometry fragment: use a new empty FDTD or MODE layout.",
             "# No solver, source, cladding or acceptance claim is included."]
    for item in model["objects"]:
        lines.extend(["addrect;" if item["kind"] == "rectangle" else "addpoly;",
                      f'set("name",{json.dumps(item["name"])});'])
        if item["kind"] == "rectangle":
            for axis in ("x", "y"):
                for bound in ("min", "max"):
                    lines.append(f'set("{axis} {bound}",{item[f"{axis}_{bound}_m"]:.17g});')
        else:
            vertices = ";".join(f"{x:.17g},{y:.17g}" for x, y in item["vertices_m"])
            lines.append(f'set("vertices",[{vertices}]);')
        for bound in ("min", "max"):
            lines.append(f'set("z {bound}",{item[f"z_{bound}_m"]:.17g});')
        lines.extend(['set("material","<Object defined dielectric>");', f'set("index",{item["index"]:.17g});'])
    return "\n".join(lines) + "\n"


def export_native_geometry(
    request: dict[str, Any], output: Path, *, height_um: float, core_index: float,
) -> dict[str, Any]:
    model = migrate_geometry(request, height_um=height_um, core_index=core_index)
    output = output.resolve()
    if output.exists():
        raise InvalidInputError(f"geometry output must be a new directory: {output}")
    output.mkdir(parents=True)
    contents = {
        "geometry.json": json.dumps(model, indent=2, allow_nan=False) + "\n",
        "geometry.lsf": geometry_script(model),
        "request.json": json.dumps(request, indent=2, allow_nan=False) + "\n",
    }
    for name, content in contents.items():
        atomic_create_text(output / name, content)
    return {
        "output_directory": str(output), "family": request["family"],
        "object_count": len(model["objects"]), "native_execution": False, "physics_accepted": False,
        "artifacts": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in contents.items()},
        "limitations": model["limitations"],
    }
