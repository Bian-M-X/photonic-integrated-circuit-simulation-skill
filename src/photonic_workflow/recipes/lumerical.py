"""Fixed numeric LSF geometry fragments; rendering never opens a product session.

Planar recipe parameters retain their original contract. Extrusion height and
constant core index are explicit renderer options, not inferred stack data.
Circular arcs use native annular sectors; Euler boundaries retain every point
of the canonical sampled polygon without additional smoothing or resampling.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.security import validate_safe_label

from .geometry import evaluate_circular_route, evaluate_symmetric_euler_bend
from .renderers import LUMERICAL_RECIPE_IDS, MAX_LUMERICAL_CIRCULAR_VERTICES, MAX_LUMERICAL_FRAGMENT_BYTES
from .types import RecipeResult


def _number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInputError("Lumerical renderer requires finite numeric data")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise InvalidInputError("Lumerical renderer received an unrepresentable number") from exc
    if not math.isfinite(number):
        raise InvalidInputError("Lumerical renderer requires finite numeric data")
    return "0.0" if number == 0 else format(number, ".17g")


def _positive(name: str, value: object) -> float:
    try:
        number = float(_number(value))
    except InvalidInputError as exc:
        raise InvalidInputError(f"Lumerical geometry requires explicit positive finite {name}") from exc
    if number <= 0:
        raise InvalidInputError(f"Lumerical geometry requires explicit positive finite {name}")
    return number


def _prefix(instance_id: str | None) -> str:
    if instance_id is None:
        raise InvalidInputError("Lumerical LSF rendering requires an explicit safe instance_id")
    label = validate_safe_label(instance_id)
    safe = re.sub(r"[^A-Za-z0-9_]", "_", label)[:48]
    digest = hashlib.sha256(label.encode("ascii")).hexdigest()[:10]
    return f"recipe_{safe}_{digest}"


def _fresh_output(result: RecipeResult) -> dict[str, Any]:
    if not isinstance(result, RecipeResult) or result.descriptor.recipe_id not in LUMERICAL_RECIPE_IDS:
        raise InvalidInputError("Unsupported recipe for Lumerical LSF geometry rendering")
    if result.descriptor.recipe_version != "1.0.0":
        raise InvalidInputError("Lumerical LSF renderer requires exact recipe version 1.0.0")
    if result.descriptor.recipe_id == "geometry.circular-route":
        vertices = result.parameters.get("vertices_um")
        if isinstance(vertices, list | tuple) and len(vertices) > MAX_LUMERICAL_CIRCULAR_VERTICES:
            raise InvalidInputError(
                f"Lumerical circular-route renderer supports at most {MAX_LUMERICAL_CIRCULAR_VERTICES} vertices"
            )
        expected = evaluate_circular_route(result.parameters)
    else:
        expected = evaluate_symmetric_euler_bend(result.parameters)
    try:
        expected_json = json.dumps(expected, sort_keys=True, allow_nan=False)
        observed_json = json.dumps(result.output, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError("Provided recipe output is not finite JSON") from exc
    if expected_json != observed_json:
        raise InvalidInputError("Provided recipe output differs from a fresh evaluation")
    return expected


def _straight_polygon(start: Sequence[float], end: Sequence[float], width: float) -> list[list[float]]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        raise InvalidInputError("Degenerate circular-route straight segment")
    ox, oy = -0.5 * width * dy / length, 0.5 * width * dx / length
    return [[(x + sx * ox) * 1e-6, (y + sy * oy) * 1e-6] for x, y, sx, sy in (
        (start[0], start[1], 1, 1), (end[0], end[1], 1, 1),
        (end[0], end[1], -1, -1), (start[0], start[1], -1, -1),
    )]


def lumerical_geometry_plan(
    result: RecipeResult, *, instance_id: str | None, height_um: float | None, core_index: float | None,
) -> dict[str, Any]:
    """Map a fresh numeric recipe to explicit native primitives, all lengths SI.

    This plan and the fragment contain no FDTD region, ports, meshing, fitting,
    sources or studies. Geometry readback is not field or device acceptance.
    """
    prefix = _prefix(instance_id)
    height = _positive("height_um", height_um)
    index = _positive("core_index", core_index)
    if height * 1e-6 <= 0:
        raise InvalidInputError("height_um is too small to represent a positive SI extrusion")
    output = _fresh_output(result)
    primitives: list[dict[str, Any]] = []
    if result.descriptor.recipe_id == "geometry.symmetric-euler-bend":
        primitives.append({"name": prefix + "_euler", "type": "polygon",
                           "vertices_m": [[float(x) * 1e-6, float(y) * 1e-6]
                                          for x, y in output["boundary_table"]]})
        representation = "canonical sampled boundary polygon; no extra interpolation"
    else:
        width = float(output["width_um"])
        radius = float(output["radius_um"])
        cursor = output["vertices_um"][0]
        for bend_index, bend in enumerate(output["bends"]):
            if math.dist(cursor, bend["t1"]) > 1e-12:
                primitives.append({"name": f"{prefix}_straight_{bend_index}", "type": "polygon",
                                   "vertices_m": _straight_polygon(cursor, bend["t1"], width)})
            low, high = sorted((math.degrees(bend["a0"]), math.degrees(bend["a1"])))
            start = low % 360
            end = start + high - low
            intervals = [(start, end)] if end <= 360 else [(start, 360), (0, end - 360)]
            for part, (theta_start, theta_stop) in enumerate(intervals):
                if theta_stop <= theta_start:
                    continue
                primitives.append({
                    "name": f"{prefix}_arc_{bend_index}_{part}", "type": "ring",
                    "x_m": float(bend["center"][0]) * 1e-6, "y_m": float(bend["center"][1]) * 1e-6,
                    "inner_radius_m": (radius - width / 2) * 1e-6,
                    "outer_radius_m": (radius + width / 2) * 1e-6,
                    "theta_start_deg": theta_start, "theta_stop_deg": theta_stop,
                })
            cursor = bend["t2"]
        last = output["vertices_um"][-1]
        if math.dist(cursor, last) > 1e-12:
            primitives.append({"name": prefix + "_straight_last", "type": "polygon",
                               "vertices_m": _straight_polygon(cursor, last, width)})
        representation = "analytic native annular sectors and exact straight offset polygons"
    if not primitives:
        raise InvalidInputError("Lumerical recipe produced no geometry")
    for primitive in primitives:
        primitive.update(z_m=0.0, z_span_m=height * 1e-6, core_index=index)
    return {
        "schema_version": "1.0", "recipe_id": result.descriptor.recipe_id,
        "recipe_version": result.descriptor.recipe_version, "instance_id": instance_id,
        "height_um": height, "core_index": index, "length_unit": "m",
        "primitives": primitives, "representation": representation,
        "will_execute": False, "physics_accepted": False,
        "limitations": ["Geometry and constant core index only; no ports, background, PML, mesh or field solve.",
                        "Explicit extrusion is a target setting, not a validated vertical material stack.",
                        "Euler uses the canonical sampled polygon; interpolation equivalence is not inferred."],
    }


def _properties(properties: Mapping[str, object]) -> list[str]:
    lines = []
    for name, value in properties.items():
        if isinstance(value, str):
            if name == "name" and not re.fullmatch(r"recipe_[A-Za-z0-9_]+", value):
                raise InvalidInputError("Unsafe generated Lumerical object name")
            if name != "name" and (name != "material" or value != "<Object defined dielectric>"):
                raise InvalidInputError("Unsupported Lumerical string property")
            rendered = '"' + value + '"'
        else:
            rendered = _number(value)
        lines.append(f'set("{name}", {rendered});')
    return lines


def render_lumerical_lsf_fragment(plan: Mapping[str, Any]) -> str:
    """Render fixed templates from ``lumerical_geometry_plan``; never evaluate LSF."""
    lines = [
        "# photonic-workflow reviewed Lumerical geometry fragment",
        "# All coordinate values are SI metres; height and index were supplied explicitly.",
        "# will_execute=false; physics_accepted=false; rendering has no product-session side effects.",
        "# Use a fresh CAD model or distinct instance_id. Add the reviewed solver stack and ports separately.",
    ]
    for primitive in plan["primitives"]:
        if primitive["type"] == "polygon":
            lines.extend(["addpoly;", *_properties({"name": primitive["name"], "x": 0.0, "y": 0.0})])
            rows = [", ".join(_number(value) for value in point) for point in primitive["vertices_m"]]
            if any(len(point) != 2 for point in primitive["vertices_m"]):
                raise InvalidInputError("Lumerical polygon vertices require exactly two numeric coordinates")
            lines.append('set("vertices", [\n' + ";\n".join(rows) + "\n]);")
        elif primitive["type"] == "ring":
            lines.extend(["addring;", *_properties({
                "name": primitive["name"], "x": primitive["x_m"], "y": primitive["y_m"],
                "inner radius": primitive["inner_radius_m"], "outer radius": primitive["outer_radius_m"],
                "theta start": primitive["theta_start_deg"], "theta stop": primitive["theta_stop_deg"],
            })])
        else:
            raise InvalidInputError("Unsupported Lumerical primitive type")
        lines.extend(_properties({"z": primitive["z_m"], "z span": primitive["z_span_m"],
                                  "material": "<Object defined dielectric>", "index": primitive["core_index"]}))
    content = "\n".join(lines) + "\n"
    if len(content.encode("utf-8")) > MAX_LUMERICAL_FRAGMENT_BYTES:
        raise InvalidInputError("Lumerical fragment exceeds the reviewed source-size limit")
    return content


__all__ = ["lumerical_geometry_plan", "render_lumerical_lsf_fragment"]
