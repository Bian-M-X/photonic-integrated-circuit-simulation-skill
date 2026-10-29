"""Shared geometry, native CAD round-trip, and continuing exterior leads."""

import copy

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical.device_geometry import FAMILIES, apply_device_geometry, build_device_geometry
from photonic_workflow.native_geometry import build_geometry
from photonic_workflow.ring_modulator import build_ring_geometry


class Session:
    def __init__(self, corrupt_index=False):
        self.objects = []
        self.corrupt_index = corrupt_index

    def addrect(self):
        self.objects.append({"kind": "rectangle"})

    def addpoly(self):
        self.objects.append({"kind": "polygon"})

    def addring(self):
        self.objects.append({"kind": "ring"})

    def set(self, key, value):
        self.objects[-1][key] = value

    def getnamed(self, name, key):
        item = next(item for item in self.objects if item["name"] == name)
        value = item[key]
        return value + 0.1 if key == "index" and self.corrupt_index else value


def apply(session, geometry, **updates):
    options = {"height_m": 0.22e-6, "core_index": 2.6, "clad_index": 1.45,
               "model_dimension": "2d", "port_buffer_m": 0.8e-6}
    return apply_device_geometry(session, geometry, **(options | updates))


@pytest.mark.parametrize("family", FAMILIES)
def test_shared_builder_and_port_order_preserved(family):
    actual = build_device_geometry(family)
    if family in {"ring", "ring-modulator"}:
        original = build_ring_geometry()
        assert actual["primitives"] == original["primitives"]
        assert actual["ports"] == original["ports"]
        assert actual["expected_core_area_um2"] == original["expected_core_area_um2"]
        assert actual["family"] == family
    else:
        assert actual == build_geometry(family)
    actual["ports"][0]["name"] = "mutated"
    assert build_device_geometry(family)["ports"][0]["name"] != "mutated"


@pytest.mark.parametrize("family", FAMILIES)
def test_cad_roundtrip_and_leads_extend_past_pml(family):
    session = Session()
    geometry = build_device_geometry(family)
    result = apply(session, geometry)
    assert result["geometry_readback"]["all_matched"]
    assert result["lead_extension_count"] == len(geometry["ports"])
    assert result["source_geometry"] == geometry
    bounds = result["solver_bounds_m"]
    for source, port in zip(geometry["ports"], result["ports"], strict=True):
        np.testing.assert_array_equal(port["center_m"], np.array(source["center_um"]) * 1e-6)
        lead = next(item for item in session.objects if item["name"] == "lead_" + port["name"])
        x, y = port["center_m"]
        if port["side"] == "left":
            assert lead["x min"] < bounds[0] < x < lead["x max"]
        elif port["side"] == "right":
            assert lead["x min"] < x < bounds[1] < lead["x max"]
        elif port["side"] == "bottom":
            assert lead["y min"] < bounds[2] < y < lead["y max"]
        else:
            assert lead["y min"] < y < bounds[3] < lead["y max"]


def test_ring_is_native_exact_annulus_and_add_drop_ports_keep_order():
    geometry = build_device_geometry("ring", {"bus_count": 2})
    session = Session()
    result = apply(session, geometry, model_dimension="3d")
    annulus = next(item for item in session.objects if item["kind"] == "ring")
    source = next(item for item in geometry["primitives"] if item["type"] == "ring")
    assert annulus["inner radius"] == source["inner_radius"] * 1e-6
    assert annulus["outer radius"] == source["outer_radius"] * 1e-6
    assert annulus["theta start"] == 0 and annulus["theta stop"] == 360
    assert [port["name"] for port in result["ports"]] == ["input", "through", "add", "drop"]
    assert not result["physics_accepted"]


def test_corrupted_material_is_observed_instead_of_assuming_assignment():
    result = apply(Session(corrupt_index=True), build_device_geometry("straight"))
    assert not result["geometry_readback"]["all_matched"]
    assert all(not obj["checks"]["index"] for obj in result["geometry_readback"]["objects"])


def test_tampered_shared_geometry_rejected_before_vendor_mutation():
    geometry = copy.deepcopy(build_device_geometry("straight"))
    geometry["primitives"][0]["width"] = 4.2
    session = Session()
    with pytest.raises(InvalidInputError, match="declared shared native builder"):
        apply(session, geometry)
    assert not session.objects


@pytest.mark.parametrize("updates", [
    {"core_index": float("nan")}, {"height_m": 0}, {"core_index": True}, {"clad_index": 3},
    {"model_dimension": "scalar"}, {"port_buffer_m": -1},
])
def test_invalid_inputs_rejected_before_vendor_mutation(updates):
    session = Session()
    with pytest.raises(InvalidInputError):
        apply(session, build_device_geometry("straight"), **updates)
    assert not session.objects
