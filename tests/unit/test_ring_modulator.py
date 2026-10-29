"""Geometry invariants and independent electrostatic/carrier-law controls."""

import copy
import math
from itertools import pairwise

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.ring_modulator import (
    build_ring_geometry,
    depletion_response,
    poisson_reference,
    render_pn_java,
)


def test_ring_true_gap_area_and_component_topology():
    geometry = build_ring_geometry()
    bus, ring = geometry["primitives"]
    bus_upper = bus["y"] + bus["height"]
    ring_lower = ring["cy"] - ring["outer_radius"]
    assert ring_lower - bus_upper == pytest.approx(0.2)
    assert geometry["expected_core_components"] == 2
    annulus_area = math.pi * (ring["outer_radius"] ** 2 - ring["inner_radius"] ** 2)
    assert geometry["expected_core_area_um2"] == pytest.approx(annulus_area + bus["width"] * bus["height"])
    for port in geometry["ports"]:
        x, y = port["center_um"]
        assert x in geometry["bbox_um"][:2]
        assert y - port["window_um"] / 2 > geometry["bbox_um"][2]
        assert y + port["window_um"] / 2 < geometry["bbox_um"][3]


def test_radius_and_gap_tune_without_changing_bus_port_width():
    original = {"radius_um": 5.0, "gap_um": 0.35}
    saved = copy.deepcopy(original)
    tuned = build_ring_geometry(original)
    assert original == saved
    assert tuned["primitives"][1]["outer_radius"] == 5.15
    assert tuned["ports"][0]["width_um"] == 0.3
    assert tuned["primitives"][1]["cy"] - 5.15 - 0.15 == pytest.approx(0.35)
    assert build_ring_geometry()["parameters"]["radius_um"] == 3.0


@pytest.mark.parametrize("parameters", [
    {"radius_um": math.nan}, {"radius_um": True}, {"radius_um": "3"}, {"radius_um": 0.1},
    {"radius_um": 10**500},
    {"gap_um": 0.0}, {"port_window_um": 0.3}, {"port_window_um": 4.0}, {"arbitrary_java": "foo"},
])
def test_geometry_rejects_unusable_or_untrusted_parameters(parameters):
    with pytest.raises(InvalidInputError):
        build_ring_geometry(parameters)


def test_zero_bias_reference_is_exact_but_carrier_absorption_is_not_zero():
    response = depletion_response()
    assert response["delta_n_eff"] == 0
    assert response["delta_k_eff"] == 0
    assert response["absolute_k_eff"] > 0
    assert response["zero_bias_alpha_eff_per_cm"] == response["absolute_alpha_eff_per_cm"]
    assert 0 < response["depletion_width_um"] < 0.3


def test_charge_balance_and_poisson_drop_for_asymmetric_junction():
    response = depletion_response({"acceptor_cm3": 2e17, "donor_cm3": 1e17, "reverse_bias_v": 1.0})
    p = response["parameters"]
    xp, xn = response["xp_um"] * 1e-6, response["xn_um"] * 1e-6
    epsilon = 8.8541878128e-12 * 11.7
    q = 1.602176634e-19
    na, nd = 2e23, 1e23
    assert na * xp == pytest.approx(nd * xn)
    # Integrate the two triangular field contributions, independent of W formula.
    potential_drop = q * (na * xp**2 + nd * xn**2) / (2 * epsilon)
    assert potential_drop == pytest.approx(response["potential_drop_v"])
    assert xp / xn == pytest.approx(0.5)
    assert response["junction_charge_c"] == pytest.approx(q * na * xp * response["junction_area_m2"])
    assert p["reverse_bias_v"] == 1.0


def test_capacitance_is_charge_derivative_not_charge_over_total_voltage():
    step = 1e-4
    center = depletion_response({"reverse_bias_v": 1.0})
    plus = depletion_response({"reverse_bias_v": 1.0 + step})
    minus = depletion_response({"reverse_bias_v": 1.0 - step})
    derivative = (plus["junction_charge_c"] - minus["junction_charge_c"]) / (2 * step)
    assert derivative == pytest.approx(center["junction_capacitance_f"], rel=2e-8)
    assert center["junction_capacitance_f"] == pytest.approx(
        center["junction_charge_c"] / (2 * center["potential_drop_v"])
    )
    assert center["junction_capacitance_f"] != pytest.approx(
        center["junction_charge_c"] / center["potential_drop_v"], rel=0.1, abs=0
    )


def test_reverse_bias_increases_index_and_reduces_free_carrier_loss():
    responses = [depletion_response({"reverse_bias_v": voltage}) for voltage in (0, 1, 2)]
    assert all(a["delta_n_eff"] < b["delta_n_eff"] for a, b in pairwise(responses))
    assert all(a["absolute_k_eff"] > b["absolute_k_eff"] for a, b in pairwise(responses))
    assert all(a["junction_capacitance_f"] > b["junction_capacitance_f"]
               for a, b in pairwise(responses))
    response = responses[1]
    assert response["absolute_k_eff"] == pytest.approx(response["absolute_alpha_eff_per_cm"] * 1.55e-4 / (4 * math.pi))
    assert response["delta_k_eff"] < 0


def test_hole_law_is_averaged_after_local_exponentiation():
    response = depletion_response({"acceptor_cm3": 2e17, "donor_cm3": 1e17, "reverse_bias_v": 1.0})
    p = response["parameters"]
    local = response["carriers"]
    fp = local["neutral_p_core_fraction"]
    fn = local["neutral_n_core_fraction"]
    average_of_law = -0.8 * (8.8e-22 * 1e17 * fn + 8.5e-18 * (2e17) ** 0.8 * fp)
    law_of_average = -0.8 * (8.8e-22 * local["mean_electron_cm3"] + 8.5e-18 * local["mean_hole_cm3"] ** 0.8)
    assert local["carrier_index_change_eff"] == pytest.approx(average_of_law)
    assert local["carrier_index_change_eff"] != pytest.approx(law_of_average, rel=0.01)
    zero = response["zero_bias"]
    expected_delta = p["optical_overlap"] * (
        8.8e-22 * p["donor_cm3"] * (zero["neutral_n_core_fraction"] - fn)
        + 8.5e-18 * p["acceptor_cm3"] ** 0.8 * (zero["neutral_p_core_fraction"] - fp)
    )
    assert response["delta_n_eff"] == pytest.approx(expected_delta)


def test_optical_depletion_saturates_while_electrical_width_continues_growing():
    first = depletion_response({"reverse_bias_v": 5.0})
    second = depletion_response({"reverse_bias_v": 7.0})
    assert first["absolute_k_eff"] == second["absolute_k_eff"] == 0
    assert first["delta_n_eff"] == second["delta_n_eff"]
    assert second["depletion_width_um"] > first["depletion_width_um"]
    assert second["junction_capacitance_f"] < first["junction_capacitance_f"]
    assert second["xp_um"] < second["parameters"]["p_region_width_um"]


def test_optical_overlap_and_active_fraction_are_declared_linear_projection():
    full = depletion_response({"reverse_bias_v": 1.0})
    half_overlap = depletion_response({"reverse_bias_v": 1.0, "optical_overlap": 0.4})
    half_active = depletion_response({"reverse_bias_v": 1.0, "active_fraction": 0.5})
    assert half_overlap["delta_n_eff"] == pytest.approx(full["delta_n_eff"] / 2)
    assert half_overlap["junction_capacitance_f"] == full["junction_capacitance_f"]
    assert half_active["delta_n_eff"] == pytest.approx(full["delta_n_eff"] / 2)
    assert half_active["junction_capacitance_f"] == pytest.approx(full["junction_capacitance_f"] / 2)
    zero = depletion_response({"reverse_bias_v": 1.0, "active_fraction": 0.0})
    assert zero["delta_n_eff"] == zero["absolute_k_eff"] == zero["junction_capacitance_f"] == 0


def test_junction_offset_changes_which_carrier_regions_overlap():
    centered = depletion_response({"reverse_bias_v": 1})
    shifted = depletion_response({"reverse_bias_v": 1, "junction_offset_um": 0.1})
    assert centered["delta_n_eff"] != shifted["delta_n_eff"]
    assert shifted["carriers"]["neutral_n_core_fraction"] == 0
    assert shifted["carriers"]["neutral_p_core_fraction"] > centered["carriers"]["neutral_p_core_fraction"]


@pytest.mark.parametrize("parameters", [
    {"reverse_bias_v": -0.1}, {"reverse_bias_v": math.inf}, {"acceptor_cm3": True},
    {"acceptor_cm3": 1e22}, {"n_region_width_um": 0.05}, {"optical_overlap": 1.1},
    {"active_fraction": -1}, {"wavelength_nm": 1310}, {"junction_offset_um": 2}, {"path": "untrusted"},
])
def test_pn_rejects_invalid_scope_and_punchthrough(parameters):
    with pytest.raises(InvalidInputError):
        depletion_response(parameters)


def test_contact_punchthrough_is_rejected_even_when_optical_core_fits():
    with pytest.raises(InvalidInputError, match="punch-through"):
        depletion_response({
            "p_region_width_um": 0.1, "n_region_width_um": 0.1,
            "optical_width_um": 0.05, "reverse_bias_v": 2.0,
        })


def test_poisson_reference_field_and_potential_satisfy_local_equations():
    parameters = {"acceptor_cm3": 2e17, "donor_cm3": 1e17, "reverse_bias_v": 2.0}
    response = depletion_response(parameters)
    positions = [-0.8, -0.7 * response["xp_um"], 0.4 * response["xn_um"], 0.8]
    rows = poisson_reference(parameters, positions)["rows"]
    assert rows[0]["potential_v"] == rows[0]["field_v_per_m"] == 0
    assert rows[-1]["potential_v"] == response["potential_drop_v"]
    assert rows[-1]["field_v_per_m"] == 0
    epsilon = 11.7 * 8.8541878128e-12
    delta_um = 1e-5
    for row in rows[1:3]:
        x = row["x_um"]
        a, b = poisson_reference(parameters, [x - delta_um, x + delta_um])["rows"]
        assert -(b["potential_v"] - a["potential_v"]) / (2 * delta_um * 1e-6) == pytest.approx(
            row["field_v_per_m"], rel=1e-8
        )
        assert (b["field_v_per_m"] - a["field_v_per_m"]) / (2 * delta_um * 1e-6) == pytest.approx(
            row["charge_c_per_m3"] / epsilon, rel=1e-8
        )


def test_poisson_potential_and_field_are_continuous_at_depletion_interfaces():
    parameters = {"acceptor_cm3": 2e17, "reverse_bias_v": 1.0}
    response = depletion_response(parameters)
    for interface in (-response["xp_um"], 0.0, response["xn_um"]):
        a, b = poisson_reference(parameters, [interface - 1e-10, interface + 1e-10])["rows"]
        assert abs(a["potential_v"] - b["potential_v"]) < 1e-8
        assert abs(a["field_v_per_m"] - b["field_v_per_m"]) < 1


def test_native_render_is_deterministic_and_accepts_only_validated_numeric_parameters():
    assert render_pn_java({"reverse_bias_v": 1.0}) == render_pn_java({"reverse_bias_v": 1})
    assert render_pn_java({"reverse_bias_v": 0.0}) != render_pn_java({"reverse_bias_v": 1.0})
    with pytest.raises(InvalidInputError):
        render_pn_java({"reverse_bias_v": '1;System.exit(0)'})


@pytest.mark.parametrize("positions", [[], [True], [math.nan], [1.01], [10**500]])
def test_poisson_reference_rejects_bad_sample_positions(positions):
    with pytest.raises(InvalidInputError):
        poisson_reference({}, positions)


def test_sample_integrated_charge_neutrality_independent_of_analytic_width_formula():
    response = depletion_response({"acceptor_cm3": 3e17, "reverse_bias_v": 1.0})
    # Midpoint quadrature separately over the two piecewise-constant charged regions.
    xp, xn = response["xp_um"], response["xn_um"]
    p_samples = (-xp + (np.arange(19) + 0.5) * xp / 19).tolist()
    n_samples = ((np.arange(23) + 0.5) * xn / 23).tolist()
    parameters = response["parameters"]
    qp = sum(row["charge_c_per_m3"] for row in poisson_reference(parameters, p_samples)["rows"]) * xp * 1e-6 / 19
    qn = sum(row["charge_c_per_m3"] for row in poisson_reference(parameters, n_samples)["rows"]) * xn * 1e-6 / 23
    assert qp + qn == pytest.approx(0, abs=1e-17)
    assert qn == pytest.approx(response["charge_per_area_c_per_m2"])


def test_add_drop_ring_has_two_separated_buses_and_physical_port_order():
    g = build_ring_geometry({"bus_count": 2, "radius_um": 4.0, "gap_um": 0.15})
    lower, annulus, upper = g["primitives"]
    assert [port["name"] for port in g["ports"]] == ["input", "through", "add", "drop"]
    assert [port["side"] for port in g["ports"]] == ["left", "right", "right", "left"]
    assert g["expected_core_components"] == 3
    assert annulus["cy"] - annulus["outer_radius"] - lower["y"] - lower["height"] == pytest.approx(.15)
    assert upper["y"] - annulus["cy"] - annulus["outer_radius"] == pytest.approx(.15)
    expected = 2 * lower["width"] * lower["height"] + 2 * math.pi * 4.0 * .3
    assert g["expected_core_area_um2"] == pytest.approx(expected)
    assert g["bbox_um"][3] > upper["y"] + upper["height"]


@pytest.mark.parametrize("count", [0, 1.5, 3, True])
def test_ring_bus_count_requires_an_explicit_supported_topology(count):
    with pytest.raises(InvalidInputError):
        build_ring_geometry({"bus_count": count})
