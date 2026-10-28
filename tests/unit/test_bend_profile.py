"""Independent Euler geometry controls; no COMSOL or producer quadrature oracle."""

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "examples/comsol-device-canary/bend_profile.py"
SPEC = importlib.util.spec_from_file_location("bend_profile", SOURCE)
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


def simpson(function, low, high, intervals=2048):
    """Independent high-order integral, unlike the recipe's midpoint steps."""
    step = (high - low) / intervals
    odd = math.fsum(function(low + i * step) for i in range(1, intervals, 2))
    even = math.fsum(function(low + i * step) for i in range(2, intervals, 2))
    return step * (function(low) + function(high) + 4 * odd + 2 * even) / 3


def euler_endpoint(angle_deg, radius):
    """Integrate the curvature-defined physical Euler curve independently."""
    turn = math.radians(abs(angle_deg))
    half = radius * turn

    def heading(distance):
        if distance <= half:
            return distance**2 / (2 * radius * half)
        return turn - (2 * half - distance) ** 2 / (2 * radius * half)

    def component(function):
        return simpson(lambda s: function(heading(s)), 0, half) + simpson(
            lambda s: function(heading(s)), half, 2 * half
        )

    return component(math.cos), math.copysign(component(math.sin), angle_deg)


def shoelace(vertices):
    return (
        abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True)))
        / 2
    )


def polyline_length(points):
    return math.fsum(math.dist(a, b) for a, b in pairwise(points))


def assert_vectors_close(left, right, tolerance=2e-13):
    assert len(left) == len(right)
    for actual, expected in zip(left, right, strict=True):
        assert actual == pytest.approx(expected, abs=tolerance)


def proper_crossing(a, b, c, d):
    def orientation(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return orientation(a, b, c) * orientation(a, b, d) < 0 and orientation(c, d, a) * orientation(c, d, b) < 0


@pytest.mark.parametrize("angle,radius,width", [(15, 3, 0.3), (-15, 3, 0.3), (30, 2, 0.4), (45, 1, 0.3)])
def test_physical_endpoint_external_integral_and_intended_length(angle, radius, width):
    profile = PROFILE.build_profile(angle, radius, width, 64)
    curves = [segment for segment in profile["segments"] if segment["kind"] == "euler"]
    assert len(curves) == 4
    reference_x, reference_y = euler_endpoint(angle, radius)
    first = curves[0]["centerline_um"]
    assert first[0] == pytest.approx((3, 0), abs=1e-14)
    assert first[-1] == pytest.approx((3 + reference_x, reference_y), abs=1e-8)
    true_length = 14 - 4 * reference_x + 8 * radius * math.radians(abs(angle))
    assert profile["centerline_length_um"] == pytest.approx(true_length, abs=4e-8)
    assert profile["intended_strip_area_um2"] == pytest.approx(width * true_length, abs=2e-8)
    assert profile["centerline_length_um"] > 14
    assert profile["sampled_polygon_area_um2"] == pytest.approx(shoelace(profile["boundary_table_um"]), abs=1e-12)
    assert profile["sampled_centerline_length_um"] == pytest.approx(
        polyline_length(profile["centerline_um"]), abs=2e-12
    )


def test_refinement_reduces_independent_endpoint_length_and_area_errors():
    reference_x, reference_y = euler_endpoint(15, 3)
    true_length = 14 - 4 * reference_x + 8 * 3 * math.radians(15)
    endpoint_errors, length_errors, area_errors = [], [], []
    for samples in (8, 16, 32, 64):
        profile = PROFILE.build_profile(samples=samples)
        first_curve = next(segment for segment in profile["segments"] if segment["kind"] == "euler")
        endpoint_errors.append(math.dist(first_curve["centerline_um"][-1], (3 + reference_x, reference_y)))
        length_errors.append(abs(profile["centerline_length_um"] - true_length))
        area_errors.append(abs(profile["sampled_polygon_area_um2"] - 0.3 * true_length))
    for errors in (endpoint_errors, length_errors, area_errors):
        assert errors[-1] > 0  # This control must distinguish a finite sampled approximation.
        assert all(fine < coarse * 0.4 + 2e-14 for coarse, fine in pairwise(errors))


def test_zero_angle_is_exact_rectangle_without_a_bend_or_solver_claim():
    profile, fragment = PROFILE.render_profile(turn_angle_deg=0)
    assert profile["zero_bend_geometry"] is True
    assert len(profile["segments"]) == 1 and profile["segments"][0]["kind"] == "rectangle"
    assert profile["centerline_length_um"] == profile["sampled_centerline_length_um"] == 14
    assert profile["intended_strip_area_um2"] == pytest.approx(4.2)
    assert profile["sampled_polygon_area_um2"] == pytest.approx(4.2)
    assert profile["core_bbox_um"] == [0, 14, -0.15, 0.15]
    assert {tuple(vertex) for vertex in profile["boundary_table_um"]} == {
        (0, -0.15),
        (14, -0.15),
        (14, 0.15),
        (0, 0.15),
    }
    assert b"InterpolationCurve" not in fragment and b'"Rectangle"' in fragment
    assert profile["will_execute"] is False and profile["physics_accepted"] is False
    assert profile["native_execution"] == "not_performed"


def test_positive_and_negative_bends_are_reflections_with_same_length_and_area():
    positive = PROFILE.build_profile(turn_angle_deg=20, minimum_radius_um=2)
    negative = PROFILE.build_profile(turn_angle_deg=-20, minimum_radius_um=2)
    assert_vectors_close(negative["centerline_um"], [(x, -y) for x, y in positive["centerline_um"]])
    assert_vectors_close(negative["tangents"], [(x, -y) for x, y in positive["tangents"]])
    assert_vectors_close(negative["left_boundary_um"], [(x, -y) for x, y in positive["right_boundary_um"]])
    assert_vectors_close(negative["right_boundary_um"], [(x, -y) for x, y in positive["left_boundary_um"]])
    for key in ("centerline_length_um", "sampled_centerline_length_um", "sampled_polygon_area_um2"):
        assert positive[key] == pytest.approx(negative[key], abs=1e-12)


def test_curvature_heading_ramps_and_connected_segment_tangents():
    angle, radius, width, samples = 25, 2, 0.4, 16
    profile = PROFILE.build_profile(angle, radius, width, samples)
    assert profile["maximum_curvature_per_um"] == pytest.approx(1 / radius)
    assert profile["offset_regularity_margin"] == pytest.approx(1 - width / (2 * radius))
    for previous, following in pairwise(profile["segments"]):
        assert previous["centerline_um"][-1] == pytest.approx(following["centerline_um"][0], abs=2e-14)
        assert previous["tangents"][-1] == pytest.approx(following["tangents"][0], abs=2e-14)
    turns = [segment for segment in profile["segments"] if segment["kind"] == "euler"]
    assert [segment["signed_turn_angle_deg"] for segment in turns] == [angle, -angle, -angle, angle]
    radians = math.radians(angle)
    for segment_index, segment in enumerate(turns):
        for index, tangent in enumerate(segment["tangents"]):
            distance_fraction = index / samples
            # Integrate a physical triangular curvature ramp in normalized arc distance.
            local_heading = radians * (
                2 * distance_fraction**2 if distance_fraction <= 0.5 else 1 - 2 * (1 - distance_fraction) ** 2
            )
            expected_heading = (local_heading, radians - local_heading, -local_heading, -radians + local_heading)[
                segment_index
            ]
            assert math.atan2(tangent[1], tangent[0]) == pytest.approx(expected_heading, abs=3e-15)


@pytest.mark.parametrize("angle", [0, 15, -15, 45])
def test_ports_tangents_and_true_normal_width(angle):
    profile = PROFILE.build_profile(angle, 1 if angle == 45 else 3)
    centers, tangents = profile["centerline_um"], profile["tangents"]
    left, right = profile["left_boundary_um"], profile["right_boundary_um"]
    assert centers[0] == [0, 0] and centers[-1] == [14, 0]
    assert tangents[0] == tangents[-1] == [1, 0]
    assert len(centers) == len(tangents) == len(left) == len(right)
    has_oblique_normal = False
    for center, tangent, upper, lower in zip(centers, tangents, left, right, strict=True):
        assert math.hypot(*tangent) == pytest.approx(1, abs=3e-15)
        displacement = (upper[0] - lower[0], upper[1] - lower[1])
        assert math.hypot(*displacement) == pytest.approx(0.3, abs=3e-14)
        assert math.fsum(d * t for d, t in zip(displacement, tangent, strict=True)) == pytest.approx(0, abs=3e-14)
        assert [(u + v) / 2 for u, v in zip(upper, lower, strict=True)] == pytest.approx(center, abs=3e-14)
        if abs(tangent[1]) > 0.1:
            has_oblique_normal = True
            assert abs(displacement[1]) < 0.3 - 1e-4
    assert has_oblique_normal == (angle != 0)


def test_sampled_outline_bounds_area_and_no_crossing_by_independent_segments():
    profile = PROFILE.build_profile(samples=16)
    vertices = profile["boundary_table_um"]
    assert len(vertices) == len(set(map(tuple, vertices)))
    assert profile["core_bbox_um"] == [
        min(x for x, _ in vertices),
        max(x for x, _ in vertices),
        min(y for _, y in vertices),
        max(y for _, y in vertices),
    ]
    assert all(0 <= x <= 14 and -2.5 < y < 2.5 for x, y in vertices)
    edges = list(zip(vertices, vertices[1:] + vertices[:1], strict=True))
    for index, (a, b) in enumerate(edges):
        for second in range(index + 2, len(edges)):
            if index == 0 and second == len(edges) - 1:
                continue
            c, d = edges[second]
            assert not proper_crossing(a, b, c, d)
    assert PROFILE.validate_sampled_polygon(vertices) == pytest.approx(shoelace(vertices), abs=1e-12)


@pytest.mark.parametrize(
    "vertices",
    [
        [[0, 0], [2, 2], [0, 2], [2, 0]],
        [[0, 0], [3, 2], [0, 3], [2, 0]],
        [[0, 0], [3, 0], [1, 0], [2, 1], [0, 1]],
        [[0, 0], [2, 0], [1, 1], [1, 0], [0, 1]],
        [[0, 0], [1, 0], [1, 0], [0, 1]],
        [[0, 0], [1, 0], [2, 0]],
        [[0, 0], [1, 0]],
        [[0, 0], [math.nan, 0], [0, 1]],
        [[0, 0], [math.inf, 0], [0, 1]],
        [[0, 0], [True, 0], [0, 1]],
        [[0, 0], [1, "0"], [0, 1]],
    ],
)
def test_polygon_validator_rejects_crossing_touching_backtracking_and_non_geometry(vertices):
    with pytest.raises(ValueError):
        PROFILE.validate_sampled_polygon(vertices)


def test_polygon_validator_accepts_both_orientations_but_not_repeated_closure():
    vertices = [[0, 0], [2, 0], [2, 1], [0, 1]]
    assert PROFILE.validate_sampled_polygon(vertices) == 2
    assert PROFILE.validate_sampled_polygon(list(reversed(vertices))) == 2
    with pytest.raises(ValueError):
        PROFILE.validate_sampled_polygon(vertices + vertices[:1])


@pytest.mark.parametrize("scale", [1, 1e-100])
def test_polygon_crossing_rejection_does_not_multiply_tiny_orientation_values(scale):
    crossing = [[0, 0], [2 * scale, 2 * scale], [0, 2 * scale], [scale, 0]]
    with pytest.raises(ValueError):
        PROFILE.validate_sampled_polygon(crossing)
    valid_rectangle = [[0, 0], [2 * scale, 0], [2 * scale, scale], [0, scale]]
    assert PROFILE.validate_sampled_polygon(valid_rectangle) == 2 * scale**2


@pytest.mark.parametrize(
    "name,value",
    [
        (name, value)
        for name in ("turn_angle_deg", "minimum_radius_um", "width_um")
        for value in (True, False, "0.3", None, [], {}, math.nan, math.inf, -math.inf, 10**1000)
    ]
    + [("samples", value) for value in (True, False, "64", 64.0, None, 0, -2, 7, 9, 257, 258)],
)
def test_invalid_types_and_nonfinite_numbers_are_rejected(name, value):
    with pytest.raises(ValueError):
        PROFILE.build_profile(**{name: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"turn_angle_deg": 90},
        {"turn_angle_deg": -90},
        {"turn_angle_deg": 180},
        {"turn_angle_deg": 1e-20},
        {"minimum_radius_um": 0},
        {"minimum_radius_um": -1},
        {"width_um": 0},
        {"width_um": -0.3},
        {"width_um": 2.4},
        {"minimum_radius_um": 0.15, "width_um": 0.3},  # The inner offset reaches the curvature center.
        {"minimum_radius_um": 0.1, "width_um": 0.3},
        {"minimum_radius_um": 10},  # Four projected bends cannot fit between the leads.
        {"turn_angle_deg": 80, "minimum_radius_um": 0.8},  # Fits x but breaches the physical y frame.
        {"width_um": 1e-300},  # Local offset vertices collapse at finite nonzero y.
    ],
)
def test_curvature_clearance_frame_and_coordinate_resolution_fail_closed(changes):
    with pytest.raises(ValueError):
        PROFILE.build_profile(**changes)


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def test_java_consumes_each_numeric_segment_and_never_builds_physics_or_a_polygon():
    profile, source = PROFILE.render_profile(samples=16)
    assert isinstance(source, bytes)
    assert hashlib.sha256(source).hexdigest() == profile["geometry_fragment_sha256"]
    text = source.decode("utf-8")
    assert text.count('"InterpolationCurve"') == 4 and text.count('"Rectangle"') == 3
    assert '"Union"' in text and '"intbnd"' in text
    assert not any(term in text for term in ('"Polygon"', '"Polyline"', "ModelUtil", ".physics(", ".study(", ".sol("))
    for segment in profile["segments"]:
        escaped = re.escape(segment["tag"])
        prefix = rf'g\.feature\(\s*"{escaped}"\s*\)\.set\('
        if segment["kind"] == "euler":
            table = re.search(prefix + r'\s*"table"\s*,\s*new double\[\]\[\]\s*\{(.*?)\}\s*\)\s*;', text, re.S)
            assert table, segment["tag"]
            pairs = re.findall(r"\{\s*(" + NUMBER + r")\s*,\s*(" + NUMBER + r")\s*\}", table[1])
            assert_vectors_close([[float(x), float(y)] for x, y in pairs], segment["boundary_table_um"], 0)
            assert re.search(prefix + r'\s*"type"\s*,\s*"solid"', text)
            assert re.search(prefix + r'\s*"rtol"\s*,\s*0(?:\.0)?\s*\)', text)
        else:
            for java_key, json_key in (("pos", "pos_um"), ("size", "size_um")):
                vector = re.search(prefix + rf'\s*"{java_key}"\s*,\s*new double\[\]\s*\{{(.*?)\}}\s*\)', text)
                assert vector
                assert [float(value) for value in vector[1].split(",")] == segment[json_key]
    union = re.search(
        r'g\.feature\(\s*"bend_core"\s*\)\.selection\(\s*"input"\s*\)'
        r"\.set\(\s*new String\[\]\s*\{(.*?)\}\s*\)",
        text,
    )
    assert union
    assert re.findall(r'"([^"]+)"', union[1]) == [segment["tag"] for segment in profile["segments"]]
    assert re.search(r'g\.feature\("bend_core"\)\.set\("intbnd",\s*"off"\)', text)
    json.dumps(profile, allow_nan=False)
    again, repeated = PROFILE.render_profile(samples=16)
    assert repeated == source and again == profile


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is unavailable")
def test_maximum_supported_sample_count_compiles_in_one_java_method(tmp_path):
    _, fragment = PROFILE.render_profile(samples=256)
    wrapper = (
        """
class BendCompileSmoke {
  static class Selection { void set(Object value) {} }
  static class Feature {
    void set(String name, Object value) {}
    Selection selection(String name) { return new Selection(); }
  }
  static class G {
    void create(String tag, String type) {}
    Feature feature(String tag) { return new Feature(); }
  }
  static void build(G g) {
"""
        + fragment.decode("utf-8")
        + """
  }
}
"""
    )
    java_file = tmp_path / "BendCompileSmoke.java"
    java_file.write_text(wrapper, encoding="utf-8")
    result = subprocess.run(
        [shutil.which("javac"), "-proc:none", "-encoding", "UTF-8", str(java_file)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "BendCompileSmoke.class").stat().st_size > 0


def test_dry_cli_has_no_output_writes_or_native_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("Native launch attempted"))
    monkeypatch.setattr(os, "system", lambda *args, **kwargs: pytest.fail("Native launch attempted"))
    assert PROFILE.main(["--turn-angle-deg", "0"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["zero_bend_geometry"] is True
    assert payload["will_execute"] is False and payload["physics_accepted"] is False
    assert list(tmp_path.iterdir()) == []


def test_cli_new_output_is_byte_bound_and_existing_directory_cannot_be_overwritten(tmp_path):
    output = tmp_path / "geometry"
    result = subprocess.run(
        [sys.executable, "-B", str(SOURCE), "--samples", "16", "--output", str(output)],
        capture_output=True,
        text=True,
        check=True,
    )
    profile = json.loads(result.stdout)
    assert {path.name for path in output.iterdir()} == {"geometry.json", "geometry_fragment.java"}
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert json.loads(before["geometry.json"]) == profile
    assert hashlib.sha256(before["geometry_fragment.java"]).hexdigest() == profile["geometry_fragment_sha256"]
    rejected = subprocess.run(
        [sys.executable, "-B", str(SOURCE), "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 2
    assert before == {path.name: path.read_bytes() for path in output.iterdir()}


def test_output_file_is_preserved_and_invalid_profile_does_not_create_directory(tmp_path):
    existing = tmp_path / "existing"
    existing.write_bytes(b"keep")
    with pytest.raises(SystemExit) as caught:
        PROFILE.main(["--output", str(existing)])
    assert caught.value.code == 2 and existing.read_bytes() == b"keep"
    invalid = tmp_path / "invalid"
    with pytest.raises(SystemExit) as caught:
        PROFILE.main(["--width-um", "nan", "--output", str(invalid)])
    assert caught.value.code == 2 and not invalid.exists()


def test_exclusive_mkdir_race_preserves_competing_directory(tmp_path, monkeypatch):
    output = tmp_path / "raced"
    original = Path.mkdir

    def competing_creation(path, *args, **kwargs):
        original(path)
        (path / "geometry_fragment.java").write_bytes(b"other owner")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", competing_creation)
    with pytest.raises(SystemExit) as caught:
        PROFILE.main(["--turn-angle-deg", "0", "--output", str(output)])
    assert caught.value.code == 2
    assert (output / "geometry_fragment.java").read_bytes() == b"other owner"
