"""Independent geometry controls for the offline configure-only profile tool."""

import hashlib
import importlib.util
import io
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "examples/comsol-device-canary/taper_profile.py"
SPEC = importlib.util.spec_from_file_location("taper_profile", SOURCE)
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


def shoelace(vertices):
    pairs = list(zip(vertices, vertices[1:] + vertices[:1], strict=True))
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairs)) / 2


def section_width(vertices, x):
    """Intersect the polygon edges with a vertical line, independent of its formula."""
    values = []
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        if ax == bx:
            if x == ax:
                values.extend((ay, by))
        elif min(ax, bx) <= x <= max(ax, bx):
            values.append(ay + (by - ay) * (x - ax) / (bx - ax))
    assert values
    return max(values) - min(values)


@pytest.mark.parametrize("width,length", [(0.34, 4), (0.3, 4), (0.3, 0), (0.5, 2), (2.399, 13.99)])
def test_polygon_independent_area_sections_symmetry_ports_and_bounds(width, length):
    p = PROFILE.build_profile(width, length)
    vertices = p["vertices_um"]
    assert len(vertices) == len({tuple(v) for v in vertices})
    assert shoelace(vertices) == pytest.approx(4.2 + length * (width - 0.3) / 2, abs=1e-13)
    assert p["core_area_um2"] == pytest.approx(shoelace(vertices), abs=1e-13)
    assert p["background_area_um2"] + shoelace(vertices) == pytest.approx(70)
    assert [min(v[0] for v in vertices), max(v[0] for v in vertices),
            min(v[1] for v in vertices), max(v[1] for v in vertices)] == p["core_bbox_um"]
    for x in (0, 0.25, 3, 6, 7, 8, 11, 13.75, 14):
        expected = 0.3 if length == 0 else 0.3 + (width - 0.3) * max(0, 1 - 2 * abs(x - 7) / length)
        assert section_width(vertices, x) == pytest.approx(expected, abs=1e-13)
        assert section_width(vertices, 14 - x) == pytest.approx(section_width(vertices, x))
    assert section_width(vertices, 0) == section_width(vertices, 14) == 0.3
    points = {tuple(v) for v in vertices}
    assert {(x, -y) for x, y in points} == points
    assert p["equal_width_geometry"] == (width == 0.3)
    assert p["will_execute"] is False and p["physics_accepted"] is False
    assert p["native_execution"] == "not_performed"


def test_zero_length_rectangle_and_positive_equal_width_control():
    zero = PROFILE.build_profile(0.3, 0)
    positive = PROFILE.build_profile(0.3, 4)
    assert zero["vertices_um"] == [[0, -0.15], [14, -0.15], [14, 0.15], [0, 0.15]]
    assert len(positive["vertices_um"]) == 10
    assert shoelace(zero["vertices_um"]) == pytest.approx(shoelace(positive["vertices_um"]))
    assert "not mesh or scattering equivalence" in " ".join(zero["limitations"])


@pytest.mark.parametrize("name,value", [
    ("center_width_um", v) for v in (True, False, "0.34", None, [], {}, math.nan, math.inf,
                                    -math.inf, 0, 0.299999, 2.4, 5, 10**1000)
] + [
    ("taper_length_um", v) for v in (True, False, "4", None, [], math.nan, math.inf,
                                    -math.inf, -1, 14, 20, 10**1000)
])
def test_reject_invalid_numeric_inputs(name, value):
    with pytest.raises(ValueError):
        PROFILE.build_profile(**{name: value})


@pytest.mark.parametrize("width", [0.30000000000000004, 0.34, 2.3])
def test_zero_length_changed_width_is_rejected(width):
    with pytest.raises(ValueError, match="Zero taper length"):
        PROFILE.build_profile(width, 0)


@pytest.mark.parametrize("length", [1e-300, 1e-17, math.ulp(7)])
def test_positive_length_below_coordinate_resolution_is_rejected(length):
    with pytest.raises(ValueError, match="resolution"):
        PROFILE.build_profile(0.34, length)


@pytest.mark.parametrize("vertices", [
    [[0, 0], [1, 0], [1, 0], [0, 1]],
    [[0, 0], [1, 0], [0, 0]],
    [[0, 0], [math.nan, 0], [0, 1]],
    [[0, 0], [True, 0], [0, 1]],
    [[0, 0], [1, 0], [2, 0]],
    [[0, 0], [1, 1], [0, 1], [1, 0]],
    [[0, 0], [0, 1], [1, 0]],
    [[0, 0], [1]],
])
def test_invalid_polygon_counterexamples(vertices):
    with pytest.raises(ValueError):
        PROFILE.validate_polygon(vertices)


@pytest.mark.parametrize("anchor", [PROFILE.AREA_ANCHOR, PROFILE.BOX_ANCHOR, PROFILE.BOX_COORDINATES_ANCHOR,
                                   PROFILE.HEIGHT_ANCHOR,
                                   PROFILE.TABLE_ANCHOR, "__STAGE__", "__SHAPE__"])
@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_template_anchor_drift_refused_even_for_default_profile(anchor, mutation):
    original = PROFILE.TEMPLATE.read_bytes()
    altered = (original.replace(anchor.encode(), b"/* drift */", 1)
               if mutation == "missing" else original + anchor.encode())
    with pytest.raises(ValueError, match="anchor"):
        PROFILE.render_profile(template_bytes=altered)


def test_default_exact_legacy_configure_bytes_and_hashes():
    original = PROFILE.TEMPLATE.read_bytes()
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="utf-8")
    stream.write(original.decode().replace("__STAGE__", "configure").replace("__SHAPE__", "taper"))
    stream.flush()
    profile, rendered = PROFILE.render_profile()
    assert rendered == buffer.getvalue()
    assert profile["template_sha256"] == hashlib.sha256(original).hexdigest()
    assert profile["configure_source_sha256"] == hashlib.sha256(rendered).hexdigest()
    # Windows baseline captured before implementation by the phase-eight campaign.
    if os.name == "nt":
        assert profile["configure_source_sha256"] == "2942831001e81e7bd1ecc6a3333d7974e32575936268e2b9fdf71e5ced4ee18d"


@pytest.mark.parametrize("width,length", [(0.3, 4), (0.3, 0), (0.6, 6)])
def test_custom_source_vertices_area_and_bbox_match_profile(width, length):
    p, source = PROFILE.render_profile(width, length)
    text = source.decode()
    match = re.search(r'g.feature\("core"\).set\("table",new double\[\]\[\]\{(.*?)\}\);', text)
    vertices = [[float(x) for x in pair.split(",")] for pair in re.findall(r"\{([^{}]+)\}", match[1])]
    assert vertices == p["vertices_um"]
    assert shoelace(vertices) == pytest.approx(p["core_area_um2"])
    assert f'?4.2:{p["core_area_um2"]!r}' in text
    assert f'?65.8:{p["background_area_um2"]!r}' in text
    assert f'?.15:{width / 2!r}):2.5;' in text
    assert 'STAGE="configure", SHAPE="taper"' in text
    assert "__STAGE__" not in text and "__SHAPE__" not in text


def test_dry_plan_has_no_writes_or_native_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("Native launch attempted"))
    monkeypatch.setattr(os, "system", lambda *a, **kw: pytest.fail("Native launch attempted"))
    assert PROFILE.main([]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["will_execute"] is False
    assert plan["physics_accepted"] is False
    assert list(tmp_path.iterdir()) == []


def test_cli_new_output_exact_files_hash_and_existing_directory_rejection(tmp_path):
    output = tmp_path / "profile"
    result = subprocess.run([sys.executable, "-B", str(SOURCE), "--center-width-um", "0.3",
                             "--taper-length-um", "0", "--output", str(output)],
                            capture_output=True, text=True, check=True)
    p = json.loads(result.stdout)
    assert set(x.name for x in output.iterdir()) == {"profile.json", "DeviceCanary.java"}
    before = {x.name: x.read_bytes() for x in output.iterdir()}
    assert json.loads(before["profile.json"]) == p
    assert hashlib.sha256(before["DeviceCanary.java"]).hexdigest() == p["configure_source_sha256"]
    rejected = subprocess.run([sys.executable, "-B", str(SOURCE), "--output", str(output)],
                              capture_output=True, text=True)
    assert rejected.returncode == 2
    assert {x.name: x.read_bytes() for x in output.iterdir()} == before


def test_existing_file_and_invalid_profile_produce_no_new_output(tmp_path):
    target = tmp_path / "existing"
    target.write_bytes(b"preserve")
    for argv in (["--output", str(target)], ["--taper-length-um", "0", "--output", str(tmp_path / "invalid")]):
        with pytest.raises(SystemExit) as error:
            PROFILE.main(argv)
        assert error.value.code == 2
    assert target.read_bytes() == b"preserve"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["existing"]


def test_exclusive_mkdir_race_cannot_overwrite_preexisting_contents(tmp_path, monkeypatch):
    output = tmp_path / "raced"
    original_mkdir = Path.mkdir

    def race(path, *args, **kwargs):
        original_mkdir(path)
        (path / "DeviceCanary.java").write_bytes(b"concurrent owner")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", race)
    with pytest.raises(SystemExit) as error:
        PROFILE.main(["--output", str(output)])
    assert error.value.code == 2
    assert (output / "DeviceCanary.java").read_bytes() == b"concurrent owner"
    assert not (output / "profile.json").exists()
