"""Synthetic audit counterexamples; never establish solver or physical validity."""

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "examples/comsol-device-canary/audit.py"


@pytest.fixture
def audit_module():
    spec = importlib.util.spec_from_file_location("device_canary_audit_tests", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_text():
    """Complete ideal synthetic source/q/selection grid, not a native log."""
    entities = {"p1": [1, 2, 3], "p2": [4, 5, 6], "open": [7, 8], "allDomains": [1, 2]}
    lines = ["CANARY STAGE audit SHAPE straight", "CANARY MATERIAL_AUDIT_PASS",
             "CANARY EXTERIOR_PARTITION_PASS", "CANARY FLUX_DATASET dset1 solution=sol1"]
    for selection in ("p1", "p2", "open"):
        lines.append(f"CANARY BOUNDARY {selection} {entities[selection]}")
    for tag, selection in (("intp1", "p1"), ("intp2", "p2"), ("intopen", "open"), ("intabs", "allDomains")):
        lines.append(f"CANARY CPL_IDENTITY {tag} dimension={2 if selection == 'allDomains' else 1} "
                     f"selection={selection} entities={entities[selection]} method=integration")
    for port in (1, 2):
        lines.append(f"CANARY FLUX_SELECTION port={port} entities={entities[f'p{port}']} "
                     f"normal_x={-1 if port == 1 else 1} bbox_um=[{0 if port == 1 else 14}, "
                     f"{0 if port == 1 else 14}, -1.2, 1.2]")
    for source in (1, 2):
        lines.append(f"CANARY FLUX_SOURCE {source},{source},1550")
        for port in (1, 2):
            lines.append(f"CANARY FLUX_S {source},{port},{0 if source == port else 1},0")
    exact = 1e-6 * (math.exp(36) - math.exp(-36)) / 30
    counter = 0
    for q, error in ((2, 1e-2), (4, 1e-4), (6, 1e-9), (8, 1e-12)):
        for selection in ("open", "allDomains", "p1", "p1", "p2", "p2"):
            counter += 1
            lines.append(f"CANARY QUAD_EVAL quadEval{counter} selection={selection} "
                         f"dimension={2 if selection == 'allDomains' else 1} intorderactive=true "
                         f"order={q} entities={entities[selection]}")
        for port in (1, 2):
            for source in (1, 2):
                power = -1 if source == port else 1
                lines.append(f"CANARY FLUX_ORDER {source},{port},{q},{power},{power},1,0,0")
                lines.append(f"CANARY QUAD_CONTROL {source},{port},{q},{exact * (1-error)},"
                             f"{exact},-1.2,1.2")
    lines.append("CANARY FLUX_AUDIT_COMPLETED")
    return "\n".join(lines) + "\n"


def rejected(module, text):
    assert module.parse_audit(audit_text())["accepted"] is True
    try:
        report = module.parse_audit(text)
    except ValueError:
        return
    assert report["accepted"] is False


def test_complete_synthetic_audit_grid_is_accepted_only_as_parser_fixture(audit_module):
    assert audit_module.parse_audit(audit_text())["accepted"] is True


@pytest.mark.parametrize("prefix", ["CANARY FLUX_SOURCE 2,", "CANARY FLUX_S 2,1,",
                                    "CANARY FLUX_ORDER 1,2,8,", "CANARY QUAD_CONTROL 2,1,8,",
                                    "CANARY QUAD_EVAL quadEval24 ", "CANARY FLUX_DATASET ",
                                    "CANARY CPL_IDENTITY intabs ",
                                    "CANARY FLUX_AUDIT_COMPLETED"])
def test_missing_required_audit_row_rejected(audit_module, prefix):
    text = "\n".join(line for line in audit_text().splitlines() if not line.startswith(prefix))
    rejected(audit_module, text)


@pytest.mark.parametrize("prefix", ["CANARY FLUX_SOURCE 1,", "CANARY FLUX_S 1,2,",
                                    "CANARY FLUX_ORDER 1,1,6,", "CANARY QUAD_CONTROL 1,1,6,",
                                    "CANARY QUAD_EVAL quadEval1 ", "CANARY FLUX_DATASET ",
                                    "CANARY CPL_IDENTITY intabs ",
                                    "CANARY FLUX_AUDIT_COMPLETED"])
def test_duplicate_required_audit_row_rejected(audit_module, prefix):
    text = audit_text()
    duplicate = next(line for line in text.splitlines() if line.startswith(prefix))
    rejected(audit_module, text + duplicate + "\n")


@pytest.mark.parametrize("old,new", [
    ("FLUX_SOURCE 2,2,1550", "FLUX_SOURCE 2,1,1550"),
    ("FLUX_SOURCE 2,2,1550", "FLUX_SOURCE 2,2,1560"),
    ("FLUX_ORDER 1,1,6,", "FLUX_ORDER 1.5,1,6,"),
    ("FLUX_ORDER 1,1,6,", "FLUX_ORDER 1,1,7,"),
    ("FLUX_ORDER 1,1,6,-1,-1,1,0,0", "FLUX_ORDER 1,1,6,nan,-1,1,0,0"),
    ("selection=p1 dimension=1 intorderactive=true order=8 entities=[1, 2, 3]",
     "selection=p1 dimension=1 intorderactive=true order=8 entities=[99]"),
    ("selection=allDomains dimension=2", "selection=allDomains dimension=1"),
    ("intorderactive=true order=8", "intorderactive=false order=8"),
    ("CANARY STAGE audit SHAPE straight", "CANARY STAGE solve SHAPE straight"),
    ("FLUX_ORDER 1,1,6,-1,-1,1,0,0", "FLUX_ORDER 1,1,6,-1,inf,1,0,0"),
    ("FLUX_S 1,2,1,0", "FLUX_S 1,2,1,nan"),
    ("FLUX_DATASET dset1 solution=sol1", "FLUX_DATASET dset1 solution="),
    ("normal_x=-1", "normal_x=1"),
    ("dimension=1 intorderactive=true order=8", "dimension=1 intorderactive=true order=8.5"),
    ("intabs dimension=2 selection=allDomains entities=[1, 2]",
     "intabs dimension=2 selection=allDomains entities=[99]"),
])
def test_wrong_audit_identity_order_entities_and_nonfinite_rejected(audit_module, old, new):
    assert old in audit_text()
    rejected(audit_module, audit_text().replace(old, new))


def test_flat_positive_control_cannot_prove_quadrature_effectiveness(audit_module):
    lines = []
    for line in audit_text().splitlines():
        if line.startswith("CANARY QUAD_CONTROL "):
            values = line[len("CANARY QUAD_CONTROL "):].split(",")
            values[3] = values[4]
            line = "CANARY QUAD_CONTROL " + ",".join(values)
        lines.append(line)
    rejected(audit_module, "\n".join(lines))


def test_wrong_analytic_reference_cannot_pass_control(audit_module):
    lines = []
    for line in audit_text().splitlines():
        if line.startswith("CANARY QUAD_CONTROL "):
            values = line[len("CANARY QUAD_CONTROL "):].split(",")
            values[4] = str(float(values[4]) * 2)
            line = "CANARY QUAD_CONTROL " + ",".join(values)
        lines.append(line)
    rejected(audit_module, "\n".join(lines))


def test_wrong_checkpoint_digest_rejected_before_output_or_launch(audit_module, tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.mph"
    checkpoint.write_bytes(b"synthetic checkpoint; must never be executed")
    output = tmp_path / "audit-output"
    monkeypatch.setattr(sys, "argv", [str(SOURCE), "--checkpoint", str(checkpoint),
                                    "--checkpoint-sha256", "0" * 64, "--output", str(output)])
    monkeypatch.setattr(audit_module.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch prohibited"))
    with pytest.raises(SystemExit) as error:
        audit_module.main()
    assert error.value.code != 0
    assert not output.exists()


def test_valid_checkpoint_defaults_to_dry_run_without_native_launch(audit_module, tmp_path, monkeypatch, capsys):
    checkpoint = tmp_path / "checkpoint.mph"
    checkpoint.write_bytes(b"synthetic checkpoint; never native evidence")
    before = (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns)
    output = tmp_path / "audit-output"
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    monkeypatch.setattr(sys, "argv", [str(SOURCE), "--checkpoint", str(checkpoint),
                                    "--checkpoint-sha256", digest, "--output", str(output)])
    monkeypatch.setattr(audit_module.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch prohibited"))
    monkeypatch.setattr(audit_module.subprocess, "run", lambda *a, **k: pytest.fail("native launch prohibited"))
    assert audit_module.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "dryrun"
    assert plan["native_execution"] == "not_supported"
    assert not output.exists()
    assert (checkpoint.read_bytes(), checkpoint.stat().st_mtime_ns) == before


def test_physical_flux_gap_cannot_be_masked_by_successful_postprocessing(audit_module):
    text = audit_text()
    assert audit_module.parse_audit(text)["accepted"] is True
    lines = []
    for line in text.splitlines():
        if line.startswith("CANARY FLUX_ORDER "):
            values = line[len("CANARY FLUX_ORDER "):].split(",")
            if values[0] != values[1]:
                values[3] = values[4] = "1.012"
                line = "CANARY FLUX_ORDER " + ",".join(values)
        lines.append(line)
    report = audit_module.parse_audit("\n".join(lines))
    assert report["postprocessing_pass"] is True
    assert report["flux_gap_pass"] is False
    assert report["accepted"] is False
    assert report["physical_qualification"] == "not_established"


@pytest.mark.parametrize("prefix,replacement", [
    ("CANARY FLUX_AUDIT_COMPLETED", "CANARY FLUX_AUDIT_COMPLETED_ERROR"),
    ("CANARY MATERIAL_AUDIT_PASS", "CANARY MATERIAL_AUDIT_PASS_ERROR"),
    ("CANARY EXTERIOR_PARTITION_PASS", "CANARY EXTERIOR_PARTITION_PASS_ERROR"),
])
def test_marker_prefix_is_not_an_exact_success_marker(audit_module, prefix, replacement):
    rejected(audit_module, audit_text().replace(prefix, replacement))


def test_offline_report_does_not_overwrite_existing_output(audit_module, tmp_path, monkeypatch):
    assert audit_module.parse_audit(audit_text())["accepted"] is True
    checkpoint = tmp_path / "checkpoint.mph"
    checkpoint.write_bytes(b"synthetic checkpoint; never native evidence")
    console = tmp_path / "console.txt"
    console.write_text(audit_text(), encoding="utf-8")
    output = tmp_path / "audit-output"
    output.mkdir()
    sentinel = output / "audit.json"
    sentinel.write_bytes(b"existing evidence must survive")
    before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
    monkeypatch.setattr(sys, "argv", [str(SOURCE), "--checkpoint", str(checkpoint), "--checkpoint-sha256",
                                    hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--output", str(output),
                                    "--console", str(console)])
    monkeypatch.setattr(audit_module.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch prohibited"))
    with pytest.raises(SystemExit) as stopped:
        audit_module.main()
    assert stopped.value.code != 0
    assert (sentinel.read_bytes(), sentinel.stat().st_mtime_ns) == before


def test_mode_power_must_remain_unit_normalized(audit_module):
    assert audit_module.parse_audit(audit_text())["accepted"] is True
    lines = []
    for line in audit_text().splitlines():
        if line.startswith("CANARY FLUX_ORDER "):
            values = line[len("CANARY FLUX_ORDER "):].split(",")
            values[5] = "2"
            line = "CANARY FLUX_ORDER " + ",".join(values)
        lines.append(line)
    report = audit_module.parse_audit("\n".join(lines))
    assert report["gates"]["mode_power_normalized"] is False
    assert report["postprocessing_pass"] is False
    assert report["accepted"] is False


def test_offline_cli_exit_and_report_preserve_physical_gap_failure(audit_module, tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.mph"
    checkpoint.write_bytes(b"synthetic CLI fixture; never native evidence")
    monkeypatch.setattr(audit_module.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch prohibited"))
    monkeypatch.setattr(audit_module.subprocess, "run", lambda *a, **k: pytest.fail("native launch prohibited"))
    # One valid baseline followed by a physically failing S/flux comparison.
    for label, text, expected_exit in (("positive", audit_text(), 0),
                                      ("gap", audit_text().replace("FLUX_S 1,2,1,0", "FLUX_S 1,2,0.9,0"), 1)):
        console = tmp_path / f"{label}.txt"
        console.write_text(text, encoding="utf-8")
        output = tmp_path / label
        monkeypatch.setattr(sys, "argv", [str(SOURCE), "--checkpoint", str(checkpoint), "--checkpoint-sha256",
                                        hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "--output", str(output),
                                        "--console", str(console)])
        assert audit_module.main() == expected_exit
        report = json.loads((output / "audit.json").read_text(encoding="utf-8"))
        assert report["postprocessing_pass"] is True
        assert report["accepted"] is (expected_exit == 0)
        assert report["flux_gap_pass"] is (expected_exit == 0)
        assert report["physical_qualification"] == "not_established"


@pytest.mark.parametrize("column", [6, 7])
def test_source_wide_open_and_absorption_copies_cannot_disagree(audit_module, column):
    """A single altered port copy must not hide source-wide flux evidence."""
    lines = audit_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("CANARY FLUX_ORDER 1,2,8,"):
            values = line[len("CANARY FLUX_ORDER "):].split(",")
            values[column] = "0.125"
            lines[index] = "CANARY FLUX_ORDER " + ",".join(values)
    rejected(audit_module, "\n".join(lines))


def test_finite_scattering_input_with_overflowing_derived_power_rejected(audit_module):
    rejected(audit_module, audit_text().replace("FLUX_S 1,2,1,0", "FLUX_S 1,2,1e308,0"))


@pytest.mark.parametrize("failure", ["quadrature_drift", "explicit_flux_disagreement"])
def test_flux_modal_agreement_cannot_mask_failed_postprocessing(audit_module, failure):
    """Matching q8/S values do not excuse an unstable or inconsistent integral."""
    assert audit_module.parse_audit(audit_text())["accepted"] is True
    lines = []
    for line in audit_text().splitlines():
        if line.startswith("CANARY FLUX_ORDER 1,2,"):
            values = line[len("CANARY FLUX_ORDER "):].split(",")
            if failure == "explicit_flux_disagreement":
                values[4] = "0.99"
            elif values[2] == "6":
                values[3] = values[4] = "0.99"
            line = "CANARY FLUX_ORDER " + ",".join(values)
        lines.append(line)
    report = audit_module.parse_audit("\n".join(lines))
    assert report["flux_gap_pass"] is True
    assert report["postprocessing_pass"] is False
    assert report["accepted"] is False
