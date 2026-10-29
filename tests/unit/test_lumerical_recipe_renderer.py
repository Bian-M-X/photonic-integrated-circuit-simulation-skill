from __future__ import annotations

import copy
import math
import re
from dataclasses import replace

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError, SecurityViolationError
from photonic_workflow.recipes import evaluate_recipe, inspect_recipe, render_recipe
from photonic_workflow.recipes.lumerical import lumerical_geometry_plan, render_lumerical_lsf_fragment
from photonic_workflow.recipes.renderers import MAX_LUMERICAL_CIRCULAR_VERTICES

CIRCULAR = {"vertices_um": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0]], "radius_um": 5.0, "width_um": 0.5}
EULER = {"turn_angle_deg": 90.0, "minimum_radius_um": 5.0, "width_um": 0.5, "samples": 64}
OPTIONS = {"instance_id": "device-arm", "height_um": 0.22, "core_index": 3.476}


def _render(recipe_id="geometry.circular-route", parameters=None, **options):
    return render_recipe(recipe_id, CIRCULAR if parameters is None else parameters,
                         renderer="lumerical-lsf-fragment", **{**OPTIONS, **options})


def test_renderer_catalog_scope_and_unchanged_default_payload():
    for recipe_id in ("geometry.circular-route", "geometry.symmetric-euler-bend"):
        assert "lumerical-lsf-fragment" in inspect_recipe(recipe_id).renderers
    assert "lumerical-lsf-fragment" not in inspect_recipe("waveguide.segmented-port-window").renderers
    canonical = render_recipe("geometry.circular-route", CIRCULAR)
    assert "renderer_options" not in canonical.to_payload()
    assert canonical.to_payload()["physics_accepted"] is False
    java = render_recipe("geometry.circular-route", CIRCULAR,
                         renderer="comsol-java-fragment", instance_id="legacy-arm")
    assert "renderer_options" not in java.to_payload()
    assert java.suggested_suffix == ".java" and 'g.lengthUnit("um")' in java.content


def test_circular_native_plan_has_exact_analytic_radius_and_straight_offset_geometry():
    result = evaluate_recipe("geometry.circular-route", CIRCULAR)
    plan = lumerical_geometry_plan(result, **OPTIONS)
    assert len(plan["primitives"]) == 3
    first, arc, last = plan["primitives"]
    np.testing.assert_allclose(first["vertices_m"], np.array([[0, .25], [15, .25], [15, -.25], [0, -.25]]) * 1e-6)
    assert arc["type"] == "ring"
    assert math.isclose(arc["inner_radius_m"], 4.75e-6)
    assert math.isclose(arc["outer_radius_m"], 5.25e-6)
    assert math.isclose(arc["x_m"], 15e-6) and math.isclose(arc["y_m"], 5e-6)
    assert arc["theta_start_deg"] == 270 and arc["theta_stop_deg"] == 360
    assert last["type"] == "polygon"
    assert all(item["z_m"] == 0 and math.isclose(item["z_span_m"], 0.22e-6) for item in plan["primitives"])
    assert not plan["will_execute"] and not plan["physics_accepted"]


def test_wraparound_arc_is_split_without_changing_total_angle_or_area():
    parameters = {**CIRCULAR, "vertices_um": [[0, 0], [20, 20], [0, 40]]}
    result = evaluate_recipe("geometry.circular-route", parameters)
    plan = lumerical_geometry_plan(result, **OPTIONS)
    arcs = [item for item in plan["primitives"] if item["type"] == "ring"]
    assert len(arcs) == 2
    angle = sum(item["theta_stop_deg"] - item["theta_start_deg"] for item in arcs)
    assert math.isclose(angle, 90)
    area = sum((item["outer_radius_m"] ** 2 - item["inner_radius_m"] ** 2)
               * math.radians(item["theta_stop_deg"] - item["theta_start_deg"]) / 2 for item in arcs)
    assert math.isclose(area, 5e-6 * .5e-6 * math.pi / 2)


@pytest.mark.parametrize("turn", [-90.0, 90.0])
def test_euler_uses_every_canonical_boundary_point_without_resampling(turn):
    parameters = {**EULER, "turn_angle_deg": turn}
    result = evaluate_recipe("geometry.symmetric-euler-bend", parameters)
    plan = lumerical_geometry_plan(result, **OPTIONS)
    assert len(plan["primitives"]) == 1
    np.testing.assert_array_equal(plan["primitives"][0]["vertices_m"],
                                  np.asarray(result.output["boundary_table"]) * 1e-6)
    assert len(plan["primitives"][0]["vertices_m"]) == 130
    rendered = _render("geometry.symmetric-euler-bend", parameters)
    assert rendered.content.count("addpoly;") == 1 and "addring;" not in rendered.content


def test_two_vertex_route_is_one_straight_polygon():
    rendered = _render(parameters={**CIRCULAR, "vertices_um": [[0, 0], [10, 0]]})
    assert rendered.content.count("addpoly;") == 1
    assert "addring;" not in rendered.content


def test_fragment_is_deterministic_bounded_numeric_and_explicitly_configured():
    rendered = _render()
    assert rendered.content == _render().content
    assert rendered.content.endswith("\n") and "\r" not in rendered.content
    assert rendered.suggested_suffix == ".lsf"
    assert rendered.media_type == "text/x-lumerical-lsf"
    assert rendered.to_payload()["renderer_options"] == {"height_um": .22, "core_index": 3.476}
    assert rendered.to_payload()["will_execute"] is False
    assert rendered.content.count("addpoly;") == 2 and rendered.content.count("addring;") == 1
    for forbidden in ("run;", "save(", "load(", "deleteall", "system(", "import(", "eval("):
        assert forbidden not in rendered.content
    names = re.findall(r'set\("name", "([^"]+)"\)', rendered.content)
    assert len(names) == len(set(names)) == 3
    alternate = _render(instance_id="device_arm")
    assert set(names).isdisjoint(re.findall(r'set\("name", "([^"]+)"\)', alternate.content))
    payload = rendered.to_payload()
    payload["renderer_options"]["core_index"] = 1
    assert rendered.to_payload()["renderer_options"]["core_index"] == 3.476


@pytest.mark.parametrize("name", ["height_um", "core_index"])
@pytest.mark.parametrize("value", [None, True, 0, -1, float("inf"), float("nan"), "2.6;run;"])
def test_missing_or_invalid_native_target_options_are_rejected(name, value):
    with pytest.raises(InvalidInputError, match="positive finite"):
        _render(**{name: value})


@pytest.mark.parametrize("renderer", ["canonical-json", "comsol-java-fragment"])
def test_native_options_are_not_silently_dropped_by_other_renderers(renderer):
    with pytest.raises(InvalidInputError, match="only by the Lumerical"):
        render_recipe("geometry.circular-route", CIRCULAR, renderer=renderer, height_um=.22)


@pytest.mark.parametrize("instance", [None, "bad\";run;", "../path", "arm/path", "中文"])
def test_namespace_cannot_inject_lsf_or_paths(instance):
    with pytest.raises((InvalidInputError, SecurityViolationError)):
        _render(instance_id=instance)


def test_changed_computed_output_is_rejected_and_caller_inputs_remain_unchanged():
    parameters = copy.deepcopy(EULER)
    result = evaluate_recipe("geometry.symmetric-euler-bend", parameters)
    corrupted = copy.deepcopy(result.output)
    corrupted["boundary_table"][0][0] += 1
    with pytest.raises(InvalidInputError, match="fresh evaluation"):
        lumerical_geometry_plan(replace(result, output=corrupted), **OPTIONS)
    assert parameters == EULER


def test_native_geometry_limits_and_unsupported_recipes_fail_before_render():
    with pytest.raises(InvalidInputError, match="at most"):
        _render(parameters={**CIRCULAR, "vertices_um": [[i, 0] for i in range(MAX_LUMERICAL_CIRCULAR_VERTICES + 1)]})
    with pytest.raises(InvalidInputError, match="does not support"):
        _render("materials.li-silicon-1980", {"wavelength_um": 1.55})
    result = evaluate_recipe("geometry.circular-route", CIRCULAR)
    plan = lumerical_geometry_plan(result, **OPTIONS)
    plan["primitives"][0]["name"] = 'bad");system("command")'
    with pytest.raises(InvalidInputError, match="Unsafe"):
        render_lumerical_lsf_fragment(plan)
