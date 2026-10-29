"""Exercise exact complex data and consumption by the existing circuit engine."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from photonic_workflow.circuits import compose, validate_manifest
from photonic_workflow.exceptions import InvalidInputError, SecurityViolationError
from photonic_workflow.lumerical_exchange import (
    dataset_from_arrays,
    export_lumerical_sparameters,
    load_lumerical_sparameters,
    normalize_lumerical_sparameters,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "lumerical" / "sparameters.json"


def fixture():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_sorts_complete_matrices_without_transposing_or_mutating_source():
    payload = fixture()
    original = copy.deepcopy(payload)
    data = normalize_lumerical_sparameters(payload)
    assert payload == original
    assert data["wavelengths_nm"] == [1540.0, 1560.0]
    assert data["source_sample_order"] == [1, 0]
    assert data["s_matrices"] == list(reversed(original["s_matrices"]))
    assert data["conventions"]["time_dependence"] == "exp(-iwt)"
    assert data["conversions"] == []
    assert data["physics_accepted"] is False


def test_explicit_time_conversion_conjugates_all_entries_only():
    payload = fixture()
    observed = normalize_lumerical_sparameters(payload, target_time_dependence="exp(+iwt)")
    original = normalize_lumerical_sparameters(payload)
    original_array = np.array(original["s_matrices"])
    observed_array = np.array(observed["s_matrices"])
    np.testing.assert_array_equal(observed_array[..., 0], original_array[..., 0])
    np.testing.assert_array_equal(observed_array[..., 1], -original_array[..., 1])
    assert observed["conversions"][0]["operation"] == "complex-conjugation"
    assert observed["channels"] == original["channels"]


@pytest.mark.parametrize("quantity,unit,values", [
    ("frequency", "Hz", [299792458 / 1560e-9, 299792458 / 1540e-9]),
    ("wavelength", "m", [1560e-9, 1540e-9]),
])
def test_explicit_frequency_and_si_wavelength_conversion(quantity, unit, values):
    payload = fixture()
    payload["spectral_axis"] = {"quantity": quantity, "unit": unit, "values": values}
    data = normalize_lumerical_sparameters(payload)
    np.testing.assert_allclose(data["wavelengths_nm"], [1540.0, 1560.0], atol=1e-12, rtol=0)
    assert data["s_matrices"] == list(reversed(payload["s_matrices"]))
    assert data["source_spectral_axis"] == payload["spectral_axis"]


def test_native_array_packing_requires_explicit_unsqueezed_axes():
    payload = fixture()
    values = np.array(payload["s_matrices"])
    matrix = values[..., 0] + 1j * values[..., 1]
    packed = dataset_from_arrays(
        matrix, spectral_axis=payload["spectral_axis"], channels=payload["channels"],
        producer=payload["producer"], model_level=payload["model_level"], passive=True,
        time_dependence="exp(-iwt)",
    )
    assert packed == payload
    for invalid in (matrix[0], matrix[..., None], np.ones((2, 2, 2), dtype=bool)):
        with pytest.raises(InvalidInputError):
            dataset_from_arrays(
                invalid, spectral_axis=payload["spectral_axis"], channels=payload["channels"],
                producer=payload["producer"], model_level="reduced", passive=True,
                time_dependence="exp(-iwt)",
            )


def test_export_is_consumed_by_existing_validator_and_complex_cascade(tmp_path):
    source = tmp_path / "native.json"
    source.write_bytes(EXAMPLE.read_bytes())
    raw_before = source.read_bytes()
    receipt = export_lumerical_sparameters(source, Path("data/native.csv"), project_root=tmp_path)
    assert source.read_bytes() == raw_before
    assert receipt["source"]["sha256"] == hashlib.sha256(raw_before).hexdigest()
    assert (tmp_path / receipt["source"]["artifact_path"]).read_bytes() == raw_before
    metadata = json.loads((tmp_path / receipt["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["channels"] == fixture()["channels"]
    assert metadata["source_sample_order"] == [1, 0]
    assert metadata["s_matrices"]["sha256"] == receipt["sha256"]
    manifest = {
        "schema_version": "1.0", "conventions": receipt["conventions"],
        "components": {"native": receipt["component"]},
        "instances": {"first": {"component": "native"}, "second": {"component": "native"}},
        "connections": [["first:right", "second:left"]],
        "external_ports": {"in": "first:left", "out": "second:right"},
    }
    manifest_path = tmp_path / "assembly.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, component_data = validate_manifest(manifest_path, project_root=tmp_path)
    rows, summary = compose(loaded, component_data)
    assert summary["wavelength_count"] == 2
    amplitudes = {
        (float(row["wavelength_nm"]), row["out_port"], row["in_port"]):
            complex(float(row["s_real"]), float(row["s_imag"]))
        for row in rows
    }
    assert amplitudes[(1540, "out", "in")] == pytest.approx((0.5 + 0.3j) ** 2)
    assert amplitudes[(1540, "in", "out")] == pytest.approx((0.3 - 0.4j) ** 2)
    assert amplitudes[(1560, "out", "in")] == pytest.approx((0.6 + 0.2j) ** 2)
    assert amplitudes[(1560, "in", "out")] == pytest.approx((0.4 - 0.3j) ** 2)
    with (tmp_path / receipt["artifact_path"]).open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == 8
    before = {path: path.read_bytes() for path in (tmp_path / receipt["artifact_path"],
                                                  tmp_path / receipt["metadata_path"])}
    with pytest.raises(InvalidInputError, match="already exists"):
        export_lumerical_sparameters(source, Path("data/native.csv"), project_root=tmp_path)
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_roundtrip_retains_binary64_real_and_imaginary_amplitudes(tmp_path):
    payload = fixture()
    real, imaginary = np.nextafter(0.4, 0.5).item(), np.nextafter(-0.3, -0.2).item()
    payload["s_matrices"][0][0][1] = [real, imaginary]
    source = tmp_path / "precision.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    receipt = export_lumerical_sparameters(source, Path("native.csv"), project_root=tmp_path)
    with (tmp_path / receipt["artifact_path"]).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row["wavelength_nm"] == "1560.0" and
               row["out_port"] == "left" and row["in_port"] == "right")
    assert float(row["s_real"]).hex() == real.hex()
    assert float(row["s_imag"]).hex() == imaginary.hex()


@pytest.mark.parametrize("case", [
    "unknown", "version", "missing_channel", "duplicate_id", "duplicate_mode", "missing_mode",
    "directions", "axis_order", "normalization", "power", "missing_matrix", "wrong_out", "wrong_in",
    "scalar", "nonfinite", "bool_amplitude", "duplicate_axis", "nonfinite_axis", "units", "passive",
    "product_object", "time_object", "empty_axis", "colon", "matrix_boolean", "wavelength_overflow",
    "nonrepresentable_integer", "surrogate",
])
def test_rejects_ambiguous_incomplete_or_invalid_data(case):
    payload = fixture()
    if case == "unknown":
        payload["arbitrary_script"] = "run;"
    elif case == "version":
        payload["schema_version"] = "2.0"
    elif case == "missing_channel":
        payload["channels"] = []
    elif case == "duplicate_id":
        payload["channels"][1]["id"] = "left"
    elif case == "duplicate_mode":
        payload["channels"][1]["port"] = "port 1"
    elif case == "missing_mode":
        del payload["channels"][0]["mode"]
    elif case == "directions":
        payload["channels"][0]["outgoing_direction"] = "Forward"
    elif case == "axis_order":
        payload["conventions"]["matrix_axes"] = ["spectral", "incoming", "outgoing"]
    elif case == "normalization":
        payload["conventions"]["sparameter_normalization"] = "electric-field"
    elif case == "power":
        payload["conventions"]["amplitude_encoding"] = "power"
    elif case == "missing_matrix":
        payload["s_matrices"].pop()
    elif case == "wrong_out":
        payload["s_matrices"][0].pop()
    elif case == "wrong_in":
        payload["s_matrices"][0][0].pop()
    elif case == "scalar":
        payload["s_matrices"][0][0][0] = 0.3
    elif case == "nonfinite":
        payload["s_matrices"][0][0][0] = [math_nan(), 0]
    elif case == "bool_amplitude":
        payload["s_matrices"][0][0][0] = [True, 0]
    elif case == "duplicate_axis":
        payload["spectral_axis"]["values"] = [1540, 1540]
    elif case == "nonfinite_axis":
        payload["spectral_axis"]["values"][0] = float("inf")
    elif case == "units":
        payload["spectral_axis"]["unit"] = "um"
    elif case == "passive":
        payload["passive"] = "true"
    elif case == "product_object":
        payload["producer"]["product"] = {}
    elif case == "time_object":
        payload["conventions"]["time_dependence"] = []
    elif case == "empty_axis":
        payload["spectral_axis"]["values"] = []
    elif case == "colon":
        payload["channels"][0]["id"] = "left:TE0"
    elif case == "matrix_boolean":
        payload["s_matrices"] = True
    elif case == "wavelength_overflow":
        payload["spectral_axis"] = {"quantity": "wavelength", "unit": "m", "values": [1e308, 1]}
    elif case == "nonrepresentable_integer":
        payload["s_matrices"][0][0][0] = [9007199254740993, 0]
    elif case == "surrogate":
        payload["channels"][0]["reference_plane"] = "\ud800"
    with pytest.raises(InvalidInputError):
        normalize_lumerical_sparameters(payload)


def math_nan():
    return float("nan")


@pytest.mark.parametrize("text", [
    '{"schema_version":"1.0","schema_version":"1.0"}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{', '[]',
])
def test_strict_json_reader(tmp_path, text):
    source = tmp_path / "bad.json"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_lumerical_sparameters(source)


def test_export_rejects_escape_and_existing_sidecar_without_partial_csv(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(SecurityViolationError):
        export_lumerical_sparameters(EXAMPLE, Path("../outside.csv"), project_root=root)
    sidecar = root / "native.csv.metadata.json"
    sidecar.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(InvalidInputError):
        export_lumerical_sparameters(EXAMPLE, Path("native.csv"), project_root=root)
    assert sidecar.read_text(encoding="utf-8") == "existing evidence"
    assert not (root / "native.csv").exists()


def test_source_archive_is_byte_exact_including_bom_crlf_and_trailing_whitespace(tmp_path):
    raw = b"\xef\xbb\xbf" + EXAMPLE.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") + b"\r\n  "
    source = tmp_path / "native.json"
    source.write_bytes(raw)
    receipt = export_lumerical_sparameters(source, Path("native.csv"), project_root=tmp_path)
    archived = tmp_path / receipt["source"]["artifact_path"]
    assert archived.read_bytes() == raw
    assert source.read_bytes() == raw
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == receipt["source"]["sha256"]
