"""Offline return-to-center Euler geometry proposal; never starts a solver."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from itertools import pairwise
from pathlib import Path

from photonic_workflow.recipes.geometry import compute_symmetric_euler_bend

SPAN_UM = 14.0
LEAD_UM = 3.0
HALF_HEIGHT_UM = 2.5
RESOLUTION_UM = 64 * math.ulp(SPAN_UM)


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite number, not bool or text")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def validate_sampled_polygon(vertices):
    """Return unsigned sample-polygon area; reject degenerate/intersecting edges.

    This checks the supplied straight sample edges, not a solver interpolant.
    """
    if not isinstance(vertices, list | tuple) or len(vertices) < 3:
        raise ValueError("Sample polygon needs at least three 2D vertices")
    points = []
    for point in vertices:
        if not isinstance(point, list | tuple) or len(point) != 2:
            raise ValueError("Sample polygon needs 2D vertices")
        points.append(tuple(_number(value, "vertex coordinate") for value in point))
    if len(set(points)) != len(points):
        raise ValueError("Repeated sample vertices; geometry may be below coordinate resolution")

    def cross(a, b, c):
        result = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if not math.isfinite(result):
            raise ValueError("Sample polygon arithmetic must remain finite")
        return result

    def on_segment(a, b, p):
        return (
            cross(a, b, p) == 0
            and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        )

    edges = list(zip(points, points[1:] + points[:1], strict=True))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            c, d = edges[j]
            if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
                continue
            if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                continue
            ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
            if (
                (((ab_c < 0 < ab_d) or (ab_d < 0 < ab_c)) and ((cd_a < 0 < cd_b) or (cd_b < 0 < cd_a)))
                or on_segment(a, b, c)
                or on_segment(a, b, d)
                or on_segment(c, d, a)
                or on_segment(c, d, b)
            ):
                raise ValueError("Self-intersecting sample polygon")
    try:
        area = abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in edges)) / 2
    except (OverflowError, ValueError) as exc:
        raise ValueError("Sample polygon area must remain finite") from exc
    if not math.isfinite(area) or area <= 0:
        raise ValueError("Sample polygon must have finite positive area")
    return area


def _offsets(points, tangents, width):
    left, right = [], []
    half = width / 2
    for (x, y), (tx, ty) in zip(points, tangents, strict=True):
        left.append([x - half * ty, y + half * tx])
        right.append([x + half * ty, y - half * tx])
    return left, right


def _segment(tag, kind, points, tangents, width, length, **metadata):
    left, right = _offsets(points, tangents, width)
    table = left + list(reversed(right))
    validate_sampled_polygon(table)
    return {
        "tag": tag,
        "kind": kind,
        "centerline_um": points,
        "tangents": tangents,
        "left_boundary_um": left,
        "right_boundary_um": right,
        "boundary_table_um": table,
        "centerline_length_um": length,
        **metadata,
    }


def _rectangle(tag, start, end, width):
    length = end[0] - start[0]
    if length <= RESOLUTION_UM or start[1] != end[1]:
        raise ValueError("Straight extent is below coordinate resolution")
    return _segment(
        tag,
        "rectangle",
        [start, end],
        [[1.0, 0.0], [1.0, 0.0]],
        width,
        length,
        pos_um=[start[0], start[1] - width / 2],
        size_um=[length, width],
    )


def build_profile(turn_angle_deg=15.0, minimum_radius_um=3.0, width_um=0.3, samples=64):
    """Compose four reflected Euler pieces with horizontal, centered end ports.

    The intended Euler length of each piece is analytic. Its endpoint is the
    existing recipe's midpoint approximation, which also sets the middle lead.
    """
    angle = _number(turn_angle_deg, "turn_angle_deg")
    radius = _number(minimum_radius_um, "minimum_radius_um")
    width = _number(width_um, "width_um")
    if not abs(angle) < 90:
        raise ValueError("turn_angle_deg must have magnitude strictly below 90 degrees")
    if radius <= 0:
        raise ValueError("minimum_radius_um must be positive")
    if not RESOLUTION_UM < width < min(2 * radius, 2.4):
        raise ValueError("width_um must exceed coordinate resolution and be smaller than 2R and 2.4 um")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples % 2 or not 8 <= samples <= 256:
        raise ValueError("samples must be an even integer from 8 through 256")

    middle = SPAN_UM - 2 * LEAD_UM
    endpoint = [0.0, 0.0]
    if angle == 0:
        segments = [_rectangle("bend_straight", [0.0, 0.0], [SPAN_UM, 0.0], width)]
    else:
        recipe = compute_symmetric_euler_bend(abs(angle), radius, width, samples)
        quarter = recipe["centerline"]
        quarter_tangents = recipe["tangents"]
        a, b = quarter[-1]
        direction = 1.0 if angle > 0 else -1.0
        endpoint = [a, direction * b]
        middle = SPAN_UM - 2 * LEAD_UM - 4 * a
        if not math.isfinite(middle) or middle <= RESOLUTION_UM:
            raise ValueError("Four Euler pieces leave no representable positive middle straight extent")
        if 2 * b <= RESOLUTION_UM:
            raise ValueError("Nonzero bend height is below coordinate resolution; use exactly zero for its control")
        starts = [
            [LEAD_UM, 0.0],
            [LEAD_UM + a, direction * b],
            [SPAN_UM - LEAD_UM - 2 * a, direction * 2 * b],
            [SPAN_UM - LEAD_UM - a, direction * b],
        ]
        ends = [starts[1], [LEAD_UM + 2 * a, direction * 2 * b], starts[3], [SPAN_UM - LEAD_UM, 0.0]]
        bend_points = [
            [[LEAD_UM + x, direction * y] for x, y in quarter],
            [[LEAD_UM + 2 * a - x, direction * (2 * b - y)] for x, y in reversed(quarter)],
            [[SPAN_UM - LEAD_UM - 2 * a + x, direction * (2 * b - y)] for x, y in quarter],
            [[SPAN_UM - LEAD_UM - x, direction * y] for x, y in reversed(quarter)],
        ]
        bend_tangents = [
            [[tx, direction * ty] for tx, ty in quarter_tangents],
            [[tx, direction * ty] for tx, ty in reversed(quarter_tangents)],
            [[tx, -direction * ty] for tx, ty in quarter_tangents],
            [[tx, -direction * ty] for tx, ty in reversed(quarter_tangents)],
        ]
        curves = []
        for index, (points, tangents) in enumerate(zip(bend_points, bend_tangents, strict=True)):
            # Shared join coordinates remove only arithmetic-order roundoff;
            # they do not refit, rotate or rescale the recipe's sampled curve.
            points[0], points[-1] = starts[index], ends[index]
            curves.append(
                _segment(
                    f"bend_curve_{index + 1}",
                    "euler",
                    points,
                    tangents,
                    width,
                    recipe["length"],
                    signed_turn_angle_deg=angle if index in (0, 3) else -angle,
                )
            )
        segments = [
            _rectangle("bend_lead_left", [0.0, 0.0], starts[0], width),
            curves[0],
            curves[1],
            _rectangle("bend_middle", ends[1], starts[2], width),
            curves[2],
            curves[3],
            _rectangle("bend_lead_right", ends[3], [SPAN_UM, 0.0], width),
        ]

    centerline, tangents = [], []
    for segment in segments:
        points, directions = segment["centerline_um"], segment["tangents"]
        if centerline:
            if centerline[-1] != points[0] or tangents[-1] != directions[0]:
                raise ValueError("Segment endpoints or tangents do not join")
            points, directions = points[1:], directions[1:]
        centerline.extend(points)
        tangents.extend(directions)
    if any(b[0] <= a[0] for a, b in pairwise(centerline)):
        raise ValueError("Centerline samples must advance in x above coordinate resolution")
    left, right = _offsets(centerline, tangents, width)
    for boundary in (left, right):
        if any(b[0] <= a[0] for a, b in pairwise(boundary)):
            raise ValueError("Normal-offset sample boundary folds or falls below coordinate resolution")
    table = left + list(reversed(right))
    area = validate_sampled_polygon(table)
    bbox = [min(p[0] for p in table), max(p[0] for p in table), min(p[1] for p in table), max(p[1] for p in table)]
    if not (bbox[0] == 0 and bbox[1] == SPAN_UM and -HALF_HEIGHT_UM < bbox[2] < bbox[3] < HALF_HEIGHT_UM):
        raise ValueError("Sampled core does not fit the fixed computational exterior")
    length = math.fsum(segment["centerline_length_um"] for segment in segments)
    sampled_length = math.fsum(math.dist(a, b) for a, b in pairwise(centerline))
    intended_area = width * length
    return {
        "schema_version": "1.0",
        "stage": "offline_geometry_proposal",
        "shape": "return_to_center_euler",
        "parameters": {"turn_angle_deg": angle, "minimum_radius_um": radius, "width_um": width, "samples": samples},
        "span_um": SPAN_UM,
        "end_lead_length_um": LEAD_UM,
        "middle_straight_length_um": middle if angle != 0 else SPAN_UM,
        "single_bend_endpoint_um": endpoint,
        "centerline_um": centerline,
        "tangents": tangents,
        "left_boundary_um": left,
        "right_boundary_um": right,
        "boundary_table_um": table,
        "segments": segments,
        "centerline_length_um": length,
        "sampled_centerline_length_um": sampled_length,
        "intended_strip_area_um2": intended_area,
        "sampled_polygon_area_um2": area,
        "sampled_area_error_um2": area - intended_area,
        "core_bbox_um": bbox,
        "maximum_curvature_per_um": 0.0 if angle == 0 else 1 / radius,
        "offset_regularity_margin": 1.0 if angle == 0 else 1 - width / (2 * radius),
        "zero_bend_geometry": angle == 0,
        "sampled_polygon_simple": True,
        "will_execute": False,
        "physics_accepted": False,
        "native_execution": "not_performed",
        "limitations": [
            "Only sample-polygon topology is checked; COMSOL interpolant topology and connectivity are unverified.",
            "Closed solid InterpolationCurve end caps may bow between constraints and affect joins or the Union.",
            "Euler endpoints use the midpoint recipe; middle-straight and full intended length depend on samples.",
            "Midpoint increments retain step length; sampled and intended length agreement is not convergence.",
            "width*length is an intended regular-strip area, not measured COMSOL core area.",
            "InterpolationCurve tables propose smooth-geometry configuration, not exact analytic Euler boundaries.",
            "Zero bend proves geometric degeneration only, not mesh, modal or scattering equivalence.",
            "No background, materials, selections, ports, mesh, study or solver has been built or executed.",
            "This proposal is not a profile_modes/profile_driven checkpoint input or an accepted performance model.",
        ],
    }


def _java_vector(values):
    return "new double[]{" + ",".join(repr(float(value)) for value in values) + "}"


def render_profile(turn_angle_deg=15.0, minimum_radius_um=3.0, width_um=0.3, samples=64):
    """Return metadata and a fixed numeric core-only COMSOL Java fragment."""
    profile = build_profile(turn_angle_deg, minimum_radius_um, width_um, samples)
    lines = [
        "// Offline geometry proposal; not native geometry or physics acceptance.",
        '// Requires an existing 2D GeomSequence g with lengthUnit("um").',
        "// No background, materials, ports, studies or solver are configured here.",
    ]
    for segment in profile["segments"]:
        tag = segment["tag"]
        if segment["kind"] == "rectangle":
            lines.extend(
                [
                    f'g.create("{tag}", "Rectangle");',
                    f'g.feature("{tag}").set("pos", {_java_vector(segment["pos_um"])});',
                    f'g.feature("{tag}").set("size", {_java_vector(segment["size_um"])});',
                ]
            )
        else:
            table = ",\n".join(
                "{" + ",".join(repr(float(v)) for v in point) + "}" for point in segment["boundary_table_um"]
            )
            lines.extend(
                [
                    f'g.create("{tag}", "InterpolationCurve");',
                    f'g.feature("{tag}").set("type", "solid");',
                    f'g.feature("{tag}").set("source", "table");',
                    f'g.feature("{tag}").set("table", new double[][]{{\n{table}\n}});',
                    f'g.feature("{tag}").set("rtol", 0.0);',
                ]
            )
    tags = ",".join('"' + segment["tag"] + '"' for segment in profile["segments"])
    lines.extend(
        [
            'g.create("bend_core", "Union");',
            f'g.feature("bend_core").selection("input").set(new String[]{{{tags}}});',
            'g.feature("bend_core").set("intbnd", "off");',
        ]
    )
    fragment = ("\n".join(lines) + "\n").encode("utf-8")
    profile["geometry_fragment_sha256"] = hashlib.sha256(fragment).hexdigest()
    return profile, fragment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turn-angle-deg", type=float, default=15.0)
    parser.add_argument("--minimum-radius-um", type=float, default=3.0)
    parser.add_argument("--width-um", type=float, default=0.3)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--output", type=Path, help="New directory; omit for JSON-only dry plan")
    args = parser.parse_args(argv)
    try:
        if args.output is not None and os.path.lexists(args.output):
            raise ValueError("Output path must not already exist")
        profile, fragment = render_profile(args.turn_angle_deg, args.minimum_radius_um, args.width_um, args.samples)
        serialized = json.dumps(profile, indent=2, allow_nan=False) + "\n"
        if args.output is not None:
            args.output.mkdir()  # Exclusive creation; parents must already exist.
            with (args.output / "geometry_fragment.java").open("xb") as stream:
                stream.write(fragment)
            with (args.output / "geometry.json").open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
        print(serialized, end="")
    except (ValueError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
