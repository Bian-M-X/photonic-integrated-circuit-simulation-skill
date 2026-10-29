"""Paired-model protocol and comparison checks; fixtures do not execute solvers."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical import parity
from photonic_workflow.native_devices import native_request


@pytest.mark.parametrize("family,ports", [("straight", 2), ("directional-coupler", 4)])
def test_plan_uses_exact_shared_geometry_and_frequency_grid(family, ports):
    plan = parity.make_benchmark_plan(family)
    geometry, config = native_request(plan["comsol_request"])
    parameters = plan["lumerical_request"]["parameters"]
    assert len(geometry["ports"]) == ports
    assert geometry == parity.build_device_geometry(family, parameters["geometry_parameters"])
    frequency = np.linspace(299792458 / 1.6e-6, 299792458 / 1.5e-6, 5)
    assert config["wavelengths_nm"] == sorted((299792458e9 / frequency).tolist())
    assert config["export_fields"] is False
    assert plan["comparison"] == "complete selected-mode powers only"
    assert plan["will_execute"] is False and plan["physics_accepted"] is False


@pytest.mark.parametrize("value", [True, 0, -0.1, 0.201, float("inf"), float("nan"), "0.03"])
def test_invalid_budget_rejected_before_reading_receipts(value):
    with pytest.raises(InvalidInputError, match="power_tolerance"):
        parity.compare_solver_runs(None, None, power_tolerance=value)


def test_unsupported_family_rejected():
    with pytest.raises(InvalidInputError, match="supports straight"):
        parity.make_benchmark_plan("ring")


def fixture_data(tmp_path, monkeypatch):
    plan = parity.make_benchmark_plan("straight")
    geometry, config = native_request(plan["comsol_request"])
    waves = config["wavelengths_nm"]
    # Independent fixture: reciprocal lossy through-path with finite reflections.
    a = np.tile(np.array([[0.1j, 0.8 + 0.1j], [0.8 + 0.1j, -0.1j]]), (len(waves), 1, 1))
    pairs = np.stack([a.real, a.imag], axis=-1).tolist()
    ports = [item["name"] for item in geometry["ports"]]
    channels = [{"id": item["name"], "port": item["name"], "mode": "fundamental TM mode",
                 "incoming_direction": "+x" if item["side"] == "left" else "-x",
                 "reference_plane": f"x={item['center_um'][0] * 1e-6:.17g} m; native port E dataset"}
                for item in geometry["ports"]]
    comsol = {"result": {"family": "straight", "model_level": "2d-scalar-index-surrogate", "port_order": ports,
                         "wavelengths_nm": waves, "s_matrices": pairs},
              "geometry": geometry, "config": config,
              "planes": [("x", item["center_um"][0] * 1e-6) for item in geometry["ports"]],
              "receipt_sha256": "a" * 64}
    fdtd = {"request": plan["lumerical_request"], "data": {"model_level": "2d-scalar-index-surrogate",
             "port_order": ports.copy(), "wavelengths_nm": waves.copy(),
             "s_matrices": copy.deepcopy(pairs), "channels": channels},
            "root": tmp_path, "receipt_sha256": "b" * 64, "receipt": {"result": {"diagnostic_passed": True}}}
    (tmp_path / "geometry.json").write_text(json.dumps({"source": geometry}))
    monkeypatch.setattr(parity, "_load_comsol", lambda path: comsol)
    monkeypatch.setattr(parity, "load_device_run", lambda path: fdtd)
    return comsol, fdtd, a


def test_phase_gauge_change_does_not_become_complex_parity(tmp_path, monkeypatch):
    _, fdtd, matrix = fixture_data(tmp_path, monkeypatch)
    # Opposite native phase gauges can change complex entries while preserving powers.
    shifted = matrix * np.exp(1.2j)
    fdtd["data"]["s_matrices"] = np.stack([shifted.real, shifted.imag], axis=-1).tolist()
    result = parity.compare_solver_runs(tmp_path / "c.json", tmp_path / "f.json", power_tolerance=1e-8)
    assert result["power_agreement_passed"] is True
    assert result["max_absolute_power_change"] < 1e-15
    assert result["matrix_element_count"] == 20
    assert result["complex_phase_comparable"] is False
    assert result["transformations_applied"] == []
    assert result["physics_accepted"] is False


def test_negative_power_result_retained_without_rescaling(tmp_path, monkeypatch):
    _, fdtd, matrix = fixture_data(tmp_path, monkeypatch)
    changed = matrix.copy()
    changed[3, 1, 0] = 0.5
    fdtd["data"]["s_matrices"] = np.stack([changed.real, changed.imag], axis=-1).tolist()
    before = copy.deepcopy(fdtd["data"]["s_matrices"])
    result = parity.compare_solver_runs(tmp_path / "c.json", tmp_path / "f.json", power_tolerance=0.03)
    assert result["power_agreement_passed"] is False
    assert result["status"] == "outside_declared_power_tolerance"
    assert result["max_absolute_power_change"] == pytest.approx(0.40)
    assert result["per_wavelength_max_power_change"][3] == pytest.approx(0.40)
    assert fdtd["data"]["s_matrices"] == before


@pytest.mark.parametrize("change,error", [
    (lambda c, f: f["request"]["parameters"].update(model_dimension="3d"), "scalar-Ez"),
    (lambda c, f: f["request"]["parameters"].update(core_index=2.7), "materials"),
    (lambda c, f: f["request"]["parameters"].update(core_material_model={"model": "li-silicon-1980"}), "materials"),
    (lambda c, f: f["data"]["port_order"].reverse(), "port/source order"),
    (lambda c, f: f["data"]["wavelengths_nm"].__setitem__(2, 1550), "spectral grids"),
    (lambda c, f: f["data"]["channels"][0].update(incoming_direction="-x"), "plane/direction"),
    (lambda c, f: f["data"]["channels"][1].update(reference_plane="x=7e-6 m; native port E dataset"),
     "reference planes"),
    (lambda c, f: f["data"].update(s_matrices=[]), "complete finite"),
])
def test_mismatched_physics_or_axes_rejected(tmp_path, monkeypatch, change, error):
    comsol, fdtd, _ = fixture_data(tmp_path, monkeypatch)
    change(comsol, fdtd)
    with pytest.raises(InvalidInputError, match=error):
        parity.compare_solver_runs(tmp_path / "c.json", tmp_path / "f.json", power_tolerance=0.03)


def test_actual_comsol_port_records_required_and_bound_to_geometry():
    geometry, _ = native_request(parity.make_benchmark_plan("straight")["comsol_request"])
    console = "PIC PORT_GEOMETRY 1 2.4 0 0 -1.2 1.2\nPIC PORT_GEOMETRY 2 2.4 6 6 -1.2 1.2\n"
    assert parity._comsol_planes(console, geometry["ports"]) == [("x", 0), ("x", 6e-6)]
    for invalid in (console.splitlines()[0], console + console.splitlines()[0],
                    console.replace("2.4 6 6", "2.4 7 7"), console.replace("2.4 0 0", "2.4 nan 0"),
                    console.replace("0 0 -1.2 1.2", "0 0 -1.5 0.9"),
                    console.replace("0 0 -1.2 1.2", "0 0 -1.3 1.3")):
        with pytest.raises(InvalidInputError):
            parity._comsol_planes(invalid, geometry["ports"])


def test_native_float_quantized_transverse_bounds_do_not_relabel_a_port():
    geometry, _ = native_request(parity.make_benchmark_plan("directional-coupler")["comsol_request"])
    rows = []
    for index, port in enumerate(geometry["ports"], 1):
        x, center = port["center_um"]
        low, high = ((0.30000001192092896, 2.700000047683716) if center > 0
                     else (-2.700000047683716, -0.30000001192092896))
        rows.append(f"PIC PORT_GEOMETRY {index} 2.4 {x} {x} {low} {high}")
    planes = parity._comsol_planes("\n".join(rows), geometry["ports"])
    assert planes == [("x", 0), ("x", 0), ("x", 16e-6), ("x", 16e-6)]
    with pytest.raises(InvalidInputError, match="plane/window"):
        parity._comsol_planes("\n".join(rows).replace("0.30000001192092896", "0.3001"), geometry["ports"])
