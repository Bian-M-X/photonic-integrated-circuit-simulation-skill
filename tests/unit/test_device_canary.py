"""Reject native identity ambiguity before any canary physics acceptance."""

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "examples/comsol-device-canary/run.py"
SPEC = importlib.util.spec_from_file_location("device_canary", SOURCE)
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


@pytest.mark.parametrize("stage", ["configure", "modes", "solve"])
@pytest.mark.parametrize("extra", ["duplicate", "conflicting_stage", "conflicting_shape", "suffix"])
def test_shared_stage_identity_rejects_ambiguous_native_stage_with_valid_positive(stage, extra):
    good = f"CANARY STAGE {stage} SHAPE straight"
    assert CANARY.stage_identity(good, stage, "straight") is True
    invalid = {"duplicate": good + "\n" + good,
               "conflicting_stage": good + "\nCANARY STAGE unknown SHAPE straight",
               "conflicting_shape": good + f"\nCANARY STAGE {stage} SHAPE taper",
               "suffix": good + "_ERROR"}[extra]
    assert CANARY.stage_identity(invalid, stage, "straight") is False


@pytest.mark.parametrize(
    "text",
    [
        "CANARY S 1.5,1,1,0,0",
        "CANARY S 1,1.5,1,0,0",
        "CANARY S 1,1,2,0,0",
        "CANARY S 1,1,1,nan,0",
        "CANARY SOURCE 1,1.5,1550",
        "CANARY POWER 1,0,0,0,0,2,2\nCANARY POWER 1,0,0,0,0,2,2",
        "CANARY FIELD 1,1550,0,0,1",
    ],
)
def test_reject_ambiguous_native_rows(text):
    with pytest.raises(ValueError):
        CANARY.parse_rows(text)


def test_source_mapping_keeps_only_declared_physical_entries():
    rows = CANARY.parse_rows("CANARY S 1,2,1,0.8,0.6\nCANARY SOURCE 1,1,1550\nCANARY SOURCE 2,2,1550")
    assert rows["S"] == [[1, 2, 1, 0.8, 0.6]]
    assert len(rows["SOURCE"]) == 2


@pytest.mark.parametrize(
    "text",
    [
        "CANARY CENSUS 1,-1,2.2,0",
        "CANARY CENSUS 1,6,2.2,0",
        "CANARY CENSUS 1,0,2.2,0\nCANARY CENSUS 1,0,2.1,0",
    ],
)
def test_census_rejects_out_of_range_and_duplicate_eigenpair_identity(text):
    with pytest.raises(ValueError):
        CANARY.parse_rows(text)


def test_terminal_error_suffix_does_not_count_as_native_completion(tmp_path):
    (tmp_path / "console.txt").write_text("CANARY NATIVE_COMPLETED_ERROR\n", encoding="utf-8")
    report = CANARY.analyze(tmp_path, "straight")
    assert report["gates"]["terminal_marker"]["status"] == "fail"


@pytest.mark.parametrize("source2_factor", [-1.0, 1.1, 1j])
def test_selected_mode_phase_changed_between_sources_blocks_complex_acceptance(tmp_path, source2_factor):
    """Identical source-1 modes cannot establish a source-independent basis."""
    lines = [
        "CANARY MATERIAL_AUDIT_PASS", "CANARY EXTERIOR_PARTITION_PASS", "CANARY CONFIGURATION_PASS",
        "CANARY NATIVE_COMPLETED", "CANARY SOURCE 1,1,1550", "CANARY SOURCE 2,2,1550",
        "CANARY S 1,1,1,0,0", "CANARY S 1,2,1,1,0", "CANARY S 2,1,2,1,0", "CANARY S 2,2,2,0,0",
        "CANARY POWER 1,0,0,-1,1,2.2,2.2", "CANARY POWER 2,0,0,1,-1,2.2,2.2",
    ]
    for port in (1, 2):
        for pair in range(6):
            lines.append(f"CANARY CENSUS {port},{pair},{2.2 if pair == 0 else 1.3},0")
    for source in (1, 2):
        for i in range(21):
            y = -1.2 + i * 0.12
            amplitude = math.exp(-(y / 0.2) ** 2)
            for port in (1, 2):
                # The second source has a genuine pi shift at port 2 only.
                factor = source2_factor if source == 2 and port == 2 else 1
                electric = complex(factor * amplitude)
                magnetic = electric if port == 1 else -electric
                lines.append(f"CANARY MODE{port} {source},1550,{0 if port == 1 else 14},{y},"
                             f"{electric.real},{electric.imag},{magnetic.real},{magnetic.imag}")
            lines.append(f"CANARY FIELD {source},1550,{i * 0.7},{y},1,0,1,0,0,0")
    (tmp_path / "console.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = CANARY.analyze(tmp_path, "straight")
    assert report["gates"]["complex_diagnostics"]["status"] != "pass"


def selected_mode_fixture(folder):
    """Synthetic parser input; this is deliberately not native mode evidence."""
    folder.mkdir(parents=True)
    (folder / "selected_modes.mph").write_bytes(b"synthetic parser checkpoint; not a native model" * 32)
    lines = ["CANARY STAGE modes SHAPE straight", "CANARY SELECTED_RUN_TO_COMPLETED", "CANARY MODES_COMPLETED"]
    neff = 2.1837000141287444
    for port in (1, 2):
        lines.append(f"CANARY SELECTED_DATASET port={port} dataset=dset{port} solution=sol{port} solnum=1")
        lines.append(f"CANARY SELECTED_SCALAR {port},{neff},0,1550,1")
        for pair in range(6):
            lines.append(f"CANARY CENSUS {port},{pair},{neff if pair == 0 else 1.3},0")
        for i in range(21):
            y = -1.2 + i * 0.12
            electric = math.exp(-(y / 0.2) ** 2)
            magnetic = (1 if port == 1 else -1) * neff / 376.730313668 * electric
            lines.append(f"CANARY SELECTED_FIELD {port},{y},{electric},0,{magnetic},0")
    (folder / "console.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def persist_synthetic_mode_evidence(folder, source_sha):
    """Test-owned evidence persistence; production parser remains read-only."""
    report = CANARY.analyze_modes(folder, "straight", source_sha)
    (folder / "mode_analysis.json").write_text(json.dumps(report), encoding="utf-8")
    for port in (1, 2):
        prefix = "CANARY SELECTED_FIELD "
        rows = [line[len(prefix):].split(",")[1:]
                for line in (folder / "console.txt").read_text(encoding="utf-8").splitlines()
                if line.startswith(prefix + f"{port},")]
        with (folder / f"selected_mode_port{port}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["y_um", "Ez_re", "Ez_im", "Hy_re", "Hy_im"])
            writer.writerows(rows)
    return report


def test_mode_parser_positive_fixture_is_explicitly_not_native_qualification(tmp_path):
    folder = selected_mode_fixture(tmp_path / "modes")
    report = CANARY.analyze_modes(folder, "straight", "synthetic-source-identity")
    assert report["accepted"] is True
    assert report["sampled_census_is_completeness_proof"] is False
    assert report["physical_qualification"] == "not_established"
    assert report["selected_checkpoint_sha256"] == CANARY.sha(folder / "selected_modes.mph")


def test_mode_parser_binds_actual_native_shape_before_acceptance(tmp_path):
    folder = selected_mode_fixture(tmp_path / "modes")
    report = CANARY.analyze_modes(folder, "taper", "synthetic-source-identity")
    assert report["accepted"] is False


@pytest.mark.parametrize("stage", [
    "CANARY STAGE solve SHAPE straight",
    "CANARY STAGE modes SHAPE taper",
    "CANARY STAGE modes SHAPE straight\nCANARY STAGE modes SHAPE taper",
    "CANARY STAGE modes SHAPE straight\nCANARY STAGE modes SHAPE straight",
    "CANARY STAGE modes SHAPE straight_ERROR",
])
def test_mode_parser_rejects_wrong_or_ambiguous_native_stage(tmp_path, stage):
    folder = selected_mode_fixture(tmp_path / "modes")
    console = folder / "console.txt"
    console.write_text(console.read_text(encoding="utf-8").replace(
        "CANARY STAGE modes SHAPE straight", stage), encoding="utf-8")
    assert CANARY.analyze_modes(folder, "straight", "synthetic-source-identity")["accepted"] is False


@pytest.mark.parametrize("marker", [
    "CANARY MODES_COMPLETED_ERROR",
    "CANARY MODES_COMPLETED\nCANARY MODES_COMPLETED",
])
def test_mode_parser_rejects_nonexact_or_repeated_terminal_marker(tmp_path, marker):
    folder = selected_mode_fixture(tmp_path / "modes")
    console = folder / "console.txt"
    console.write_text(console.read_text(encoding="utf-8").replace(
        "CANARY MODES_COMPLETED", marker), encoding="utf-8")
    assert CANARY.analyze_modes(folder, "straight", "synthetic-source-identity")["accepted"] is False


def test_mode_reanalysis_has_no_file_or_timestamp_side_effects(tmp_path):
    folder = selected_mode_fixture(tmp_path / "modes")
    CANARY.analyze_modes(folder, "straight", "synthetic-source-identity")
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir() if p.is_file()}
    report = CANARY.analyze_modes(folder, "straight", "synthetic-source-identity", report_name=None)
    assert report["accepted"] is True
    assert {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("replacement", [
    "port=2 dataset=dset1 solution=sol2 solnum=1",
    "port=2 solution=sol2 solnum=1",
    "port=2 dataset=dset2 solution= solnum=1",
    "port=99 port=2 dataset=dset2 solution=sol2 solnum=1",
])
def test_selected_dataset_identity_must_be_unique_complete_and_unambiguous(tmp_path, replacement):
    folder = selected_mode_fixture(tmp_path / "modes")
    console = folder / "console.txt"
    console.write_text(console.read_text(encoding="utf-8").replace(
        "port=2 dataset=dset2 solution=sol2 solnum=1", replacement), encoding="utf-8")
    try:
        report = CANARY.analyze_modes(folder, "straight", "synthetic-source-identity")
    except ValueError:
        return
    assert report["accepted"] is False


def resume_fixture(tmp_path):
    folder = selected_mode_fixture(tmp_path / "producer" / "straight_modes")
    java = SOURCE.with_name("DeviceCanary.java").read_bytes()
    (folder.parent / "original-source.java").write_bytes(java)
    (folder.parent / "runner-source.py").write_bytes(SOURCE.read_bytes())
    persist_synthetic_mode_evidence(folder, CANARY.sha(folder.parent / "original-source.java"))
    solver = tmp_path / "solver" / "bin" / "win64"
    solver.mkdir(parents=True)
    for name in ("comsolcompile.exe", "comsolbatch.exe"):
        (solver / name).write_bytes(b"placeholder for dry-run parser test; must never execute")
    arguments = ["run.py", "--output", str(tmp_path / "new-output"), "--solver-root", str(solver.parents[1]),
                 "--stop-after", "solve", "--restart", str(folder / "selected_modes.mph"),
                 "--mode-report", str(folder / "mode_analysis.json")]
    return folder, arguments


def test_resume_rejects_changed_checkpoint_before_output_or_launch(tmp_path, monkeypatch):
    folder, arguments = resume_fixture(tmp_path)
    source_sha = CANARY.sha(folder.parent / "original-source.java")
    assert CANARY.analyze_modes(folder, "straight", source_sha)["accepted"] is True
    (folder / "selected_modes.mph").write_bytes(b"tampered checkpoint" * 80)
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(CANARY.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch is prohibited"))
    with pytest.raises(SystemExit) as stopped:
        CANARY.main()
    assert stopped.value.code == 2
    assert not (tmp_path / "new-output").exists()


def test_resume_rejects_changed_frozen_geometry_source_before_launch(tmp_path, monkeypatch):
    folder, arguments = resume_fixture(tmp_path)
    (folder.parent / "original-source.java").write_bytes(b"changed geometry definition")
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(CANARY.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch is prohibited"))
    with pytest.raises(SystemExit) as stopped:
        CANARY.main()
    assert stopped.value.code == 2
    assert not (tmp_path / "new-output").exists()


def test_resume_validation_does_not_rewrite_frozen_mode_evidence(tmp_path, monkeypatch):
    folder, arguments = resume_fixture(tmp_path)
    paths = [folder / "mode_analysis.json", folder / "selected_mode_port1.csv", folder / "selected_mode_port2.csv"]
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in paths}
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(CANARY.subprocess, "Popen", lambda *a, **k: pytest.fail("dry-run must not launch native"))
    assert CANARY.main() == 0
    assert {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in paths} == before
    plan = json.loads((tmp_path / "new-output" / "plan.json").read_text(encoding="utf-8"))
    assert plan["will_execute"] is False


@pytest.mark.parametrize("field,value", [
    ("native_console_sha256", "0" * 64),
    ("selected_checkpoint_sha256", "0" * 64),
    ("original_java_sha256", "0" * 64),
    ("parser_sha256", "0" * 64),
    ("shape", "taper"),
    ("analytic_neff", 99),
])
def test_resume_rejects_tampered_mode_report_before_output_or_launch(tmp_path, monkeypatch, field, value):
    folder, arguments = resume_fixture(tmp_path)
    path = folder / "mode_analysis.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report[field] = value
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(CANARY.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch is prohibited"))
    with pytest.raises(SystemExit) as stopped:
        CANARY.main()
    assert stopped.value.code == 2
    assert not (tmp_path / "new-output").exists()


def test_resume_rejects_changed_producer_before_output_or_launch(tmp_path, monkeypatch):
    folder, arguments = resume_fixture(tmp_path)
    (folder.parent / "runner-source.py").write_bytes(b"changed evidence producer")
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(CANARY.subprocess, "Popen", lambda *a, **k: pytest.fail("native launch is prohibited"))
    with pytest.raises(SystemExit) as stopped:
        CANARY.main()
    assert stopped.value.code == 2
    assert not (tmp_path / "new-output").exists()


def driven_fixture(tmp_path):
    """Self-consistent synthetic input tests parser logic, never solver validity."""
    modes, _ = resume_fixture(tmp_path)
    folder = tmp_path / "driven" / "straight_solve"
    folder.mkdir(parents=True)
    (folder.parent / "original-source.java").write_bytes(SOURCE.with_name("DeviceCanary.java").read_bytes())
    copies = {"accepted_mode_report.json": modes / "mode_analysis.json",
              "input_modes.mph": modes / "selected_modes.mph",
              "predrive_console.txt": modes / "console.txt",
              "mode_exporter.java": modes.parent / "original-source.java",
              "accepted_parser.py": modes.parent / "runner-source.py"}
    for port in (1, 2):
        copies[f"predrive_mode_port{port}.csv"] = modes / f"selected_mode_port{port}.csv"
    for name, origin in copies.items():
        (folder / name).write_bytes(origin.read_bytes())
    binding = {"accepted_mode_report_sha256": CANARY.sha(folder / "accepted_mode_report.json"),
               "selected_checkpoint_sha256": CANARY.sha(folder / "input_modes.mph"),
               "mode_definition_sha256": CANARY.mode_definition_sha((folder / "mode_exporter.java").read_bytes()),
               "mode_exporter_original_java_sha256": CANARY.sha(folder / "mode_exporter.java")}
    (folder / "resume_binding.json").write_text(json.dumps(binding), encoding="utf-8")
    lines = ["CANARY STAGE solve SHAPE straight", "CANARY NATIVE_COMPLETED",
             "CANARY MATERIAL_AUDIT_PASS", "CANARY EXTERIOR_PARTITION_PASS", "CANARY CONFIGURATION_PASS",
             "CANARY RESUME_FROM_FROZEN sol1/st3", "CANARY SOURCE 1,1,1550", "CANARY SOURCE 2,2,1550",
             "CANARY S 1,1,1,0,0", "CANARY S 1,2,1,1,0", "CANARY S 2,1,2,1,0", "CANARY S 2,2,2,0,0"]
    for source in (1, 2):
        for port in (1, 2):
            with (folder / f"predrive_mode_port{port}.csv").open(encoding="utf-8", newline="") as stream:
                for row in list(csv.reader(stream))[1:]:
                    lines.append(f"CANARY MODE{port} {source},1550,{0 if port == 1 else 14}," + ",".join(row))
    (folder / "console.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_complete_synthetic_resume_accepts_only_parser_basis_contract(tmp_path):
    report = CANARY.analyze(driven_fixture(tmp_path), "straight", report_name=None)
    for name in ("pre_driven_mode_acceptance", "cross_source_mode_basis", "pre_post_mode_basis", "complex_diagnostics"):
        assert report["gates"][name]["status"] == "pass"
    assert report["physical_qualification"] == "not_established"
    assert report["pass"] is False


@pytest.mark.parametrize("marker", ["MATERIAL_AUDIT_PASS", "EXTERIOR_PARTITION_PASS", "CONFIGURATION_PASS"])
def test_configuration_rejects_error_suffix_with_valid_resume_basis(tmp_path, marker):
    folder = driven_fixture(tmp_path)
    assert CANARY.analyze(folder, "straight", report_name=None)["gates"]["configuration"]["status"] == "pass"
    console = folder / "console.txt"
    console.write_text(console.read_text(encoding="utf-8").replace(marker, marker + "_ERROR"), encoding="utf-8")
    assert CANARY.analyze(folder, "straight", report_name=None)["gates"]["configuration"]["status"] == "fail"


@pytest.mark.parametrize("port", [1, 2])
def test_missing_predrive_mode_csv_blocks_acceptance(tmp_path, port):
    folder = driven_fixture(tmp_path)
    positive = CANARY.analyze(folder, "straight", report_name=None)
    assert positive["gates"]["pre_post_mode_basis"]["status"] == "pass"
    assert positive["gates"]["complex_diagnostics"]["status"] == "pass"
    (folder / f"predrive_mode_port{port}.csv").unlink()
    report = CANARY.analyze(folder, "straight", report_name=None)
    assert report["gates"]["pre_post_mode_basis"]["status"] != "pass"
    assert report["gates"]["complex_diagnostics"]["status"] != "pass"


@pytest.mark.parametrize("factor", [-1, 1.1, 1j])
def test_source2_phase_or_amplitude_change_fails_with_valid_predrive_evidence(tmp_path, factor):
    folder = driven_fixture(tmp_path)
    positive = CANARY.analyze(folder, "straight", report_name=None)
    assert positive["gates"]["cross_source_mode_basis"]["status"] == "pass"
    assert positive["gates"]["complex_diagnostics"]["status"] == "pass"
    console = folder / "console.txt"
    altered = []
    for line in console.read_text(encoding="utf-8").splitlines():
        if line.startswith("CANARY MODE2 2,"):
            parts = line[len("CANARY MODE2 "):].split(",")
            for re_col, im_col in ((4, 5), (6, 7)):
                value = complex(float(parts[re_col]), float(parts[im_col])) * factor
                parts[re_col], parts[im_col] = str(value.real), str(value.imag)
            line = "CANARY MODE2 " + ",".join(parts)
        altered.append(line)
    console.write_text("\n".join(altered) + "\n", encoding="utf-8")
    report = CANARY.analyze(folder, "straight", report_name=None)
    assert report["gates"]["cross_source_mode_basis"]["status"] != "pass"
    assert report["gates"]["complex_diagnostics"]["status"] != "pass"


@pytest.mark.parametrize("filename", ["accepted_mode_report.json", "input_modes.mph", "mode_exporter.java",
                                      "accepted_parser.py", "predrive_console.txt", "resume_binding.json"])
def test_driven_analysis_rejects_tampered_bound_resume_artifact(tmp_path, filename):
    folder = driven_fixture(tmp_path)
    positive = CANARY.analyze(folder, "straight", report_name=None)
    assert positive["gates"]["pre_driven_mode_acceptance"]["status"] == "pass"
    artifact = folder / filename
    if filename.endswith(".json"):
        data = json.loads(artifact.read_text(encoding="utf-8"))
        data["unbound_extra_field"] = "tamper changes report hash"
        if filename == "resume_binding.json":
            data["accepted_mode_report_sha256"] = "0" * 64
        artifact.write_text(json.dumps(data), encoding="utf-8")
    else:
        artifact.write_bytes(artifact.read_bytes() + b"\ntampered\n")
    report = CANARY.analyze(folder, "straight", report_name=None)
    assert report["gates"]["pre_driven_mode_acceptance"]["status"] != "pass"
