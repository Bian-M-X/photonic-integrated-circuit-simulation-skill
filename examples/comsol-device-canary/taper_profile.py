"""Offline symmetric taper geometry and configure-source generator; no solver calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

TEMPLATE = Path(__file__).with_name("DeviceCanary.java")
AREA_ANCHOR = ('double expected=tag.equals("coremat")?(SHAPE.equals("straight")?4.2:4.28)'
               ':(SHAPE.equals("straight")?65.8:65.72);')
BOX_ANCHOR = 'double half=tag.equals("coremat")?(SHAPE.equals("straight")?.15:.17):2.5;'
BOX_COORDINATES_ANCHOR = 'double[] expectedBox={0,14,-half,half};'
HEIGHT_ANCHOR = 'double h=SHAPE.equals("straight")?.15:.17;'
TABLE_ANCHOR = ('g.feature("core").set("table",new double[][]{{0,-.15},{5,-.15},{7,-h},{9,-.15},'
                '{14,-.15},{14,.15},{9,.15},{7,h},{5,.15},{0,.15}});')


def _number(value, name):
    # Deliberately accept only JSON-like Python numbers, never bool or strings.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite number, not bool or text")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def validate_polygon(vertices):
    """Reject nonfinite, repeated, zero-area or intersecting polygon vertices."""
    if len(vertices) < 3 or any(len(v) != 2 for v in vertices):
        raise ValueError("Polygon needs at least three 2D vertices")
    points = [tuple(_number(v, "vertex coordinate") for v in point) for point in vertices]
    if len(set(points)) != len(points):
        raise ValueError("Duplicate polygon vertices; positive length may be below numeric resolution")

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, p):
        return (cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))

    edges = list(zip(points, points[1:] + points[:1], strict=True))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            c, d = edges[j]
            ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
            if ((ab_c * ab_d < 0 and cd_a * cd_b < 0)
                    or on_segment(a, b, c) or on_segment(a, b, d)
                    or on_segment(c, d, a) or on_segment(c, d, b)):
                raise ValueError("Self-intersecting polygon")
    area = 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    if not math.isfinite(area) or area <= 0:
        raise ValueError("Polygon must have finite positive counterclockwise area")
    return area


def build_profile(center_width_um=0.34, taper_length_um=4.0):
    width = _number(center_width_um, "center_width_um")
    length = _number(taper_length_um, "taper_length_um")
    if not 0.30 <= width < 2.4:
        raise ValueError("center_width_um must satisfy 0.30 <= W < 2.4")
    if not 0 <= length < 14:
        raise ValueError("taper_length_um must satisfy 0 <= L < 14")
    if length == 0 and width != 0.30:
        raise ValueError("Zero taper length requires center width 0.30; a step is not defined")
    half = width / 2
    if length == 0:
        vertices = [[0.0, -0.15], [14.0, -0.15], [14.0, 0.15], [0.0, 0.15]]
    else:
        left, right = 7 - length / 2, 7 + length / 2
        vertices = [[0.0, -0.15], [left, -0.15], [7.0, -half], [right, -0.15],
                    [14.0, -0.15], [14.0, 0.15], [right, 0.15], [7.0, half],
                    [left, 0.15], [0.0, 0.15]]
        if not 0 < left < 7 < right < 14:
            raise ValueError("Positive taper extent is below floating-point coordinate resolution")
    area = 4.2 + 0.5 * length * (width - 0.30)
    if not math.isclose(validate_polygon(vertices), area, rel_tol=1e-14, abs_tol=1e-14):
        raise ValueError("Polygon area differs from requested geometry")
    return {
        "schema_version": "1.0", "stage": "configure", "shape": "symmetric_double_ramp",
        "center_width_um": width, "taper_length_um": length, "end_width_um": 0.30,
        "center_x_um": 7.0, "total_length_um": 14.0, "vertices_um": vertices,
        "core_area_um2": area, "background_area_um2": 70 - area,
        "core_bbox_um": [0.0, 14.0, -half, half],
        "equal_width_geometry": width == 0.30,
        "will_execute": False, "physics_accepted": False,
        "native_execution": "not_performed",
        "limitations": [
            "Custom profile has not undergone native execution or physical acceptance.",
            "Equal width establishes geometric equivalence only, not mesh or scattering equivalence.",
            "The legacy runner has a fixed profile; its modes, solve and plots do not accept this custom profile.",
            "Positive length must remain representable as distinct vertices at x=7 um.",
        ],
    }


def render_profile(center_width_um=0.34, taper_length_um=4.0, *, template_bytes=None):
    """Return profile metadata and exact legacy-write-compatible configure bytes."""
    profile = build_profile(center_width_um, taper_length_um)
    original = TEMPLATE.read_bytes() if template_bytes is None else template_bytes
    text = original.decode("utf-8")
    for anchor in (AREA_ANCHOR, BOX_ANCHOR, BOX_COORDINATES_ANCHOR,
                   HEIGHT_ANCHOR, TABLE_ANCHOR, "__STAGE__", "__SHAPE__"):
        if text.count(anchor) != 1:
            raise ValueError(f"Template anchor must occur exactly once: {anchor}")
    width, length = profile["center_width_um"], profile["taper_length_um"]
    if (width, length) != (0.34, 4.0):
        half = repr(width / 2)
        table = ",".join("{" + repr(x) + "," + repr(y) + "}" for x, y in profile["vertices_um"])
        replacements = {
            AREA_ANCHOR: ('double expected=tag.equals("coremat")?(SHAPE.equals("straight")?4.2:'
                          + repr(profile["core_area_um2"]) + '):(SHAPE.equals("straight")?65.8:'
                          + repr(profile["background_area_um2"]) + ');'),
            BOX_ANCHOR: f'double half=tag.equals("coremat")?(SHAPE.equals("straight")?.15:{half}):2.5;',
            HEIGHT_ANCHOR: f'double h=SHAPE.equals("straight")?.15:{half};',
            TABLE_ANCHOR: 'g.feature("core").set("table",new double[][]{' + table + '});',
        }
        for anchor, replacement in replacements.items():
            text = text.replace(anchor, replacement)
    text = text.replace("__STAGE__", "configure").replace("__SHAPE__", "taper")
    # Match run.py: raw UTF-8 decode, replacements, then write_text(newline=None).
    source = text.replace("\n", os.linesep).encode("utf-8")
    profile["template_sha256"] = hashlib.sha256(original).hexdigest()
    profile["configure_source_sha256"] = hashlib.sha256(source).hexdigest()
    return profile, source


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-width-um", type=float, default=0.34)
    parser.add_argument("--taper-length-um", type=float, default=4.0)
    parser.add_argument("--output", type=Path, help="New directory; omit for JSON-only dry plan")
    args = parser.parse_args(argv)
    try:
        if args.output is not None and os.path.lexists(args.output):
            raise ValueError("Output path must not already exist")
        profile, source = render_profile(args.center_width_um, args.taper_length_um)
        serialized = json.dumps(profile, indent=2, allow_nan=False) + "\n"
        if args.output is not None:
            args.output.mkdir()  # Exclusive creation; parents must already exist.
            with (args.output / "DeviceCanary.java").open("xb") as stream:
                stream.write(source)
            with (args.output / "profile.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
        print(serialized, end="")
    except (ValueError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
