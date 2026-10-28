"""Real main entrypoint, strict input parsing and circuit-ready device exports."""

from __future__ import annotations

import csv
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
import pytest

from photonic_workflow.circuits import compose, validate_manifest
from photonic_workflow.cli import main

EXAMPLES = Path(__file__).resolve().parents[2] / "examples/device-models"


def invoke(arguments):
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        code = main(arguments)
    return code, output.getvalue(), error.getvalue()


def test_list_and_seven_example_evaluations_use_main():
    code, output, error = invoke(["device", "list", "--json"])
    assert (code, error) == (0, ""), output
    models = json.loads(output)["data"]["models"]
    assert len(models) == 7
    for model in models:
        source = EXAMPLES / (model["model"] + ".json")
        code, output, error = invoke(["device", "evaluate", str(source), "--json"])
        assert (code, error) == (0, "")
        result = json.loads(output)["data"]
        assert result["model"] == model["model"]
        assert len(result["s_matrices"]) == 5
        assert result["physics_accepted"] is False and result["will_execute"] is False


@pytest.mark.parametrize("model,ports", [
    ("mmi2x2-ideal", {"upper_left", "lower_left", "upper_right", "lower_right"}),
    ("ybranch-ideal", {"trunk", "upper", "lower"}),
])
def test_ideal_cli_exports_all_port_pairs_per_wavelength(tmp_path, model, ports):
    project = tmp_path / f"{model}-project"
    assert invoke(["init", str(project), "--json"])[0] == 0
    code, output, error = invoke([
        "device", "export", str(EXAMPLES / f"{model}.json"),
        "--output", "components/sparameters/ideal.csv", "--project-root", str(project), "--json",
    ])
    assert (code, error) == (0, "")
    report = json.loads(output)["data"]
    rows = list(csv.DictReader(io.StringIO((project / report["artifact_path"]).read_text(encoding="utf-8"))))
    assert len(rows) == 5 * len(ports) ** 2
    for wavelength in {row["wavelength_nm"] for row in rows}:
        assert {(row["out_port"], row["in_port"]) for row in rows if row["wavelength_nm"] == wavelength} == {
            (out_port, in_port) for out_port in ports for in_port in ports
        }


@pytest.mark.parametrize("text,reason", [
    ('{"schema_version":"1.0","schema_version":"1.0"}', "duplicate JSON key"),
    ('{"parameters":{"length_um":1,"length_um":2}}', "duplicate JSON key"),
    ('{"parameters":{"neff":NaN}}', "non-finite JSON number"),
    ('{"parameters":{"neff":Infinity}}', "non-finite JSON number"),
    ('{"parameters":{"neff":-Infinity}}', "non-finite JSON number"),
    ('{"schema_version":', ""),
])
def test_json_parser_rejects_duplicates_and_nonfinite_tokens(tmp_path, text, reason):
    source = tmp_path / "bad.json"
    source.write_text(text, encoding="utf-8")
    code, output, error = invoke(["device", "evaluate", str(source), "--json"])
    assert (code, error) == (2, "")
    result = json.loads(output)
    assert result["ok"] is False
    assert reason in " ".join(result["errors"])


@pytest.mark.parametrize("edit", ["unknown_root", "unknown_parameter", "missing", "bool", "overflow", "version"])
def test_cli_model_envelope_rejects_wrong_fields_and_numeric_types(tmp_path, edit):
    payload = json.loads((EXAMPLES / "waveguide.json").read_text(encoding="utf-8"))
    if edit == "unknown_root":
        payload["execute"] = True
    elif edit == "unknown_parameter":
        payload["parameters"]["width_um"] = 0.5
    elif edit == "missing":
        del payload["parameters"]["loss_db_per_cm"]
    elif edit == "bool":
        payload["parameters"]["neff"] = True
    elif edit == "version":
        payload["schema_version"] = "2.0"
    text = json.dumps(payload)
    if edit == "overflow":
        text = text.replace('"neff": 2.4', '"neff": 1e999')
    source = tmp_path / "bad.json"
    source.write_text(text, encoding="utf-8")
    code, output, error = invoke(["device", "evaluate", str(source), "--json"])
    assert (code, error) == (2, "")
    assert json.loads(output)["ok"] is False


def test_export_roundtrips_through_real_assembly_and_preserves_existing_artifact(tmp_path):
    project = tmp_path / "project"
    code, _, error = invoke(["init", str(project), "--json"])
    assert (code, error) == (0, "")
    source = EXAMPLES / "waveguide.json"
    arguments = ["device", "export", str(source), "--output", "components/sparameters/analytic.csv",
                 "--project-root", str(project), "--json"]
    code, output, error = invoke(arguments)
    assert (code, error) == (0, "")
    report = json.loads(output)["data"]
    artifact = project / report["artifact_path"]
    data_before = artifact.read_bytes()
    reader = csv.DictReader(io.StringIO(data_before.decode("utf-8")))
    assert reader.fieldnames == ["wavelength_nm", "out_port", "in_port", "s_real", "s_imag"]
    assert len(list(reader)) == 20
    manifest = {
        "schema_version": "1.0",
        "conventions": {"wavelength_unit": "nm", "sparameter_normalization": "power-wave",
                        "time_dependence": "exp(+iwt)"},
        "components": {"propagation": report["component"]},
        "instances": {"first": {"component": "propagation"}, "second": {"component": "propagation"}},
        "connections": [["first:right", "second:left"]],
        "external_ports": {"in": "first:left", "out": "second:right"},
    }
    manifest_path = project / "analytic-assembly.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, data = validate_manifest(manifest_path, project_root=project)
    composed, summary = compose(loaded, data)
    assert summary["wavelength_count"] == 5
    assert summary["max_network_singular_value"] <= 1
    observed = [complex(float(row["s_real"]), float(row["s_imag"])) for row in composed
                if row["out_port"] == "out" and row["in_port"] == "in"]
    wavelengths = np.array([1520, 1535, 1550, 1565, 1580]) / 1000
    expected = 10 ** (-3 * 200 / 200000) * np.exp(-1j * 2 * np.pi * 2.4 * 200 / wavelengths)
    np.testing.assert_allclose(observed, expected, atol=1e-12)
    code, output, error = invoke(arguments)
    assert (code, error) == (2, "")
    assert "already exists" in " ".join(json.loads(output)["errors"])
    assert artifact.read_bytes() == data_before


def test_export_requires_project_and_rejects_path_escape(tmp_path):
    project = tmp_path / "project"
    assert invoke(["init", str(project), "--json"])[0] == 0
    source = str(EXAMPLES / "waveguide.json")
    for target in ("../outside.csv", str(tmp_path / "absolute-outside.csv")):
        code, output, error = invoke(["device", "export", source, "--output", target,
                                      "--project-root", str(project), "--json"])
        assert code == 7, (output, error)
    assert not (tmp_path / "outside.csv").exists()
    assert not (tmp_path / "absolute-outside.csv").exists()
    code, _, error = invoke(["device", "export", source, "--output", str(tmp_path / "no-root.csv")])
    assert code == 2 and "--project-root" in error
    assert not (tmp_path / "no-root.csv").exists()
