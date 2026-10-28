"""Offline bundle and geometry-probe consumption tests; no COMSOL calls."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "examples/comsol-device-canary/bend_geometry.py"
SPEC = importlib.util.spec_from_file_location("bend_geometry", SOURCE)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


@pytest.mark.parametrize("angle", [0, 15, -15])
def test_probe_embeds_exact_geometry_fragment_and_independent_identity(angle):
    profile, java = PROBE.render_geometry_probe(turn_angle_deg=angle, samples=8)
    _, fragment = PROBE.profile_module().render_profile(turn_angle_deg=angle, samples=8)
    assert java.count(fragment) == 1
    identity = sha(canonical(profile))
    assert java.count(('marker("IDENTITY ' + identity + '")').encode()) == 1
    assert java.count(('marker("FRAGMENT_SHA256 ' + sha(fragment) + '")').encode()) == 1
    assert b'g.feature("bend_core").set("selresult","on")' in java
    assert b'new String[]{"g_bend_core_dom"}' in java
    assert b'.selection("coreBoundary").geom("g",2,1,new String[]{"exterior"})' in java
    assert b"int[] edges=intersection(" in java
    assert b'.selection("p"+port).entities(1)' in java
    assert b'measureFinal().selection().geom("g",dimension)' in java
    assert b".getVolume()" in java and b".getBoundingBox()" in java
    assert b"g.edgeParamRange(edge)" in java and b"g.edgeX(edge,parameters)" in java
    assert b"parameters[0]=range[0]; parameters[64]=range[1]" in java
    assert b"coordinates.length!=65" in java
    assert java.count(b'marker("NATIVE_COMPLETED")') == 1
    assert java.index(b'm.save("BendGeometryProbe.mph")') < java.index(b'marker("CHECKPOINT_SAVED")')
    assert java.index(b'marker("CHECKPOINT_SAVED")') < java.index(b'marker("NATIVE_COMPLETED")')
    assert b'marker("FAILED "' in java
    for forbidden in (b".physics().create(", b".mesh().create(", b".study().create(", b".sol().create(", b".runAll("):
        assert forbidden not in java
    assert b'.lengthUnit("um")' in java
    assert profile["physics_accepted"] is False and profile["will_execute"] is False


def test_new_bundle_exact_members_hashes_and_read_only_verification(tmp_path):
    folder = tmp_path / "bundle"
    manifest = PROBE.prepare_bundle(folder, turn_angle_deg=0)
    before = {member.name: member.read_bytes() for member in folder.iterdir()}
    assert set(before) == {"geometry.json", "geometry_fragment.java", "BendGeometryProbe.java", "manifest.json"}
    assert manifest["files"] == {name: sha(data) for name, data in before.items() if name != "manifest.json"}
    profile = json.loads(before["geometry.json"])
    assert manifest["geometry_identity"] == sha(canonical(profile))
    assert manifest["source_sha256"] == sha(before["BendGeometryProbe.java"])
    assert manifest["fragment_sha256"] == sha(before["geometry_fragment.java"])
    assert set(manifest["dependencies"]) == {
        "bend_geometry.py",
        "bend_profile.py",
        "photonic_workflow.recipes.geometry",
    }
    assert manifest["native_execution"] == "not_performed"
    assert manifest["will_execute"] is False and manifest["physics_accepted"] is False
    assert PROBE.verify_bundle(folder) == manifest
    assert before == {member.name: member.read_bytes() for member in folder.iterdir()}


@pytest.mark.parametrize("member", sorted(PROBE.BUNDLE_FILES))
def test_whitespace_changes_are_not_rebased_or_accepted(tmp_path, member):
    folder = tmp_path / "bundle"
    PROBE.prepare_bundle(folder, turn_angle_deg=0)
    with (folder / member).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError):
        PROBE.verify_bundle(folder)


def test_forged_source_and_rehashed_manifest_cannot_replace_trusted_rendering(tmp_path):
    folder = tmp_path / "bundle"
    manifest = PROBE.prepare_bundle(folder, turn_angle_deg=0)
    changed = (folder / "BendGeometryProbe.java").read_bytes().replace(b'"2.6"', b'"1.45"')
    (folder / "BendGeometryProbe.java").write_bytes(changed)
    manifest["source_sha256"] = manifest["files"]["BendGeometryProbe.java"] = sha(changed)
    (folder / "manifest.json").write_bytes(PROBE.serialized(manifest))
    with pytest.raises(ValueError, match=r"manifest|producer"):
        PROBE.verify_bundle(folder)


@pytest.mark.parametrize("mutation", ["extra", "missing", "directory"])
def test_bundle_census_and_regular_files_are_required(tmp_path, mutation):
    folder = tmp_path / "bundle"
    PROBE.prepare_bundle(folder, turn_angle_deg=0)
    if mutation == "extra":
        (folder / "producer.py").write_text("raise RuntimeError('never import bundle code')", encoding="utf-8")
    else:
        (folder / "geometry_fragment.java").unlink()
        if mutation == "directory":
            (folder / "geometry_fragment.java").mkdir()
    with pytest.raises(ValueError):
        PROBE.verify_bundle(folder)


@pytest.mark.parametrize(
    "change",
    [
        {"will_execute": True},
        {"physics_accepted": True},
        {"dependencies": {}},
        {"source_sha256": "0" * 64},
        {"geometry_identity": "0" * 64},
        {"native_execution": "completed"},
    ],
)
def test_manifest_cannot_promote_claims_or_drop_producer_identity(tmp_path, change):
    folder = tmp_path / "bundle"
    manifest = PROBE.prepare_bundle(folder, turn_angle_deg=0)
    manifest.update(change)
    (folder / "manifest.json").write_bytes(PROBE.serialized(manifest))
    with pytest.raises(ValueError):
        PROBE.verify_bundle(folder)


def test_unknown_parameters_and_noncanonical_manifest_are_rejected(tmp_path):
    folder = tmp_path / "bundle"
    manifest = PROBE.prepare_bundle(folder, turn_angle_deg=0)
    manifest["parameters"]["python_source"] = "producer.py"
    (folder / "manifest.json").write_bytes(PROBE.serialized(manifest))
    with pytest.raises(ValueError, match="parameters"):
        PROBE.verify_bundle(folder)


def test_existing_outputs_and_invalid_geometry_do_not_write(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    sentinel = folder / "keep"
    sentinel.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="already exist"):
        PROBE.prepare_bundle(folder)
    assert sentinel.read_bytes() == b"preserve"
    invalid = tmp_path / "invalid"
    with pytest.raises(ValueError):
        PROBE.prepare_bundle(invalid, width_um=float("nan"))
    assert not invalid.exists()


def test_prepare_and_verify_never_launch_processes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("Process launch attempted"))
    monkeypatch.setattr(os, "system", lambda *args, **kwargs: pytest.fail("Process launch attempted"))
    folder = tmp_path / "bundle"
    assert PROBE.main(["prepare", "--output", str(folder), "--turn-angle-deg", "0"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert PROBE.main(["verify", "--bundle", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out) == first


STUB = """package com.comsol.model;
public class Stub {
  public Stub component(){return this;} public Stub component(String s){return this;}
  public Stub geom(){return this;} public GeomSequence geom(String s){return new GeomSequence();}
  public Stub feature(String s){return this;} public Stub selection(){return this;}
  public Stub selection(String s){return this;} public Stub material(){return this;}
  public Stub material(String s){return this;} public Stub propertyGroup(){return this;}
  public Stub propertyGroup(String s){return this;} public Stub physics(){return this;}
  public Stub mesh(){return this;} public Stub study(){return this;} public Stub sol(){return this;}
  public Stub create(String s,String t){return this;} public Stub create(String s,boolean b){return this;}
  public Stub create(String s,int n){return this;} public Stub set(String s,Object v){return this;}
  public Stub set(int[] v){return this;} public Stub set(String[] v){return this;}
  public Stub geom(String s,int n){return this;}
  public Stub geom(String s,int n,int m,String[] t){return this;} public Stub all(){return this;}
  public Stub named(String s){return this;} public Stub measureFinal(){return this;}
  public int[] entities(int n){return new int[]{1};} public double getVolume(){return 1;}
  public double[] getBoundingBox(){return new double[]{0,14,-.15,.15};}
  public double[] getDoubleArray(String s){return new double[]{0,0};}
  public double[][] getDoubleMatrix(String s){return new double[][]{{0,0}};}
  public String[] getStringArray(String s){return new String[]{"0"};}
  public String[] tags(){return new String[]{};} public void run(){} public void modelPath(String s){}
  public void label(String s){} public void save(String s){}
}
"""


@pytest.mark.skipif(not shutil.which("javac") or not shutil.which("java"), reason="JDK is unavailable")
@pytest.mark.parametrize(
    "unit_literal,codepoints,canonical_unit",
    [
        ('"um"', [117, 109], "um"),
        ('"\\u00b5m"', [181, 109], "um"),
        ('"\\u03bcm"', [956, 109], "um"),
        ('"?m"', [63, 109], "unsupported"),
        ('"mm"', [109, 109], "unsupported"),
    ],
)
def test_java_protocol_compiles_and_emits_parseable_json_with_a_non_solver_stub(
    tmp_path, unit_literal, codepoints, canonical_unit
):
    package = tmp_path / "com/comsol/model"
    utility = package / "util"
    utility.mkdir(parents=True)
    (package / "Stub.java").write_text(STUB, encoding="utf-8")
    (package / "Model.java").write_text(
        "package com.comsol.model; public class Model extends Stub {}", encoding="utf-8"
    )
    (package / "GeomSequence.java").write_text(
        "package com.comsol.model; public class GeomSequence extends Stub {"
        "public void lengthUnit(String s){} "
        f"public String lengthUnit(){{return {unit_literal};}}"
        "public int[] getNEntities(){return new int[]{4,4,1};}"
        "public double[] edgeParamRange(int e){return new double[]{0,1};}"
        "public double[][] edgeX(int e,double[] p){return new double[p.length][2];}}",
        encoding="utf-8",
    )
    (utility / "ModelUtil.java").write_text(
        "package com.comsol.model.util; import com.comsol.model.Model;"
        "public class ModelUtil {public static Model create(String s){return new Model();}}",
        encoding="utf-8",
    )
    _, source = PROBE.render_geometry_probe(samples=8)
    (tmp_path / "BendGeometryProbe.java").write_bytes(source)
    compilation = subprocess.run(
        [shutil.which("javac"), "-encoding", "UTF-8", str(tmp_path / "BendGeometryProbe.java")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    assert compilation.returncode == 0, compilation.stderr
    execution = subprocess.run(
        [shutil.which("java"), "-cp", str(tmp_path), "BendGeometryProbe"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
    )
    assert execution.returncode == 0, execution.stderr
    rows = [
        json.loads(line.removeprefix("BEND_GEOMETRY RECORD "))
        for line in execution.stdout.splitlines()
        if line.startswith("BEND_GEOMETRY RECORD ")
    ]
    assert len([row for row in rows if row["kind"] == "table"]) == 4
    assert len([row for row in rows if row["kind"] == "rectangle"]) == 3
    assert len([row for row in rows if row["kind"] == "domain"]) == 3
    assert len([row for row in rows if row["kind"] == "material"]) == 2
    assert len([row for row in rows if row["kind"] == "boundary"]) == 7
    samples = [row for row in rows if row["kind"] == "edge_samples"]
    assert len(samples) == 1 and len(samples[0]["coordinates"]) == 65
    assert f"BEND_GEOMETRY GEOMETRY_UNIT_CODEPOINTS {codepoints}" in execution.stdout
    assert f"BEND_GEOMETRY GEOMETRY_UNIT {canonical_unit}\n" in execution.stdout
    assert execution.stdout.count("BEND_GEOMETRY NATIVE_COMPLETED\n") == 1
    assert not list(tmp_path.glob("*.mph"))  # Stub save is intentionally inert; this is not native evidence.
