"""Exercise the documented commands without a vendor API or license."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from photonic_workflow.cli import main


def invoke(arguments):
    output = io.StringIO()
    with redirect_stdout(output):
        code = main([*arguments, "--json"])
    return code, json.loads(output.getvalue())


def test_geometry_and_sparameter_commands_write_usable_artifacts(tmp_path):
    examples = Path(__file__).resolve().parents[1] / "examples/lumerical"
    output = tmp_path / "geometry"
    code, report = invoke(["lumerical", "export-geometry", str(examples / "crossing-geometry.json"),
                           "--output", str(output), "--height-um", "0.22", "--core-index", "3.48"])
    assert code == 0 and report["data"]["native_execution"] is False
    assert (output / "geometry.lsf").is_file()
    code, report = invoke(["lumerical", "import-sparameters", str(examples / "sparameters.json"),
                           "--output", str(tmp_path / "s.csv"), "--project-root", str(tmp_path),
                           "--target-time-dependence", "exp(+iwt)"])
    assert code == 0 and report["ok"]
    assert (tmp_path / "s.csv.source.json").read_bytes() == (examples / "sparameters.json").read_bytes()
    assert json.loads((tmp_path / "s.csv.metadata.json").read_text())["conventions"]["time_dependence"] == "exp(+iwt)"


@pytest.mark.parametrize("status,code", [("failed", 5), ("timeout", 8), ("cleanup_failed", 5)])
def test_run_propagates_failure_codes_without_claiming_success(tmp_path, monkeypatch, status, code):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"schema_version": "1.0", "operation": "mode-waveguide", "parameters": {}}))
    monkeypatch.setattr("photonic_workflow.lumerical.run_request", lambda *args, **kwargs: {
        "status": status, "native_execution": False, "solve_completed": False,
    })
    actual, report = invoke(["lumerical", "run", str(request), "--output", str(tmp_path / "absent")])
    assert actual == code and report["ok"] is False
    assert report["data"]["solve_completed"] is False
