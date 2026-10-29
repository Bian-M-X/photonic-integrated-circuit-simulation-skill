"""Exercise installed MCP stdio against retained native data, without a solver.

The caller supplies an installed wheel, an existing device receipt, a local
installation root for filesystem discovery and a fresh output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt, installation = args.receipt.resolve(), args.install_root.resolve()
    recipe = output / "circular-request.json"
    recipe.write_text(json.dumps({"schema_version": "1.0", "recipe_id": "geometry.circular-route",
        "recipe_version": "1.0.0", "parameters": {"vertices_um": [[0, 0], [20, 0], [20, 20]],
                                                   "radius_um": 5, "width_um": .5}}), encoding="utf-8")
    requests, labels = [], {}

    def add(label, method, params):
        identity = len(requests) + 1
        labels[label] = identity
        requests.append({"jsonrpc": "2.0", "id": identity, "method": method, "params": params})

    def tool(label, name, arguments):
        add(label, "tools/call", {"name": name, "arguments": arguments})

    add("initialize", "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "installed-lumerical-smoke", "version": "1"}})
    add("tools", "tools/list", {})
    add("resources", "resources/list", {})
    add("manifest", "resources/read", {"uri": "photonic://server/manifest"})
    tool("discover", "discover_lumerical_install", {"install_root": str(installation)})
    tool("plan", "plan_lumerical_run", {"request_file": str(receipt.parent / "request.json"),
                                         "install_root": str(installation)})
    tool("inspect", "inspect_lumerical_result", {"receipt_file": str(receipt)})
    tool("compare", "compare_lumerical_results", {"coarse_receipt": str(receipt), "fine_receipt": str(receipt)})
    project = output / "project"
    tool("scaffold", "create_project_scaffold", {"project_root": str(project), "device_family": "mzi"})
    tool("export", "export_lumerical_result", {"receipt_file": str(receipt), "output": str(project / "native.csv"),
                                                "project_root": str(project), "passivity_tolerance": .005})
    tool("recipe", "render_recipe", {"request_file": str(recipe), "output": str(project / "circular.lsf"),
        "renderer": "lumerical-lsf-fragment", "instance_id": "installed_circle",
        "height_um": .22, "core_index": 2.6})
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(args.installed_root.resolve())
    command = [sys.executable, "-B", "-m", "photonic_workflow.mcp.server",
               "--read-root", str(receipt.parent), "--read-root", str(installation),
               "--read-root", str(output), "--write-root", str(output)]
    completed = subprocess.run(command, input="".join(json.dumps(item) + "\n" for item in requests),
                               cwd=output, env=environment, capture_output=True, text=True,
                               encoding="utf-8", timeout=180, check=True)
    responses = {item["id"]: item for item in map(json.loads, completed.stdout.splitlines())}
    if set(responses) != set(labels.values()):
        raise RuntimeError("Installed MCP response identities differ")
    errors = {label: responses[index].get("error") for label, index in labels.items()
              if "error" in responses[index]}
    if errors:
        raise RuntimeError("Installed MCP returned errors: " + json.dumps(errors))

    def data(label):
        result = responses[labels[label]]["result"]
        if result.get("isError"):
            raise RuntimeError("Installed tool failed: " + label)
        return result.get("structuredContent", result)

    tools, resources = data("tools")["tools"], data("resources")["resources"]
    if len(tools) != 18 or len(resources) != 43:
        raise RuntimeError("Installed MCP surface differs from reviewed surface")
    if data("plan")["execution"] or data("inspect")["will_execute"]:
        raise RuntimeError("MCP changed its non-executing contract")
    if not data("inspect")["artifact_integrity_verified"] or data("compare")["max_absolute_power_change"] != 0:
        raise RuntimeError("Installed MCP native-data verification differs")
    source = receipt.parent / "source_dataset.json"
    archived = project / "native.csv.source.json"
    if source.read_bytes() != archived.read_bytes() or not (project / "circular.lsf").is_file():
        raise RuntimeError("Installed native export or recipe output differs")
    summary = {"status": "passed", "transport": "installed JSON-RPC stdio", "native_execution": False,
               "tool_count": len(tools), "resource_count": len(resources),
               "all_five_lumerical_tools_passed": True, "lsf_recipe_rendered": True,
               "native_source_bytes_preserved": True,
               "native_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(), "physics_accepted": False}
    (output / "responses.json").write_text(json.dumps(responses, indent=2), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
