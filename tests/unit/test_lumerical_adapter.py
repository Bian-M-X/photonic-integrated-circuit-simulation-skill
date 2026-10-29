"""The built-in Lumerical factory supports only bounded discovery and dry plans."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from photonic_workflow.adapters import default_adapter_registry
from photonic_workflow.adapters.lumerical import LumericalAdapter
from photonic_workflow.exceptions import InvalidInputError, SecurityViolationError, UnavailableCapabilityError
from photonic_workflow.lumerical.runtime import validate_request
from photonic_workflow.models import AvailabilityStatus, RunSpec


@pytest.fixture
def setup(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    install = project / "app"
    product = install / "v999/Lumerical"
    (product / "api/python").mkdir(parents=True)
    (product / "api/python/lumapi.py").write_text("raise AssertionError('must not import vendor code')")
    (product / "bin").mkdir()
    (product / "bin/fdtd-solutions.exe").write_bytes(b"synthetic installation fixture")
    (product / "bin/fdtd-engine.exe").write_bytes(b"synthetic installation fixture")
    (product / "VERSION").write_text("test-only version")
    adapter = LumericalAdapter(project_root=project, runtime_directory=Path("runs/planned"),
                               install_root=install, allowed_roots=[project])
    request = {"schema_version": "1.0", "operation": "fdtd-device", "parameters": {"family": "straight"}}
    spec = RunSpec(stable_id="run:adapter-test", name="Plan test", source="synthetic offline test",
                   operation="fdtd-device", adapter="lumerical", inputs={"request": request, "threads": 2},
                   timeout_s=180)
    return project, install, adapter, spec


def test_registry_has_builtin_plan_factory_without_enabling_execution(setup):
    project, install, _, spec = setup
    registry = default_adapter_registry()
    assert registry.has_factory("lumerical")
    adapter = registry.create("lumerical", project_root=project, install_root=install,
                              runtime_directory=Path("runs/registry"), allowed_roots=[project])
    assert isinstance(adapter, LumericalAdapter)
    assert adapter.descriptor == registry.descriptor("lumerical")
    with patch("subprocess.Popen", side_effect=AssertionError("must not start a process")):
        plan = adapter.plan(spec)
        with pytest.raises(UnavailableCapabilityError):
            adapter.execute(plan)
    assert not (project / "runs").exists()


def test_discovery_remains_unverified_and_never_imports_vendor_code(setup):
    project, _, adapter, _ = setup
    with patch("subprocess.Popen", side_effect=AssertionError("must not start a process")):
        report = adapter.check()
    assert report.availability == AvailabilityStatus.UNVERIFIED
    assert report.features["installation_files_present"] is True
    assert report.features["api_imported"] is False
    assert report.features["license_checked"] is False
    assert report.features["generic_execution_enabled"] is False
    missing = LumericalAdapter(project_root=project, install_root=project / "missing",
                               runtime_directory=Path("runs/missing"))
    assert missing.check().availability == AvailabilityStatus.UNAVAILABLE


def test_fixed_plan_matches_normalized_request_and_controls_artifact_paths(setup):
    project, install, adapter, spec = setup
    plan = adapter.plan(spec)
    assert plan.command[:6][1:] == ("-B", "-m", "photonic_workflow.cli", "lumerical", "run")
    assert plan.command[9:11] == ("--install-root", str(install.resolve()))
    assert plan.shell is False and plan.dry_run is True and plan.execution_verified is False
    assert plan.availability == AvailabilityStatus.UNVERIFIED
    assert len(plan.generated_files) == 1
    assert json.loads(plan.generated_files[0].content) == validate_request(spec.inputs["request"])
    assert plan.generated_files[0].path == project / "runs/planned/request.json"
    native = project / "runs/planned/native"
    assert {path.name for path in plan.expected_artifacts} >= {
        "receipt.json", "source_dataset.json", "raw.npz", "source-01.fsp", "source-02.fsp",
    }
    assert all(path.is_relative_to(native) for path in plan.expected_artifacts)
    assert "PYTHONPATH" in plan.environment_dict()
    public = plan.public_payload()
    assert public["execution_verified"] is False and public["working_directory"] == "<runtime-directory>"
    assert public["environment"]["PYTHONPATH"] == "<redacted>"
    assert str(project) not in json.dumps(public)
    assert not (project / "runs").exists()


@pytest.mark.parametrize("changes", [
    {"adapter": "comsol"}, {"operation": "fdtd-uniform"},
    {"inputs": {}}, {"inputs": {"request": {}, "threads": 2, "script": "untrusted"}},
    {"inputs": {"request": "untrusted.json", "threads": 2}},
    {"inputs": {"request": {"schema_version": "1.0", "operation": "fdtd-device", "parameters": {}},
                "threads": True}},
    {"inputs": {"request": {"schema_version": "1.0", "operation": "fdtd-device", "parameters": {}},
                "threads": 17}},
    {"timeout_s": 4}, {"timeout_s": 7201},
    {"worker_count": 2, "commercial_parallel_authorized": True},
])
def test_unknown_or_unsupported_runs_are_rejected_without_output(setup, changes):
    project, _, adapter, spec = setup
    # These internal replacements exercise adapter boundary validation; they are
    # not external contract readers and do not bypass persisted-version routing.
    candidate = spec.model_copy(update=changes)
    with pytest.raises(InvalidInputError):
        adapter.plan(candidate)
    assert not (project / "runs").exists()


def test_dry_run_false_and_nonrequest_objects_cannot_enable_execution(setup):
    project, _, adapter, spec = setup
    with pytest.raises(UnavailableCapabilityError, match="plan-only"):
        adapter.plan(spec.model_copy(update={"dry_run": False}))
    with pytest.raises(InvalidInputError):
        adapter.plan({"adapter": "lumerical"})
    assert not (project / "runs").exists()


def test_runtime_and_expected_artifacts_cannot_escape_controlled_project(setup):
    project, install, adapter, spec = setup
    with pytest.raises(SecurityViolationError):
        LumericalAdapter(project_root=project, install_root=install, runtime_directory=project.parent / "outside",
                         allowed_roots=[project, project.parent / "outside"])
    with pytest.raises(InvalidInputError, match="isolated"):
        LumericalAdapter(project_root=project, install_root=install, runtime_directory=project)
    with pytest.raises(SecurityViolationError):
        LumericalAdapter(project_root=project, install_root=project.parent / "outside-app",
                         runtime_directory=Path("runs/outside"))
    for artifacts in (["../../outside.log"], [str(project / "outside.log")]):
        with pytest.raises(SecurityViolationError):
            adapter.plan(spec.model_copy(update={"expected_artifacts": artifacts}))
    assert not (project / "runs").exists()


def test_existing_planned_files_are_not_overwritten(setup):
    project, _, adapter, spec = setup
    target = project / "runs/planned/request.json"
    target.parent.mkdir(parents=True)
    target.write_text("existing evidence")
    with pytest.raises(InvalidInputError, match="must be new"):
        adapter.plan(spec)
    assert target.read_text() == "existing evidence"
