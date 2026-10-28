"""Independent ideal-MMI channel oracles; no geometry or native EM acceptance."""

import csv
import io
import json

import numpy as np
import pytest

from photonic_workflow.circuits import compose, validate_manifest, write_composition
from photonic_workflow.circuits.assembly import load_component_data
from photonic_workflow.device_models import evaluate_device, scattering_csv
from photonic_workflow.diagnostics import scattering_audit

WAVELENGTHS = [1500.0, 1550.0, 1600.0]
PORTS = ["upper_left", "lower_left", "upper_right", "lower_right"]


def evaluate(k=0.5, loss=0.0, phase=0.0):
    result = evaluate_device({
        "schema_version": "1.0", "model": "mmi2x2-ideal",
        "wavelengths_nm": WAVELENGTHS,
        "parameters": {"coupling_power": k, "excess_loss_db": loss, "phase_rad": phase},
    })
    pairs = np.asarray(result["s_matrices"], dtype=float)
    return result, pairs[..., 0] + 1j * pairs[..., 1]


def channel_oracle(k, loss, phase):
    # Work in even/odd orthonormal channels, not the implementation's
    # square-root through/cross formula. Their relative phases are +/-theta.
    even = np.array([1.0, 1.0]) / np.sqrt(2)
    odd = np.array([1.0, -1.0]) / np.sqrt(2)
    theta = np.arcsin(np.sqrt(k))
    forward = (np.exp(-1j * theta) * np.outer(even, even)
               + np.exp(1j * theta) * np.outer(odd, odd))
    forward *= np.exp(-loss * np.log(10) / 20 - 1j * phase)
    # Send every left/right source separately. Reciprocity pairs the
    # reverse coefficient with the same forward coefficient, without conjugacy.
    result = np.zeros((4, 4), dtype=complex)
    for source in range(2):
        result[2:, source] = forward @ np.eye(2)[:, source]
        result[:2, source + 2] = forward.T @ np.eye(2)[:, source]
    return result


def audit(matrix, *, lossless=True):
    sources = {port: f"source-{index}" for index, port in enumerate(PORTS)}
    return scattering_audit({
        "channels": PORTS, "source_map": sources, "wavelength_nm": 1550.0,
        "tolerance": 1e-12,
        "assumptions": {"passive": True, "reciprocal": True, "lossless": lossless,
                        "complete_channels": True, "power_orthonormal": True,
                        "source_independent_basis": True, "reciprocity_paired_basis": True,
                        "evidence": ["analytic even/odd orthonormal-channel construction (unit fixture)"]},
        "columns": [{"input_channel": port, "source_id": sources[port],
                     "model_id": "ideal-mmi-fixture", "basis_id": "fixed-local-power-wave",
                     "dataset_id": "one-matrix", "wavelength_nm": 1550.0,
                     "values": [[float(z.real), float(z.imag)] for z in matrix[:, index]]}
                    for index, port in reversed(list(enumerate(PORTS)))],
    })


@pytest.mark.parametrize("k", [0.0, 0.17, 0.5, 1.0])
@pytest.mark.parametrize("loss", [0.0, 2.7, 20.0])
@pytest.mark.parametrize("phase", [-0.73, 0.0, 0.91])
def test_all_four_complex_columns_against_even_odd_channels(k, loss, phase):
    _, matrices = evaluate(k, loss, phase)
    eta = 10 ** (-loss / 10)
    expected = channel_oracle(k, loss, phase)
    assert matrices.shape == (3, 4, 4)
    for matrix in matrices:
        np.testing.assert_allclose(matrix, expected, rtol=2e-14, atol=8e-16)
        np.testing.assert_allclose(matrix, matrix.T, atol=8e-16)
        np.testing.assert_allclose(matrix.conj().T @ matrix, eta * np.eye(4), atol=8e-16)
        np.testing.assert_allclose(np.sum(abs(matrix) ** 2, axis=0), eta, atol=8e-16)
        assert np.linalg.svd(matrix, compute_uv=False)[0] <= 1 + 1e-14


def test_frozen_port_phase_scope_and_complete_complex_csv():
    result, matrices = evaluate(0.17, 2.7, -0.73)
    assert result["port_order"] == PORTS
    assert result["wavelengths_nm"] == WAVELENGTHS
    assert result["model_version"] == "1.0.0"
    assert result["model_level"] == "analytic"
    assert result["physics_accepted"] is False
    assert result["will_execute"] is False
    # Constant parameters do not manufacture wavelength dispersion.
    np.testing.assert_array_equal(matrices[0], matrices[1])
    np.testing.assert_array_equal(matrices[1], matrices[2])
    rows = list(csv.DictReader(io.StringIO(scattering_csv(result))))
    assert len(rows) == 16 * len(WAVELENGTHS)
    assert list(rows[0]) == ["wavelength_nm", "out_port", "in_port", "s_real", "s_imag"]
    lookup = {(float(row["wavelength_nm"]), row["out_port"], row["in_port"]):
              complex(float(row["s_real"]), float(row["s_imag"])) for row in rows}
    assert len(lookup) == len(rows)
    for wavelength in WAVELENGTHS:
        for i, out_port in enumerate(PORTS):
            for j, in_port in enumerate(PORTS):
                assert lookup[wavelength, out_port, in_port] == matrices[0, i, j]


@pytest.mark.parametrize("input_phase", [0.0, np.pi / 2, -np.pi / 2])
def test_coherent_two_input_interference_requires_quadrature_phase(input_phase):
    _, matrices = evaluate()
    incoming = np.array([1, np.exp(1j * input_phase), 0, 0]) / np.sqrt(2)
    for matrix in matrices:
        outgoing = matrix @ incoming
        expected_powers = [(1 + np.sin(input_phase)) / 2, (1 - np.sin(input_phase)) / 2]
        np.testing.assert_allclose(abs(outgoing[2:]) ** 2, expected_powers, atol=8e-16)
        np.testing.assert_allclose(np.vdot(outgoing, outgoing), 1.0, atol=8e-16)


@pytest.mark.parametrize("arm_phase", [0.0, np.pi / 2, np.pi])
@pytest.mark.parametrize("mmi_phase", [0.0, -0.37])
@pytest.mark.parametrize("loss", [0.0, 2.3])
def test_real_loader_two_mmi_interferometer_all_complex_ports(tmp_path, arm_phase, mmi_phase, loss):
    mmi_result, _ = evaluate(loss=loss, phase=mmi_phase)
    models = {"mmi": mmi_result}
    # Lower-arm length gives arm_phase at 1550 nm. Other wavelengths retain
    # the actual waveguide phase rather than silently treating it as constant.
    lower_length = arm_phase * 1.55 / (2 * np.pi * 2.4)
    for name, length in [("upper", 0.0), ("lower", float(lower_length))]:
        models[name] = evaluate_device({
            "schema_version": "1.0", "model": "waveguide", "wavelengths_nm": WAVELENGTHS,
            "parameters": {"length_um": length, "neff": 2.4, "loss_db_per_cm": 0.0},
        })
    components = {}
    for name, result in models.items():
        (tmp_path / f"{name}.csv").write_text(scattering_csv(result), encoding="utf-8")
        ports = result["port_order"]
        components[name] = {"ports": ports, "port_modes": dict.fromkeys(ports, "TE0"),
                            "model_level": "analytic", "reference_plane": "local physical endpoint",
                            "sparameters": f"{name}.csv", "passive": True}
    external_ports = {"upper_left": "first:upper_left", "lower_left": "first:lower_left",
                      "upper_right": "second:upper_right", "lower_right": "second:lower_right"}
    manifest = {
        "schema_version": "1.0",
        "conventions": {"wavelength_unit": "nm", "sparameter_normalization": "power-wave",
                        "time_dependence": "exp(+iwt)"},
        "components": components,
        "instances": {"first": {"component": "mmi"}, "second": {"component": "mmi"},
                      "upper": {"component": "upper"}, "lower": {"component": "lower"}},
        "connections": [["first:upper_right", "upper:left"], ["first:lower_right", "lower:left"],
                        ["upper:right", "second:upper_left"], ["lower:right", "second:lower_left"]],
        "external_ports": external_ports,
    }
    path = tmp_path / "mmi-interferometer.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, data = validate_manifest(path, project_root=tmp_path)
    rows, summary = compose(loaded, data)
    assert summary["instance_count"] == 4
    assert summary["wavelength_count"] == len(WAVELENGTHS)
    write_composition(tmp_path / "interferometer.csv", rows)
    reloaded = load_component_data(path, "interferometer", {
        "ports": PORTS, "port_modes": dict.fromkeys(PORTS, "TE0"), "model_level": "analytic",
        "reference_plane": "external local physical endpoints", "sparameters": "interferometer.csv",
        "passive": True,
    }, project_root=tmp_path)
    for wavelength in WAVELENGTHS:
        delta = arm_phase * 1550 / wavelength
        # Derived independently from constructive/destructive two-path sums.
        # At delta=0 the cascade swaps channels with amplitude -i*g^2.
        prefactor = -1j * np.exp(-1j * (2 * mmi_phase + delta / 2)) * 10 ** (-loss / 10)
        forward = prefactor * np.array([[-np.sin(delta / 2), np.cos(delta / 2)],
                                        [np.cos(delta / 2), np.sin(delta / 2)]])
        expected = np.zeros((4, 4), dtype=complex)
        expected[2:, :2], expected[:2, 2:] = forward, forward.T
        actual = reloaded.matrices[wavelength]
        np.testing.assert_allclose(actual, expected, atol=8e-16, rtol=2e-14)
        np.testing.assert_allclose(actual.conj().T @ actual,
                                   10 ** (-2 * loss / 10) * np.eye(4), atol=1e-15)


def test_real_positive_cross_mutant_keeps_split_but_fails_actual_passivity_audit():
    _, matrices = evaluate()
    correct = matrices[1]
    assert audit(correct)["status"] == "pass"
    mutant = abs(correct).astype(complex)
    np.testing.assert_allclose(abs(mutant) ** 2, abs(correct) ** 2, atol=0)
    incoming = np.array([1, 1, 0, 0]) / np.sqrt(2)
    np.testing.assert_allclose(np.vdot(mutant @ incoming, mutant @ incoming), 2.0, atol=8e-16)
    result = audit(mutant)
    assert result["checks"]["passivity"]["status"] == "fail"
    assert result["checks"]["unitarity"]["status"] == "fail"
    assert result["checks"]["reciprocity"]["status"] == "pass"
    np.testing.assert_allclose(result["raw_metrics"]["column_power"], 1.0, atol=8e-16)
    np.testing.assert_allclose(result["raw_metrics"]["sigma_max"], np.sqrt(2), atol=8e-16)
    assert result["physics_accepted"] is False


def test_twenty_db_equal_split_is_passive_but_cannot_pass_lossless_audit():
    _, matrices = evaluate(loss=20.0)
    matrix = matrices[1]
    np.testing.assert_allclose(abs(matrix[2:, 0]) ** 2, [0.005, 0.005], atol=1e-17)
    result = audit(matrix, lossless=False)
    assert result["checks"]["passivity"]["status"] == "pass"
    assert result["checks"]["unitarity"]["status"] == "not_applicable"
    np.testing.assert_allclose(result["raw_metrics"]["column_power"], 0.01, atol=1e-17)
    np.testing.assert_allclose(1 - np.asarray(result["raw_metrics"]["column_power"]), 0.99, atol=1e-16)
    assert audit(matrix, lossless=True)["checks"]["unitarity"]["status"] == "fail"
    assert result["physics_accepted"] is False
