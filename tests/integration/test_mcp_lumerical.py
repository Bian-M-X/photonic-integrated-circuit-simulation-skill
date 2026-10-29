"""MCP reuses native plan/result services without exposing solver execution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from photonic_workflow.exceptions import InvalidInputError, SecurityViolationError
from photonic_workflow.lumerical.inspection import inspect_device_run
from photonic_workflow.lumerical.runtime import plan_run
from photonic_workflow.lumerical.workflow import compare_device_runs, export_device_run
from photonic_workflow.mcp.server import McpError, PhotonicMcpServer
from photonic_workflow.recipes import load_recipe_request, render_recipe
from tests.test_lumerical_workflow import native_fixture

ROOT = Path(__file__).resolve().parents[2]
NEW_TOOLS = {"discover_lumerical_install", "plan_lumerical_run", "inspect_lumerical_result",
             "compare_lumerical_results", "export_lumerical_result"}


@pytest.fixture
def environment(tmp_path):
    read, write = tmp_path / "read", tmp_path / "write"
    read.mkdir()
    write.mkdir()
    installation = read / "app"
    product = installation / "v999/Lumerical"
    (product / "api/python").mkdir(parents=True)
    (product / "bin").mkdir()
    (product / "api/python/lumapi.py").write_text("raise AssertionError('vendor module must not be imported')")
    for name in ("fdtd-solutions.exe", "fdtd-engine.exe", "mode-solutions.exe"):
        (product / "bin" / name).write_bytes(b"test fixture; not executable")
    (product / "VERSION").write_text("synthetic installation")
    server = PhotonicMcpServer(tmp_path / "skill", [read], [write])
    return read, write, installation, server


def call(server, name, **arguments):
    with patch("subprocess.Popen", side_effect=AssertionError("MCP must not execute a solver")):
        response = server.tool_call(name, arguments)
    assert response["isError"] is False
    assert json.loads(response["content"][0]["text"]) == response["structuredContent"]
    return response["structuredContent"]


def test_new_tools_keep_closed_schemas_and_nonexecuting_annotations(environment):
    *_, server = environment
    tools = {item["name"]: item for item in server.tool_list()}
    assert len(tools) == 18 and tools.keys() >= NEW_TOOLS
    for name in NEW_TOOLS:
        tool = tools[name]
        assert tool["inputSchema"]["additionalProperties"] is False
        assert "execute" not in tool["inputSchema"]["properties"]
        assert tool["annotations"]["readOnlyHint"] == (name != "export_lumerical_result")
        assert tool["annotations"]["destructiveHint"] is False
    assert json.loads(server.resource_read("photonic://server/manifest")[0]["text"])["execution"] == "not exposed"


def test_discovery_and_plan_match_shared_service_without_vendor_import(environment):
    read, write, installation, server = environment
    discovery = call(server, "discover_lumerical_install", install_root=str(installation))
    assert discovery["available"] and discovery["products_present"]["FDTD"]
    assert discovery["api_imported"] is False and discovery["license_checked"] is False
    request = {"schema_version": "1.0", "operation": "fdtd-device", "parameters": {"family": "straight"}}
    path = read / "request.json"
    path.write_text(json.dumps(request))
    planned = call(server, "plan_lumerical_run", request_file=str(path), install_root=str(installation))
    assert planned == {**plan_run(request, install_root=installation), "will_execute": False}
    assert planned["execution"] is False
    assert list(write.iterdir()) == []
    path.write_text(json.dumps({**request, "script": "untrusted"}))
    with pytest.raises(InvalidInputError):
        call(server, "plan_lumerical_run", request_file=str(path), install_root=str(installation))


def test_inspection_recomputes_compact_metrics_and_preserves_negative_diagnostics(environment):
    read, write, _, server = environment
    receipt = native_fixture(read / "native")
    document = json.loads(receipt.read_text())
    document["result"].update(diagnostic_passed=False, max_singular_value=99)
    receipt.write_text(json.dumps(document))
    observed = call(server, "inspect_lumerical_result", receipt_file=str(receipt))
    assert observed == inspect_device_run(receipt)
    assert observed["matrix_shape"] == [2, 2, 2]
    assert observed["metrics_recomputed_from_native_matrix"]["max_singular_value"] == pytest.approx(0.9)
    assert observed["native_diagnostic_passed"] is False
    assert observed["will_execute"] is False and observed["physics_accepted"] is False
    assert len(json.dumps(observed)) < 5000
    assert "s_matrices" not in observed and "raw" not in observed
    with pytest.raises(InvalidInputError, match="diagnostics failed"):
        call(server, "inspect_lumerical_result", receipt_file=str(receipt), require_diagnostics=True)
    assert list(write.iterdir()) == []


def test_comparison_and_export_reuse_verified_data_without_phase_loss(environment):
    read, write, _, server = environment
    coarse = native_fixture(read / "coarse", mesh=3, through=0.9)
    fine = native_fixture(read / "fine", mesh=5, through=0.91)
    compared = call(server, "compare_lumerical_results", coarse_receipt=str(coarse), fine_receipt=str(fine))
    assert compared == {**compare_device_runs(coarse, fine), "will_execute": False}
    exported = call(server, "export_lumerical_result", receipt_file=str(coarse),
                    output=str(write / "mcp.csv"), project_root=str(write), passivity_tolerance=0.005)
    direct = export_device_run(coarse, write / "direct.csv", project_root=write, passivity_tolerance=0.005)
    assert (write / "mcp.csv").read_bytes() == (write / "direct.csv").read_bytes()
    assert (write / "mcp.csv.source.json").read_bytes() == (coarse.parent / "source_dataset.json").read_bytes()
    assert exported["native_receipt_sha256"] == direct["native_receipt_sha256"]
    assert exported["component"]["passivity_tolerance"] == 0.005
    assert exported["will_execute"] is False
    before = (write / "mcp.csv").read_bytes()
    with pytest.raises(InvalidInputError, match="already exists"):
        call(server, "export_lumerical_result", receipt_file=str(coarse),
             output=str(write / "mcp.csv"), project_root=str(write))
    assert (write / "mcp.csv").read_bytes() == before


def test_hash_failure_blocks_inspection_and_export_before_writes(environment):
    read, write, _, server = environment
    receipt = native_fixture(read / "native")
    (receipt.parent / "source_dataset.json").write_text("{}")
    with pytest.raises(InvalidInputError, match="changed or missing"):
        call(server, "inspect_lumerical_result", receipt_file=str(receipt))
    with pytest.raises(InvalidInputError, match="changed or missing"):
        call(server, "export_lumerical_result", receipt_file=str(receipt),
             output=str(write / "new/component.csv"), project_root=str(write))
    assert list(write.iterdir()) == []


def test_allowlists_absolute_paths_and_unknown_execution_flags_are_enforced(environment):
    read, write, installation, server = environment
    receipt = native_fixture(read / "native")
    outside = native_fixture(read.parent / "outside")
    for name, arguments in (
        ("discover_lumerical_install", {"install_root": str(read.parent / "outside-install")}),
        ("plan_lumerical_run", {"request_file": str(outside.parent / "request.json"),
                                "install_root": str(installation)}),
        ("inspect_lumerical_result", {"receipt_file": str(outside)}),
        ("compare_lumerical_results", {"coarse_receipt": str(receipt), "fine_receipt": str(outside)}),
        ("export_lumerical_result", {"receipt_file": str(receipt), "output": str(read / "out.csv"),
                                     "project_root": str(read)}),
    ):
        with pytest.raises(SecurityViolationError):
            call(server, name, **arguments)
    for name, arguments in (
        ("discover_lumerical_install", {"install_root": "app"}),
        ("plan_lumerical_run", {"request_file": "request.json", "install_root": str(installation)}),
        ("inspect_lumerical_result", {"receipt_file": "receipt.json"}),
        ("export_lumerical_result", {"receipt_file": str(receipt), "output": "out.csv",
                                     "project_root": str(write)}),
        ("inspect_lumerical_result", {"receipt_file": str(receipt), "require_diagnostics": "true"}),
    ):
        with pytest.raises(McpError):
            call(server, name, **arguments)
    for name in NEW_TOOLS:
        with pytest.raises(McpError):
            call(server, name, execute=True)
    assert list(write.iterdir()) == []


def test_indirect_native_artifact_and_installation_symlink_escapes_are_rejected(environment):
    read, write, installation, server = environment
    receipt = native_fixture(read / "native")
    outside = read.parent / "outside.dat"
    outside.write_bytes(b"private outside read roots")
    artifact = receipt.parent / "source-0.fsp"
    artifact.unlink()
    try:
        artifact.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(InvalidInputError, match="artifact path"):
        call(server, "inspect_lumerical_result", receipt_file=str(receipt))
    version = installation / "v999/Lumerical/VERSION"
    version.unlink()
    version.symlink_to(outside)
    with pytest.raises(SecurityViolationError):
        call(server, "discover_lumerical_install", install_root=str(installation))
    assert list(write.iterdir()) == []


def test_export_rejects_existing_sidecar_without_partial_new_output(environment):
    read, write, _, server = environment
    receipt = native_fixture(read / "native")
    sidecar = write / "data.csv.metadata.json"
    sidecar.write_text("preserve this existing evidence")
    with pytest.raises(InvalidInputError, match="already exists"):
        call(server, "export_lumerical_result", receipt_file=str(receipt),
             output=str(write / "data.csv"), project_root=str(write))
    assert sidecar.read_text() == "preserve this existing evidence"
    assert {path.name for path in write.iterdir()} == {sidecar.name}


def test_lumerical_recipe_fragment_matches_shared_renderer_with_explicit_stack(environment):
    read, write, _, server = environment
    request_path = read / "bend.json"
    request_path.write_bytes((ROOT / "examples/recipes/symmetric-euler-bend.json").read_bytes())
    request = load_recipe_request(request_path)
    expected = render_recipe(request.recipe_id, request.parameters, renderer="lumerical-lsf-fragment",
                             instance_id="mcp-bend", height_um=0.22, core_index=2.6)
    exported = call(server, "render_recipe", request_file=str(request_path), output=str(write / "bend.lsf"),
                    renderer="lumerical-lsf-fragment", instance_id="mcp-bend", height_um=0.22, core_index=2.6)
    assert (write / "bend.lsf").read_bytes() == expected.content.encode("utf-8")
    assert exported["renderer_options"] == {"height_um": 0.22, "core_index": 2.6}
    assert exported["sha256"] == expected.sha256
    assert exported["media_type"] == "text/x-lumerical-lsf"
    assert exported["will_execute"] is False
    for options in ({}, {"height_um": 0.22}, {"height_um": True, "core_index": 2.6},
                    {"height_um": 0.22, "core_index": 2.6, "instance_id": 'bad";run;'}):
        arguments = {"request_file": str(request_path), "output": str(write / "invalid.lsf"),
                     "renderer": "lumerical-lsf-fragment", "instance_id": "safe", **options}
        with pytest.raises((InvalidInputError, McpError, SecurityViolationError)):
            call(server, "render_recipe", **arguments)
    with pytest.raises(InvalidInputError, match="only by the Lumerical"):
        call(server, "render_recipe", request_file=str(request_path), output=str(write / "invalid.json"),
             height_um=0.22)
    assert not (write / "invalid.lsf").exists() and not (write / "invalid.json").exists()
