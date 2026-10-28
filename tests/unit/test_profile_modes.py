"""Offline substitution and field ambiguity tests for profile-bound modes."""

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2] / "examples" / "comsol-device-canary"
spec = importlib.util.spec_from_file_location("profile_modes_under_test", HERE / "profile_modes.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_prepare_is_offline_and_exact(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("native execution attempted"))
    bundle = tmp_path / "bundle"
    manifest = helper.prepare_bundle(bundle, 0.30, 4)
    assert helper.verify_bundle(bundle) == manifest
    source = (bundle / "DeviceCanary.java").read_text()
    assert 'STAGE="modes"' in source
    assert "Selected store must precede driven start" in source
    assert "PROFILE_IDENTITY " + manifest["profile_identity"] in source
    assert manifest["physics_accepted"] is False
    with pytest.raises(ValueError, match="new"):
        helper.prepare_bundle(bundle, 0.30, 4)


@pytest.mark.parametrize("name", ["profile.json", "DeviceCanary.java", "manifest.json"])
def test_altered_bundle_rejected(tmp_path, name):
    bundle = tmp_path / "bundle"
    helper.prepare_bundle(bundle, 0.30, 0)
    with (bundle / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError):
        helper.verify_bundle(bundle)


def test_cross_profile_source_and_extra_path_rejected(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    helper.prepare_bundle(a, 0.30, 4)
    helper.prepare_bundle(b, 0.30, 0)
    (a / "DeviceCanary.java").write_bytes((b / "DeviceCanary.java").read_bytes())
    with pytest.raises(ValueError):
        helper.verify_bundle(a)
    (b / "unexpected").write_text("x")
    with pytest.raises(ValueError):
        helper.verify_bundle(b)


def test_symlink_output_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError):
        helper.prepare_bundle(link / "bundle", 0.30, 4)


def fields(conflict=0):
    rows = []
    for port in (1, 2):
        for y in (-1.2, 0, 1.2):
            rows.append(f"CANARY SELECTED_FIELD {port},{y},1,0,{port},0")
        rows.append(f"CANARY SELECTED_FIELD {port},0,{1 + conflict},0,{port},0")
    return "\n".join(rows)


def test_duplicate_conflict_rejected_and_roundoff_recorded():
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        helper.duplicate_spreads(fields(0.01))
    report = helper.duplicate_spreads(fields(1e-8))
    assert report["1"]["E"]["duplicate_rows"] == 1
    assert report["1"]["E"]["max_pair_spread"] > 0


def test_missing_receipt_identity_rejected(tmp_path):
    bundle = tmp_path / "bundle"
    helper.prepare_bundle(bundle, 0.30, 4)
    run = tmp_path / "run"
    run.mkdir()
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"accepted": True}))
    with pytest.raises(ValueError, match="identity/status"):
        helper.validate_evidence(bundle, run, receipt)


def synthetic_evidence(tmp_path):
    # Deliberately synthetic: verifies parser contracts, never native physics.
    import math

    bundle = tmp_path / "bundle"
    manifest = helper.prepare_bundle(bundle)
    profile = json.loads((bundle / "profile.json").read_bytes())
    run = tmp_path / "run"
    run.mkdir()
    (run / "DeviceCanary.java").write_bytes((bundle / "DeviceCanary.java").read_bytes())
    (run / "selected_modes.mph").write_bytes(b"SYNTHETIC_NOT_NATIVE" * 100)
    lines = [
        "CANARY STAGE modes SHAPE taper",
        "CANARY PROFILE_IDENTITY " + manifest["profile_identity"],
        "CANARY SELECTED_RUN_TO_COMPLETED",
        "CANARY MODES_COMPLETED",
        "CANARY P10_TABLE " + str(profile["vertices_um"]),
        "CANARY P10_DOMAINS [1, 2]",
        "CANARY MATERIAL coremat selection=g_core_dom entities=[1] area="
        + str(profile["core_area_um2"])
        + " bbox="
        + str(profile["core_bbox_um"])
        + " n=[2.6] ki=[0]",
        "CANARY MATERIAL clad selection=bg entities=[2] area="
        + str(profile["background_area_um2"])
        + " bbox=[0,14,-2.5,2.5] n=[1.45] ki=[0]",
        "CANARY EXTERIOR_PARTITION_PASS [1,2,3]",
        "CANARY P10_READBACK_COMPLETED",
        "CANARY P10_BOUNDARY_GEOMETRY open length=33.2 bbox=[0,14,-2.5,2.5]",
    ]
    for t, i in [("p1", 1), ("p2", 2), ("open", 3)]:
        lines.append(f"CANARY BOUNDARY {t} [{i}]")
    for t, i in [("port1", 1), ("port2", 2), ("sctr", 3)]:
        lines.append(f"CANARY P10_PHYSICS {t} [{i}]")
    neff = 2.1837000141287444
    for port, x in [(1, 0), (2, 14)]:
        lines.extend(
            [
                f"CANARY P10_PORT_SETTINGS {port} type=Numeric name={port} phase=0 Pin=1[W/m]",
                f"CANARY P10_BOUNDARY_GEOMETRY p{port} length=2.4 bbox=[{x},{x},-1.2,1.2]",
                f"CANARY BMA_BINDING {port}={port} shift=2.2 neigs=1",
                f"CANARY P10_STORE port={port} tag=store{port} solution=sol{port}",
                f"CANARY SELECTED_DATASET port={port} dataset=dset{port} solution=sol{port} solnum=1",
                f"CANARY SELECTED_SCALAR {port},{neff},0,1550,1",
            ]
        )
        for i in range(6):
            lines.append(f"CANARY CENSUS {port},{i},{neff if i == 0 else 1.3},0")
        for i in range(21):
            y = -1.2 + i * 0.12
            e = math.exp(-((y / 0.2) ** 2))
            h = (1 if port == 1 else -1) * neff / 376.730313668 * e
            lines.append(f"CANARY SELECTED_FIELD {port},{y},{e},0,{h},0")
    base = "\n".join(lines) + "\n"
    (run / "console.txt").write_text(base, encoding="utf-8")
    receipt = run / "receipt.json"
    rec = {
        "schema_version": "profile-modes-native-v1",
        "status": "native_completed",
        "stage": "modes",
        "profile_identity": manifest["profile_identity"],
        "bundle_manifest_sha256": helper.digest((bundle / "manifest.json").read_bytes()),
        "source_sha256": manifest["source_sha256"],
        "console_sha256": helper.digest((run / "console.txt").read_bytes()),
        "selected_checkpoint_sha256": helper.digest((run / "selected_modes.mph").read_bytes()),
        "compile_exit_code": 0,
        "batch_exit_code": 0,
    }
    rec["artifacts"] = [
        {"path": n, "sha256": helper.digest((run / n).read_bytes())}
        for n in ("DeviceCanary.java", "console.txt", "selected_modes.mph")
    ]
    receipt.write_text(json.dumps(rec))
    return bundle, run, receipt, rec


def test_synthetic_evidence_control(tmp_path):
    bundle, run, receipt, _ = synthetic_evidence(tmp_path)
    result = helper.validate_evidence(bundle, run, receipt)
    assert result["mode_readiness"] == "accepted_for_profile_scoped_reuse"
    assert result["physics_accepted"] is False


@pytest.mark.parametrize(
    "attack",
    [
        "checkpoint",
        "console",
        "source",
        "receipt_source",
        "geometry",
        "mode_id",
        "duplicate",
        "missing_membership",
        "unsafe_path",
        "accepted_flag",
    ],
)
def test_evidence_substitutions_rejected(tmp_path, attack):
    bundle, run, receipt, rec = synthetic_evidence(tmp_path)
    if attack in ("checkpoint", "console", "source"):
        name = {"checkpoint": "selected_modes.mph", "console": "console.txt", "source": "DeviceCanary.java"}[attack]
        with (run / name).open("ab") as stream:
            stream.write(b"SUBSTITUTION")
    elif attack == "receipt_source":
        rec["source_sha256"] = "0" * 64
    elif attack == "missing_membership":
        rec["artifacts"] = rec["artifacts"][:-1]
    elif attack == "unsafe_path":
        rec["artifacts"].append({"path": "../foreign", "sha256": "0" * 64})
    else:
        console = run / "console.txt"
        text = console.read_text()
        if attack == "geometry":
            text = text.replace("CANARY P10_TABLE [[0.0, -0.15]", "CANARY P10_TABLE [[1.0, -0.15]")
        elif attack == "mode_id":
            text = text.replace("dataset=dset1 solution=sol1", "dataset=dset1 solution=sol2")
        elif attack == "duplicate":
            text += "CANARY SELECTED_FIELD 1,0.0,20,0,0,0\n"
        elif attack == "accepted_flag":
            rec["accepted"] = True
            text = text.replace("2.1837000141287444", "1.8")
        console.write_text(text, encoding="utf-8")
        rec["console_sha256"] = helper.digest(console.read_bytes())
        next(x for x in rec["artifacts"] if x["path"] == "console.txt")["sha256"] = rec["console_sha256"]
    receipt.write_text(json.dumps(rec))
    with pytest.raises(ValueError):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize("status", [None, "failed", "running", True])
def test_receipt_requires_native_completed(tmp_path, status):
    bundle, run, receipt, rec = synthetic_evidence(tmp_path)
    if status is None:
        rec.pop("status")
    else:
        rec["status"] = status
    receipt.write_text(json.dumps(rec))
    with pytest.raises(ValueError, match="identity/status"):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize(
    "marker",
    [
        "CANARY DRIVEN_TEST",
        "CANARY SOURCE 1,1,1550",
        "CANARY S 1,1,1,1,0",
        "CANARY POWER 1,0,0,0,0,0,0",
        "CANARY RESUME_FROM_FROZEN sol1/st3",
        "CANARY ACTUAL_DATASET dset1",
        "CANARY NATIVE_COMPLETED",
    ],
)
def test_forbidden_driven_markers(tmp_path, marker):
    bundle, run, receipt, rec = synthetic_evidence(tmp_path)
    console = run / "console.txt"
    with console.open("a", encoding="utf-8") as stream:
        stream.write(marker + "\n")
    rec["console_sha256"] = helper.digest(console.read_bytes())
    next(x for x in rec["artifacts"] if x["path"] == "console.txt")["sha256"] = rec["console_sha256"]
    receipt.write_text(json.dumps(rec))
    with pytest.raises(ValueError, match="Forbidden driven"):
        helper.validate_evidence(bundle, run, receipt)
