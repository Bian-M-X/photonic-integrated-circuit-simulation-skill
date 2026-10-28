"""Smoke-test an installed wheel without relying on a repository checkout."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import photonic_workflow
from photonic_workflow import __version__
from photonic_workflow.circuits import validate_manifest
from photonic_workflow.circuits.assembly import load_component_data
from photonic_workflow.device_models import evaluate_device, list_models, scattering_csv
from photonic_workflow.mcp.server import (
    AGENT_RESOURCES,
    REFERENCE_RESOURCES,
    PhotonicMcpServer,
    default_skill_root,
)
from photonic_workflow.project import create_project_scaffold


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--forbid-root",
        type=Path,
        help="Repository root that packaged resources must not resolve through.",
    )
    args = parser.parse_args()

    distribution_version = importlib.metadata.version("photonic-workflow")
    if distribution_version != __version__:
        raise RuntimeError(
            f"distribution {distribution_version} != runtime {__version__}"
        )

    skill_root = default_skill_root().resolve()
    if args.forbid_root is not None:
        repository_root = args.forbid_root.resolve()
        source_root = repository_root / "src"
        package_module = Path(photonic_workflow.__file__).resolve()
        if (
            skill_root == repository_root
            or source_root == package_module
            or source_root in package_module.parents
        ):
            raise RuntimeError(
                "installed package or MCP resources resolved through source checkout: "
                f"{package_module}; {skill_root}"
            )

    server = PhotonicMcpServer(skill_root, read_roots=[], write_roots=[])
    resources = server.resource_list()
    tools = server.tool_list()
    expected_resource_uris = {
        "photonic://server/manifest",
        *(f"photonic://skill/reference/{name}" for name in REFERENCE_RESOURCES),
        *(f"photonic://skill/agent/{name}" for name in AGENT_RESOURCES),
    }
    actual_resource_uris = {resource["uri"] for resource in resources}
    expected_tools = {
        "list_allowed_roots", "list_recipes", "inspect_recipe", "render_recipe",
        "create_project_scaffold", "audit_project_artifacts", "parse_sweep_table",
        "validate_contract", "inspect_project", "validate_circuit", "compose_circuit",
        "gate_status", "run_java_batch",
    }
    if actual_resource_uris != expected_resource_uris or {item["name"] for item in tools} != expected_tools:
        raise RuntimeError(
            "unexpected MCP surface: "
            f"{len(resources)} resources, {len(tools)} tools; "
            f"missing={sorted(expected_resource_uris - actual_resource_uris)}, "
            f"extra={sorted(actual_resource_uris - expected_resource_uris)}"
        )
    for resource in resources:
        contents = server.resource_read(resource["uri"])
        if len(contents) != 1 or not contents[0]["text"]:
            raise RuntimeError(f"empty installed MCP resource: {resource['uri']}")

    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as temporary:
        outside = Path(temporary)
        os.chdir(outside)
        try:
            canary_audit = skill_root / "examples" / "comsol-device-canary" / "audit.py"
            checkpoint = outside / "synthetic-checkpoint.mph"
            checkpoint.write_bytes(b"installation smoke fixture; not native evidence")
            audit_output = outside / "audit-dryrun"
            probe = subprocess.run([
                sys.executable, "-B", str(canary_audit),
                "--checkpoint", str(checkpoint),
                "--checkpoint-sha256", hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                "--output", str(audit_output),
            ], check=True, capture_output=True, text=True)
            audit_plan = json.loads(probe.stdout)
            if (audit_plan["mode"] != "dryrun"
                    or audit_plan["native_execution"] != "not_supported"
                    or audit_output.exists()):
                raise RuntimeError("installed canary audit violated its offline dry-run contract")
            profile_tool = skill_root / "examples" / "comsol-device-canary" / "taper_profile.py"
            profile_probe = subprocess.run([
                sys.executable, "-B", str(profile_tool),
            ], check=True, capture_output=True, text=True)
            profile_plan = json.loads(profile_probe.stdout)
            profile_output = outside / "zero-change-profile"
            profile_write = subprocess.run([
                sys.executable, "-B", str(profile_tool), "--center-width-um", "0.3",
                "--taper-length-um", "0", "--output", str(profile_output),
            ], check=True, capture_output=True, text=True)
            zero_profile = json.loads(profile_write.stdout)
            if (profile_plan["will_execute"] or profile_plan["physics_accepted"]
                    or zero_profile["will_execute"] or zero_profile["physics_accepted"]
                    or zero_profile["native_execution"] != "not_performed"
                    or len(zero_profile["vertices_um"]) != 4
                    or not zero_profile["equal_width_geometry"]
                    or json.loads((profile_output / "profile.json").read_text(encoding="utf-8")) != zero_profile
                    or hashlib.sha256((profile_output / "DeviceCanary.java").read_bytes()).hexdigest()
                    != zero_profile["configure_source_sha256"]):
                raise RuntimeError("installed taper profile violated its offline geometry contract")
            modes_tool = skill_root / "examples" / "comsol-device-canary" / "profile_modes.py"
            modes_bundle = outside / "profile-mode-bundle"
            modes_prepare = subprocess.run([
                sys.executable, "-B", str(modes_tool), "prepare", "--output", str(modes_bundle),
                "--center-width-um", "0.30", "--taper-length-um", "4",
            ], check=True, capture_output=True, text=True)
            modes_manifest = json.loads(modes_prepare.stdout)
            modes_verify = subprocess.run([
                sys.executable, "-B", str(modes_tool), "verify", "--bundle", str(modes_bundle),
            ], check=True, capture_output=True, text=True)
            if (json.loads(modes_verify.stdout) != modes_manifest
                    or modes_manifest["will_execute"] or modes_manifest["physics_accepted"]
                    or hashlib.sha256((modes_bundle / "DeviceCanary.java").read_bytes()).hexdigest()
                    != modes_manifest["source_sha256"]):
                raise RuntimeError("installed profile modes preparation or identity check failed")
            with (modes_bundle / "profile.json").open("ab") as stream:
                stream.write(b" ")
            modes_changed = subprocess.run([
                sys.executable, "-B", str(modes_tool), "verify", "--bundle", str(modes_bundle),
            ], capture_output=True, text=True)
            if modes_changed.returncode == 0:
                raise RuntimeError("installed profile modes accepted a modified bundle")
            driven_tool = skill_root / "examples" / "comsol-device-canary" / "profile_driven.py"
            subprocess.run([
                sys.executable, "-B", str(driven_tool), "--help",
            ], check=True, capture_output=True, text=True)
            bend_tool = skill_root / "examples" / "comsol-device-canary" / "bend_profile.py"
            bend_output = outside / "bend-geometry"
            bend_write = subprocess.run([
                sys.executable, "-B", str(bend_tool), "--output", str(bend_output),
            ], check=True, capture_output=True, text=True)
            bend_profile = json.loads(bend_write.stdout)
            bend_zero = json.loads(subprocess.run([
                sys.executable, "-B", str(bend_tool), "--turn-angle-deg", "0",
            ], check=True, capture_output=True, text=True).stdout)
            if (bend_profile["will_execute"] or bend_profile["physics_accepted"]
                    or bend_profile["native_execution"] != "not_performed"
                    or bend_profile["zero_bend_geometry"] or not bend_zero["zero_bend_geometry"]
                    or bend_zero["centerline_length_um"] != 14
                    or bend_zero["will_execute"] or bend_zero["physics_accepted"]
                    or json.loads((bend_output / "geometry.json").read_text(encoding="utf-8")) != bend_profile
                    or hashlib.sha256((bend_output / "geometry_fragment.java").read_bytes()).hexdigest()
                    != bend_profile["geometry_fragment_sha256"]):
                raise RuntimeError("installed bend geometry violated its offline contract")
            geometry_tool = skill_root / "examples" / "comsol-device-canary" / "bend_geometry.py"
            for label, angle in (("zero", "0"), ("bend", "15")):
                geometry_bundle = outside / ("native-geometry-" + label)
                prepared = json.loads(subprocess.run([
                    sys.executable, "-B", str(geometry_tool), "prepare", "--output", str(geometry_bundle),
                    "--turn-angle-deg", angle,
                ], check=True, capture_output=True, text=True).stdout)
                verified = json.loads(subprocess.run([
                    sys.executable, "-B", str(geometry_tool), "verify", "--bundle", str(geometry_bundle),
                ], check=True, capture_output=True, text=True).stdout)
                if (prepared != verified or prepared["will_execute"] or prepared["physics_accepted"]
                        or prepared["native_execution"] != "not_performed"
                        or {p.name for p in geometry_bundle.iterdir()} != {
                            "geometry.json", "geometry_fragment.java", "BendGeometryProbe.java", "manifest.json",
                        }):
                    raise RuntimeError("installed geometry probe prepare/verify contract failed")
                for name, digest in prepared["files"].items():
                    if hashlib.sha256((geometry_bundle / name).read_bytes()).hexdigest() != digest:
                        raise RuntimeError("installed geometry probe member hash differs")
                with (geometry_bundle / "BendGeometryProbe.java").open("ab") as stream:
                    stream.write(b"\n// changed after preparation\n")
                if subprocess.run([
                    sys.executable, "-B", str(geometry_tool), "verify", "--bundle", str(geometry_bundle),
                ], capture_output=True, text=True).returncode == 0:
                    raise RuntimeError("installed geometry verifier accepted substituted source")
            project = outside / "installed-wheel-project"
            create_project_scaffold(project, device_family="mzi")
            manifest, data = validate_manifest(project / "circuits" / "assembly.json")
            if len(manifest["instances"]) != 4 or len(data) != 2:
                raise RuntimeError("installed MZI template did not validate")
            recipe_server = PhotonicMcpServer(skill_root, [outside], [outside])
            request = outside / "material-request.json"
            request.write_text(json.dumps({
                "schema_version": "1.0", "recipe_id": "materials.li-silicon-1980",
                "recipe_version": "1.0.0", "parameters": {"wavelength_um": 1.55},
            }), encoding="utf-8")
            receipt = recipe_server.tool_call("render_recipe", {
                "request_file": str(request), "output": str(outside / "material.json"),
            })["structuredContent"]
            if not receipt["written"] or receipt["physics_accepted"] or receipt["will_execute"]:
                raise RuntimeError("installed recipe result violated its claim boundary")
            models = list_models()
            if {item["model"] for item in models} != {
                "waveguide", "directional-coupler", "ring-allpass", "ring-adddrop", "bragg-uniform",
                "mmi2x2-ideal", "ybranch-ideal",
            }:
                raise RuntimeError("installed device model catalog differs from the seven fixed models")
            for descriptor in models:
                model = descriptor["model"]
                example = skill_root / "examples" / "device-models" / f"{model}.json"
                result = evaluate_device(json.loads(example.read_text(encoding="utf-8")))
                csv_path = outside / f"{model}.csv"
                csv_path.write_text(scattering_csv(result), encoding="utf-8")
                loaded = load_component_data(
                    outside / "assembly.json", model,
                    {"ports": result["port_order"], "sparameters": csv_path.name, "passive": True},
                )
                if len(loaded.wavelengths_nm) != 5 or result["physics_accepted"] or result["will_execute"]:
                    raise RuntimeError(f"installed device model failed: {model}")
        finally:
            os.chdir(original_cwd)

    print(
        json.dumps(
            {
                "version": __version__,
                "mcp_resource_count": len(resources),
                "mcp_tool_count": len(tools),
                "packaged_skill_root": skill_root.name,
                "template_smoke": "passed",
                "recipe_smoke": "passed",
                "device_models_and_csv": f"{len(models)} passed; no native solve",
                "canary_audit_dryrun": "passed from installed wheel; no native solve",
                "taper_profile_smoke": "passed installed dry plan and zero-length rectangle; no native solve",
                "profile_modes_smoke": "passed installed prepare, verify and substitution rejection; no native solve",
                "profile_driven_smoke": "installed offline CLI starts; evidence fixtures tested separately",
                "bend_profile_smoke": "passed installed own bend and zero-angle geometry controls; no native solve",
                "bend_geometry_smoke": (
                    "passed installed zero/bend prepare, verify and source substitution rejection; no native run"
                ),
            },
            indent=2,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
