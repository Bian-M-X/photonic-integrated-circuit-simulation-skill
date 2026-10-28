"""Independent bright/dark-channel oracles, without native electromagnetic claims."""

import csv
import io
import json

import numpy as np
import pytest

from photonic_workflow.circuits import AssemblyError, compose, validate_manifest, write_composition
from photonic_workflow.circuits.assembly import load_component_data
from photonic_workflow.device_models import evaluate_device, scattering_csv
from photonic_workflow.diagnostics import phase_audit, scattering_audit

WAVELENGTHS = [1500.0, 1550.0, 1600.0]
PORTS = ["trunk", "upper", "lower"]


def channels(coupling):
    """Orthogonal *branch* channels; equal-weight parity only at k=1/2."""
    bright = np.sqrt([1 - coupling, coupling])
    dark = np.array([-bright[1], bright[0]])
    return bright, dark


def y_action(incident, coupling, loss=0, phase=0):
    # Change coordinates, swap trunk/bright amplitudes, reflect dark with -1,
    # then reconstruct. No entrywise implementation matrix is used here.
    bright, dark = channels(coupling)
    trunk = incident[0]
    branch_bright = bright @ incident[1:]
    branch_dark = dark @ incident[1:]
    outgoing = np.concatenate(([branch_bright], trunk * bright - branch_dark * dark))
    return np.exp(-loss * np.log(10) / 20 - 1j * phase) * outgoing


def oracle(coupling, loss=0, phase=0):
    return np.column_stack([y_action(source, coupling, loss, phase) for source in np.eye(3)])


def evaluate(coupling=0.5, loss=0, phase=0, wavelengths=None):
    result = evaluate_device({
        "schema_version": "1.0", "model": "ybranch-ideal",
        "wavelengths_nm": WAVELENGTHS if wavelengths is None else wavelengths,
        "parameters": {"coupling_power": coupling, "excess_loss_db": loss, "phase_rad": phase},
    })
    encoded = np.asarray(result["s_matrices"], dtype=float)
    return result, encoded[..., 0] + 1j * encoded[..., 1]


def scattering_check(matrix, *, lossless=True):
    """Use the real conditional auditor, declaring this analytic basis explicitly."""
    return scattering_audit({
        "channels": PORTS,
        "source_map": {port: f"source-{port}" for port in PORTS},
        "wavelength_nm": 1550.0, "tolerance": 1e-11,
        "assumptions": {
            "passive": True, "reciprocal": True, "lossless": lossless,
            "complete_channels": True, "power_orthonormal": True,
            "source_independent_basis": True, "reciprocity_paired_basis": True,
            "evidence": ["analytic-bright-dark-orthonormal-derivation"],
        },
        "columns": [{
            "input_channel": port, "source_id": f"source-{port}",
            "model_id": "same-analytic-Y", "basis_id": "fixed-power-wave-basis",
            "dataset_id": "analytic", "wavelength_nm": 1550.0,
            "values": [[float(z.real), float(z.imag)] for z in matrix[:, j]],
        } for j, port in enumerate(PORTS)],
    })


def compare_phase(reference, candidate):
    # Exclude structural zeros whose phases are undefined, retaining *all*
    # nonzero matrix entries including the reflected branch block.
    selected = np.abs(reference) > 1e-8
    return phase_audit({
        "reference": [[float(z.real), float(z.imag)] for z in reference[selected]],
        "candidate": [[float(z.real), float(z.imag)] for z in candidate[selected]],
        "amplitude_floor": 1e-8, "phase_tolerance_rad": 1e-10,
        "complex_tolerance": 1e-10, "policy_id": "Y-fixed-local-reference-planes-v1",
    })


@pytest.mark.parametrize("coupling", [0, 0.17, 0.5, 1])
@pytest.mark.parametrize("loss", [0, 2.7, 20])
@pytest.mark.parametrize("phase", [-0.73, 0, 0.41])
def test_all_complex_columns_from_independent_channel_action(coupling, loss, phase):
    result, matrices = evaluate(coupling, loss, phase)
    expected = oracle(coupling, loss, phase)
    assert result["port_order"] == PORTS
    assert result["model_level"] == "analytic"
    assert result["model_version"] == "1.0.0"
    assert result["physics_accepted"] is False and result["will_execute"] is False
    assert matrices.shape == (3, 3, 3)
    np.testing.assert_allclose(matrices, np.broadcast_to(expected, matrices.shape), atol=5e-15)
    for matrix in matrices:
        np.testing.assert_allclose(matrix, matrix.T, atol=1e-15)
        np.testing.assert_allclose(matrix.conj().T @ matrix,
                                   np.eye(3) * 10 ** (-loss / 10), atol=3e-15)
        np.testing.assert_allclose(np.sum(abs(matrix) ** 2, axis=0), 10 ** (-loss / 10), atol=3e-15)


@pytest.mark.parametrize("coupling", [0, 0.17, 0.5, 1])
def test_bright_trunk_exchange_and_dark_pi_reflection(coupling):
    _, matrices = evaluate(coupling, phase=0.37)
    bright, dark = channels(coupling)
    trunk = np.array([1, 0, 0])
    bright3 = np.concatenate(([0], bright))
    dark3 = np.concatenate(([0], dark))
    factor = np.exp(-0.37j)
    for matrix in matrices:
        np.testing.assert_allclose(matrix @ trunk, factor * bright3, atol=4e-15)
        np.testing.assert_allclose(matrix @ bright3, factor * trunk, atol=4e-15)
        np.testing.assert_allclose(matrix @ dark3, -factor * dark3, atol=4e-15)


@pytest.mark.parametrize("source", [1, 2])
def test_balanced_single_branch_has_half_quarter_quarter_power(source):
    _, matrices = evaluate()
    for matrix in matrices:
        np.testing.assert_allclose(abs(matrix[:, source]) ** 2, [.5, .25, .25], atol=2e-15)
        assert abs(matrix[source, source]) > 0.49
        assert matrix[0, 0] == 0


@pytest.mark.parametrize("coupling", [0.17, 0.5])
@pytest.mark.parametrize("relative_phase", [0, np.pi / 2, np.pi, -0.37])
def test_coherent_branch_combining_retains_relative_phase(coupling, relative_phase):
    _, matrices = evaluate(coupling, loss=2.7, phase=-0.23)
    bright, _ = channels(coupling)
    incident = np.array([0, 1, np.exp(1j * relative_phase)]) / np.sqrt(2)
    # Coherent scalar sum in the frozen branch gauges, not sum of powers.
    trunk_power = 10 ** (-2.7 / 10) * abs(bright @ incident[1:]) ** 2
    for matrix in matrices:
        actual = matrix @ incident
        np.testing.assert_allclose(actual, y_action(incident, coupling, 2.7, -0.23), atol=3e-15)
        assert abs(actual[0]) ** 2 == pytest.approx(trunk_power, abs=2e-15)
        assert np.vdot(actual, actual).real == pytest.approx(10 ** (-2.7 / 10), abs=3e-15)
    if coupling == .5 and relative_phase == np.pi:
        assert abs(actual[0]) < 2e-15
        assert np.linalg.norm(actual[1:]) > .7


def test_complete_csv_is_actually_reloaded_in_all_nine_pairs(tmp_path):
    result, matrices = evaluate(.17, 2.7, -.73)
    csv_text = scattering_csv(result)
    reader = csv.DictReader(io.StringIO(csv_text))
    assert reader.fieldnames == ["wavelength_nm", "out_port", "in_port", "s_real", "s_imag"]
    rows = list(reader)
    assert len(rows) == 27
    assert {(row["out_port"], row["in_port"]) for row in rows} == {(a, b) for a in PORTS for b in PORTS}
    (tmp_path / "y.csv").write_text(csv_text, encoding="utf-8")
    component = component_definition(PORTS, "y.csv")
    loaded = load_component_data(tmp_path / "assembly.json", "Y", component, project_root=tmp_path)
    assert loaded.ports == tuple(PORTS)
    for index, wavelength in enumerate(WAVELENGTHS):
        np.testing.assert_allclose(loaded.matrices[wavelength], matrices[index], atol=1e-15)
        np.testing.assert_allclose(loaded.matrices[wavelength], oracle(.17, 2.7, -.73), atol=3e-15)


@pytest.mark.parametrize("coupling", [0, .17, .5, 1])
@pytest.mark.parametrize("loss", [0, 20])
def test_real_scattering_diagnostic_accepts_only_applicable_losslessness(coupling, loss):
    _, matrices = evaluate(coupling, loss, .37)
    report = scattering_check(matrices[0], lossless=loss == 0)
    assert report["status"] == "pass"
    assert report["physics_accepted"] is False
    if loss:
        assert report["checks"]["unitarity"]["status"] == "not_applicable"
        rejected = scattering_check(matrices[0], lossless=True)
        assert rejected["checks"]["unitarity"]["status"] == "fail"


@pytest.mark.parametrize("deleted", ["entire_branch_block", "branch_diagonals"])
def test_deleted_reflections_are_rejected_by_real_scattering_diagnostic(deleted):
    _, matrices = evaluate()
    corrupted = matrices[0].copy()
    if deleted == "entire_branch_block":
        corrupted[1:, 1:] = 0
    else:
        corrupted[1, 1] = corrupted[2, 2] = 0
    # Trunk splitting and raw reciprocity survive both incorrect mutations.
    np.testing.assert_allclose(abs(corrupted[1:, 0]) ** 2, [.5, .5], atol=2e-15)
    np.testing.assert_allclose(corrupted, corrupted.T, atol=1e-15)
    report = scattering_check(corrupted)
    assert report["status"] == "fail"
    assert report["checks"]["unitarity"]["status"] == "fail"
    if deleted == "branch_diagonals":
        assert np.count_nonzero(np.diag(corrupted)) == 0
        assert report["checks"]["passivity"]["status"] == "fail"


def test_phase_drop_keeps_all_powers_but_real_phase_auditor_rejects():
    _, reference = evaluate(.17, phase=.73)
    _, dropped = evaluate(.17, phase=0)
    np.testing.assert_allclose(abs(reference) ** 2, abs(dropped) ** 2, atol=2e-15)
    assert scattering_check(dropped[0])["status"] == "pass"
    report = compare_phase(reference[0], dropped[0])
    assert report["status"] == "fail"
    assert report["checks"]["strict_phase"]["status"] == "fail"
    assert report["checks"]["absolute_complex"]["status"] == "fail"


def test_twenty_db_retains_split_ratio_but_only_one_percent_power():
    _, reference = evaluate(.17)
    _, attenuated = evaluate(.17, loss=20)
    ratio = abs(attenuated[0, 2, 0]) ** 2 / np.sum(abs(attenuated[0, 1:, 0]) ** 2)
    assert ratio == pytest.approx(.17)
    np.testing.assert_allclose(np.sum(abs(attenuated[0]) ** 2, axis=0), .01, atol=1e-16)
    assert scattering_check(attenuated[0], lossless=False)["status"] == "pass"
    assert scattering_check(attenuated[0])["checks"]["unitarity"]["status"] == "fail"
    assert compare_phase(reference[0], attenuated[0])["checks"]["absolute_complex"]["status"] == "fail"


def component_definition(ports, filename):
    return {"ports": ports, "port_modes": dict.fromkeys(ports, "TE0"),
            "model_level": "analytic", "reference_plane": "physical local endpoints",
            "sparameters": filename, "passive": True}


def propagation(length, loss, wavelength):
    return np.exp(-loss * np.log(10) * length / 200000 - 2j * np.pi * 2.4 * length / (wavelength / 1000))


def dark_feedback_oracle(left, right, arms):
    """Solve two dark-channel return amplitudes, not global S-block elimination.

    dL=vL.P.y, dR=vR.P.x; x=fL(tL*uL-dL*vL),
    y=fR(tR*uR-dR*vR). P propagates in *both* directions.
    """
    u_left, v_left = channels(left[0])
    u_right, v_right = channels(right[0])
    f_left = np.exp(-left[1] * np.log(10) / 20 - 1j * left[2])
    f_right = np.exp(-right[1] * np.log(10) / 20 - 1j * right[2])
    cross = v_left @ (arms * v_right)
    equations = np.array([[1, f_right * cross], [f_left * cross, 1]])
    result = np.zeros((2, 2), dtype=complex)
    for source in range(2):
        t_left, t_right = np.eye(2)[source]
        d_left, d_right = np.linalg.solve(equations, [
            f_right * t_right * (v_left @ (arms * u_right)),
            f_left * t_left * (v_right @ (arms * u_left)),
        ])
        x = f_left * (t_left * u_left - d_left * v_left)
        y = f_right * (t_right * u_right - d_right * v_right)
        result[:, source] = [f_left * (u_left @ (arms * y)), f_right * (u_right @ (arms * x))]
    return result, float(np.linalg.cond(equations))


def build_y_network(directory, left, right, lengths, arm_loss=0, wavelengths=None):
    wavelengths = WAVELENGTHS if wavelengths is None else wavelengths
    components = {}
    for name, parameters in [("first", left), ("second", right)]:
        result, _ = evaluate(*parameters, wavelengths=wavelengths)
        (directory / f"{name}.csv").write_text(scattering_csv(result), encoding="utf-8")
        components[name] = component_definition(PORTS, f"{name}.csv")
    for name, length in zip(["upper", "lower"], lengths, strict=True):
        result = evaluate_device({
            "schema_version": "1.0", "model": "waveguide", "wavelengths_nm": wavelengths,
            "parameters": {"length_um": length, "neff": 2.4, "loss_db_per_cm": arm_loss},
        })
        (directory / f"{name}.csv").write_text(scattering_csv(result), encoding="utf-8")
        components[name] = component_definition(["left", "right"], f"{name}.csv")
    manifest = {
        "schema_version": "1.0", "conventions": {
            "wavelength_unit": "nm", "sparameter_normalization": "power-wave", "time_dependence": "exp(+iwt)"},
        "components": components, "instances": {name: {"component": name} for name in components},
        "connections": [["first:upper", "upper:left"], ["first:lower", "lower:left"],
                        ["upper:right", "second:upper"], ["lower:right", "second:lower"]],
        "external_ports": {"left": "first:trunk", "right": "second:trunk"},
    }
    path = directory / "two_y.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, validate_manifest(path, project_root=directory)


@pytest.mark.parametrize("couplings", [(.5, .5), (.17, .63)])
@pytest.mark.parametrize("loss", [0, 2.7])
def test_true_csv_two_y_reflection_feedback_matches_dark_equations(tmp_path, couplings, loss):
    # Nonresonant phases are explicit. No added numerical damping is used.
    left, right = (couplings[0], loss, .21), (couplings[1], loss, -.37)
    lengths, arm_loss = [17.2, 22.9], (0 if loss == 0 else 3)
    path, (manifest, components) = build_y_network(tmp_path, left, right, lengths, arm_loss)
    rows, summary = compose(manifest, components)
    assert summary["instance_count"] == 4 and summary["connection_count"] == 4
    assert len(rows) == 12
    write_composition(tmp_path / "network.csv", rows)
    actual = load_component_data(path, "network", component_definition(["left", "right"], "network.csv"),
                                 project_root=tmp_path)
    for wavelength in WAVELENGTHS:
        arms = np.array([propagation(length, arm_loss, wavelength) for length in lengths])
        expected, condition = dark_feedback_oracle(left, right, arms)
        assert condition < 10
        np.testing.assert_allclose(actual.matrices[wavelength], expected, rtol=0, atol=5e-12)
        np.testing.assert_allclose(expected, expected.T, atol=2e-15)
        assert abs(expected[0, 0]) > 1e-3
        # Omitting branch reflection retains the one-pass path but loses feedback.
        u_left, _ = channels(left[0])
        u_right, _ = channels(right[0])
        one_pass = np.exp(-2 * loss * np.log(10) / 20 - 1j * (left[2] + right[2])) * (u_right @ (arms * u_left))
        assert abs(expected[1, 0] - one_pass) > 1e-3
        if loss == 0:
            np.testing.assert_allclose(expected.conj().T @ expected, np.eye(2), atol=8e-14)
        else:
            assert np.linalg.svd(expected, compute_uv=False)[0] < 1


@pytest.mark.parametrize("coupling", [0, 1])
def test_exact_closed_dark_loop_is_rejected_without_epsilon(tmp_path, coupling):
    _, (manifest, components) = build_y_network(tmp_path, (coupling, 0, 0), (coupling, 0, 0),
                                               [0, 0], wavelengths=[1550])
    with pytest.raises(AssemblyError, match="singular internal network"):
        compose(manifest, components)


def test_balanced_closed_dark_loop_is_rejected_without_epsilon(tmp_path):
    # Mathematically singular as at the endpoints; square-root roundoff must
    # not turn the unspecified internal dark field into accepted evidence.
    _, (manifest, components) = build_y_network(tmp_path, (.5, 0, 0), (.5, 0, 0),
                                               [0, 0], wavelengths=[1550])
    with pytest.raises(AssemblyError, match="singular internal network"):
        compose(manifest, components)


@pytest.mark.parametrize("phase", [1e-6, 1e-4])
def test_near_closed_dark_loop_with_resolvable_phase_is_not_silently_damped(tmp_path, phase):
    left, right = (.5, 0, phase), (.5, 0, 0)
    path, (manifest, components) = build_y_network(tmp_path, left, right, [0, 0], wavelengths=[1550])
    rows, _ = compose(manifest, components)
    write_composition(tmp_path / "network.csv", rows)
    actual = load_component_data(path, "network", component_definition(["left", "right"], "network.csv"),
                                 project_root=tmp_path).matrices[1550]
    expected, condition = dark_feedback_oracle(left, right, np.ones(2, dtype=complex))
    assert 1e4 < condition < 1e7
    # Bright and dark are decoupled when both arms are identity. Although the
    # internal dark solution is sensitive, the external bright solution is
    # known exactly, so no condition-scaled tolerance relaxation is necessary.
    bright_external = np.array([[0, np.exp(-1j * phase)], [np.exp(-1j * phase), 0]])
    np.testing.assert_allclose(actual, expected, rtol=0, atol=5e-12)
    np.testing.assert_allclose(actual, bright_external, rtol=0, atol=5e-12)
