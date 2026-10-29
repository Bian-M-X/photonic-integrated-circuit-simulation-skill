"""Synthetic protocol counterexamples; no fixture here is native COMSOL evidence."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import shutil

import numpy as np
import pytest

from photonic_workflow.circuits import compose, validate_manifest
from photonic_workflow.circuits.assembly import load_component_data
from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.native_devices import (
    calibrate_native_run,
    compare_native_meshes,
    load_native_json,
    native_catalog,
    native_request,
    native_scattering_csv,
    parse_native_output,
)


def request(family="crossing", **updates):
    return {"schema_version": "1.0", "family": family, "wavelengths_nm": [1530.0, 1550.0], **updates}


def synthetic_case(family="crossing", *, stage="solve", matrix=None):
    """Construct complete exact-axis data with independently chosen unitary S."""
    geometry, config = native_request(request(family, stage=stage))
    count = len(geometry["ports"])
    if matrix is None:
        if count == 4:
            matrix = np.zeros((4, 4), dtype=complex)
            matrix[0, 1] = matrix[1, 0] = np.exp(0.3j)
            matrix[2, 3] = matrix[3, 2] = np.exp(-0.2j)
        else:
            # Symmetric Fourier matrix: a complete reciprocal three-port unitary
            # counterexample, not an asserted geometry or all-ports-matched Y.
            indices = np.arange(count)
            matrix = np.exp(2j * np.pi * np.outer(indices, indices) / count) / math.sqrt(count)
    area = geometry["expected_core_area_um2"]
    box = geometry["bbox_um"]
    all_area = (box[1] - box[0]) * (box[3] - box[2])
    lines = [f"PIC STAGE {stage}", "PIC UNIT_CODEPOINTS [181, 109]", "PIC UNIT um",
             f"PIC AREA core {area:.17g}", "PIC AREA active 0", f"PIC AREA bg {all_area - area:.17g}",
             f"PIC AREA all {all_area:.17g}", "PIC GEOMETRY_PASS", "PIC PORTS_PASS"]
    lines += [f"PIC CORE_END {index} {port['width_um']:.17g}"
              for index, port in enumerate(geometry["ports"], 1)]
    if stage != "configure":
        for wavelength in config["wavelengths_nm"]:
            for source in range(1, count + 1):
                lines += [f"PIC MODE {wavelength} {source} 2.18 0",
                          f"PIC MODE_ANCHOR {wavelength} {source} 1 0",
                          f"PIC MODE_POWER {wavelength} {source} 1"]
    if stage == "solve":
        for wavelength in config["wavelengths_nm"]:
            for source in range(1, count + 1):
                lines.append(f"PIC SOURCE {wavelength} {source} {source}")
                for receive in range(1, count + 1):
                    value = matrix[receive - 1, source - 1]
                    lines.append(f"PIC S {wavelength} {source} {receive} {value.real:.17g} {value.imag:.17g}")
                    flux = abs(value) ** 2 - (receive == source)
                    lines.append(f"PIC FLUX {wavelength} {source} p{receive} {flux:.17g}")
                lines += [f"PIC FLUX {wavelength} {source} open 0", f"PIC FLUX {wavelength} {source} abs 0"]
    lines.append(f"PIC COMPLETE {stage}")
    return geometry, config, lines, matrix


def parse_case(family="crossing", *, stage="solve", matrix=None):
    geometry, config, lines, wanted = synthetic_case(family, stage=stage, matrix=matrix)
    return parse_native_output("\n".join(lines), geometry, config), wanted


def replace_row(lines, prefix, replacement):
    changed = list(lines)
    index = next(i for i, line in enumerate(changed) if line.startswith(prefix))
    changed[index] = replacement
    return changed


def synthetic_curved_areas():
    geometry, config, lines, _ = synthetic_case("ring")
    core = geometry["expected_core_area_um2"]
    ring = next(p for p in geometry["primitives"] if p["type"] == "ring")
    active = math.pi * (ring["outer_radius"] ** 2 - ring["inner_radius"] ** 2)
    box = geometry["bbox_um"]
    total = (box[1] - box[0]) * (box[3] - box[2])
    lines = replace_row(lines, "PIC AREA core ", f"PIC AREA core {core * .9999}")
    lines = replace_row(lines, "PIC AREA active ", f"PIC AREA active {active * .9999}")
    lines = replace_row(lines, "PIC AREA bg ", f"PIC AREA bg {total - core * .9999}")
    lines[-1:-1] = [f"PIC AREA_MESH {label} {value}" for label, value in
                   (("core", core), ("active", active), ("bg", total - core), ("all", total))]
    return geometry, config, lines


def test_curved_mesh_integration_is_distinct_from_rendering_area_without_looser_tolerance():
    geometry, config, lines = synthetic_curved_areas()
    result = parse_native_output("\n".join(lines), geometry, config)
    assert result["areas_um2"]["core"] == pytest.approx(geometry["expected_core_area_um2"])
    assert result["render_areas_um2"]["core"] < result["areas_um2"]["core"] * .99995
    assert result["physics_accepted"] is False


@pytest.mark.parametrize("fault", ["missing", "partial", "duplicate", "nonfinite", "wrong_active", "disabled"])
def test_curved_area_protocol_cannot_hide_missing_or_changed_actual_mesh_geometry(fault):
    geometry, config, lines = synthetic_curved_areas()
    if fault == "missing":
        lines = [line for line in lines if not line.startswith("PIC AREA_MESH ")]
    elif fault == "partial":
        lines = [line for line in lines if not line.startswith("PIC AREA_MESH bg ")]
    elif fault == "duplicate":
        lines += [next(line for line in lines if line.startswith("PIC AREA_MESH core "))]
    elif fault == "nonfinite":
        lines = replace_row(lines, "PIC AREA_MESH core ", "PIC AREA_MESH core NaN")
    elif fault == "wrong_active":
        lines = replace_row(lines, "PIC AREA_MESH active ", "PIC AREA_MESH active 0")
    else:
        config["measure_mesh_area"] = False
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(lines), geometry, config)


def test_catalog_separates_preparation_execution_and_physical_acceptance():
    catalog = native_catalog()
    assert set(catalog["families"]) == {"straight", "crossing", "directional-coupler", "mmi2x2", "ybranch",
                                        "ring", "ring-modulator"}
    assert catalog["preparation_executes_solver"] is False
    assert catalog["physics_accepted"] is False


@pytest.mark.parametrize("family", ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch"))
def test_requests_preserve_native_geometry_and_single_scalar_port_level(family):
    geometry, config = native_request(request(family))
    assert geometry["family"] == family
    assert geometry["model_level"] == "2d-scalar-index-surrogate"
    assert config["wavelengths_nm"] == [1530.0, 1550.0]
    assert config["core_index"] == 2.6
    assert config["cladding_index"] == 1.45
    assert config["stage"] == "solve"


@pytest.mark.parametrize("updates", [
    {"schema_version": "2.0"}, {"family": "not-a-family"}, {"execute": True},
    {"parameters": []}, {"parameters": {"widht_um": 0.3}}, {"wavelengths_nm": []},
    {"wavelengths_nm": [1550, 1550]}, {"wavelengths_nm": [1550, 1530]}, {"wavelengths_nm": [True]},
    {"wavelengths_nm": [1550, math.nan]}, {"wavelengths_nm": [1199]}, {"wavelengths_nm": [1701]},
    {"wavelengths_nm": [1550] * 129}, {"materials": {"core_index": 1.4, "cladding_index": 1.45}},
    {"materials": {"core_index": math.inf}}, {"materials": {"core_index": 10**500}},
    {"materials": {"epsilon": 12}}, {"mesh": {"core_mesh_um": 0.001}},
    {"mesh": {"cladding_mesh_um": True}}, {"mesh": {"unused": 1}},
    {"stage": "accept"}, {"pn": {}},
])
def test_invalid_requests_reject_before_native_preparation(updates):
    with pytest.raises(InvalidInputError):
        native_request(request(**updates))


def test_scalar_slab_cutoff_rejects_second_bound_mode_including_equality():
    wavelength, ncore, nclad = 1550.0, 2.6, 1.45
    cutoff = wavelength / 1000 / (2 * math.sqrt(ncore * ncore - nclad * nclad))
    native_request(request("straight", wavelengths_nm=[wavelength], parameters={"width_um": cutoff * (1 - 1e-8)}))
    for width in (cutoff, cutoff * (1 + 1e-8)):
        with pytest.raises(InvalidInputError, match="additional scalar slab modes"):
            native_request(request("straight", wavelengths_nm=[wavelength], parameters={"width_um": width}))
    # Shortest requested wavelength, not mean or longest, controls coverage.
    with pytest.raises(InvalidInputError, match="additional scalar slab modes"):
        native_request(request("straight", wavelengths_nm=[1200.0, 1700.0]))


@pytest.mark.parametrize("payload", [
    '{"family":"crossing","family":"straight"}',
    '{"parameters":{"width_um":0.3,"width_um":0.2}}',
    '{"wavelengths_nm":[NaN]}', '{"wavelengths_nm":[Infinity]}', '{"wavelengths_nm":[-Infinity]}',
    '[]', 'null',
])
def test_json_loader_rejects_duplicate_keys_nonfinite_tokens_and_nonobjects(tmp_path, payload):
    path = tmp_path / "synthetic.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_native_json(path)


@pytest.mark.parametrize("family", ("crossing", "ybranch"))
def test_complete_four_and_three_port_axes_recover_exact_complex_matrices(family):
    result, wanted = parse_case(family)
    actual = np.array(result["s_matrices"])
    np.testing.assert_allclose(actual[..., 0] + 1j * actual[..., 1], [wanted, wanted], atol=2e-15)
    assert result["physics_accepted"] is False
    for diagnostic in result["diagnostics"]:
        assert diagnostic["max_singular_value"] == pytest.approx(1, abs=2e-15)
        assert diagnostic["max_power_reciprocity_gap"] < 2e-15
        for column in diagnostic["columns"]:
            assert column["guided_power_sum"] == pytest.approx(1, abs=2e-15)
            assert column["signed_power_balance"] == pytest.approx(0, abs=2e-15)
            assert column["max_port_flux_modal_gap"] < 2e-15


@pytest.mark.parametrize("prefix", ("PIC S ", "PIC MODE ", "PIC SOURCE ", "PIC FLUX ", "PIC CORE_END ",
                                    "PIC AREA ", "PIC UNIT_CODEPOINTS ", "PIC GEOMETRY_PASS", "PIC PORTS_PASS",
                                    "PIC STAGE ", "PIC COMPLETE "))
@pytest.mark.parametrize("mutation", ("missing", "duplicate"))
def test_missing_and_duplicate_native_rows_are_rejected(prefix, mutation):
    geometry, config, lines, _ = synthetic_case()
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    if mutation == "missing":
        del lines[index]
    else:
        lines.insert(index, lines[index])
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(lines), geometry, config)


@pytest.mark.parametrize("prefix, replacement", [
    ("PIC S ", "PIC S 1530 1 1 NaN 0"),
    ("PIC MODE ", "PIC MODE 1530 1 2.18 Infinity"),
    ("PIC SOURCE ", "PIC SOURCE 1530 1 NaN"),
    ("PIC FLUX ", "PIC FLUX 1530 1 p1 NaN"),
    ("PIC AREA core ", "PIC AREA core NaN"),
    ("PIC CORE_END 1 ", "PIC CORE_END 1 NaN"),
    ("PIC SOURCE ", "PIC SOURCE 1530 1 2"),
    ("PIC S ", "PIC S 1531 1 1 0 0"),
    ("PIC S ", "PIC S 1530 0 1 0 0"),
    ("PIC MODE ", "PIC MODE 1530 1 1.44 0"),
    ("PIC MODE ", "PIC MODE 1530 1 2.61 0"),
    ("PIC MODE ", "PIC MODE 1530 1 2.18 0.01"),
])
def test_nonfinite_or_misidentified_actual_native_axes_are_rejected(prefix, replacement):
    geometry, config, lines, _ = synthetic_case()
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(replace_row(lines, prefix, replacement)), geometry, config)


@pytest.mark.parametrize("unit", ("[117, 109]", "[181, 109]", "[956, 109]"))
def test_real_micrometre_unit_spellings_are_equivalent_without_rescaling(unit):
    geometry, config, lines, _ = synthetic_case()
    changed = replace_row(lines, "PIC UNIT_CODEPOINTS ", "PIC UNIT_CODEPOINTS " + unit)
    result = parse_native_output("\n".join(changed), geometry, config)
    assert result["areas_um2"]["all"] == 36


@pytest.mark.parametrize("unit", ("[63, 109]", "[109, 109]", "[]", "null", '"um"', "not-json"))
def test_replacement_characters_and_wrong_geometry_units_are_rejected(unit):
    geometry, config, lines, _ = synthetic_case()
    with pytest.raises(InvalidInputError, match="unit"):
        parse_native_output("\n".join(replace_row(lines, "PIC UNIT_CODEPOINTS ",
                                                 "PIC UNIT_CODEPOINTS " + unit)), geometry, config)


@pytest.mark.parametrize("prefix, replacement", [
    ("PIC AREA core ", "PIC AREA core 3.6"),
    ("PIC AREA active ", "PIC AREA active 4"),
    ("PIC AREA bg ", "PIC AREA bg 0"),
    ("PIC AREA all ", "PIC AREA all 35"),
    ("PIC CORE_END 1 ", "PIC CORE_END 1 0.31"),
])
def test_actual_geometry_material_partition_and_port_widths_are_required(prefix, replacement):
    geometry, config, lines, _ = synthetic_case()
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(replace_row(lines, prefix, replacement)), geometry, config)


@pytest.mark.parametrize("stage", ("configure", "modes"))
def test_non_driven_stages_have_no_exportable_scattering(stage):
    result, _ = parse_case(stage=stage)
    assert result["s_matrices"] == []
    with pytest.raises(InvalidInputError, match="driven"):
        native_scattering_csv(result)


def test_signed_flux_disagreement_is_preserved_as_diagnostic_not_silently_normalized():
    geometry, config, lines, wanted = synthetic_case()
    changed = replace_row(lines, "PIC FLUX 1530.0 1 p2 ", "PIC FLUX 1530.0 1 p2 0.7")
    result = parse_native_output("\n".join(changed), geometry, config)
    column = result["diagnostics"][0]["columns"][0]
    assert column["max_port_flux_modal_gap"] == pytest.approx(0.3, abs=1e-15)
    assert column["signed_power_balance"] == pytest.approx(-0.3, abs=1e-15)
    actual = np.array(result["s_matrices"])[0]
    np.testing.assert_allclose(actual[..., 0] + 1j * actual[..., 1], wanted, atol=1e-15)
    assert result["physics_accepted"] is False


def test_negative_absorption_or_inward_open_flux_is_reported_without_clipping():
    geometry, config, lines, _ = synthetic_case()
    changed = replace_row(lines, "PIC FLUX 1530.0 1 abs ", "PIC FLUX 1530.0 1 abs -0.07")
    changed = replace_row(changed, "PIC FLUX 1530.0 1 open ", "PIC FLUX 1530.0 1 open -0.03")
    result = parse_native_output("\n".join(changed), geometry, config)
    column = result["diagnostics"][0]["columns"][0]
    assert column["absorbed_power"] == -0.07
    assert column["open_flux"] == -0.03
    assert column["signed_power_balance"] == pytest.approx(-0.1)


@pytest.mark.parametrize("family", ("crossing", "ybranch"))
def test_native_csv_contains_all_named_port_pairs_and_reuses_existing_complex_loader(tmp_path, family):
    result, wanted = parse_case(family)
    text = native_scattering_csv(result)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2 * len(result["port_order"]) ** 2
    assert {(row["out_port"], row["in_port"]) for row in rows} == {
        (out_port, in_port) for out_port in result["port_order"] for in_port in result["port_order"]}
    path = tmp_path / "native.csv"
    path.write_text(text, encoding="utf-8")
    # Retain the native scalar level. A raw CSV roundtrip does not relabel this
    # surrogate as 2D EIM or accept a complete circuit model contract.
    component = {"ports": result["port_order"], "sparameters": path.name,
                 "model_level": result["model_level"], "passive": True}
    loaded = load_component_data(tmp_path / "assembly.json", "synthetic-native", component, project_root=tmp_path)
    assert loaded.ports == tuple(result["port_order"])
    assert loaded.wavelengths_nm == (1530.0, 1550.0)
    for wavelength in loaded.wavelengths_nm:
        np.testing.assert_allclose(loaded.matrices[wavelength], wanted, atol=1e-15)


def test_two_native_crossings_compose_without_upgrading_their_scalar_model_level(tmp_path):
    result, _ = parse_case("crossing")
    (tmp_path / "crossing.csv").write_text(native_scattering_csv(result), encoding="utf-8")
    component = {
        "ports": result["port_order"],
        "port_modes": dict.fromkeys(result["port_order"], "scalar_bound_fundamental"),
        "model_level": result["model_level"],
        "reference_plane": "actual native exterior faces in one unmodified port basis",
        "sparameters": "crossing.csv", "passive": True,
    }
    manifest = {
        "schema_version": "1.0",
        "conventions": {"wavelength_unit": "nm", "sparameter_normalization": "power-wave",
                        "time_dependence": "exp(+iwt)"},
        "components": {"crossing": component},
        "instances": {"a": {"component": "crossing"}, "b": {"component": "crossing"}},
        "connections": [["a:east", "b:west"]],
        "external_ports": {"left": "a:west", "right": "b:east", "a_south": "a:south", "a_north": "a:north",
                           "b_south": "b:south", "b_north": "b:north"},
    }
    path = tmp_path / "assembly.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, data = validate_manifest(path, project_root=tmp_path)
    assert loaded["components"]["crossing"]["model_level"] == "2d-scalar-index-surrogate"
    rows, summary = compose(loaded, data)
    assert summary["wavelength_count"] == 2
    ports = list(manifest["external_ports"])
    index = {name: position for position, name in enumerate(ports)}
    wanted = np.zeros((6, 6), dtype=complex)
    wanted[0, 1] = wanted[1, 0] = np.exp(0.6j)
    wanted[2, 3] = wanted[3, 2] = np.exp(-0.2j)
    wanted[4, 5] = wanted[5, 4] = np.exp(-0.2j)
    for wavelength in result["wavelengths_nm"]:
        selected = [row for row in rows if float(row["wavelength_nm"]) == wavelength]
        assert len(selected) == 36
        actual = np.zeros((6, 6), dtype=complex)
        for row in selected:
            actual[index[row["out_port"]], index[row["in_port"]]] = complex(float(row["s_real"]), float(row["s_imag"]))
        np.testing.assert_allclose(actual, wanted, atol=2e-12)


@pytest.mark.parametrize("mutation", ("truncated", "nonfinite", "wavelength_count"))
def test_scattering_export_rejects_mutated_incomplete_or_nonfinite_results(mutation):
    result, _ = parse_case()
    if mutation == "truncated":
        result["s_matrices"][0] = result["s_matrices"][0][:1]
    elif mutation == "nonfinite":
        result["s_matrices"][0][0][0][0] = math.nan
    else:
        result["wavelengths_nm"].append(1570)
    with pytest.raises(InvalidInputError):
        native_scattering_csv(result)


def test_mesh_comparison_uses_power_without_claiming_cross_model_gauge_alignment():
    coarse, matrix = parse_case()
    row_gauge = np.exp(1j * np.array([0.1, -0.2, 0.7, -1.2]))
    column_gauge = np.exp(1j * np.array([-0.8, 0.2, -0.5, 0.4]))
    fine, _ = parse_case(matrix=row_gauge[:, None] * matrix * column_gauge[None, :])
    comparison = compare_native_meshes(coarse, fine)
    assert comparison["max_absolute_power_change"] < 4e-16
    assert comparison["physics_accepted"] is False
    assert comparison["complex_phase_convergence"].startswith("not asserted")
    different, _ = parse_case(matrix=0.8 * matrix)
    assert compare_native_meshes(coarse, different)["max_absolute_power_change"] == pytest.approx(0.36)


@pytest.mark.parametrize("mutation", ("family", "port_order", "wavelengths_nm", "model_level",
                                     "truncated", "nonfinite"))
def test_mesh_comparison_requires_identical_physical_axes_and_complete_finite_matrices(mutation):
    coarse, _ = parse_case()
    fine = copy.deepcopy(coarse)
    if mutation == "family":
        fine["family"] = "mmi2x2"
    elif mutation == "port_order":
        fine["port_order"].reverse()
    elif mutation == "wavelengths_nm":
        fine["wavelengths_nm"][0] = 1531.0
    elif mutation == "model_level":
        fine["model_level"] = "full-wave-3d"
    elif mutation == "truncated":
        coarse["s_matrices"] = fine["s_matrices"] = [[[[0.0, 0.0]]]]
    else:
        coarse["s_matrices"][0][0][0][0] = math.nan
        fine["s_matrices"][0][0][0][0] = math.nan
    with pytest.raises(InvalidInputError):
        compare_native_meshes(coarse, fine)


@pytest.mark.parametrize("stage", ("modes", "solve"))
@pytest.mark.parametrize("prefix", ("PIC MODE ", "PIC MODE_ANCHOR ", "PIC MODE_POWER "))
@pytest.mark.parametrize("mutation", ("missing", "duplicate", "nonfinite"))
def test_selected_mode_stages_require_all_finite_unique_branches_anchors_and_normalizations(stage, prefix, mutation):
    geometry, config, lines, _ = synthetic_case(stage=stage)
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    if mutation == "missing":
        del lines[index]
    elif mutation == "duplicate":
        lines.insert(index, lines[index])
    else:
        fields = lines[index].split()
        fields[-1] = "NaN"
        lines[index] = " ".join(fields)
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(lines), geometry, config)


@pytest.mark.parametrize("stage", ("modes", "solve"))
@pytest.mark.parametrize("prefix, replacement", [
    ("PIC MODE ", "PIC MODE 1530 1 1.4 0"),
    ("PIC MODE_ANCHOR ", "PIC MODE_ANCHOR 1530 1 0 0"),
    ("PIC MODE_POWER ", "PIC MODE_POWER 1530 1 0.5"),
])
def test_selected_mode_stages_reject_unbound_branches_zero_anchor_and_wrong_power(stage, prefix, replacement):
    geometry, config, lines, _ = synthetic_case(stage=stage)
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(replace_row(lines, prefix, replacement)), geometry, config)


@pytest.mark.parametrize("stage", ("configure", "modes"))
def test_non_driven_stage_cannot_silently_consume_mixed_driven_records(stage):
    geometry, config, lines, _ = synthetic_case(stage=stage)
    lines.insert(-1, "PIC S 1530 1 1 0 0")
    with pytest.raises(InvalidInputError):
        parse_native_output("\n".join(lines), geometry, config)


def synthetic_receipt(tmp_path):
    """Byte-bound fake-class fixture; explicitly not native execution evidence."""
    from photonic_workflow.native_backend import prepare_native_bundle

    geometry, config, lines, _ = synthetic_case(stage="configure")
    bundle, run = tmp_path / "bundle", tmp_path / "run"
    prepare_native_bundle(bundle, geometry, config)
    run.mkdir()
    shutil.copyfile(bundle / "NativePic.java", run / "NativePic.java")
    (run / "NativePic.class").write_bytes(b"synthetic test bytes; no native or Java execution")
    (run / "console.log").write_text("\n".join(lines), encoding="utf-8")

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    receipt = {"schema_version": "1.0", "status": "completed", "family": "crossing", "stage": "configure",
               "bundle": str(bundle), "manifest_sha256": digest(bundle / "manifest.json"),
               "java_sha256": digest(run / "NativePic.java"), "class_sha256": digest(run / "NativePic.class"),
               "artifacts": []}
    for name in ("NativePic.java", "NativePic.class", "console.log"):
        receipt["artifacts"].append({"path": name, "bytes": (run / name).stat().st_size,
                                     "sha256": digest(run / name)})
    path = run / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, receipt


def test_receipt_binding_retains_unauthenticated_local_status_and_never_promotes_physics(tmp_path):
    path, receipt = synthetic_receipt(tmp_path)
    result = calibrate_native_run(path)
    assert result["physics_accepted"] is False
    assert result["s_matrices"] == []
    assert result["provenance"]["manifest_sha256"] == receipt["manifest_sha256"]
    assert "not independently authenticated" in result["provenance"]["source"]


@pytest.mark.parametrize("mutation", ("java", "class", "console", "missing", "duplicate", "path_escape",
                                      "manifest", "family", "stage", "failed"))
def test_receipt_source_class_console_members_and_bundle_identity_cannot_be_substituted(tmp_path, mutation):
    path, receipt = synthetic_receipt(tmp_path)
    if mutation in {"java", "class", "console"}:
        name = {"java": "NativePic.java", "class": "NativePic.class", "console": "console.log"}[mutation]
        target = path.parent / name
        target.write_bytes(target.read_bytes() + b"\nsynthetic changed content")
        if mutation != "console":
            artifact = next(row for row in receipt["artifacts"] if row["path"] == name)
            artifact.update(bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            if mutation == "java":
                receipt["java_sha256"] = artifact["sha256"]
    elif mutation == "missing":
        receipt["artifacts"] = receipt["artifacts"][:-1]
    elif mutation == "duplicate":
        receipt["artifacts"].append(receipt["artifacts"][0])
    elif mutation == "path_escape":
        receipt["artifacts"][0]["path"] = "../elsewhere.java"
    elif mutation == "manifest":
        receipt["manifest_sha256"] = "0" * 64
    elif mutation == "family":
        receipt["family"] = "ybranch"
    elif mutation == "stage":
        receipt["stage"] = "solve"
    else:
        receipt["status"] = "failed"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(InvalidInputError):
        calibrate_native_run(path)
