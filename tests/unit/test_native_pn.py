"""Synthetic parser/provenance/launcher controls; no native solver executes."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from photonic_workflow import native_backend as backend
from photonic_workflow import native_pn
from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.ring_modulator import depletion_response, poisson_reference


def synthetic_output(parameters=None):
    """Construct labeled software fixtures, never claimed as native evidence."""
    response = depletion_response(parameters)
    p = response["parameters"]
    sheet = response["charge_per_area_c_per_m2"]
    readback = [p[key] for key in ("acceptor_cm3", "donor_cm3", "intrinsic_cm3", "temperature_k",
                                  "relative_permittivity", "reverse_bias_v", "p_region_width_um",
                                  "n_region_width_um")]
    readback += [response["xp_um"], response["xn_um"], response["built_in_voltage_v"], response["potential_drop_v"],
                 sheet, -sheet, 0.0, response["capacitance_per_area_f_per_m2"]]
    identity = hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    lines = [
        "SYNTHETIC FIXTURE; NOT NATIVE EVIDENCE", f"PN IDENTITY {identity}", "PN UNIT_CODEPOINTS [181, 109]",
        "PN UNIT um", "PN CONTACT left [1]", "PN CONTACT right [5]", "PN DATASET dset1 SOLUTION sol1",
        "PN READBACK " + json.dumps(readback), f"PN XP {readback[8]}", f"PN XN {readback[9]}",
        f"PN POTENTIAL {readback[11]}", f"PN CHARGE {readback[12]},{readback[13]},{readback[14]}",
        f"PN CAPACITANCE {readback[15]}",
    ]
    positions = [-p["p_region_width_um"] + (p["p_region_width_um"] + p["n_region_width_um"]) * i / 100
                 for i in range(101)]
    for index, row in enumerate(poisson_reference(p, positions)["rows"]):
        lines.append(f"PN SAMPLE {index},{row['x_um']},{row['potential_v']},{row['field_v_per_m']},"
                     f"{row['charge_c_per_m3']}")
    lines.extend(("PN FIELD sampled_actual_solution_gradient", native_pn._COMPLETION))
    return "\n".join(lines) + "\n"


def change_record(text, marker, transform):
    lines = text.splitlines()
    matching = [index for index, line in enumerate(lines) if line.startswith("PN " + marker + " ")]
    assert len(matching) == 1
    index = matching[0]
    lines[index] = "PN " + marker + " " + transform(lines[index].split(" ", 2)[2])
    return "\n".join(lines) + "\n"


def test_bundle_round_trip_rejects_existing_destination(tmp_path):
    bundle = tmp_path / "pn"
    manifest = native_pn.prepare_pn_bundle(bundle, {"reverse_bias_v": 2})
    verified = native_pn.verify_pn_bundle(bundle)
    assert verified["manifest"] == manifest
    assert verified["parameters"]["reverse_bias_v"] == 2
    assert manifest["native_execution"] is False
    with pytest.raises(FileExistsError):
        native_pn.prepare_pn_bundle(bundle)


@pytest.mark.parametrize("name", ["pn.json", "NativePn.java", "manifest.json"])
def test_bundle_altered_member_or_manifest_fails(tmp_path, name):
    bundle = tmp_path / "pn"
    native_pn.prepare_pn_bundle(bundle)
    path = bundle / name
    if name == "manifest.json":
        content = json.loads(path.read_bytes())
        content["native_execution"] = True
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(InvalidInputError):
        native_pn.verify_pn_bundle(bundle)


def test_recomputed_hash_cannot_authorize_arbitrary_source(tmp_path):
    bundle = tmp_path / "pn"
    native_pn.prepare_pn_bundle(bundle)
    source = bundle / "NativePn.java"
    source.write_text("class NativePn { static { System.exit(0); } }", encoding="utf-8")
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest["files"]["NativePn.java"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(InvalidInputError, match="trusted generation"):
        native_pn.verify_pn_bundle(bundle)


def test_duplicate_json_keys_rejected_in_data_and_manifest(tmp_path):
    bundle = tmp_path / "pn"
    native_pn.prepare_pn_bundle(bundle)
    manifest = bundle / "manifest.json"
    raw = manifest.read_text()
    manifest.write_text(raw.replace('"schema_version":"1.0"', '"schema_version":"1.0","schema_version":"1.0"'))
    with pytest.raises(InvalidInputError, match="Duplicate"):
        native_pn.verify_pn_bundle(bundle)


@pytest.mark.parametrize("parameters", [{}, {"reverse_bias_v": 2}, {"acceptor_cm3": 3e17, "reverse_bias_v": 1}])
def test_complete_synthetic_protocol_and_equations_pass_without_physics_promotion(parameters):
    result = native_pn.parse_pn_output(synthetic_output(parameters), parameters)
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["physics_accepted"] is False
    assert len(result["samples"]) == 101


@pytest.mark.parametrize("mutate", [
    lambda text: text.replace("PN IDENTITY ", "PN IDENTITY wrong"),
    lambda text: text.replace(native_pn._COMPLETION, ""),
    lambda text: text + native_pn._COMPLETION + "\n",
    lambda text: text + "PN FAILED java.lang.IllegalStateException: failed\n",
    lambda text: text + "java.lang.RuntimeException: failure after completion\n",
    lambda text: text.replace("PN UNIT um", "PN UNIT mm"),
    lambda text: text.replace("PN UNIT_CODEPOINTS [181, 109]", "PN UNIT_CODEPOINTS [63, 109]"),
    lambda text: text.replace("PN CONTACT right [5]", "PN CONTACT right [1]"),
    lambda text: text.replace("PN DATASET dset1 SOLUTION sol1", "PN DATASET unknown"),
    lambda text: text + "PN XP 0.1\n",
    lambda text: change_record(text, "XN", lambda _: "0.1"),
    lambda text: text.replace("PN SAMPLE 100,", "PN SAMPLE 99,"),
    lambda text: text.replace("PN SAMPLE 50,0.0,", "PN SAMPLE 50,1e-6,"),
    lambda text: text.replace("PN SAMPLE 99,", "PN SAMPLE 99,nan,"),
])
def test_wrong_identity_axes_units_duplicates_and_fatal_records_are_rejected(mutate):
    with pytest.raises((InvalidInputError, ValueError)):
        native_pn.parse_pn_output(mutate(synthetic_output()))


def test_wrong_parameter_readback_is_rejected():
    def wrong(raw):
        values = json.loads(raw)
        values[0] *= 2
        return json.dumps(values)

    with pytest.raises(InvalidInputError, match="parameter readback"):
        native_pn.parse_pn_output(change_record(synthetic_output(), "READBACK", wrong))


def test_coordinate_unit_error_is_rejected_before_field_comparison():
    text = synthetic_output()
    text = text.replace("PN SAMPLE 0,-1.0,", "PN SAMPLE 0,-1e-6,")
    with pytest.raises(InvalidInputError, match="coordinates"):
        native_pn.parse_pn_output(text)


def test_completed_native_numerical_failures_stay_visible():
    text = synthetic_output()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("PN SAMPLE 50,"):
            fields = line.split(",")
            fields[2] = str(float(fields[2]) + 0.01)
            lines[index] = ",".join(fields)
    result = native_pn.parse_pn_output("\n".join(lines))
    assert result["benchmark_passed"] is False
    assert result["checks"]["sampled_potential"] is False
    assert result["max_potential_error_v"] == pytest.approx(0.01)
    assert result["checks"]["charge_neutrality"] is True


def fake_solver(tmp_path):
    directory = tmp_path / "synthetic-solver" / "bin" / "win64"
    directory.mkdir(parents=True)
    for name in ("comsolcompile.exe", "comsolbatch.exe"):
        (directory / name).write_bytes(b"nonexecutable synthetic launcher")
    return directory.parent.parent


def run_fixture(tmp_path, monkeypatch, *, scenario=None):
    scenario = scenario or {}
    bundle = tmp_path / "pn"
    native_pn.prepare_pn_bundle(bundle)
    calls = []

    def launch(command, folder, log, timeout):
        calls.append(command)
        assert timeout > 0
        compile_stage = log.name == "compile.log"
        if compile_stage:
            log.write_text("synthetic compilation; no native execution", encoding="utf-8")
            if not scenario.get("missing_class"):
                (folder / "NativePn.class").write_bytes(b"synthetic class fixture, never executed" * 4)
            if scenario.get("change_bundle"):
                (bundle / "pn.json").write_bytes((bundle / "pn.json").read_bytes() + b" ")
        else:
            log.write_text(scenario.get("console", synthetic_output()), encoding="utf-8")
            if not scenario.get("missing_checkpoint"):
                (folder / "pn_checkpoint.mph").write_bytes(b"synthetic checkpoint, not a COMSOL model" * 12)
        return {"exit_code": scenario.get("compile_code" if compile_stage else "batch_code", 0),
                "timed_out": scenario.get("timed_out", False), "owned_processes_exited": True,
                "stdout": log.name, "seconds": 0.01, "argv": command}

    import psutil

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(()))
    monkeypatch.setattr(backend, "_launch", launch)
    receipt = native_pn.run_pn_bundle(bundle, fake_solver(tmp_path), timeout_s=30, compile_timeout_s=10, cores=2)
    return receipt, calls


def test_mocked_success_receipt_binds_raw_source_class_and_checkpoint(tmp_path, monkeypatch):
    receipt, calls = run_fixture(tmp_path, monkeypatch)
    assert receipt["status"] == "completed"
    assert receipt["benchmark_passed"] is True
    assert receipt["physical_qualification"] == "not_established"
    assert len(calls) == 2
    result = native_pn.calibrate_pn_run(Path(receipt["run_directory"]) / "receipt.json")
    assert result["benchmark_passed"] is True
    assert result["physics_accepted"] is False
    for artifact in receipt["artifacts"]:
        path = Path(receipt["run_directory"]) / artifact["path"]
        assert artifact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("scenario", [
    {"compile_code": 1}, {"missing_class": True}, {"batch_code": 1}, {"missing_checkpoint": True},
    {"timed_out": True}, {"change_bundle": True},
    {"console": synthetic_output().replace(native_pn._COMPLETION, "PN COMPLETED_wrong")},
    {"console": synthetic_output() + native_pn._COMPLETION + "\n"},
])
def test_failed_execution_keeps_its_receipt_and_cannot_calibrate(tmp_path, monkeypatch, scenario):
    receipt, calls = run_fixture(tmp_path, monkeypatch, scenario=scenario)
    assert receipt["status"] == "failed"
    assert receipt["error"]
    path = Path(receipt["run_directory"]) / "receipt.json"
    assert path.is_file()
    with pytest.raises(InvalidInputError, match="completed"):
        native_pn.calibrate_pn_run(path)
    if scenario.get("compile_code") or scenario.get("missing_class") or scenario.get("change_bundle"):
        assert len(calls) == 1


@pytest.mark.parametrize("artifact", ["console.log", "NativePn.class", "NativePn.java", "pn_checkpoint.mph"])
def test_receipt_member_changes_cannot_reuse_calibration(tmp_path, monkeypatch, artifact):
    receipt, _ = run_fixture(tmp_path, monkeypatch)
    root = Path(receipt["run_directory"])
    path = root / artifact
    path.write_bytes(path.read_bytes() + b" altered")
    with pytest.raises(InvalidInputError, match="changed"):
        native_pn.calibrate_pn_run(root / "receipt.json")


def test_altered_receipt_process_status_cannot_calibrate(tmp_path, monkeypatch):
    receipt, _ = run_fixture(tmp_path, monkeypatch)
    path = Path(receipt["run_directory"]) / "receipt.json"
    receipt["batch"]["owned_processes_exited"] = False
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(InvalidInputError, match="process"):
        native_pn.calibrate_pn_run(path)


@pytest.mark.parametrize("kwargs", [{"timeout_s": 0}, {"compile_timeout_s": 61}, {"cores": True}, {"cores": 5}])
def test_execution_budget_rejected_before_solver_launch(tmp_path, kwargs):
    bundle = tmp_path / "pn"
    native_pn.prepare_pn_bundle(bundle)
    with pytest.raises((InvalidInputError, ValueError)):
        native_pn.run_pn_bundle(bundle, **kwargs)
    assert not list(bundle.glob("run-*"))


def test_live_solver_prevents_concurrent_native_job(tmp_path, monkeypatch):
    import psutil

    bundle = tmp_path / "pn"
    native_pn.prepare_pn_bundle(bundle)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter((SimpleNamespace(info={"name": "comsol.exe"}),)))
    with pytest.raises(RuntimeError, match="concurrency"):
        native_pn.run_pn_bundle(bundle, fake_solver(tmp_path))
    assert not list(bundle.glob("run-*"))
