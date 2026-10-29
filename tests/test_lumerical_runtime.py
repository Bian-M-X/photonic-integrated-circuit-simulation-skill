"""Offline interface/physics-oracle tests; these do not claim licensed execution."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError, UnavailableCapabilityError
from photonic_workflow.lumerical import discover_install, plan_run, run_request, validate_request
from photonic_workflow.lumerical.runtime import _supervise
from photonic_workflow.lumerical.worker import _failure, _fdtd, _geometry, _mode


def request(operation="mode-waveguide", **parameters):
    return {"schema_version": "1.0", "operation": operation, "parameters": parameters}


def fake_install(root: Path):
    (root / "api/python").mkdir(parents=True)
    (root / "api/python/lumapi.py").write_text("raise AssertionError('Discovery imported vendor API')")
    (root / "bin").mkdir()
    (root / "bin/mode-solutions.exe").touch()
    (root / "bin/fdtd-solutions.exe").touch()
    (root / "bin/fdtd-engine.exe").touch()
    (root / "VERSION").write_text("MAJORRELEASE=2026R1\nBUILDNUMBER=4413\n")


def test_discovery_parent_version_product_and_no_import(tmp_path):
    root = tmp_path / "vendor"
    product = root / "v261/Lumerical"
    fake_install(product)
    for path in (root, root / "v261", product):
        found = discover_install(path)
        assert found["available"]
        assert Path(found["product_root"]) == product
        assert found["products_present"]["MODE"]
        assert not found["license_checked"] and not found["api_imported"]


def test_discovery_selects_latest_version_and_explicit_env(tmp_path, monkeypatch):
    fake_install(tmp_path / "v99/Lumerical")
    fake_install(tmp_path / "v261/Lumerical")
    monkeypatch.setenv("PHOTONIC_LUMERICAL_ROOT", str(tmp_path))
    before = dict(os.environ)
    found = discover_install()
    assert "v261" in found["product_root"]
    assert before == dict(os.environ)


@pytest.mark.parametrize(
    "parameters",
    [
        {"mesh_cells": True},
        {"mesh_cells": 40.5},
        {"width_m": float("nan")},
        {"core_index": 1.2},
        {"width_m": 4e-6},
        {"script": "run;"},
    ],
)
def test_strict_request_rejects_unsupported_or_nonphysical_values(parameters):
    with pytest.raises(InvalidInputError):
        validate_request(request(**parameters))


def test_plan_normalizes_without_vendor_or_solver(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a: pytest.fail("Unexpected vendor import"))
    plan = plan_run(request(), install_root=tmp_path)
    assert not plan["install"]["available"]
    assert not plan["execution"] and not plan["physics_accepted"]
    assert plan["request"]["parameters"]["mesh_cells"] == 100
    assert plan["product"] == "MODE"


def test_run_refuses_missing_product_and_existing_output_before_execution(tmp_path):
    with pytest.raises(UnavailableCapabilityError):
        run_request(request(), tmp_path / "new", install_root=tmp_path / "missing")
    product = tmp_path / "installed"
    fake_install(product)
    with pytest.raises(InvalidInputError, match="must be new"):
        run_request(request(), tmp_path, install_root=product)


class Session:
    """Small independent data-producing fake; no vendor or script evaluator."""

    def __init__(self, phase_offset=0.0, power=1.0, material_index_offset=0.0, monitor_offsets=(0.0, 0.0)):
        self.objects = []
        self.phase_offset = phase_offset
        self.power = power
        self.material_index_offset = material_index_offset
        self.monitor_offsets = monitor_offsets
        self.ran = False

    def addrect(self):
        self.objects.append({"kind": "rect"})

    def addpoly(self):
        self.objects.append({"kind": "poly"})

    def addfde(self):
        self.objects.append({"kind": "fde"})

    def addfdtd(self):
        self.objects.append({"kind": "fdtd"})

    def addplane(self):
        self.objects.append({"kind": "plane"})

    def addpower(self):
        self.objects.append({"kind": "power"})

    def set(self, name, value):
        self.objects[-1][name] = value

    def setanalysis(self, name, value):
        self.objects[-1][name] = value

    def getnamed(self, name, prop):
        value = next(obj for obj in self.objects if obj.get("name") == name)[prop]
        return value + self.material_index_offset if prop == "index" else value

    def save(self, path):
        Path(path).write_bytes(b"offline-fake-model")

    def findmodes(self):
        return 1

    def getdata(self, mode, field):
        if field == "neff":
            return np.array([[2.45 + 1e-10j]])
        if field == "TE polarization fraction":
            return np.array([[0.98]])
        return np.ones((2, 3, 1), dtype=complex)

    def load(self, path):
        assert Path(path).is_file()
        self.ran = True

    def getresult(self, name, field):
        assert self.ran and field == "E"
        probe = next(obj for obj in self.objects if obj.get("name") == name)
        fdtd = next(obj for obj in self.objects if obj["kind"] == "fdtd")
        frequency = np.array([299792458.0 / 1.5e-6, 299792458.0 / 1.6e-6])
        actual_x = probe["x"] + self.monitor_offsets[int(name[-1]) - 1]
        phase = 2 * np.pi * frequency / 299792458.0 * fdtd["background index"] * actual_x
        if name == "probe2":
            phase = phase + self.phase_offset
        electric = np.zeros((1, 3, 1, 2, 3), dtype=complex)
        electric[..., 1] = np.exp(1j * phase)
        return {
            "E": electric,
            "f": frequency,
            "x": np.array([actual_x]),
            "y": np.linspace(-0.5e-6, 0.5e-6, 3),
            "z": np.array([0.0]),
        }

    def transmission(self, name):
        return np.array([self.power, self.power])


def test_mode_offline_diagnostic_raw_complex_data_and_material_readback(tmp_path):
    result = _mode(Session(), validate_request(request())["parameters"], tmp_path)
    assert result["diagnostic_passed"]
    assert result["modes"][0]["neff_real"] == 2.45
    with np.load(tmp_path / "raw.npz") as raw:
        assert np.iscomplexobj(raw["mode1_neff"])
        assert "mode1_Ey" in raw
    corrupted = tmp_path / "wrong-material"
    corrupted.mkdir()
    result = _mode(Session(material_index_offset=0.2), validate_request(request())["parameters"], corrupted)
    assert not result["diagnostic_checks"]["material_index_readback"]


def test_fdtd_offline_oracle_accepts_expected_phase_and_detects_errors(tmp_path, monkeypatch):
    def run_engine(command, **kwargs):
        assert command[1:3] == ["-t", "2"]
        assert kwargs["check"] and not kwargs.get("shell")

    monkeypatch.setattr("photonic_workflow.lumerical.worker.subprocess.run", run_engine)
    p = validate_request(request("fdtd-uniform"))["parameters"]
    result = _fdtd(Session(), p, tmp_path, 2, Path("fdtd-engine.exe"))
    assert result["diagnostic_passed"]
    assert result["max_phase_error_rad"] < 1e-12
    bad = tmp_path / "bad"
    bad.mkdir()
    result = _fdtd(Session(phase_offset=0.5, power=0.8), p, bad, 2, Path("fdtd-engine.exe"))
    assert not result["diagnostic_passed"]
    assert not result["diagnostic_checks"]["phase_error_below_0p15rad"]
    assert not result["diagnostic_checks"]["power_error_below_5pct"]


def test_fdtd_phase_uses_sampled_mesh_reference_planes_and_preserves_requested(tmp_path, monkeypatch):
    monkeypatch.setattr("photonic_workflow.lumerical.worker.subprocess.run", lambda *a, **k: None)
    p = validate_request(request("fdtd-uniform"))["parameters"]
    offsets = (-30e-9, 35e-9)
    result = _fdtd(Session(monitor_offsets=offsets), p, tmp_path, 2, Path("fdtd-engine.exe"))
    assert result["diagnostic_passed"]
    assert result["max_phase_error_rad"] < 1e-12
    assert np.allclose(result["monitor_displacements_m"], offsets, rtol=0.0, atol=1e-20)
    with np.load(tmp_path / "raw.npz") as raw:
        assert np.max(np.abs(raw["phase_error_requested_planes_rad"])) > 0.3
        assert np.array_equal(raw["sampled_probe_positions_m"], result["probe_positions_m"])
        assert "probe1_x" in raw and "probe2_y" in raw and "probe2_z" in raw
    bad = tmp_path / "bad-physical-phase"
    bad.mkdir()
    result = _fdtd(Session(monitor_offsets=offsets, phase_offset=0.5), p, bad, 2, Path("fdtd-engine.exe"))
    assert not result["diagnostic_checks"]["phase_error_below_0p15rad"]


@pytest.mark.parametrize("family", ["straight", "ybranch"])
def test_migrated_geometry_readback_rectangles_and_polygons(tmp_path, family):
    p = validate_request(
        request(
            "geometry-readback",
            native_request={
                "schema_version": "1.0",
                "family": family,
                "parameters": {},
            },
        )
    )["parameters"]
    session = Session()
    result = _geometry(session, p, tmp_path)
    assert result["diagnostic_passed"] and not result["solve_executed"]
    assert not session.ran
    bridge = json.loads((tmp_path / "geometry.json").read_text())
    assert len(result["object_readback"]) == len(bridge["objects"])
    assert all(obj["index_matches"] for obj in result["object_readback"])


def test_timeout_stops_owned_worker(tmp_path):
    pytest.importorskip("psutil")
    result = _supervise([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path, 0.2)
    assert result["timed_out"]
    assert result["owned_processes_exited"]
    assert result["exit_code"] != 0


def test_timeout_stops_descendant_and_preserves_unrelated_process(tmp_path):
    psutil = pytest.importorskip("psutil")
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    child_pid_file = tmp_path / "child.pid"
    code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    try:
        result = _supervise([sys.executable, "-c", code], tmp_path, 0.7)
        assert result["timed_out"] and result["owned_processes_exited"]
        assert child_pid_file.is_file()
        assert not psutil.pid_exists(int(child_pid_file.read_text()))
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)


def test_failed_worker_creates_inspectable_receipt(tmp_path):
    product = tmp_path / "vendor"
    fake_install(product)
    folder = tmp_path / "failure"
    receipt = run_request(request(), folder, install_root=product, timeout_s=10)
    assert receipt["status"] == "failed"
    assert not receipt["physics_accepted"]
    assert receipt["worker_launched"]
    assert not receipt["native_execution"] and not receipt["solve_invoked"]
    assert receipt["result"]["failure_category"] == "api_import_failed"
    assert receipt["artifacts"]["request.json"]["sha256"]
    assert (folder / "receipt.json").is_file()
    assert "AssertionError" in (folder / "worker.log").read_text()


def test_license_failure_has_explicit_stage_and_sanitized_availability():
    result = _failure(
        RuntimeError("Could not connect to Ansys license server 1055@private-host"),
        {
            "stage": "session-start",
            "api_imported": True,
            "session_opened": False,
            "solve_invoked": False,
            "solve_completed": False,
        },
    )
    assert result["failure_category"] == "license_unavailable"
    assert result["license_status"] == "unavailable"
    assert not result["session_opened"] and not result["solve_invoked"]
    assert "private-host" not in json.dumps(result)
    assert result["details_log"] == "worker.log"
