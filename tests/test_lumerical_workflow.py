"""Native receipt consistency and shared optimization integration; synthetic I/O."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from photonic_workflow.circuits import AssemblyError, validate_manifest
from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical.runtime import validate_request
from photonic_workflow.lumerical.workflow import (
    compare_device_runs,
    export_device_run,
    load_device_run,
    objective_value,
    optimize_step,
)
from photonic_workflow.lumerical_exchange import dataset_from_arrays
from photonic_workflow.models import OptimizationSpec, OptimizationTrial
from photonic_workflow.models.io import load_contract, write_contract
from photonic_workflow.optimization import suggest_candidate


def native_fixture(folder, *, mesh=3, through=0.9, parameters=None):
    folder.mkdir(parents=True)
    p = {"family": "straight", "mesh_accuracy": mesh, "geometry_parameters": parameters or {"width_um": 0.3}}
    request = validate_request({"schema_version": "1.0", "operation": "fdtd-device", "parameters": p})
    frequency = np.array([299792458 / 1500e-9, 299792458 / 1600e-9])
    matrix = np.zeros((2, 2, 2), dtype=complex)
    matrix[:, 0, 1] = matrix[:, 1, 0] = through * np.exp(0.4j)
    channels = [{"id": name, "port": name, "mode": "fundamental TM mode", "incoming_direction": incoming,
                 "outgoing_direction": outgoing, "reference_plane": plane}
                for name, incoming, outgoing, plane in [("left", "+x", "-x", "x=0 m"),
                                                       ("right", "-x", "+x", "x=6e-6 m")]]
    spectral_axis = {"quantity": "frequency", "unit": "Hz", "values": frequency.tolist()}
    dataset = dataset_from_arrays(matrix, spectral_axis=spectral_axis,
                                  channels=channels, producer={"product": "FDTD", "version": "synthetic-test"},
                                  model_level="2d-scalar-index-surrogate", passive=True, time_dependence="exp(-iwt)")
    (folder / "request.json").write_text(json.dumps(request))
    (folder / "geometry.json").write_text(json.dumps({"test": "synthetic fixture"}))
    (folder / "source_dataset.json").write_text(json.dumps(dataset))
    np.savez(folder / "raw.npz", s_matrix=matrix, frequency_hz=frequency)
    columns = []
    for index, name in enumerate(("left", "right")):
        model, raw = f"source-{index}.fsp", f"source-{index}.npz"
        (folder / model).write_bytes(b"synthetic fixture; not a native model")
        np.savez(folder / raw, values=matrix[:, :, index])
        columns.append({"source_index": index, "source_port": name, "source_port_readback": name,
                        "source_mode_readback": "mode 1", "source_model": model, "raw": raw})
    receipt = {"operation": "fdtd-device", "status": "completed", "native_execution": True, "solve_completed": True,
               "result": {"family": "straight", "model_level": "2d-scalar-index-surrogate", "source_columns": columns,
                          "matrix_complete": True, "basis_consistent": True, "diagnostic_passed": True},
               "artifacts": {path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                        "bytes": path.stat().st_size}
                             for path in folder.iterdir() if path.is_file()}}
    path = folder / "receipt.json"
    path.write_text(json.dumps(receipt))
    return path


def test_receipt_data_is_verified_and_consumed_without_phase_loss(tmp_path):
    path = native_fixture(tmp_path / "native")
    run = load_device_run(path)
    assert objective_value(run["data"], {"name": "through", "in_port": "left", "out_port": "right",
                                          "statistic": "mean_power"}) == pytest.approx(0.81)
    exported = export_device_run(path, tmp_path / "component.csv", project_root=tmp_path)
    assert exported["component"]["ports"] == ["left", "right"]
    assert (tmp_path / "component.csv.source.json").read_bytes() == (path.parent / "source_dataset.json").read_bytes()
    (path.parent / "geometry.json").write_text("changed")
    with pytest.raises(InvalidInputError, match="changed"):
        load_device_run(path)


@pytest.mark.parametrize("field,value", [("source_index", 1), ("source_port_readback", "right"),
                                        ("source_mode_readback", "mode 2"), ("raw", "missing.npz")])
def test_source_identity_corruption_is_rejected(tmp_path, field, value):
    path = native_fixture(tmp_path / "native")
    receipt = json.loads(path.read_text())
    receipt["result"]["source_columns"][0][field] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(InvalidInputError):
        load_device_run(path)


def test_changed_but_rehashed_export_must_still_match_raw_matrix(tmp_path):
    path = native_fixture(tmp_path / "native")
    dataset_path = path.parent / "source_dataset.json"
    dataset = json.loads(dataset_path.read_text())
    dataset["s_matrices"][0][0][1] = [0.1, 0.2]
    dataset_path.write_text(json.dumps(dataset))
    receipt = json.loads(path.read_text())
    receipt["artifacts"][dataset_path.name] = {"sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                                             "bytes": dataset_path.stat().st_size}
    path.write_text(json.dumps(receipt))
    with pytest.raises(InvalidInputError, match="raw source-bound"):
        load_device_run(path)


@pytest.mark.parametrize("field,value", [("native_execution", "true"), ("solve_completed", 1),
                                        ("result", []), ("artifacts", []),
                                        ("result.source_columns", [None]),
                                        ("result.source_columns", [{}])])
def test_malformed_receipt_fields_raise_structured_input_errors(tmp_path, field, value):
    path = native_fixture(tmp_path / "native")
    receipt = json.loads(path.read_text())
    target = receipt
    *parents, key = field.split(".")
    for parent in parents:
        target = target[parent]
    target[key] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(InvalidInputError):
        load_device_run(path)


@pytest.mark.parametrize("raw", [{"s_matrix": np.ones((2, 2, 2), dtype=complex)},
                                 {"s_matrix": np.ones((2, 2, 2), dtype=complex), "frequency_hz": [1, 1]},
                                 {"s_matrix": np.ones((2, 2), dtype=complex), "frequency_hz": [1, 2]},
                                 {"s_matrix": np.ones((2, 2, 2), dtype=complex), "frequency_hz": [0, 2]}])
def test_rehashed_raw_must_have_complete_finite_spectral_arrays(tmp_path, raw):
    path = native_fixture(tmp_path / "native")
    raw_path = path.parent / "raw.npz"
    np.savez(raw_path, **raw)
    receipt = json.loads(path.read_text())
    receipt["artifacts"][raw_path.name] = {"sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                                         "bytes": raw_path.stat().st_size}
    path.write_text(json.dumps(receipt))
    with pytest.raises(InvalidInputError, match="raw"):
        load_device_run(path)


@pytest.mark.parametrize("field,value", [("time_dependence", "exp(+iwt)"), ("mode", "fundamental TE mode")])
def test_rehashed_native_conventions_cannot_change_independently(tmp_path, field, value):
    path = native_fixture(tmp_path / "native")
    dataset_path = path.parent / "source_dataset.json"
    dataset = json.loads(dataset_path.read_text())
    target = dataset["conventions"] if field == "time_dependence" else dataset["channels"][0]
    target[field] = value
    dataset_path.write_text(json.dumps(dataset))
    receipt = json.loads(path.read_text())
    receipt["artifacts"][dataset_path.name] = {"sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                                             "bytes": dataset_path.stat().st_size}
    path.write_text(json.dumps(receipt))
    with pytest.raises(InvalidInputError, match="phasor convention or selected mode"):
        load_device_run(path)


def test_mesh_comparison_checks_same_device_and_reports_power_only(tmp_path):
    a = native_fixture(tmp_path / "coarse", mesh=3, through=0.9)
    b = native_fixture(tmp_path / "fine", mesh=5, through=0.91)
    assert compare_device_runs(a, b)["max_absolute_power_change"] == pytest.approx(0.91**2 - 0.9**2)
    c = native_fixture(tmp_path / "changed-geometry", parameters={"width_um": 0.31})
    with pytest.raises(InvalidInputError, match="matching geometry"):
        compare_device_runs(a, c)


def test_power_comparison_allows_only_native_plane_roundoff(tmp_path):
    a = native_fixture(tmp_path / "coarse", mesh=3)
    b = native_fixture(tmp_path / "fine", mesh=5)
    for path, coordinate in ((a, "6.0000000000000078e-06"), (b, "6.0000000000000002e-06")):
        dataset_path = path.parent / "source_dataset.json"
        dataset = json.loads(dataset_path.read_text())
        dataset["channels"][1]["reference_plane"] = f"x={coordinate} m; native port E dataset"
        dataset_path.write_text(json.dumps(dataset))
        receipt = json.loads(path.read_text())
        receipt["artifacts"][dataset_path.name] = {"sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                                                 "bytes": dataset_path.stat().st_size}
        path.write_text(json.dumps(receipt))
    compared = compare_device_runs(a, b)
    assert 0 < compared["max_reference_plane_roundoff_m"] < compared["reference_plane_roundoff_tolerance_m"]
    assert compared["max_absolute_power_change"] == 0
    dataset_path = b.parent / "source_dataset.json"
    dataset = json.loads(dataset_path.read_text())
    dataset["channels"][1]["reference_plane"] = "x=6.0001e-06 m; native port E dataset"
    dataset_path.write_text(json.dumps(dataset))
    receipt = json.loads(b.read_text())
    receipt["artifacts"][dataset_path.name] = {"sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                                             "bytes": dataset_path.stat().st_size}
    b.write_text(json.dumps(receipt))
    with pytest.raises(InvalidInputError, match="reference-plane roundoff"):
        compare_device_runs(a, b)


def test_explicit_circuit_tolerance_never_changes_native_complex_data(tmp_path):
    native = native_fixture(tmp_path / "native", through=1.002)
    strict = export_device_run(native, tmp_path / "strict.csv", project_root=tmp_path)
    tolerant = export_device_run(native, tmp_path / "tolerant.csv", project_root=tmp_path, passivity_tolerance=0.005)
    assert (tmp_path / "strict.csv").read_bytes() == (tmp_path / "tolerant.csv").read_bytes()
    manifest = {"schema_version": "1.0", "conventions": strict["conventions"],
                "components": {"device": strict["component"]}, "instances": {"one": {"component": "device"}},
                "connections": [], "external_ports": {"left": "one:left", "right": "one:right"}}
    path = tmp_path / "assembly.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(AssemblyError, match="passive model"):
        validate_manifest(path)
    manifest["components"]["device"] = tolerant["component"]
    path.write_text(json.dumps(manifest))
    validate_manifest(path)
    manifest["components"]["device"]["passivity_tolerance"] = True
    path.write_text(json.dumps(manifest))
    with pytest.raises(AssemblyError, match="passivity_tolerance"):
        validate_manifest(path)


def test_export_preserves_failed_native_diagnostics_without_accepting_physics(tmp_path):
    native = native_fixture(tmp_path / "native")
    receipt = json.loads(native.read_text())
    receipt["result"]["diagnostic_passed"] = False
    receipt["result"]["diagnostic_checks"] = {"passivity_with_5pct_numeric_budget": False}
    native.write_text(json.dumps(receipt))
    exported = export_device_run(native, tmp_path / "component.csv", project_root=tmp_path)
    assert exported["native_diagnostic_passed"] is False
    assert exported["native_diagnostic_checks"] == {"passivity_with_5pct_numeric_budget": False}
    assert exported["physics_accepted"] is False
    assert (tmp_path / "component.csv.source.json").read_bytes() == (native.parent / "source_dataset.json").read_bytes()


def configuration(folder, *, unit="um"):
    spec = OptimizationSpec(stable_id="optimization:lumerical-test", name="native test", source="synthetic test",
                            solver_backend="lumerical-fdtd-device", fidelity="full-wave-2d-scalar",
                            variables=[{"name": "width", "lower": 0.28, "upper": 0.32, "unit": unit}],
                            objectives=[{"name": "through", "sense": "maximize"}],
                            evaluation_budget=6, random_seed=12, promotion_rule={"validation_reserve": 1})
    write_contract(folder / "spec.json", spec)
    base = {"schema_version": "1.0", "operation": "fdtd-device", "parameters": {}}
    (folder / "base.json").write_text(json.dumps(base))
    config = {"schema_version": "1.0", "spec_file": "spec.json", "base_request": "base.json", "trials_dir": "trials",
              "objective": {"name": "through", "out_port": "right", "in_port": "left", "statistic": "mean_power"},
              "parameter_map": {"width": "geometry_parameters.width_um"}}
    path = folder / "config.json"
    path.write_text(json.dumps(config))
    return path, spec


def test_shared_optimizer_uses_retained_device_data_and_resumes_history(tmp_path, monkeypatch):
    config, spec = configuration(tmp_path)
    calls = []

    def fake_run(candidate, output, **kwargs):
        width = candidate["parameters"]["geometry_parameters"]["width_um"]
        calls.append(width)
        path = native_fixture(output, through=0.5 + width, parameters={"width_um": width})
        return json.loads(path.read_text())

    monkeypatch.setattr("photonic_workflow.lumerical.runtime.run_request", fake_run)
    plan = optimize_step(config, tmp_path / "plan")
    assert not plan["will_execute"] and not calls and not (tmp_path / "trials").exists()
    result = optimize_step(config, tmp_path / "step", execute=True)
    assert result["status"] == "succeeded"
    trial = load_contract(Path(result["trial_file"]), "OptimizationTrial")
    assert isinstance(trial, OptimizationTrial)
    assert trial.objectives["through"] == pytest.approx((0.5 + calls[0]) ** 2)
    assert suggest_candidate(spec, [trial])["parameters"]["width"] != calls[0]
    result2 = optimize_step(config, tmp_path / "step2", execute=True)
    assert result2["status"] == "succeeded" and calls[1] != calls[0]


def test_optimizer_rejects_unit_mismatch_before_plan_or_solve(tmp_path):
    config, _ = configuration(tmp_path, unit="nm")
    with pytest.raises(InvalidInputError, match="um parameter/unit"):
        optimize_step(config, tmp_path / "absent", execute=True)
    assert not (tmp_path / "absent").exists()
