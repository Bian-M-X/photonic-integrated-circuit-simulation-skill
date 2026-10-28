"""Input envelopes, physical endpoints, stable resonances and export contracts."""

from __future__ import annotations

import copy
import csv
import io
import json
import math

import numpy as np
import pytest

from photonic_workflow.device_models import evaluate_device, list_models, scattering_csv
from photonic_workflow.exceptions import InvalidInputError

PARAMETERS = {
    "waveguide": {"length_um": 10, "neff": 2.4, "loss_db_per_cm": 3},
    "directional-coupler": {
        "length_um": 10, "neff_1": 2.4, "neff_2": 2.41, "kappa_per_um": 0.1, "loss_db_per_cm": 3,
    },
    "ring-allpass": {"roundtrip_length_um": 20, "neff": 2.4, "loss_db_per_cm": 3, "coupling_power": 0.1},
    "ring-adddrop": {
        "roundtrip_length_um": 20, "neff": 2.4, "loss_db_per_cm": 3,
        "coupling_power_1": 0.1, "coupling_power_2": 0.2, "arc_fraction": 0.3,
    },
    "bragg-uniform": {"length_um": 10, "neff": 2.4, "period_um": 0.32, "kappa_per_um": 0.1},
    "mmi2x2-ideal": {"coupling_power": 0.5, "excess_loss_db": 0, "phase_rad": 0},
    "ybranch-ideal": {"coupling_power": 0.5, "excess_loss_db": 0, "phase_rad": 0},
}


def request(model="waveguide", **changes):
    parameters = {**PARAMETERS[model], **changes}
    return {"schema_version": "1.0", "model": model, "wavelengths_nm": [1520, 1550, 1580],
            "parameters": parameters}


def matrix(payload):
    result = np.asarray(evaluate_device(payload)["s_matrices"])
    return result[..., 0] + 1j * result[..., 1]


def test_catalog_is_detached_and_all_models_are_json_safe():
    descriptors = list_models()
    assert {item["model"] for item in descriptors} == set(PARAMETERS)
    descriptors[0]["port_order"].clear()
    assert list_models()[0]["port_order"] == ["left", "right"]
    for model in PARAMETERS:
        result = evaluate_device(request(model))
        assert result["physics_accepted"] is False and result["will_execute"] is False
        assert result["validity"]["calibration"] == "not established"
        assert result["limitations"]
        assert set(result["reference_planes"]) == set(result["port_order"])
        assert result["convention"]["time_dependence"] == "exp(+iwt)"
        json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("model", PARAMETERS)
def test_every_parameter_is_required_and_extra_keys_are_rejected(model):
    for name in PARAMETERS[model]:
        payload = request(model)
        del payload["parameters"][name]
        with pytest.raises(InvalidInputError, match="fields mismatch"):
            evaluate_device(payload)
    with pytest.raises(InvalidInputError, match="unknown"):
        evaluate_device(request(model, invented=1))


@pytest.mark.parametrize("model", PARAMETERS)
@pytest.mark.parametrize("bad", [True, False, "1", None, math.nan, math.inf, -math.inf, 10**1000])
def test_all_numeric_parameters_reject_wrong_type_or_nonfinite(model, bad):
    for name in PARAMETERS[model]:
        with pytest.raises(InvalidInputError):
            evaluate_device(request(model, **{name: bad}))


@pytest.mark.parametrize("field,value", [
    ("schema_version", "2.0"), ("schema_version", 1), ("model", "ring"), ("model", []),
    ("wavelengths_nm", []), ("wavelengths_nm", [1550] * 257), ("wavelengths_nm", [1550, 1550]),
    ("wavelengths_nm", [True]), ("wavelengths_nm", [0]), ("wavelengths_nm", [-1]),
    ("wavelengths_nm", [math.nan]), ("wavelengths_nm", "1550"), ("parameters", []),
])
def test_request_envelope_rejections(field, value):
    payload = request()
    payload[field] = value
    with pytest.raises(InvalidInputError):
        evaluate_device(payload)


def test_unknown_missing_root_fields_and_empty_model_are_rejected():
    payload = request()
    payload["execute"] = True
    with pytest.raises(InvalidInputError):
        evaluate_device(payload)
    for field in request():
        payload = request()
        del payload[field]
        with pytest.raises(InvalidInputError):
            evaluate_device(payload)


@pytest.mark.parametrize("model,name,value", [
    ("waveguide", "length_um", -1), ("waveguide", "loss_db_per_cm", -1),
    ("waveguide", "neff", 0), ("directional-coupler", "neff_1", -1),
    ("directional-coupler", "kappa_per_um", -0.1), ("ring-allpass", "coupling_power", 1.1),
    ("ring-allpass", "coupling_power", -0.1), ("ring-adddrop", "arc_fraction", 0),
    ("ring-adddrop", "arc_fraction", 1), ("bragg-uniform", "period_um", 0),
    ("mmi2x2-ideal", "coupling_power", -0.1), ("mmi2x2-ideal", "coupling_power", 1.1),
    ("mmi2x2-ideal", "excess_loss_db", -0.1),
    ("ybranch-ideal", "coupling_power", -0.1), ("ybranch-ideal", "coupling_power", 1.1),
    ("ybranch-ideal", "excess_loss_db", -0.1),
])
def test_parameter_bounds(model, name, value):
    with pytest.raises(InvalidInputError, match="bounds"):
        evaluate_device(request(model, **{name: value}))


def test_wavelength_order_is_preserved_without_mutating_input():
    payload = request()
    payload["wavelengths_nm"] = [1580, 1520, 1550]
    original = copy.deepcopy(payload)
    assert evaluate_device(payload)["wavelengths_nm"] == [1580, 1520, 1550]
    assert payload == original


def test_zero_length_waveguide_and_coupler_are_through_and_loss_conversion_is_power():
    np.testing.assert_array_equal(matrix(request(length_um=0))[0], [[0, 1], [1, 0]])
    dc = matrix(request("directional-coupler", length_um=0))[0]
    np.testing.assert_array_equal(dc, [[0, 0, 1, 0], [0, 0, 0, 1], [1, 0, 0, 0], [0, 1, 0, 0]])
    power = abs(matrix(request(length_um=10000, loss_db_per_cm=20))[0, 1, 0]) ** 2
    assert power == pytest.approx(0.01, abs=1e-15)


def test_matched_coupler_complete_transfer_and_mismatch_bound():
    coupling = 0.3
    payload = request("directional-coupler", neff_1=2, neff_2=2, loss_db_per_cm=0,
                      length_um=math.pi / (2 * coupling), kappa_per_um=coupling)
    s = matrix(payload)
    np.testing.assert_allclose(abs(s[:, 3, 0]) ** 2, 1, atol=2e-15)
    np.testing.assert_allclose(abs(s[:, 2, 0]) ** 2, 0, atol=1e-28)
    payload = request("directional-coupler", loss_db_per_cm=0)
    s = matrix(payload)
    wavelengths = np.asarray(payload["wavelengths_nm"]) / 1000
    delta = math.pi * (PARAMETERS["directional-coupler"]["neff_1"]
                       - PARAMETERS["directional-coupler"]["neff_2"]) / wavelengths
    ceiling = 0.1**2 / (0.1**2 + delta**2)
    assert np.all(abs(s[:, 3, 0]) ** 2 <= ceiling + 1e-14)


def test_disconnected_ring_at_internal_resonance_has_external_identity_and_no_nan():
    allpass = request("ring-allpass", coupling_power=0, loss_db_per_cm=0, neff=1, roundtrip_length_um=1.55)
    np.testing.assert_array_equal(matrix(allpass), np.broadcast_to([[0, 1], [1, 0]], (3, 2, 2)))
    drop = request("ring-adddrop", coupling_power_1=0, coupling_power_2=0, loss_db_per_cm=0)
    expected = [[0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]]
    np.testing.assert_array_equal(matrix(drop), np.broadcast_to(expected, (3, 4, 4)))


def test_full_coupling_ring_and_one_decoupled_adddrop_bus():
    payload = request("ring-allpass", coupling_power=1)
    straight = request(length_um=20)
    np.testing.assert_allclose(matrix(payload), -matrix(straight), atol=1e-14)
    drop = matrix(request("ring-adddrop", coupling_power_2=0))
    np.testing.assert_allclose(drop[:, 1, 0], matrix(request("ring-allpass"))[:, 1, 0], atol=1e-14)
    np.testing.assert_array_equal(drop[:, 3, 2], 1)
    np.testing.assert_array_equal(drop[:, 3, 0], 0)


def test_high_q_ring_exact_zero_length_resonance_preserves_small_couplings():
    # q=0 eliminates phase-roundoff so this specifically challenges denominator cancellation.
    s = matrix(request("ring-allpass", roundtrip_length_um=0, coupling_power=1e-24, loss_db_per_cm=0))
    np.testing.assert_allclose(s[:, 1, 0], -1, atol=1e-15)
    s = matrix(request("ring-adddrop", roundtrip_length_um=0, coupling_power_1=1e-24,
                       coupling_power_2=1e-24, loss_db_per_cm=0))
    np.testing.assert_allclose(s[:, 3, 0], -1, atol=1e-15)
    np.testing.assert_allclose(s[:, 1, 0], 0, atol=1e-15)


def test_ring_critical_coupling_and_uniform_asymmetric_arc_loss():
    length, loss = 1.55, 2000
    roundtrip_power = 10 ** (-loss * length / 100000)
    payload = request("ring-allpass", roundtrip_length_um=length, neff=1,
                      loss_db_per_cm=loss, coupling_power=1 - roundtrip_power)
    payload["wavelengths_nm"] = [1550]
    assert abs(matrix(payload)[0, 1, 0]) < 1e-13
    payload = request("ring-adddrop", arc_fraction=0.2, loss_db_per_cm=2000)
    s = matrix(payload)
    # Both cross directions share the same feedback denominator; uniform arc loss differs.
    ratio = abs(s[:, 3, 0] / s[:, 1, 2]) ** 2
    expected = 10 ** (-2000 * 20 * (2 * 0.2 - 1) / 100000)
    np.testing.assert_allclose(ratio, expected, rtol=1e-14)


def test_bragg_zero_coupling_matches_physical_propagation_and_large_stopband_is_finite():
    payload = request("bragg-uniform", kappa_per_um=0)
    control = request(loss_db_per_cm=0)
    np.testing.assert_allclose(matrix(payload), matrix(control), atol=1e-15)
    payload = request("bragg-uniform", neff=1.55, period_um=0.5, kappa_per_um=1, length_um=1000)
    payload["wavelengths_nm"] = [1550]
    s = matrix(payload)[0]
    assert abs(s[0, 0]) == pytest.approx(1)
    assert abs(s[1, 0]) < 1e-300
    assert np.isfinite(s).all()


def test_bragg_zero_length_has_identity_transmission():
    np.testing.assert_array_equal(matrix(request("bragg-uniform", length_um=0))[0], [[0, 1], [1, 0]])


def test_mmi_descriptor_is_analytic_with_signed_phase_and_explicit_limits():
    descriptor = next(item for item in list_models() if item["model"] == "mmi2x2-ideal")
    assert descriptor["model_level"] == "analytic"
    assert descriptor["model_version"] == "1.0.0"
    assert descriptor["port_order"] == ["upper_left", "lower_left", "upper_right", "lower_right"]
    assert descriptor["parameters"]["coupling_power"]["minimum"] == 0
    assert descriptor["parameters"]["coupling_power"]["maximum"] == 1
    assert descriptor["parameters"]["excess_loss_db"]["minimum"] == 0
    assert "minimum" not in descriptor["parameters"]["phase_rad"]
    assert "maximum" not in descriptor["parameters"]["phase_rad"]
    limits = " ".join(descriptor["limitations"])
    for word in ("self-imaging", "geometry", "dispersion", "reference-plane calibration", "power deficit"):
        assert word in limits


@pytest.mark.parametrize("coupling", [0, 0.5, 1])
@pytest.mark.parametrize("phase", [-0.7, 0, 0.7])
def test_mmi_all_columns_have_declared_power_and_signed_common_phase(coupling, phase):
    payload = request("mmi2x2-ideal", coupling_power=coupling, excess_loss_db=20, phase_rad=phase)
    s = matrix(payload)
    factor = 0.1 * complex(math.cos(phase), -math.sin(phase))
    np.testing.assert_allclose(s[:, 2, 0], factor * math.sqrt(1 - coupling), atol=1e-15)
    np.testing.assert_allclose(s[:, 3, 0], -1j * factor * math.sqrt(coupling), atol=1e-15)
    np.testing.assert_allclose(np.sum(abs(s) ** 2, axis=1), 0.01, atol=1e-15)
    np.testing.assert_array_equal(s, np.swapaxes(s, 1, 2))
    np.testing.assert_array_equal(s, np.broadcast_to(s[0], s.shape))


@pytest.mark.parametrize("model,through_port", [("mmi2x2-ideal", 2), ("ybranch-ideal", 1)])
@pytest.mark.parametrize("phase", [-1e308, 1e308])
def test_ideal_largest_finite_loss_underflows_cleanly_and_finite_phases_remain_valid(model, through_port, phase):
    result = evaluate_device(request(model, excess_loss_db=1.7976931348623157e308,
                                     phase_rad=phase))
    assert np.count_nonzero(result["s_matrices"]) == 0
    json.dumps(result, allow_nan=False)
    s = matrix(request(model, phase_rad=phase))
    assert np.isfinite(s).all()
    np.testing.assert_allclose(s[:, through_port, 0], complex(math.cos(phase), -math.sin(phase)) / math.sqrt(2),
                               atol=1e-15)
    np.testing.assert_allclose(np.sum(abs(s) ** 2, axis=1), 1, atol=1e-15)


def test_ybranch_descriptor_declares_three_ports_signed_phase_and_claim_limits():
    descriptor = next(item for item in list_models() if item["model"] == "ybranch-ideal")
    assert descriptor["model_level"] == "analytic"
    assert descriptor["model_version"] == "1.0.0"
    assert descriptor["port_order"] == ["trunk", "upper", "lower"]
    assert descriptor["parameters"]["coupling_power"]["minimum"] == 0
    assert descriptor["parameters"]["coupling_power"]["maximum"] == 1
    assert descriptor["parameters"]["excess_loss_db"]["minimum"] == 0
    assert "minimum" not in descriptor["parameters"]["phase_rad"]
    assert "maximum" not in descriptor["parameters"]["phase_rad"]
    limits = " ".join(descriptor["limitations"])
    for word in ("trunk-to-lower", "reflect", "bright", "dark", "phase lag", "geometry", "modal conversion",
                 "dispersion", "loss mechanism", "reference-plane calibration", "power deficit"):
        assert word in limits
    result = evaluate_device(request("ybranch-ideal"))
    assert all("Declared ideal port basis" in plane for plane in result["reference_planes"].values())


@pytest.mark.parametrize("coupling", [0, 0.23, 0.5, 1])
@pytest.mark.parametrize("phase", [-0.7, 0, 0.7])
def test_ybranch_all_columns_are_reciprocal_with_common_phase_and_uniform_power(coupling, phase):
    s = matrix(request("ybranch-ideal", coupling_power=coupling, excess_loss_db=20, phase_rad=phase))
    factor = 0.1 * complex(math.cos(phase), -math.sin(phase))
    np.testing.assert_allclose(s[:, 1, 0], factor * math.sqrt(1 - coupling), atol=1e-15)
    np.testing.assert_allclose(s[:, 2, 0], factor * math.sqrt(coupling), atol=1e-15)
    np.testing.assert_array_equal(s[:, 0, 0], 0)
    np.testing.assert_allclose(np.sum(abs(s) ** 2, axis=1), 0.01, atol=1e-15)
    np.testing.assert_array_equal(s, np.swapaxes(s, 1, 2))
    np.testing.assert_array_equal(s, np.broadcast_to(s[0], s.shape))


def test_ybranch_balanced_branch_input_retains_both_reflection_channels():
    s = matrix(request("ybranch-ideal"))[0]
    np.testing.assert_allclose(abs(s[:, 1]) ** 2, [0.5, 0.25, 0.25], atol=1e-15)
    assert s[1, 1] == pytest.approx(-0.5)
    assert s[2, 1] == pytest.approx(0.5)


@pytest.mark.parametrize("model,updates", [
    ("waveguide", {"neff": 1e308}), ("waveguide", {"length_um": 1e308}),
    ("waveguide", {"length_um": 1e308, "loss_db_per_cm": 1e308}),
    ("directional-coupler", {"kappa_per_um": 1e308}),
    ("bragg-uniform", {"period_um": 1e-320}),
])
def test_finite_inputs_with_nonfinite_intermediates_fail_clearly(model, updates):
    with pytest.raises(InvalidInputError, match=r"nonfinite|numerical"):
        evaluate_device(request(model, **updates))


@pytest.mark.parametrize("model", PARAMETERS)
def test_csv_has_exact_five_columns_and_all_source_pairs(model):
    result = evaluate_device(request(model))
    reader = csv.DictReader(io.StringIO(scattering_csv(result)))
    assert reader.fieldnames == ["wavelength_nm", "out_port", "in_port", "s_real", "s_imag"]
    rows = list(reader)
    n = len(result["port_order"])
    assert len(rows) == 3 * n * n
    assert {(row["out_port"], row["in_port"]) for row in rows} == {
        (a, b) for a in result["port_order"] for b in result["port_order"]
    }


@pytest.mark.parametrize("edit", ["shape", "nonfinite", "port", "convention", "acceptance"])
def test_csv_rejects_malformed_or_incompatible_result(edit):
    result = evaluate_device(request())
    if edit == "shape":
        result["s_matrices"][0].pop()
    elif edit == "nonfinite":
        result["s_matrices"][0][0][0][0] = math.nan
    elif edit == "port":
        result["port_order"].reverse()
    elif edit == "convention":
        result["convention"]["time_dependence"] = "exp(-iwt)"
    else:
        result["physics_accepted"] = True
    with pytest.raises(InvalidInputError):
        scattering_csv(result)
