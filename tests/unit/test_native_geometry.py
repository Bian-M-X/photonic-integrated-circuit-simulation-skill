"""Independent area, exterior-face, clearance and symmetry geometry checks."""

import json
import math
from itertools import pairwise

import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.native_geometry import build_geometry

FAMILIES = ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch")


def polygon(primitive):
    if primitive["type"] == "polygon":
        return primitive["points"]
    x, y, w, h = (primitive[name] for name in ("x", "y", "width", "height"))
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def area(points):
    return abs(sum(a[0] * b[1] - a[1] * b[0]
                   for a, b in zip(points, points[1:] + points[:1], strict=True))) / 2


def proper_intersection(a, b, c, d):
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return cross(a, b, c) * cross(a, b, d) < -1e-26 and cross(c, d, a) * cross(c, d, b) < -1e-26


def vertical_intervals(points, x):
    intersections = sorted(a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
                           for a, b in zip(points, points[1:] + points[:1], strict=True)
                           if min(a[0], b[0]) < x < max(a[0], b[0]))
    assert len(intersections) % 2 == 0
    return list(zip(intersections[::2], intersections[1::2], strict=True))


def union_height(polygons, x):
    """Independent union oracle via covered elementary intervals at one x."""
    intervals = [row for poly in polygons for row in vertical_intervals(poly, x)]
    coordinates = sorted({coordinate for row in intervals for coordinate in row})
    return sum(high - low for low, high in pairwise(coordinates)
               if any(start <= (low + high) / 2 <= stop for start, stop in intervals))


@pytest.mark.parametrize("family", FAMILIES)
def test_geometry_is_finite_json_data_and_declares_actual_port_faces(family):
    geometry = build_geometry(family)
    assert json.loads(json.dumps(geometry, allow_nan=False)) == geometry
    assert geometry["model_level"] == "2d-scalar-index-surrogate"
    xmin, xmax, ymin, ymax = geometry["bbox_um"]
    assert xmin < xmax and ymin < ymax
    assert geometry["expected_core_area_um2"] > 0
    names = [p["name"] for p in geometry["ports"]]
    assert len(names) == len(set(names))
    for primitive in geometry["primitives"]:
        points = polygon(primitive)
        assert area(points) > 0
        assert all(xmin - 1e-12 <= x <= xmax + 1e-12 and ymin - 1e-12 <= y <= ymax + 1e-12
                   for x, y in points)
    for port in geometry["ports"]:
        x, y = port["center_um"]
        half = port["window_um"] / 2
        assert port["width_um"] < port["window_um"]
        if port["side"] in {"left", "right"}:
            assert x == (xmin if port["side"] == "left" else xmax)
            assert ymin < y - half < y + half < ymax
        else:
            assert y == (ymin if port["side"] == "bottom" else ymax)
            assert xmin < x - half < x + half < xmax
    for i, port in enumerate(geometry["ports"]):
        for other in geometry["ports"][i + 1:]:
            if port["side"] == other["side"]:
                coordinate = 1 if port["side"] in {"left", "right"} else 0
                assert abs(port["center_um"][coordinate] - other["center_um"][coordinate]) > (
                    port["window_um"] + other["window_um"]) / 2


@pytest.mark.parametrize("family", FAMILIES)
def test_all_external_core_intersections_are_exact_port_widths(family):
    geometry = build_geometry(family)
    xmin, xmax, ymin, ymax = geometry["bbox_um"]
    for port in geometry["ports"]:
        direction = port["side"]
        core_coordinates = []
        for primitive in geometry["primitives"]:
            for x, y in polygon(primitive):
                if (direction == "left" and x == xmin) or (direction == "right" and x == xmax):
                    core_coordinates.append(y)
                elif (direction == "bottom" and y == ymin) or (direction == "top" and y == ymax):
                    core_coordinates.append(x)
        center = port["center_um"][1 if direction in {"left", "right"} else 0]
        selected = sorted({value for value in core_coordinates if abs(value - center) <= port["window_um"] / 2})
        assert len(selected) == 2
        assert selected[0] == pytest.approx(center - port["width_um"] / 2, abs=1e-13)
        assert selected[1] == pytest.approx(center + port["width_um"] / 2, abs=1e-13)


def test_straight_and_square_crossing_union_areas_have_closed_form_controls():
    straight = build_geometry("straight", {"width_um": 0.4, "length_um": 9})
    assert straight["expected_core_area_um2"] == pytest.approx(3.6, abs=1e-13)
    for junction in (0.3, 0.6, 1.2):
        cross = build_geometry("crossing", {"center_width_um": junction})
        # Four arm segments outside the central square, plus that square.
        expected = 4 * (3 - junction / 2) * 0.3 + junction * junction
        assert cross["expected_core_area_um2"] == pytest.approx(expected, abs=2e-13)


@pytest.mark.parametrize("family", ("directional-coupler", "mmi2x2", "ybranch"))
def test_sampled_normal_offset_polygons_have_no_proper_self_intersection(family):
    for count in (8, 32, 64):
        geometry = build_geometry(family, {"samples": count})
        for primitive in geometry["primitives"]:
            points = polygon(primitive)
            edges = list(zip(points, points[1:] + points[:1], strict=True))
            for i, (a, b) in enumerate(edges):
                for j in range(i + 2, len(edges)):
                    if i == 0 and j == len(edges) - 1:
                        continue
                    assert not proper_intersection(a, b, *edges[j])


def test_coupler_has_positive_gap_and_area_equals_two_disjoint_polygon_areas():
    for gap in (0.05, 0.2, 0.7):
        geometry = build_geometry("directional-coupler", {"gap_um": gap})
        upper, lower = map(polygon, geometry["primitives"])
        assert min(y for _, y in upper) - max(y for _, y in lower) == pytest.approx(gap, abs=2e-13)
        assert geometry["expected_core_area_um2"] == pytest.approx(area(upper) + area(lower), abs=3e-13)
        reflected = sorted((round(x, 12), round(-y, 12)) for x, y in upper)
        assert reflected == sorted((round(x, 12), round(y, 12)) for x, y in lower)
        assert geometry["expected_core_components"] == 2


def test_coupler_zero_parallel_length_keeps_distinct_ports_and_access_path():
    geometry = build_geometry("directional-coupler", {"coupling_length_um": 0})
    assert geometry["bbox_um"][1] == 10
    assert geometry["centerline_lengths_um"]["upper"] > 10
    assert geometry["expected_core_area_um2"] > 2 * 0.3 * 10
    assert geometry["centerline_lengths_um"]["upper"] == geometry["centerline_lengths_um"]["lower"]


def test_mmi_area_is_body_plus_nonoverlapping_access_polygons():
    geometry = build_geometry("mmi2x2")
    expected = sum(area(polygon(primitive)) for primitive in geometry["primitives"])
    assert geometry["expected_core_area_um2"] == pytest.approx(expected, abs=3e-13)
    assert geometry["expected_core_components"] == 1
    access_x = geometry["parameters"]["lead_um"] + geometry["parameters"]["transition_um"]
    assert union_height([polygon(p) for p in geometry["primitives"]], access_x + 0.01) == pytest.approx(1.5)


def test_y_branch_union_area_includes_overlap_without_double_counting():
    geometry = build_geometry("ybranch")
    polygons = [polygon(p) for p in geometry["primitives"]]
    assert geometry["expected_core_area_um2"] < sum(map(area, polygons))
    # An independently gridded integral, not the producer's edge-intersection sweep.
    count, xmax = 18000, geometry["bbox_um"][1]
    approximate = xmax / count * sum(union_height(polygons, xmax * (i + 0.5) / count) for i in range(count))
    assert geometry["expected_core_area_um2"] == pytest.approx(approximate, abs=2e-6)
    assert geometry["expected_core_components"] == 1
    assert geometry["centerline_lengths_um"]["trunk_to_upper"] > xmax
    assert geometry["centerline_lengths_um"]["trunk_to_upper"] == geometry["centerline_lengths_um"]["trunk_to_lower"]


def test_centerline_length_uses_curve_not_declared_x_span_and_refines_separately():
    coarse = build_geometry("directional-coupler", {"samples": 8})
    fine = build_geometry("directional-coupler", {"samples": 128})
    assert coarse["centerline_lengths_um"] == fine["centerline_lengths_um"]
    assert fine["centerline_lengths_um"]["upper"] > fine["bbox_um"][1]
    assert abs(fine["expected_core_area_um2"] - 0.6 * fine["centerline_lengths_um"]["upper"]) < abs(
        coarse["expected_core_area_um2"] - 0.6 * coarse["centerline_lengths_um"]["upper"])
    # Independent numerical integral of ds/dt for each cubic, plus the straight pieces.
    n, shift, length = 20000, -1.25, 3
    integral = sum(math.hypot(length, 6 * shift * t * (1 - t))
                   for t in ((i + 0.5) / n for i in range(n))) / n
    assert fine["centerline_lengths_um"]["upper"] == pytest.approx(10 + 2 * integral, abs=1e-10)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("bad", (True, None, "0.3", math.nan, math.inf, -0.2, 10**500))
def test_invalid_widths_and_nonfinite_inputs_are_rejected(family, bad):
    with pytest.raises(InvalidInputError):
        build_geometry(family, {"width_um": bad})


@pytest.mark.parametrize("family, parameters", [
    ("unknown", {}), ("straight", {"widht_um": 0.3}), ("straight", []),
    ("directional-coupler", {"samples": 9.5}), ("ybranch", {"samples": 257}),
    ("ybranch", {"port_offset_um": 0.4, "port_window_um": 0.8}),
    ("mmi2x2", {"access_offset_um": 0.7}), ("mmi2x2", {"access_offset_um": 0.15}),
    ("crossing", {"center_width_um": 0.2}), ("crossing", {"arm_length_um": 1, "center_width_um": 2}),
    ("crossing", {"arm_length_um": 1.1, "center_width_um": 0.3}),
    ("mmi2x2", {"width_um": 0.6, "port_offset_um": 3, "transition_um": 1}),
    ("ybranch", {"width_um": 0.8, "port_offset_um": 2, "branch_length_um": 1}),
])
def test_parameter_combinations_that_break_geometry_are_rejected(family, parameters):
    with pytest.raises(InvalidInputError):
        build_geometry(family, parameters)


def test_outputs_are_independent_values_and_do_not_mutate_caller_parameters():
    supplied = {"coupling_length_um": 4}
    left = build_geometry("directional-coupler", supplied)
    right = build_geometry("directional-coupler", supplied)
    left["parameters"]["gap_um"] = 2
    left["primitives"][0]["points"][0][0] = -99
    assert right["parameters"]["gap_um"] == 0.2
    assert right["primitives"][0]["points"][0][0] == 0
    assert supplied == {"coupling_length_um": 4}
