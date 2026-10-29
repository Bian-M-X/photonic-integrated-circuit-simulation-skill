"""Assert the geometry migration preserves the existing numerical construction."""

import json

import numpy as np
import pytest

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.lumerical_geometry import export_native_geometry, migrate_geometry
from photonic_workflow.native_geometry import build_geometry


@pytest.mark.parametrize("family", ["straight", "crossing", "directional-coupler", "mmi2x2", "ybranch"])
def test_coordinates_port_order_and_core_area_survive_migration(family):
    request = {"schema_version": "1.0", "family": family, "parameters": {}}
    source = build_geometry(family)
    migrated = migrate_geometry(request, height_um=0.22, core_index=3.48)
    assert migrated["source_geometry"] == source
    assert len(migrated["objects"]) == len(source["primitives"])
    for old, new in zip(source["primitives"], migrated["objects"], strict=True):
        assert new["z_max_m"] - new["z_min_m"] == pytest.approx(0.22e-6)
        if old["type"] == "rectangle":
            assert new["x_min_m"] == old["x"] * 1e-6
            assert new["y_min_m"] == old["y"] * 1e-6
            assert new["x_max_m"] - new["x_min_m"] == pytest.approx(old["width"] * 1e-6)
            assert new["y_max_m"] - new["y_min_m"] == pytest.approx(old["height"] * 1e-6)
        else:
            np.testing.assert_array_equal(new["vertices_m"], np.array(old["points"]) * 1e-6)


def test_rejects_untranslated_physics_and_preserves_existing_output(tmp_path):
    request = {"schema_version": "1.0", "family": "straight", "parameters": {}}
    with pytest.raises(InvalidInputError):
        migrate_geometry(request | {"materials": {"core_index": 2.6}}, height_um=0.22, core_index=3.48)
    output = tmp_path / "geometry"
    receipt = export_native_geometry(request, output, height_um=0.22, core_index=3.48)
    original = (output / "geometry.lsf").read_bytes()
    assert json.loads((output / "geometry.json").read_text())["physics_accepted"] is False
    assert receipt["native_execution"] is False
    with pytest.raises(InvalidInputError):
        export_native_geometry(request, output, height_um=0.5, core_index=2)
    assert (output / "geometry.lsf").read_bytes() == original


@pytest.mark.parametrize("height,index", [(0, 3.48), (float("nan"), 3.48), (0.22, True)])
def test_bad_extrusion_does_not_create_output(tmp_path, height, index):
    with pytest.raises(InvalidInputError):
        export_native_geometry({"schema_version": "1.0", "family": "straight", "parameters": {}},
                               tmp_path / "absent", height_um=height, core_index=index)
    assert not (tmp_path / "absent").exists()
