"""Independent complex-column oracles and device request invariants; no vendor."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from numpy.testing import assert_allclose, assert_array_equal

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical.device import (
    _profile_overlap,
    _save_native_dataset,
    _selected_profile_fields,
    _single_mode_s,
    run_fdtd_device,
    validate_device_parameters,
)
from photonic_workflow.lumerical_exchange import normalize_lumerical_sparameters


class Session:
    def __init__(self, *, profile_phase=0.0, source_failure=None, source_power=1.0,
                 non_source_power=0.0, profile_axis_shift=0.0):
        self.objects = [{"name": "FDTD::ports", "kind": "group"}]
        self.current = None
        self.profile_phase = profile_phase
        self.source_failure = source_failure
        self.solved_sources = []
        self.counter = 0
        self.source_power = source_power
        self.non_source_power = non_source_power
        self.profile_axis_shift = profile_axis_shift

    def _add(self, kind):
        self.counter += 1
        self.current = {"name": f"object{self.counter}", "kind": kind}
        self.objects.append(self.current)

    def addrect(self):
        self._add("rect")

    def addpoly(self):
        self._add("poly")

    def addring(self):
        self._add("ring")

    def addfdtd(self):
        self._add("fdtd")
        self.current["name"] = "FDTD"

    def addport(self):
        self._add("port")

    def set(self, key, value):
        self.current[key] = value

    def select(self, name):
        self.current = next(item for item in self.objects if item["name"] == name)

    def setnamed(self, name, key, value):
        self.select(name)
        self.set(key, value)

    def getnamed(self, name, key):
        return next(item for item in self.objects if item["name"] == name)[key]

    def setglobalsource(self, key, value):
        pass

    def setglobalmonitor(self, key, value):
        pass

    def updateportmodes(self):
        pass

    def save(self, path):
        Path(path).write_bytes(b"synthetic-native-project")

    def load(self, path):
        source = self.getnamed("FDTD::ports", "source port")
        if source == self.source_failure:
            raise RuntimeError("synthetic engine output missing")
        self.solved_sources.append(source)

    def switchtolayout(self):
        pass

    def version(self):
        return "synthetic-vendor"

    def getresult(self, path, name):
        port_name = path.split("::")[-1]
        port = next(item for item in self.objects if item["name"] == port_name)
        source = self.getnamed("FDTD::ports", "source port")
        frequencies = np.array([299792458.0 / 1.6e-6, 299792458.0 / 1.5e-6])
        expected = {("left", "left"): 0.01 + 0.02j, ("right", "left"): 0.7 + 0.2j,
                    ("left", "right"): 0.3 - 0.4j, ("right", "right"): -0.01 + 0.03j}
        if name == "S":
            return {"f": frequencies[:, None], "S": np.full((2, 1), expected[port_name, source])}
        if name == "expansion for port monitor":
            sign = 1 if port_name == "left" else -1
            incoming = self.source_power if port_name == source else self.non_source_power
            return {"a": np.ones((2, 1), dtype=complex), "b": np.full((2, 1), 0.03j),
                    "N": np.ones((2, 1)), "P": np.ones((2, 1)), "f": frequencies,
                    "T_in": np.full((2, 1), sign * incoming)}
        if name == "E":
            return {"x": np.array([port["x"]]), "y": np.array([port["y"] - 1e-6, port["y"] + 1e-6]),
                    "z": np.array([0.0]), "f": frequencies, "E": np.ones((1, 2, 1, 2, 3), dtype=complex)}
        if name == "mode profiles":
            phase = self.profile_phase if source == "right" else 0.0
            axis_shift = self.profile_axis_shift if source == "right" else 0.0
            return {"E": np.ones((1, 2, 1, 2, 3), dtype=complex) * np.exp(1j * phase),
                    "H": np.ones((1, 2, 1, 2, 3), dtype=complex) * np.exp(1j * phase),
                    "x": np.array([port["x"]]), "y": np.array([-1e-6, 1e-6]) + axis_shift,
                    "z": np.array([0.0]), "f": frequencies}
        raise AssertionError(name)


def no_engine(monkeypatch):
    commands = []

    def run(command, **kwargs):
        assert command[1:3] == ["-t", "2"]
        assert kwargs["check"] and not kwargs.get("shell", False)
        commands.append(command)

    monkeypatch.setattr("photonic_workflow.lumerical.device.subprocess.run", run)
    return commands


def test_complete_columns_preserve_nonreciprocity_and_feed_existing_exchange(tmp_path, monkeypatch):
    commands = no_engine(monkeypatch)
    session = Session()
    result = run_fdtd_device(session, {"frequency_points": 2}, tmp_path, 2, Path("fdtd-engine.exe"))
    assert session.solved_sources == ["left", "right"]
    assert len(commands) == 2 and result["matrix_complete"]
    assert result["basis_consistent"]
    assert not result["diagnostic_checks"]["reciprocity_with_5pct_amplitude_budget"]
    dataset = json.loads((tmp_path / "source_dataset.json").read_text())
    normalized = normalize_lumerical_sparameters(dataset)
    matrix = np.array(normalized["s_matrices"])
    values = matrix[..., 0] + 1j * matrix[..., 1]
    assert_allclose(values[:, 1, 0], 0.7 + 0.2j)
    assert_allclose(values[:, 0, 1], 0.3 - 0.4j)
    assert_allclose(result["reflection_power_per_source"], [[0.0005, 0.001], [0.0005, 0.001]])
    assert len(result["source_columns"]) == 2
    with np.load(tmp_path / "raw.npz") as raw:
        assert raw["s_matrix"].shape == (2, 2, 2)
        assert "source2__port2__mode__H" in raw


def test_modal_sign_change_is_exposed_without_rewriting_raw_matrix(tmp_path, monkeypatch):
    no_engine(monkeypatch)
    result = run_fdtd_device(Session(profile_phase=np.pi), {"frequency_points": 2}, tmp_path, 2,
                             Path("fdtd-engine.exe"))
    assert not result["basis_consistent"]
    assert not result["diagnostic_checks"]["same_modal_basis_across_sources"]
    assert (tmp_path / "source_dataset.json").is_file()
    assert not result["physics_accepted"]


def test_mode_grid_change_and_incoming_contamination_fail_without_normalization(tmp_path, monkeypatch):
    no_engine(monkeypatch)
    result = run_fdtd_device(Session(source_power=0.8, non_source_power=0.02, profile_axis_shift=1e-9),
                             {"frequency_points": 2}, tmp_path, 2, Path("fdtd-engine.exe"))
    assert not result["basis_consistent"]
    assert not result["diagnostic_checks"]["source_incoming_power_within_5pct"]
    assert not result["diagnostic_checks"]["non_source_incoming_below_1e_3"]
    assert result["max_non_source_incoming_power"] == 0.02
    with np.load(tmp_path / "raw.npz") as raw:
        assert_allclose(raw["s_matrix"][:, 1, 0], 0.7 + 0.2j)
        assert_allclose(raw["direction_adjusted_incoming_power"][:, 0, 0], 0.8)


def test_partial_solve_failure_retains_first_column_and_never_exports_incomplete_matrix(tmp_path, monkeypatch):
    no_engine(monkeypatch)
    with pytest.raises(RuntimeError):
        run_fdtd_device(Session(source_failure="right"), {"frequency_points": 2}, tmp_path, 2,
                        Path("fdtd-engine.exe"))
    assert (tmp_path / "source-01-raw.npz").is_file()
    assert not (tmp_path / "source_dataset.json").exists()


@pytest.mark.parametrize("parameters", [
    {"mode_selection": "arbitrary"}, {"model_dimension": "2d", "mode_selection": "fundamental TE mode"},
    {"geometry_parameters": {"width_um": 0.8}}, {"core_index": 1.2},
    {"frequency_points": True}, {"simulation_time_s": float("nan")}, {"arbitrary_script": "run"},
    {"model_dimension": []}, {"mode_selection": {}},
])
def test_invalid_requests_fail_before_vendor_launch(parameters):
    with pytest.raises(InvalidInputError):
        validate_device_parameters(parameters)


def test_native_s_axis_contract_rejects_transposed_or_multiple_mode_arrays():
    with pytest.raises(ValueError):
        _single_mode_s({"f": [1, 2], "S": np.ones((1, 2))})
    with pytest.raises(ValueError):
        _single_mode_s({"f": [1, 2], "S": np.ones((2, 2))})
    frequency, values = _single_mode_s({"f": [1, 2], "S": np.array([[0.1j], [0.2j]])})
    assert_array_equal(frequency, [1, 2])
    assert_array_equal(values, [0.1j, 0.2j])


def test_overlap_does_not_treat_sign_or_grid_changes_as_the_same_basis():
    field = np.array([1 + 1j, 2 - 1j])
    assert _profile_overlap(field, field)["same_basis"]
    assert not _profile_overlap(field, -field)["same_basis"]
    assert not _profile_overlap(field, field * 2)["same_basis"]
    assert not _profile_overlap(field, field[:1])["same_basis"]


def test_ragged_vendor_metadata_retains_labels_without_object_arrays():
    arrays = {}
    metadata = _save_native_dataset(arrays, "port1__", {
        "E": np.ones((2, 3), dtype=complex),
        "Lumerical_dataset": {"parameters": [["lambda", "f"], ["n"]], "attributes": ["E", "H"]},
    })
    assert arrays["port1__E"].shape == (2, 3)
    assert all(array.dtype.kind != "O" for array in arrays.values())
    assert metadata["Lumerical_dataset"]["parameters"] == [["lambda", "f"], ["n"]]
    assert metadata["E"]["npz_key"] == "port1__E"


def test_selected_native_mode_profile_attributes_are_bound_to_explicit_mode_id():
    field = np.ones((1, 2, 1, 3), dtype=complex)
    fields, labels = _selected_profile_fields({"E2": field, "H2": field * 0.2}, {"n": [2]})
    assert labels == {"E": "E2", "H": "H2"}
    assert_array_equal(fields["E"], field)
    with pytest.raises(ValueError):
        _selected_profile_fields({"E2": field, "H2": field}, {"n": [1]})
    with pytest.raises(ValueError):
        _selected_profile_fields({"E1": field, "H1": field, "E2": field, "H2": field}, {})


def test_sampled_recipe_is_assigned_and_bad_native_fit_fails_diagnostic(tmp_path, monkeypatch):
    no_engine(monkeypatch)

    def fitted(session, name, samples):
        return {"material_name": name, "source_samples": samples,
                "max_index_fit_error": 0.02, "fitted_minimum_extinction": 0.0}

    monkeypatch.setattr("photonic_workflow.lumerical.materials.apply_sampled_material", fitted)
    result = run_fdtd_device(Session(), {
        "frequency_points": 2, "geometry_parameters": {"width_um": 0.2},
        "core_material_model": {"model": "li-silicon-1980"},
        "clad_material_model": {"model": "malitson-fused-silica-1965"},
    }, tmp_path, 2, Path("fdtd-engine.exe"))
    assert result["sampled_materials"]["core"]["assignments_match"]
    assert result["sampled_materials"]["clad"]["assignments"] == {"FDTD background": "shared_clad_material"}
    assert not result["diagnostic_checks"]["sampled_material_fit_and_assignment"]
    assert not result["diagnostic_passed"]
