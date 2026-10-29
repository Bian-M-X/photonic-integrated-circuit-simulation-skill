"""Parameterized planar core geometry for the native multiport examples.

Coordinates are in micrometres. Curved access guides are normal-offset sampled
cubic paths with polygonal edges, not exact Euler curves or solver evidence.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from itertools import pairwise
from typing import Any

from photonic_workflow.exceptions import InvalidInputError

_COMMON = {
    "width_um": (0.3, 0.08, 0.8),
    "clearance_um": (1.2, 0.5, 10.0),
    "port_window_um": (2.4, 0.5, 5.0),
}
_FAMILIES = {
    "straight": {"length_um": (6.0, 0.5, 100.0)},
    "crossing": {
        "arm_length_um": (3.0, 1.0, 30.0),
        "center_width_um": (0.3, 0.08, 3.0),
    },
    "directional-coupler": {
        "coupling_length_um": (6.0, 0.0, 50.0),
        "gap_um": (0.2, 0.05, 3.0),
        "port_offset_um": (1.5, 0.4, 5.0),
        "lead_um": (2.0, 0.5, 20.0),
        "transition_um": (3.0, 1.0, 30.0),
        "samples": (32, 8, 256),
    },
    "mmi2x2": {
        "body_width_um": (1.5, 0.5, 8.0),
        "body_length_um": (4.5, 0.5, 50.0),
        "access_offset_um": (0.4, 0.15, 3.5),
        "port_offset_um": (1.5, 0.4, 5.0),
        "lead_um": (2.0, 0.5, 20.0),
        "transition_um": (3.0, 1.0, 30.0),
        "samples": (32, 8, 256),
    },
    "ybranch": {
        "branch_length_um": (5.0, 1.0, 40.0),
        "port_offset_um": (1.5, 0.4, 5.0),
        "lead_um": (2.0, 0.5, 20.0),
        "samples": (32, 8, 256),
    },
}
_MODEL_LEVEL = "2d-scalar-index-surrogate"
_BASE_LIMITS = [
    "Planar core geometry only; native material, mode, field and convergence readbacks are separate evidence.",
    "No vertical stack, effective-index calibration, fabrication rule or polarization conversion is inferred.",
]


def _parameters(family: str, supplied: Mapping[str, Any] | None) -> dict[str, float | int]:
    if not isinstance(family, str) or family not in _FAMILIES:
        raise InvalidInputError(f"Unsupported native geometry family: {family!r}")
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, Mapping) or any(not isinstance(key, str) for key in supplied):
        raise InvalidInputError("Geometry parameters must be a mapping with string keys")
    definitions = _COMMON | _FAMILIES[family]
    unknown = sorted(set(supplied) - definitions.keys())
    if unknown:
        raise InvalidInputError(f"Unknown {family} geometry parameters: {unknown}")
    result: dict[str, float | int] = {}
    for name, (default, low, high) in definitions.items():
        value = supplied.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidInputError(f"{name} must be a finite number")
        try:
            converted = float(value)
        except (OverflowError, ValueError) as exc:
            raise InvalidInputError(f"{name} must be a finite number") from exc
        if not math.isfinite(converted) or not low <= converted <= high:
            raise InvalidInputError(f"{name} must be in [{low}, {high}]")
        if name == "samples":
            if converted != int(converted):
                raise InvalidInputError("samples must be an integer")
            result[name] = int(converted)
        else:
            result[name] = converted
    if result["port_window_um"] <= result["width_um"]:
        raise InvalidInputError("port_window_um must exceed the core width")
    if "port_offset_um" in result and result["port_window_um"] >= 2 * result["port_offset_um"]:
        raise InvalidInputError("Same-face port windows must be disjoint")
    if family == "crossing":
        if "center_width_um" not in supplied:
            result["center_width_um"] = result["width_um"]
        if result["center_width_um"] < result["width_um"]:
            raise InvalidInputError("center_width_um must be at least width_um")
        if result["center_width_um"] >= 2 * result["arm_length_um"]:
            raise InvalidInputError("Crossing center must leave straight arms at the exterior ports")
        if result["port_window_um"] >= 2 * result["arm_length_um"]:
            raise InvalidInputError("Crossing port windows must not reach adjacent exterior faces")
        if result["arm_length_um"] - result["center_width_um"] / 2 < result["clearance_um"]:
            raise InvalidInputError("Crossing arms must leave the declared junction-to-exterior clearance")
    if family == "mmi2x2":
        if result["access_offset_um"] <= result["width_um"] / 2:
            raise InvalidInputError("MMI access guides must be distinct before entering the body")
        if result["access_offset_um"] + result["width_um"] / 2 > result["body_width_um"] / 2:
            raise InvalidInputError("MMI access guides must fit completely on the body face")
    if family in {"directional-coupler", "mmi2x2", "ybranch"}:
        if family == "directional-coupler":
            offset = (result["width_um"] + result["gap_um"]) / 2 - result["port_offset_um"]
            transition = result["transition_um"]
        elif family == "mmi2x2":
            offset = result["access_offset_um"] - result["port_offset_um"]
            transition = result["transition_um"]
        else:
            offset, transition = result["port_offset_um"], result["branch_length_um"]
        # For y=dy*(3t^2-2t^3), |curvature| is bounded by 6|dy|/L^2.
        # A normal offset becomes singular when half-width * curvature >= 1.
        if 3 * result["width_um"] * abs(offset) >= transition * transition:
            raise InvalidInputError("Core half-width reaches the minimum cubic bend radius")
    return result


def _rectangle(tag: str, x: float, y: float, width: float, height: float) -> dict[str, Any]:
    return {"tag": tag, "type": "rectangle", "x": x, "y": y, "width": width, "height": height, "group": "core"}


def _port(name: str, side: str, x: float, y: float, p: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "side": side, "center_um": [x, y],
            "width_um": p["width_um"], "window_um": p["port_window_um"]}


def _smooth_samples(x: float, y0: float, y1: float, length: float, samples: int) -> list[tuple[float, float, float]]:
    """Return (x, y, dy/dx) for a zero-end-slope cubic centerline."""
    points = []
    for i in range(samples + 1):
        t = i / samples
        points.append((x + length * t, y0 + (y1 - y0) * t * t * (3 - 2 * t),
                       (y1 - y0) * 6 * t * (1 - t) / length))
    return points


def _strip(tag: str, center: list[tuple[float, float, float]], width: float) -> dict[str, Any]:
    clean = [center[0]]
    for row in center[1:]:
        if row[:2] != clean[-1][:2]:
            clean.append(row)
    upper = []
    lower = []
    for x, y, slope in clean:
        half = width / (2 * math.sqrt(1 + slope * slope))
        upper.append([x - slope * half, y + half])
        lower.append([x + slope * half, y - half])
    return {"tag": tag, "type": "polygon", "points": upper + lower[::-1], "group": "core"}


def _smooth_length(length: float, offset: float) -> float:
    """Adaptive Simpson length of the intended cubic, not its sampled chords."""
    def speed(t: float) -> float:
        return math.hypot(length, offset * 6 * t * (1 - t))

    def integrate(a: float, b: float, fa: float, fm: float, fb: float, previous: float, depth: int) -> float:
        mid = (a + b) / 2
        fl, fr = speed((a + mid) / 2), speed((mid + b) / 2)
        left = (mid - a) * (fa + 4 * fl + fm) / 6
        right = (b - mid) * (fm + 4 * fr + fb) / 6
        delta = left + right - previous
        if depth == 0 or abs(delta) <= 1e-12 * max(1.0, length):
            return left + right + delta / 15
        return integrate(a, mid, fa, fl, fm, left, depth - 1) + integrate(mid, b, fm, fr, fb, right, depth - 1)

    fa, fm, fb = speed(0), speed(0.5), speed(1)
    return integrate(0, 1, fa, fm, fb, (fa + 4 * fm + fb) / 6, 18)


def _polygon(primitive: dict[str, Any]) -> list[list[float]]:
    if primitive["type"] == "polygon":
        return primitive["points"]
    x, y, width, height = (primitive[name] for name in ("x", "y", "width", "height"))
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def _union_area(primitives: list[dict[str, Any]]) -> float:
    """Exact piecewise-linear polygon union area, up to floating point error.

    Every vertex and proper edge-intersection x splits the vertical sweep.
    Between these breakpoints each union interval endpoint is linear, so its
    midpoint width integrates exactly. This is independent of a native CAD API.
    """
    polygons = [_polygon(primitive) for primitive in primitives]
    edges = [(a, b) for poly in polygons for a, b in zip(poly, poly[1:] + poly[:1], strict=True)]
    cuts = {point[0] for poly in polygons for point in poly}
    for i, (a, b) in enumerate(edges):
        dx, dy = b[0] - a[0], b[1] - a[1]
        for c, d in edges[i + 1:]:
            ex, ey = d[0] - c[0], d[1] - c[1]
            divisor = dx * ey - dy * ex
            if divisor == 0:
                continue
            cx, cy = c[0] - a[0], c[1] - a[1]
            t, u = (cx * ey - cy * ex) / divisor, (cx * dy - cy * dx) / divisor
            if 0 < t < 1 and 0 < u < 1:
                cuts.add(a[0] + t * dx)
    ordered = sorted(cuts)
    pieces = []
    for left, right in pairwise(ordered):
        if right - left <= 1e-14:
            continue
        x = (left + right) / 2
        intervals = []
        for poly in polygons:
            crossings = sorted(
                a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
                for a, b in zip(poly, poly[1:] + poly[:1], strict=True)
                if min(a[0], b[0]) < x < max(a[0], b[0])
            )
            if len(crossings) % 2:
                raise InvalidInputError("Invalid polygon vertical intersection parity")
            intervals.extend(zip(crossings[::2], crossings[1::2], strict=True))
        if not intervals:
            continue
        intervals.sort()
        start, stop = intervals[0]
        total = 0.0
        for bottom, top in intervals[1:]:
            if bottom <= stop:
                stop = max(stop, top)
            else:
                total += stop - start
                start, stop = bottom, top
        pieces.append((right - left) * (total + stop - start))
    return math.fsum(pieces)


def _straight(p: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, float]]:
    length, width = p["length_um"], p["width_um"]
    return ([_rectangle("guide", 0, -width / 2, length, width)],
            [_port("left", "left", 0, 0, p), _port("right", "right", length, 0, p)], {"guide": length})


def _crossing(p: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, float]]:
    arm, width, center = (p[name] for name in ("arm_length_um", "width_um", "center_width_um"))
    primitives = [_rectangle("horizontal", -arm, -width / 2, 2 * arm, width),
                  _rectangle("vertical", -width / 2, -arm, width, 2 * arm)]
    if center > width:
        primitives.append(_rectangle("junction", -center / 2, -center / 2, center, center))
    ports = [_port("west", "left", -arm, 0, p), _port("east", "right", arm, 0, p),
             _port("south", "bottom", 0, -arm, p), _port("north", "top", 0, arm, p)]
    return primitives, ports, {"horizontal": 2 * arm, "vertical": 2 * arm}


def _coupler(p: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, float]]:
    lead, transition, interaction = (p[name] for name in ("lead_um", "transition_um", "coupling_length_um"))
    offset, near, width = p["port_offset_um"], (p["width_um"] + p["gap_um"]) / 2, p["width_um"]
    total = 2 * (lead + transition) + interaction
    primitives = []
    for tag, sign in (("upper", 1), ("lower", -1)):
        center = [(0, sign * offset, 0)]
        center += _smooth_samples(lead, sign * offset, sign * near, transition, p["samples"])
        center += _smooth_samples(lead + transition + interaction, sign * near, sign * offset,
                                  transition, p["samples"])
        center.append((total, sign * offset, 0))
        primitives.append(_strip(tag, center, width))
    ports = [_port("upper_left", "left", 0, offset, p), _port("lower_left", "left", 0, -offset, p),
             _port("upper_right", "right", total, offset, p), _port("lower_right", "right", total, -offset, p)]
    length = 2 * lead + interaction + 2 * _smooth_length(transition, near - offset)
    return primitives, ports, {"upper": length, "lower": length}


def _mmi(p: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, float]]:
    lead, transition, body = (p[name] for name in ("lead_um", "transition_um", "body_length_um"))
    far, near, width = p["port_offset_um"], p["access_offset_um"], p["width_um"]
    total, entry = 2 * (lead + transition) + body, lead + transition
    primitives = [_rectangle("body", entry, -p["body_width_um"] / 2, body, p["body_width_um"])]
    for tag, sign in (("upper", 1), ("lower", -1)):
        left = [(0, sign * far, 0), *_smooth_samples(lead, sign * far, sign * near, transition, p["samples"])]
        right = _smooth_samples(entry + body, sign * near, sign * far, transition, p["samples"])
        right.append((total, sign * far, 0))
        primitives.extend([_strip(tag + "_left", left, width), _strip(tag + "_right", right, width)])
    ports = [_port("upper_left", "left", 0, far, p), _port("lower_left", "left", 0, -far, p),
             _port("upper_right", "right", total, far, p), _port("lower_right", "right", total, -far, p)]
    return primitives, ports, {"each_access": lead + _smooth_length(transition, near - far), "body_axis": body}


def _ybranch(p: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, float]]:
    lead, branch, offset, width = (p[name] for name in ("lead_um", "branch_length_um", "port_offset_um", "width_um"))
    total = 2 * lead + branch
    primitives = [_rectangle("trunk", 0, -width / 2, lead, width)]
    for tag, sign in (("upper", 1), ("lower", -1)):
        center = _smooth_samples(lead, 0, sign * offset, branch, p["samples"])
        center.append((total, sign * offset, 0))
        primitives.append(_strip(tag, center, width))
    ports = [_port("trunk", "left", 0, 0, p), _port("upper", "right", total, offset, p),
             _port("lower", "right", total, -offset, p)]
    path = 2 * lead + _smooth_length(branch, offset)
    return primitives, ports, {"trunk_to_upper": path, "trunk_to_lower": path}


_BUILDERS = {"straight": _straight, "crossing": _crossing, "directional-coupler": _coupler,
             "mmi2x2": _mmi, "ybranch": _ybranch}


def build_geometry(family: str, parameters: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build data-only core primitives and exterior port definitions.

    Port list order is the numeric native source order. Coupler/MMI and Y names
    match the corresponding reduced-model channel order. The area describes
    emitted polygons; it does not assert a smooth-curve or native CAD area.
    """
    p = _parameters(family, parameters)
    primitives, ports, lengths = _BUILDERS[family](p)
    points = [point for primitive in primitives for point in _polygon(primitive)]
    xmin, xmax = min(point[0] for point in points), max(point[0] for point in points)
    ymin, ymax = min(point[1] for point in points), max(point[1] for point in points)
    margin, window = p["clearance_um"], p["port_window_um"] / 2
    if family == "crossing":
        arm = p["arm_length_um"]
        bbox = [-arm, arm, -arm, arm]
    else:
        # Include the complete port windows and protect the upper/lower core.
        lower_window = min(port["center_um"][1] - window for port in ports)
        upper_window = max(port["center_um"][1] + window for port in ports)
        bbox = [0.0, xmax, min(ymin - margin, lower_window - 0.1), max(ymax + margin, upper_window + 0.1)]
    tolerance = 1e-12
    if xmin < bbox[0] - tolerance or xmax > bbox[1] + tolerance:
        raise InvalidInputError("A normal-offset guide extends beyond its declared exterior planes")
    limits = list(_BASE_LIMITS)
    if "samples" in p:
        limits.append("Cubic access paths use sampled normal-offset polygons; refine samples for geometry convergence.")
        limits.append("Centerline lengths integrate intended cubic curves; polygon edges remain separate geometry.")
    if family == "crossing":
        limits.append("The direct orthogonal crossing and optional square junction are not a low-crosstalk design.")
    elif family == "mmi2x2":
        limits.append("The multimode body length is not asserted to give self-imaging or a 50:50 split.")
    elif family == "ybranch":
        limits.append("Overlapping branch strips form the junction; native topology and reflection require checks.")
    elif family == "directional-coupler":
        limits.append("Access transitions also couple; zero parallel length is not a zero-coupling control.")
    return {"family": family, "parameters": p, "bbox_um": bbox, "primitives": primitives, "ports": ports,
            "expected_core_area_um2": _union_area(primitives),
            "expected_core_components": 2 if family == "directional-coupler" else 1,
            "centerline_lengths_um": lengths, "model_level": _MODEL_LEVEL, "limitations": limits}


__all__ = ["build_geometry"]
