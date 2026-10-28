"""Self-contained synthetic identity tests; these fixtures are never native evidence."""

import importlib.util
import json
import math
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[2] / "examples" / "comsol-device-canary"
SPEC = importlib.util.spec_from_file_location("profile_driven_under_test", HERE / "profile_driven.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
DATASET_AXIS = "pnames=[freq, PortName] pvalues=[1.9341448903225803E14, 1.0, 1.9341448903225803E14, 2.0]"


def write_json(path, value):
    path.write_bytes(helper.canonical(value))


def membership(run, names):
    return [{"path": name, "sha256": helper.digest((run / name).read_bytes())} for name in names]


def refresh_artifact(run, receipt, rec, name, hash_key):
    rec[hash_key] = helper.digest((run / name).read_bytes())
    next(item for item in rec["artifacts"] if item["path"] == name)["sha256"] = rec[hash_key]
    write_json(receipt, rec)


def geometry_lines(profile):
    lines = [
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
        "CANARY P10_BOUNDARY_GEOMETRY open length=33.2 bbox=[0,14,-2.5,2.5]",
    ]
    for tag, entity in [("p1", 1), ("p2", 2), ("open", 3)]:
        lines.append(f"CANARY BOUNDARY {tag} [{entity}]")
    for tag, entity in [("port1", 1), ("port2", 2), ("sctr", 3)]:
        lines.append(f"CANARY P10_PHYSICS {tag} [{entity}]")
    for port, x in [(1, 0), (2, 14)]:
        lines.extend(
            [
                f"CANARY P10_PORT_SETTINGS {port} type=Numeric name={port} phase=0 Pin=1[W/m]",
                f"CANARY P10_BOUNDARY_GEOMETRY p{port} length=2.4 bbox=[{x},{x},-1.2,1.2]",
            ]
        )
    return [*lines, "CANARY P10_READBACK_COMPLETED"]


def synthetic_modes(root, *, historical=False):
    """Generate complete mode-parser input without another test module or saved run."""
    mode = helper.modes()
    bundle, run = root / "modes_bundle", root / "modes_run"
    manifest = mode.prepare_bundle(bundle, 0.30, 4.0)
    run.mkdir()
    (run / "DeviceCanary.java").write_bytes((bundle / "DeviceCanary.java").read_bytes())
    (run / "selected_modes.mph").write_bytes(b"SYNTHETIC_NOT_NATIVE" * 100)
    profile = json.loads((bundle / "profile.json").read_bytes())
    lines = [
        "CANARY STAGE modes SHAPE taper",
        "CANARY PROFILE_IDENTITY " + manifest["profile_identity"],
        "CANARY SELECTED_RUN_TO_COMPLETED",
        "CANARY MODES_COMPLETED",
        "CANARY RUN_TO_SELECTED solMain/store2 future_driven_start=st3",
        *geometry_lines(profile),
    ]
    neff = 2.1837000141287444
    for port in (1, 2):
        lines.extend(
            [
                f"CANARY BMA_BINDING {port}={port} shift=2.2 neigs=1",
                f"CANARY P10_STORE port={port} tag=store{port} solution=sol{port}",
                f"CANARY SELECTED_DATASET port={port} dataset=dset{port} solution=sol{port} solnum=1",
                f"CANARY SELECTED_SCALAR {port},{neff},0,1550,1",
            ]
        )
        lines.extend(f"CANARY CENSUS {port},{i},{neff if i == 0 else 1.3},0" for i in range(6))
        for i in range(21):
            y = -1.2 + i * 0.12
            electric = math.exp(-((y / 0.2) ** 2))
            magnetic = (1 if port == 1 else -1) * neff / 376.730313668 * electric
            lines.append(f"CANARY SELECTED_FIELD {port},{y},{electric},0,{magnetic},0")
    (run / "console.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rec = {
        "schema_version": "profile-modes-native-v1",
        "status": "native_completed",
        "stage": "modes",
        "profile_identity": manifest["profile_identity"],
        "source_sha256": manifest["source_sha256"],
        "console_sha256": helper.digest((run / "console.txt").read_bytes()),
        "selected_checkpoint_sha256": helper.digest((run / "selected_modes.mph").read_bytes()),
        "compile_exit_code": 0,
        "batch_exit_code": 0,
    }
    options = {}
    names = ["DeviceCanary.java", "console.txt", "selected_modes.mph"]
    if historical:
        snapshot = root / "producer_snapshot"
        snapshot.mkdir()
        # Authenticated caller Python is deliberately poisonous if imported/executed.
        for name in mode.FILES:
            (snapshot / name).write_bytes(b"raise AssertionError('producer code was executed')\n")
        producer = {name: helper.digest((snapshot / name).read_bytes()) for name in mode.FILES}
        producer_manifest = run / "sourcecopy_manifest.json"
        write_json(producer_manifest, producer)
        manifest["dependencies"] = producer
        write_json(bundle / "manifest.json", manifest)
        rec["helper_sourcecopy_manifest_sha256"] = helper.digest(producer_manifest.read_bytes())
        names.append("sourcecopy_manifest.json")
        options = {"producer_snapshot": snapshot, "producer_manifest": producer_manifest}
    rec["bundle_manifest_sha256"] = helper.digest((bundle / "manifest.json").read_bytes())
    rec["artifacts"] = membership(run, names)
    receipt = run / "receipt.json"
    write_json(receipt, rec)
    return bundle, run, receipt, rec, options


def synthetic_driven(root, *, historical=False):
    mode_bundle, mode_run, mode_receipt, _mode_rec, options = synthetic_modes(root, historical=historical)
    bundle = root / "driven_bundle"
    manifest = helper.prepare_bundle(bundle, mode_bundle, mode_run, mode_receipt, **options)
    profile = json.loads((bundle / "profile.json").read_bytes())
    run = root / "driven_run"
    run.mkdir()
    for name in ("DeviceCanary.java", "input_modes.mph"):
        (run / name).write_bytes((bundle / name).read_bytes())
    (run / "driven_checkpoint.mph").write_bytes(b"SYNTHETIC_DRIVEN_NOT_NATIVE" * 100)
    lines = [
        "CANARY STAGE solve SHAPE taper",
        *geometry_lines(profile),
        "CANARY P11_STORE port=1 tag=store1 solution=sol1 dataset=dset1",
        "CANARY P11_STORE port=2 tag=store2 solution=sol2 dataset=dset2",
        "CANARY P11_PROFILE_VALIDATED",
        "CANARY PROFILE_IDENTITY " + manifest["profile_identity"],
        "CANARY MODE_ORIGIN_IDENTITY " + manifest["mode_origin_identity"],
        "CANARY P11_INPUT_CHECKPOINT " + manifest["input_checkpoint_sha256"],
        "CANARY RESUME_FROM_FROZEN solMain/st3",
        "CANARY DRIVEN_CHECKPOINT_SAVED",
        "CANARY ACTUAL_DATASET dset3 solution=solMain " + DATASET_AXIS,
        "CANARY SOURCE 1,1,1550",
        "CANARY S 1,1,1,0.1,0",
        "CANARY S 1,2,1,0.9,0.1",
        "CANARY POWER 1,0.1,0,-0.99,0.82,2.1837,2.1837",
        "CANARY SOURCE 2,2,1550",
        "CANARY S 2,1,2,0.9,0.1",
        "CANARY S 2,2,2,0.1,0",
        "CANARY POWER 2,0.1,0,0.82,-0.99,2.1837,2.1837",
        "CANARY P11_STORE_AFTER port=1 tag=store1 solution=sol1 dataset=dset1",
        "CANARY P11_STORE_AFTER port=2 tag=store2 solution=sol2 dataset=dset2",
        "CANARY NATIVE_COMPLETED",
    ]
    (run / "console.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rec = {
        "schema_version": "profile-driven-native-v1",
        "status": "native_completed",
        "stage": "solve",
        "profile_identity": manifest["profile_identity"],
        "mode_origin_identity": manifest["mode_origin_identity"],
        "bundle_manifest_sha256": helper.digest((bundle / "manifest.json").read_bytes()),
        "source_sha256": manifest["source_sha256"],
        "input_checkpoint_sha256": manifest["input_checkpoint_sha256"],
        "driven_checkpoint_sha256": helper.digest((run / "driven_checkpoint.mph").read_bytes()),
        "console_sha256": helper.digest((run / "console.txt").read_bytes()),
        "compile_exit_code": 0,
        "batch_exit_code": 0,
    }
    rec["artifacts"] = membership(run, ["DeviceCanary.java", "input_modes.mph", "driven_checkpoint.mph", "console.txt"])
    receipt = run / "receipt.json"
    write_json(receipt, rec)
    return bundle, run, receipt, rec


@pytest.mark.parametrize("historical", [False, True])
def test_prepare_and_validate_are_offline_self_contained_and_diagnostic(tmp_path, monkeypatch, historical):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("native execution attempted"))
    bundle, run, receipt, _rec = synthetic_driven(tmp_path, historical=historical)
    manifest = helper.verify_bundle(bundle)
    assert {p.name for p in bundle.iterdir()} == helper.BUNDLE_FILES
    assert manifest["will_execute"] is False
    assert manifest["physics_accepted"] is False
    (tmp_path / "modes_bundle").rename(tmp_path / "unavailable_modes_bundle")
    (tmp_path / "modes_run").rename(tmp_path / "unavailable_modes_run")
    if historical:
        (tmp_path / "producer_snapshot").rename(tmp_path / "unavailable_producer")
    assert helper.verify_bundle(bundle) == manifest
    result = helper.validate_evidence(bundle, run, receipt)
    assert result["evidence_integrity"] == "validated"
    assert result["physics_accepted"] is False
    assert result["physical_qualification"] == "not_established"
    assert len(result["complex_S"]) == 4
    for row in result["diagnostics"]:
        assert row["R"] == pytest.approx(0.01)
        assert row["T"] == pytest.approx(0.82)
        assert row["one_minus_R_minus_T"] == pytest.approx(0.17)
        assert row["closed_surface_residual_W_per_m"] == pytest.approx(-0.07)


def test_historical_mode_verifier_stays_strict_and_snapshot_is_data(tmp_path):
    bundle, run, receipt, _rec, options = synthetic_modes(tmp_path, historical=True)
    with pytest.raises(ValueError, match="dependency"):
        helper.modes().verify_bundle(bundle)
    with pytest.raises(ValueError):
        helper.prepare_bundle(tmp_path / "missing_explicit_origin", bundle, run, receipt)
    driven = tmp_path / "historical_driven"
    helper.prepare_bundle(driven, bundle, run, receipt, **options)
    origin = json.loads((driven / "mode_origin.json").read_bytes())
    assert origin["historical"] is True
    assert origin["validator_dependencies"] == helper.dependencies()


def test_renderer_loads_and_asserts_checkpoint_before_resume(tmp_path):
    bundle, _run, _receipt, _rec = synthetic_driven(tmp_path)
    text = (bundle / "DeviceCanary.java").read_text(encoding="utf-8")
    branch = text.split('if(STAGE.equals("solve")){', 1)[1].split("return m;", 1)[0]
    assert 'ModelUtil.load("Canary","input_modes.mph")' in branch
    assert "build()" not in branch and "sequence(m)" not in branch
    assert branch.index("profileDrivenAudit(m)") < branch.index("resumeDriven(m)")
    for token in ("PROFILE_IDENTITY", "MODE_ORIGIN_IDENTITY", "P11_INPUT_CHECKPOINT"):
        assert branch.index("profileDrivenAudit(m)") < branch.index('marker("' + token + " ")
        assert branch.index('marker("' + token + " ") < branch.index("resumeDriven(m)")
    for asserted in (
        "Persisted profile coordinates",
        "Persisted input normalization",
        "Persisted BMA settings",
        "Persisted port window",
        "Persisted material field model",
        "Persisted selected store mapping",
        "Frozen stores must precede driven start",
    ):
        assert asserted in text


@pytest.mark.parametrize(
    "name", ["profile.json", "DeviceCanary.java", "input_modes.mph", "mode_origin.json", "manifest.json"]
)
def test_bundle_substitution_is_rejected(tmp_path, name):
    bundle, _run, _receipt, _rec = synthetic_driven(tmp_path)
    with (bundle / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError):
        helper.verify_bundle(bundle)


@pytest.mark.parametrize("status", [None, "running", "failed", True])
def test_driven_receipt_requires_completed_status(tmp_path, status):
    bundle, run, receipt, rec = synthetic_driven(tmp_path)
    if status is None:
        rec.pop("status")
    else:
        rec["status"] = status
    write_json(receipt, rec)
    with pytest.raises(ValueError):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize(
    "attack",
    [
        "input",
        "checkpoint",
        "source",
        "console",
        "receipt_source",
        "receipt_input",
        "receipt_origin",
        "membership",
        "duplicate_membership",
        "unsafe_path",
        "bool_exit",
        "empty_checkpoint",
    ],
)
def test_driven_artifact_or_receipt_substitution_is_rejected(tmp_path, attack):
    bundle, run, receipt, rec = synthetic_driven(tmp_path)
    if attack in {"input", "checkpoint", "source", "console"}:
        name = {
            "input": "input_modes.mph",
            "checkpoint": "driven_checkpoint.mph",
            "source": "DeviceCanary.java",
            "console": "console.txt",
        }[attack]
        with (run / name).open("ab") as stream:
            stream.write(b"SUBSTITUTION")
    elif attack.startswith("receipt_"):
        key = {
            "receipt_source": "source_sha256",
            "receipt_input": "input_checkpoint_sha256",
            "receipt_origin": "mode_origin_identity",
        }[attack]
        rec[key] = "0" * 64
    elif attack == "membership":
        rec["artifacts"] = rec["artifacts"][:-1]
    elif attack == "duplicate_membership":
        rec["artifacts"].append(rec["artifacts"][0].copy())
    elif attack == "unsafe_path":
        rec["artifacts"].append({"path": "../foreign", "sha256": "0" * 64})
    elif attack == "bool_exit":
        rec["batch_exit_code"] = False
    else:
        (run / "driven_checkpoint.mph").write_bytes(b"short")
        refresh_artifact(run, receipt, rec, "driven_checkpoint.mph", "driven_checkpoint_sha256")
    write_json(receipt, rec)
    with pytest.raises(ValueError):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("CANARY SOURCE 2,2,1550", "CANARY SOURCE 2,2,1560"),
        ("CANARY SOURCE 2,2,1550", "CANARY SOURCE 1,1,1550"),
        ("CANARY SOURCE 1,1,1550", "CANARY SOURCE 1.5,1.5,1550"),
        ("CANARY S 1,1,1,0.1,0", "CANARY S 1,1,2,0.1,0"),
        ("CANARY S 1,1,1,0.1,0", "CANARY S 1.5,1,1.5,0.1,0"),
        ("CANARY S 1,1,1,0.1,0", "CANARY S 1,1.5,1,0.1,0"),
        ("CANARY S 1,1,1,0.1,0", "CANARY S 1,2,1,0.1,0"),
        ("CANARY S 2,2,2,0.1,0\n", ""),
        ("CANARY S 1,1,1,0.1,0", "CANARY S 1,1,1,nan,0"),
        ("CANARY S 1,1,1,0.1,0", "CANARY S 1,1,1,1e308,0"),
        ("CANARY POWER 2,0.1,0,0.82,-0.99,2.1837,2.1837", "CANARY POWER 2.5,0.1,0,0.82,-0.99,2.1837,2.1837"),
        ("CANARY POWER 2,0.1,0,0.82,-0.99,2.1837,2.1837\n", ""),
        ("CANARY POWER 1,0.1,0,-0.99,0.82,2.1837,2.1837", "CANARY POWER 1,0.1,0,-0.99,0.82,1.3,2.1837"),
        ("CANARY P10_TABLE [[0.0, -0.15]", "CANARY P10_TABLE [[0.1, -0.15]"),
        ("n=[2.6] ki=[0]", "n=[2.5] ki=[0]"),
        ("CANARY P10_PHYSICS port1 [1]", "CANARY P10_PHYSICS port1 [2]"),
        ("phase=0 Pin=1[W/m]", "phase=0 Pin=2[W/m]"),
        (
            "CANARY P11_STORE_AFTER port=1 tag=store1 solution=sol1 dataset=dset1",
            "CANARY P11_STORE_AFTER port=1 tag=store1 solution=sol2 dataset=dset1",
        ),
        ("CANARY P11_PROFILE_VALIDATED\n", ""),
        ("CANARY RESUME_FROM_FROZEN solMain/st3", "CANARY RESUME_FROM_FROZEN foreign/st3"),
        ("CANARY ACTUAL_DATASET dset3 solution=solMain", "CANARY ACTUAL_DATASET dset3 solution=foreign"),
        (DATASET_AXIS, "pnames=[freq, foreign] pvalues=[1.9341448903225803E14, 1.0, 1.9341448903225803E14, 2.0]"),
        (DATASET_AXIS, "pnames=[freq, PortName] pvalues=[1.9341448903225803E14, 7, 1.9341448903225803E14, 9]"),
        (DATASET_AXIS, "pnames=[freq, PortName] pvalues=[2E14, 1.0, 2E14, 2.0]"),
        ("CANARY NATIVE_COMPLETED", "CANARY NATIVE_COMPLETED\nCANARY NATIVE_COMPLETED"),
        ("CANARY NATIVE_COMPLETED", "CANARY NATIVE_COMPLETED\nCANARY FAILED"),
        ("CANARY NATIVE_COMPLETED", "CANARY NATIVE_COMPLETED\njava.lang.IllegalStateException: diagnostic failure"),
        ("CANARY NATIVE_COMPLETED", "CANARY MODES_COMPLETED\nCANARY NATIVE_COMPLETED"),
        ("CANARY NATIVE_COMPLETED", "CANARY SELECTED_SCALAR 1,2.1837,0,1550,1\nCANARY NATIVE_COMPLETED"),
        (
            "CANARY NATIVE_COMPLETED",
            "CANARY RUN_TO_SELECTED solMain/store2 future_driven_start=st3\nCANARY NATIVE_COMPLETED",
        ),
    ],
)
def test_rehashed_bad_native_records_are_rejected(tmp_path, old, new):
    bundle, run, receipt, rec = synthetic_driven(tmp_path)
    console = run / "console.txt"
    text = console.read_text(encoding="utf-8")
    assert old in text
    console.write_text(text.replace(old, new), encoding="utf-8")
    refresh_artifact(run, receipt, rec, "console.txt", "console_sha256")
    with pytest.raises(ValueError):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize("moved_marker", ["P10_READBACK_COMPLETED", "P11_PROFILE_VALIDATED"])
def test_native_readbacks_must_precede_the_resume_they_authorize(tmp_path, moved_marker):
    bundle, run, receipt, rec = synthetic_driven(tmp_path)
    console = run / "console.txt"
    text = console.read_text(encoding="utf-8")
    marker = "CANARY " + moved_marker
    text = text.replace(marker + "\n", "").replace(
        "CANARY RESUME_FROM_FROZEN solMain/st3", "CANARY RESUME_FROM_FROZEN solMain/st3\n" + marker
    )
    console.write_text(text, encoding="utf-8")
    refresh_artifact(run, receipt, rec, "console.txt", "console_sha256")
    with pytest.raises(ValueError):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize("token", ["PROFILE_IDENTITY", "MODE_ORIGIN_IDENTITY", "P11_INPUT_CHECKPOINT"])
@pytest.mark.parametrize("position", ["before_audit", "after_resume"])
def test_runtime_identity_tokens_must_follow_actual_audit_and_precede_resume(tmp_path, token, position):
    bundle, run, receipt, rec = synthetic_driven(tmp_path)
    console = run / "console.txt"
    lines = console.read_text(encoding="utf-8").splitlines()
    identity = next(line for line in lines if line.startswith("CANARY " + token + " "))
    lines.remove(identity)
    if position == "before_audit":
        lines.insert(lines.index("CANARY P11_PROFILE_VALIDATED"), identity)
    else:
        lines.insert(lines.index("CANARY RESUME_FROM_FROZEN solMain/st3") + 1, identity)
    console.write_text("\n".join(lines) + "\n", encoding="utf-8")
    refresh_artifact(run, receipt, rec, "console.txt", "console_sha256")
    with pytest.raises(ValueError):
        helper.validate_evidence(bundle, run, receipt)


@pytest.mark.parametrize(
    "attack", ["snapshot_bytes", "snapshot_census", "manifest_hash", "mode_console", "mode_checkpoint"]
)
def test_original_mode_origin_substitution_is_rejected(tmp_path, attack):
    bundle, run, receipt, rec, options = synthetic_modes(tmp_path, historical=True)
    if attack == "snapshot_bytes":
        (options["producer_snapshot"] / "profile_modes.py").write_bytes(b"different producer")
    elif attack == "snapshot_census":
        (options["producer_snapshot"] / "extra.py").write_bytes(b"extra")
    elif attack == "manifest_hash":
        rec["helper_sourcecopy_manifest_sha256"] = "0" * 64
        write_json(receipt, rec)
    elif attack == "mode_console":
        console = run / "console.txt"
        console.write_text(console.read_text().replace("2.1837000141287444", "1.8"), encoding="utf-8")
        refresh_artifact(run, receipt, rec, "console.txt", "console_sha256")
    else:
        (run / "selected_modes.mph").write_bytes(b"substituted checkpoint" * 100)
    with pytest.raises(ValueError):
        helper.prepare_bundle(tmp_path / "rejected", bundle, run, receipt, **options)


@pytest.mark.parametrize("fatal", ["CANARY FAILED", "java.lang.IllegalStateException: diagnostic failure"])
def test_mode_fatal_records_block_public_and_driven_consumption(tmp_path, fatal):
    bundle, run, receipt, rec, _options = synthetic_modes(tmp_path)
    console = run / "console.txt"
    with console.open("a", encoding="utf-8") as stream:
        stream.write(fatal + "\n")
    refresh_artifact(run, receipt, rec, "console.txt", "console_sha256")
    with pytest.raises(ValueError):
        helper.modes().validate_evidence(bundle, run, receipt)
    with pytest.raises(ValueError):
        helper.prepare_bundle(tmp_path / "rejected_fatal_mode", bundle, run, receipt)


@pytest.mark.parametrize("attack", ["receipt", "dependencies", "origin_schema", "producer_bytes"])
def test_embedded_mode_origin_is_rechecked(tmp_path, attack):
    bundle, _run, _receipt, _rec = synthetic_driven(tmp_path, historical=True)
    origin_path = bundle / "mode_origin.json"
    origin = json.loads(origin_path.read_bytes())
    if attack == "receipt":
        rec = json.loads(helper.decoded(origin["mode_receipt"]))
        rec["status"] = "failed"
        origin["mode_receipt"] = helper.encoded(helper.canonical(rec))
    elif attack == "dependencies":
        origin["validator_dependencies"]["profile_driven.py"] = "0" * 64
    elif attack == "origin_schema":
        origin["schema_version"] = "unknown"
    else:
        origin["producer_files"]["profile_modes.py"] = helper.encoded(b"wrong bytes")
    write_json(origin_path, origin)
    with pytest.raises(ValueError):
        helper.verify_bundle(bundle)
