"""Independent reduced-model physics oracles; these tests provide no native EM evidence."""

import csv
import io
import json

import numpy as np
import pytest

from photonic_workflow.circuits import AssemblyError, compose, validate_manifest, write_composition
from photonic_workflow.circuits.assembly import load_component_data
from photonic_workflow.device_models import evaluate_device, scattering_csv

WAVELENGTHS = [1500.0, 1550.0, 1600.0]


def evaluated(model, parameters, wavelengths=None):
    result = evaluate_device({
        "schema_version": "1.0",
        "model": model,
        "wavelengths_nm": wavelengths or WAVELENGTHS,
        "parameters": parameters,
    })
    encoded = np.asarray(result["s_matrices"], dtype=float)
    return result, encoded[..., 0] + 1j * encoded[..., 1]


def propagation(length, neff, loss, wavelength):
    # Integrate the scalar amplitude equation; dB/cm -> dB/um.
    generator = -loss * np.log(10) / 200000 - 2j * np.pi * neff / (wavelength / 1000)
    return np.exp(generator * length)


def dc_oracle(parameters, wavelength):
    hamiltonian = np.array([
        [2 * np.pi * parameters["neff_1"] / (wavelength / 1000), parameters["kappa_per_um"]],
        [parameters["kappa_per_um"], 2 * np.pi * parameters["neff_2"] / (wavelength / 1000)],
    ])
    eigenvalues, eigenvectors = np.linalg.eigh(hamiltonian)
    transfer = (eigenvectors * np.exp(-1j * eigenvalues * parameters["length_um"])) @ eigenvectors.T
    transfer *= abs(propagation(parameters["length_um"], 0, parameters["loss_db_per_cm"], wavelength))
    result = np.zeros((4, 4), dtype=complex)
    result[2:, :2] = transfer
    result[:2, 2:] = transfer.T
    return result


def ring_forward(kpowers, arcs):
    # Unknowns are incoming ring fields u1,u2. Solve each actual source,
    # without using a ring rational transfer formula.
    t1, t2 = np.sqrt(1 - np.asarray(kpowers))
    k1, k2 = np.sqrt(kpowers)
    p12, p21 = arcs
    equations = np.array([[1, -p21 * t2], [-p12 * t1, 1]], dtype=complex)
    transfer = np.zeros((2, 2), dtype=complex)
    for source in range(2):
        x1, x2 = np.eye(2)[source]
        incoming = np.linalg.solve(equations, [-1j * p21 * k2 * x2, -1j * p12 * k1 * x1])
        transfer[:, source] = [t1 * x1 - 1j * k1 * incoming[0], t2 * x2 - 1j * k2 * incoming[1]]
    return transfer


def ring_oracle(parameters, wavelength, adddrop):
    length = parameters["roundtrip_length_um"]
    loss = parameters["loss_db_per_cm"]
    neff = parameters["neff"]
    if not adddrop:
        p = propagation(length, neff, loss, wavelength)
        k = np.sqrt(parameters["coupling_power"])
        t = np.sqrt(1 - parameters["coupling_power"])
        result = np.zeros((2, 2), dtype=complex)
        for source in range(2):
            incoming = np.linalg.solve(np.array([[1, -p], [-t, 1]], dtype=complex), [0, -1j * k])
            result[1 - source, source] = t - 1j * k * incoming[0]
        return result
    fraction = parameters["arc_fraction"]
    p12 = propagation(length * fraction, neff, loss, wavelength)
    p21 = propagation(length * (1 - fraction), neff, loss, wavelength)
    powers = [parameters["coupling_power_1"], parameters["coupling_power_2"]]
    forward = ring_forward(powers, (p12, p21))
    backward = ring_forward(powers, (p21, p12))
    result = np.zeros((4, 4), dtype=complex)
    result[np.ix_([1, 3], [0, 2])] = forward
    result[np.ix_([0, 2], [1, 3])] = backward
    return result


def bragg_oracle(parameters, wavelength):
    # RK4 solves the constant first-order envelope ODE independently of
    # hyperbolic closed forms, including the stop-band edge.
    carrier = np.pi / parameters["period_um"]
    detuning = 2 * np.pi * parameters["neff"] / (wavelength / 1000) - carrier
    kappa = parameters["kappa_per_um"]
    generator = np.array([[-1j * detuning, -1j * kappa], [1j * kappa, 1j * detuning]])
    step = parameters["length_um"] / 1800
    transfer = np.eye(2, dtype=complex)
    for _ in range(1800):
        k1 = generator @ transfer
        k2 = generator @ (transfer + step * k1 / 2)
        k3 = generator @ (transfer + step * k2 / 2)
        k4 = generator @ (transfer + step * k3)
        transfer += step * (k1 + 2 * k2 + 2 * k3 + k4) / 6
    # Boundary-value solve in physical local-field gauges, for both sources.
    phase = np.exp(-1j * carrier * parameters["length_um"])
    result = np.zeros((2, 2), dtype=complex)
    for source in range(2):
        left_in, right_in = np.eye(2)[source]
        right_envelope = right_in * phase
        left_out = (right_envelope - transfer[1, 0] * left_in) / transfer[1, 1]
        right_out = phase * (transfer[0, 0] * left_in + transfer[0, 1] * left_out)
        result[:, source] = [left_out, right_out]
    return result


@pytest.mark.parametrize("loss", [0, 2.7])
def test_waveguide_loss_phase_and_group_delay(loss):
    parameters = {"length_um": 37.0, "neff": 2.4, "loss_db_per_cm": loss}
    _, matrices = evaluated("waveguide", parameters)
    for wavelength, matrix in zip(WAVELENGTHS, matrices, strict=True):
        p = propagation(37, 2.4, loss, wavelength)
        np.testing.assert_allclose(matrix, [[0, p], [p, 0]], atol=2e-13)
    wavelengths = [1549.99, 1550, 1550.01]
    _, fine = evaluated("waveguide", parameters, wavelengths)
    omega = 2 * np.pi * 299792458 / (np.asarray(wavelengths) * 1e-9)
    delay = -np.diff(np.unwrap(np.angle(fine[:, 1, 0]))) / np.diff(omega)
    np.testing.assert_allclose(delay, 37e-6 * 2.4 / 299792458, rtol=1e-6)


@pytest.mark.parametrize("mismatch", [0, 0.021, -0.034])
@pytest.mark.parametrize("loss", [0, 4.1])
def test_directional_coupler_independent_eigh(mismatch, loss):
    parameters = {"length_um": 19.3, "neff_1": 2.4, "neff_2": 2.4 + mismatch,
                  "kappa_per_um": 0.087, "loss_db_per_cm": loss}
    _, matrices = evaluated("directional-coupler", parameters)
    for wavelength, matrix in zip(WAVELENGTHS, matrices, strict=True):
        np.testing.assert_allclose(matrix, dc_oracle(parameters, wavelength), atol=9e-14)


@pytest.mark.parametrize("adddrop", [False, True])
@pytest.mark.parametrize("loss", [0, 8])
def test_rings_independent_feedback_all_sources(adddrop, loss):
    parameters = {"roundtrip_length_um": 27.3, "neff": 2.4, "loss_db_per_cm": loss}
    if adddrop:
        parameters.update(coupling_power_1=0.17, coupling_power_2=0.31, arc_fraction=0.23)
    else:
        parameters.update(coupling_power=0.17)
    _, matrices = evaluated("ring-adddrop" if adddrop else "ring-allpass", parameters)
    for wavelength, matrix in zip(WAVELENGTHS, matrices, strict=True):
        np.testing.assert_allclose(matrix, ring_oracle(parameters, wavelength, adddrop), atol=5e-13)


@pytest.mark.parametrize("detuning", [0, 0.06, -0.06, 0.19])
def test_bragg_independent_rk4_with_physical_carrier(detuning):
    wavelength = 1550.0
    neff = 2.4
    kappa = 0.06
    period = np.pi / (2 * np.pi * neff / 1.55 - detuning)
    parameters = {"length_um": 14.7, "neff": neff, "period_um": period, "kappa_per_um": kappa}
    _, matrices = evaluated("bragg-uniform", parameters, [wavelength])
    np.testing.assert_allclose(matrices[0], bragg_oracle(parameters, wavelength), atol=2e-11)


@pytest.mark.parametrize("length,kappa", [(0, 0.08), (19.2, 0)])
def test_bragg_zero_length_and_zero_coupling(length, kappa):
    parameters = {"length_um": length, "neff": 2.4, "period_um": 0.32, "kappa_per_um": kappa}
    _, matrices = evaluated("bragg-uniform", parameters)
    for wavelength, matrix in zip(WAVELENGTHS, matrices, strict=True):
        p = propagation(length, 2.4, 0, wavelength)
        np.testing.assert_allclose(matrix, [[0, p], [p, 0]], atol=3e-13)


CASES = [
    ("waveguide", {"length_um": 9, "neff": 2.4, "loss_db_per_cm": 0}),
    ("directional-coupler", {"length_um": 9, "neff_1": 2.4, "neff_2": 2.42,
                             "kappa_per_um": 0.13, "loss_db_per_cm": 0}),
    ("ring-allpass", {"roundtrip_length_um": 21, "neff": 2.4, "loss_db_per_cm": 0,
                     "coupling_power": 0.15}),
    ("ring-adddrop", {"roundtrip_length_um": 21, "neff": 2.4, "loss_db_per_cm": 0,
                     "coupling_power_1": 0.15, "coupling_power_2": 0.22, "arc_fraction": 0.19}),
    ("bragg-uniform", {"length_um": 21, "neff": 2.4, "period_um": 0.322, "kappa_per_um": 0.13}),
]


@pytest.mark.parametrize("model,parameters", CASES)
def test_every_lossless_model_reciprocity_and_unitarity(model, parameters):
    _, matrices = evaluated(model, parameters)
    for matrix in matrices:
        np.testing.assert_allclose(matrix, matrix.T, atol=1e-12)
        np.testing.assert_allclose(matrix.conj().T @ matrix, np.eye(len(matrix)), atol=1e-12)


@pytest.mark.parametrize("model,parameters", CASES[:-1])
def test_lossy_models_passive_and_reciprocal(model, parameters):
    _, matrices = evaluated(model, {**parameters, "loss_db_per_cm": 9})
    for matrix in matrices:
        np.testing.assert_allclose(matrix, matrix.T, atol=1e-12)
        assert np.linalg.svd(matrix, compute_uv=False)[0] <= 1 + 1e-12


def test_true_csv_roundtrip_and_two_segment_circuit(tmp_path):
    lengths = [17.2, 31.9]
    components = {}
    for index, length in enumerate(lengths):
        result, expected = evaluated("waveguide", {"length_um": length, "neff": 2.4, "loss_db_per_cm": 3})
        csv_text = scattering_csv(result)
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        assert len(rows) == len(WAVELENGTHS) * 4
        assert list(rows[0]) == ["wavelength_nm", "out_port", "in_port", "s_real", "s_imag"]
        (tmp_path / f"segment{index}.csv").write_text(csv_text, encoding="utf-8")
        components[f"segment{index}"] = {
            "ports": ["left", "right"],
            "port_modes": {"left": "TE0", "right": "TE0"},
            "model_level": "analytic", "reference_plane": "physical local endpoint",
            "sparameters": f"segment{index}.csv", "passive": True,
        }
        assert expected.shape == (3, 2, 2)
    manifest = {
        "schema_version": "1.0",
        "conventions": {"wavelength_unit": "nm", "sparameter_normalization": "power-wave",
                        "time_dependence": "exp(+iwt)"},
        "components": components,
        "instances": {"a": {"component": "segment0"}, "b": {"component": "segment1"}},
        "connections": [["a:right", "b:left"]],
        "external_ports": {"left": "a:left", "right": "b:right"},
    }
    path = tmp_path / "assembly.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, data = validate_manifest(path, project_root=tmp_path)
    composed, summary = compose(loaded, data)
    assert summary["wavelength_count"] == 3
    for row in composed:
        actual = complex(float(row["s_real"]), float(row["s_imag"]))
        expected_value = 0 if row["out_port"] == row["in_port"] else propagation(
            sum(lengths), 2.4, 3, float(row["wavelength_nm"]))
        np.testing.assert_allclose(actual, expected_value, atol=2e-13)
    # Existing circuit writer exports a sixth derived power column. Reimport
    # the actual composition, preserving the authoritative complex amplitudes.
    export_path = tmp_path / "composed.csv"
    write_composition(export_path, composed)
    exported_component = {
        **components["segment0"], "sparameters": "composed.csv",
    }
    reloaded = load_component_data(path, "composed", exported_component, project_root=tmp_path)
    for wavelength in WAVELENGTHS:
        p = propagation(sum(lengths), 2.4, 3, wavelength)
        np.testing.assert_allclose(reloaded.matrices[wavelength], [[0, p], [p, 0]], atol=2e-13)
    for invalid_power in ("nan", "inf", "999"):
        corrupt_rows = [dict(row) for row in composed]
        corrupt_rows[0]["power"] = invalid_power
        write_composition(export_path, corrupt_rows)
        with pytest.raises(AssemblyError):
            load_component_data(path, "composed", exported_component, project_root=tmp_path)
    with export_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*composed[0], "unknown_column"])
        writer.writeheader()
        writer.writerows([{**row, "unknown_column": "0"} for row in composed])
    with pytest.raises(AssemblyError):
        load_component_data(path, "composed", exported_component, project_root=tmp_path)


def test_zero_hamiltonian_coupler_continuous_limit():
    parameters = {"length_um": 12.1, "neff_1": 2.4, "neff_2": 2.4,
                  "kappa_per_um": 0, "loss_db_per_cm": 0}
    _, matrices = evaluated("directional-coupler", parameters)
    for wavelength, matrix in zip(WAVELENGTHS, matrices, strict=True):
        np.testing.assert_allclose(matrix, dc_oracle(parameters, wavelength), atol=1e-13)


@pytest.mark.parametrize("adddrop", [False, True])
def test_high_finesse_ring_against_feedback(adddrop):
    parameters = {"roundtrip_length_um": 31, "neff": 2.4, "loss_db_per_cm": 0}
    if adddrop:
        parameters.update(coupling_power_1=2e-5, coupling_power_2=3e-5, arc_fraction=0.31)
    else:
        parameters.update(coupling_power=2e-5)
    wavelengths = [1550 - 1e-6, 1550, 1550 + 1e-6]
    _, matrices = evaluated("ring-adddrop" if adddrop else "ring-allpass", parameters, wavelengths)
    for wavelength, matrix in zip(wavelengths, matrices, strict=True):
        np.testing.assert_allclose(matrix, ring_oracle(parameters, wavelength, adddrop), atol=5e-10)
        np.testing.assert_allclose(matrix.conj().T @ matrix, np.eye(len(matrix)), atol=5e-10)


@pytest.mark.parametrize("adddrop", [False, True])
def test_ring_critical_through_cancellation(adddrop):
    parameters = {"roundtrip_length_um": 31, "neff": 2.4, "loss_db_per_cm": 1000}
    amplitude = abs(propagation(31, 2.4, 1000, 1550))
    if adddrop:
        parameters.update(coupling_power_1=1 - 0.8 * amplitude**2,
                          coupling_power_2=0.2, arc_fraction=0.27)
    else:
        parameters.update(coupling_power=1 - amplitude**2)
    _, matrices = evaluated("ring-adddrop" if adddrop else "ring-allpass", parameters, [1550])
    np.testing.assert_allclose(matrices[0], ring_oracle(parameters, 1550, adddrop), atol=3e-13)
    assert abs(matrices[0, 1, 0]) < 3e-13


def test_bragg_strong_stopband_stays_finite_and_passive():
    parameters = {"length_um": 20000, "neff": 2.4, "period_um": 1.55 / 4.8, "kappa_per_um": 0.1}
    _, matrices = evaluated("bragg-uniform", parameters, [1550])
    assert np.isfinite(matrices).all()
    assert abs(matrices[0, 1, 0]) < 1e-100
    np.testing.assert_allclose(abs(matrices[0, 0, 0]), 1, atol=2e-12)
    np.testing.assert_allclose(matrices[0].conj().T @ matrices[0], np.eye(2), atol=2e-12)


def test_unbalanced_mzi_true_csv_assembly_and_six_column_reload(tmp_path):
    coupler_parameters = {"length_um": 5, "neff_1": 2.4, "neff_2": 2.4,
                          "kappa_per_um": np.pi / 20, "loss_db_per_cm": 0}
    components = {}
    models = [("dc", "directional-coupler", coupler_parameters)]
    for name, length in [("upper", 17.2), ("lower", 22.9)]:
        models.append((name, "waveguide", {"length_um": length, "neff": 2.4, "loss_db_per_cm": 3}))
    for name, model, parameters in models:
        result, _ = evaluated(model, parameters)
        ports = result["port_order"]
        (tmp_path / f"{name}.csv").write_text(scattering_csv(result), encoding="utf-8")
        components[name] = {
            "ports": ports, "port_modes": dict.fromkeys(ports, "TE0"),
            "model_level": "analytic", "reference_plane": "physical local endpoint",
            "sparameters": f"{name}.csv", "passive": True,
        }
    external_ports = {"in_upper": "first:upper_left", "in_lower": "first:lower_left",
                      "out_upper": "second:upper_right", "out_lower": "second:lower_right"}
    manifest = {
        "schema_version": "1.0",
        "conventions": {"wavelength_unit": "nm", "sparameter_normalization": "power-wave",
                        "time_dependence": "exp(+iwt)"},
        "components": components,
        "instances": {"first": {"component": "dc"}, "second": {"component": "dc"},
                      "upper": {"component": "upper"}, "lower": {"component": "lower"}},
        "connections": [["first:upper_right", "upper:left"], ["first:lower_right", "lower:left"],
                        ["upper:right", "second:upper_left"], ["lower:right", "second:lower_left"]],
        "external_ports": external_ports,
    }
    path = tmp_path / "mzi.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, data = validate_manifest(path, project_root=tmp_path)
    rows, summary = compose(loaded, data)
    assert summary["instance_count"] == 4
    write_composition(tmp_path / "mzi.csv", rows)
    ports = list(external_ports)
    exported = {"ports": ports, "port_modes": dict.fromkeys(ports, "TE0"),
                "model_level": "analytic", "reference_plane": "external physical local endpoints",
                "sparameters": "mzi.csv", "passive": True}
    reloaded = load_component_data(path, "mzi", exported, project_root=tmp_path)
    for wavelength in WAVELENGTHS:
        coupler = dc_oracle(coupler_parameters, wavelength)[2:, :2]
        arms = np.diag([propagation(17.2, 2.4, 3, wavelength), propagation(22.9, 2.4, 3, wavelength)])
        forward = coupler @ arms @ coupler
        expected = np.zeros((4, 4), dtype=complex)
        expected[2:, :2] = forward
        expected[:2, 2:] = forward.T
        np.testing.assert_allclose(reloaded.matrices[wavelength], expected, atol=2e-13)
