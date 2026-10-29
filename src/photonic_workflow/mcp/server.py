from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from photonic_workflow import __version__
from photonic_workflow.application import ProjectStatusService
from photonic_workflow.audit import audit_project_artifacts
from photonic_workflow.circuits import compose, validate_manifest, write_composition
from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.gates import GateLedger
from photonic_workflow.models import WorkflowProfile
from photonic_workflow.models.io import atomic_create_text, load_contract
from photonic_workflow.project import create_project_scaffold
from photonic_workflow.provenance import sha256_file
from photonic_workflow.recipes import (
    RecipeRenderer,
    inspect_recipe,
    list_recipes,
    load_recipe_request,
    provenance_for,
    render_recipe,
)
from photonic_workflow.recipes.artifacts import checked_recipe_output
from photonic_workflow.security import (
    ensure_within_allowed_roots,
    redact_text,
    validate_safe_label,
)
from photonic_workflow.solvers import build_java_batch_plan
from photonic_workflow.sparams.sweep import (
    parse_table,
    summary_row,
    summary_structured,
    write_csv,
)

SERVER_NAME = "photonic-waveguide-optics-mcp"
REFERENCE_RESOURCES = {
    name: f"references/{name}.md"
    for name in (
        "adjoint-and-fabrication",
        "comsol-adjoint-inverse-design",
        "comsol-mcp-evaluation",
        "comsol-field-physical-audit",
        "comsol-performance",
        "device-family-workflows",
        "engineering-workflow",
        "environment-and-runner",
        "executable-diagnostics",
        "executable-device-models",
        "fabrication-aware-robust-design",
        "frequency-domain-source-sweeps",
        "hierarchical-device-workflow",
        "interferometer-workflows",
        "inverse-design-evidence",
        "legal-and-trademark-notes",
        "low-cost-optimization",
        "modeling-recipes",
        "multifidelity-and-error-budgets",
        "native-device-library",
        "optimization-and-reporting",
        "pn-ring-model",
        "project-structure-and-git",
        "quantum-photonic-knowledge-base",
        "smooth-bend-geometry",
        "source-notes",
        "subagent-orchestration",
        "tool-selection",
        "verification-gates",
        "wave-optics-port-models",
    )
}
AGENT_RESOURCES = {
    name: f"agents/{name}-agent.md"
    for name in (
        "code-auditor",
        "data-processing",
        "execution",
        "geometry-modeling",
        "literature-knowledge",
        "mcp-integration",
        "model-auditor",
        "planning",
        "results-auditor",
    )
}


class McpError(Exception):
    def __init__(self, message: str, code: int = -32000) -> None:
        super().__init__(message)
        self.code = code


def strict_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent, ensure_ascii=False, allow_nan=False)


def reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def request_id(request: Any) -> str | int | float | None:
    if not isinstance(request, dict):
        return None
    value = request.get("id")
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _unique_roots(roots: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root.resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _tool(
    name: str,
    title: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    *,
    read_only: bool = False,
    destructive: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "title": title,
        "description": description,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False if read_only else destructive,
            "idempotentHint": read_only,
            "openWorldHint": False,
        },
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


class PhotonicMcpServer:
    """JSON-RPC transport only; domain behavior lives in photonic_workflow."""

    def __init__(
        self,
        skill_root: Path,
        read_roots: list[Path],
        write_roots: list[Path],
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.read_roots = _unique_roots([self.skill_root, *read_roots])
        self.write_roots = _unique_roots(write_roots)

    def _read_path(self, raw: str) -> Path:
        return ensure_within_allowed_roots(Path(raw), self.read_roots)

    def _write_path(self, raw: str) -> Path:
        if not self.write_roots:
            raise McpError("no writable roots were configured", code=-32602)
        return ensure_within_allowed_roots(Path(raw), self.write_roots)

    def _validate_tool_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        schemas = {
            item["name"]: item["inputSchema"]
            for item in self.tool_list()
        }
        schema = schemas.get(name)
        if schema is None:
            raise McpError(f"unknown tool: {name}", code=-32602)
        if not isinstance(arguments, dict):
            raise McpError("tool arguments must be an object", code=-32602)

        properties = schema.get("properties", {})
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise McpError(
                "unexpected argument"
                + ("s" if len(unexpected) != 1 else "")
                + f" for {name}: {', '.join(unexpected)}",
                code=-32602,
            )
        missing = sorted(set(schema.get("required", ())) - set(arguments))
        if missing:
            raise McpError(
                "missing required argument"
                + ("s" if len(missing) != 1 else "")
                + f" for {name}: {', '.join(missing)}",
                code=-32602,
            )

        for key, value in arguments.items():
            property_schema = properties[key]
            expected_type = property_schema.get("type")
            matches = {
                "string": type(value) is str,
                "boolean": type(value) is bool,
                "integer": type(value) is int,
                "number": (
                    type(value) in {int, float}
                    and math.isfinite(float(value))
                ),
                "object": type(value) is dict,
                "array": type(value) is list,
            }.get(expected_type, True)
            if not matches:
                raise McpError(
                    f"argument {key!r} for {name} must have JSON type {expected_type}",
                    code=-32602,
                )
            if "enum" in property_schema and value not in property_schema["enum"]:
                raise McpError(
                    f"argument {key!r} for {name} is not an allowed value",
                    code=-32602,
                )
        return dict(arguments)

    def resource_list(self) -> list[dict[str, str]]:
        resources = [
            {
                "uri": "photonic://server/manifest",
                "name": "server manifest",
                "description": "Version, capability and root-policy summary",
                "mimeType": "application/json",
            }
        ]
        resources.extend(
            {
                "uri": f"photonic://skill/reference/{name}",
                "name": f"reference: {name}",
                "description": "Photonic workflow reference",
                "mimeType": "text/markdown",
            }
            for name in sorted(REFERENCE_RESOURCES)
        )
        resources.extend(
            {
                "uri": f"photonic://skill/agent/{name}",
                "name": f"agent: {name}",
                "description": "Photonic subagent role contract",
                "mimeType": "text/markdown",
            }
            for name in sorted(AGENT_RESOURCES)
        )
        return resources

    def resource_read(self, uri: str) -> list[dict[str, str]]:
        if uri == "photonic://server/manifest":
            payload = {
                "name": SERVER_NAME,
                "version": __version__,
                "read_roots_count": len(self.read_roots),
                "write_roots_count": len(self.write_roots),
                "execution": "not exposed",
                "tools": [item["name"] for item in self.tool_list()],
                "resources": [item["uri"] for item in self.resource_list()],
            }
            return [{"uri": uri, "mimeType": "application/json", "text": strict_json(payload, indent=2)}]
        mappings: tuple[tuple[str, dict[str, str]], ...] = (
            ("photonic://skill/reference/", REFERENCE_RESOURCES),
            ("photonic://skill/agent/", AGENT_RESOURCES),
        )
        for prefix, mapping in mappings:
            if uri.startswith(prefix):
                name = uri.removeprefix(prefix)
                relative = mapping.get(name)
                if relative is None:
                    raise McpError(f"unknown resource: {uri}", code=-32602)
                path = ensure_within_allowed_roots(self.skill_root / relative, [self.skill_root])
                return [{"uri": uri, "mimeType": "text/markdown", "text": path.read_text(encoding="utf-8")}]
        raise McpError(f"unknown resource uri: {uri}", code=-32602)

    def tool_list(self) -> list[dict[str, Any]]:
        path = {"type": "string"}
        return [
            _tool("list_allowed_roots", "List roots", "List distinct read and write roots.", {}, read_only=True),
            _tool(
                "list_recipes",
                "List modeling recipes",
                "List compact recipe identities and summaries; inspect one recipe for its parameter contract.",
                {},
                read_only=True,
            ),
            _tool(
                "inspect_recipe",
                "Inspect modeling recipe",
                "Read one built-in recipe's version, units, parameter bounds, renderers and provenance; no solver.",
                {"recipe_id": {"type": "string"}, "version": {"type": "string"}},
                ["recipe_id"],
                read_only=True,
            ),
            _tool(
                "render_recipe",
                "Write modeling recipe artifact",
                "Evaluate a strict versioned recipe file and create a new JSON or fixed Java fragment. "
                "Returns a compact hash receipt; refuses overwrite; never compiles, solves or changes gates.",
                {
                    "request_file": {"type": "string", "description": "Absolute path under a read root."},
                    "output": {"type": "string", "description": "New absolute file path under a write root."},
                    "renderer": {
                        "type": "string",
                        "enum": [item.value for item in RecipeRenderer],
                        "default": RecipeRenderer.CANONICAL_JSON.value,
                    },
                    "instance_id": {"type": "string", "description": "Safe instance ID; required for Java only."},
                },
                ["request_file", "output"],
                destructive=False,
            ),
            _tool(
                "create_project_scaffold",
                "Create project scaffold",
                "Create an installable-runtime project; does not copy business logic.",
                {
                    "project_root": path,
                    "device_family": {"type": "string", "default": "waveguide"},
                    "profile": {"type": "string", "default": "custom-device-first"},
                },
                ["project_root"],
            ),
            _tool(
                "audit_project_artifacts",
                "Audit artifacts",
                "Read every eligible text file and report blocked or sensitive artifacts.",
                {"project_root": path, "large_file_mb": {"type": "integer", "default": 25}},
                ["project_root"],
                read_only=True,
            ),
            _tool(
                "parse_sweep_table",
                "Parse COMSOL sweep table",
                "Parse and validate a legacy scalar sweep table, then write summary and trace CSV.",
                {
                    "table_file": path,
                    "output_dir": path,
                    "label": {"type": "string"},
                    "peak_threshold": {"type": "number", "default": 0.02},
                },
                ["table_file", "output_dir"],
            ),
            _tool(
                "validate_contract",
                "Validate contract",
                "Validate a versioned JSON contract using the shared Pydantic registry.",
                {"contract_file": path, "expected_type": {"type": "string"}},
                ["contract_file"],
                read_only=True,
            ),
            _tool(
                "inspect_project",
                "Inspect project",
                "Return bounded gate and project-state metadata.",
                {"project_root": path},
                ["project_root"],
                read_only=True,
            ),
            _tool(
                "validate_circuit",
                "Validate circuit",
                "Validate assembly v1 structure and complete complex S matrices.",
                {"manifest": path, "structure_only": {"type": "boolean", "default": False}},
                ["manifest"],
                read_only=True,
            ),
            _tool(
                "compose_circuit",
                "Compose circuit",
                "Compose assembly v1 and write the external complex S matrix.",
                {"manifest": path, "output": path, "summary": path},
                ["manifest", "output"],
            ),
            _tool(
                "gate_status",
                "Read gate status",
                "Read G0-G8 and M0-M4 without changing the ledger.",
                {"project_root": path},
                ["project_root"],
                read_only=True,
            ),
            _tool(
                "run_java_batch",
                "Render COMSOL Java plan",
                "Render an allowlist-checked, redacted dry-run plan; execution is never exposed.",
                {
                    "java_file": path,
                    "output_mph": path,
                    "batch_log": path,
                    "runtime_dir": path,
                    "solver_root": {"type": "string"},
                    "timeout_s": {"type": "integer", "default": 3600},
                    "dry_run": {"type": "boolean", "default": True},
                    "allow_execute": {"type": "boolean", "default": False},
                },
                ["java_file", "output_mph", "batch_log", "runtime_dir"],
                read_only=True,
            ),
        ]

    def _parse_sweep(self, arguments: dict[str, Any]) -> dict[str, Any]:
        table = self._read_path(str(arguments["table_file"]))
        output_dir = self._write_path(str(arguments["output_dir"]))
        raw_label = arguments.get("label", table.stem)
        label = validate_safe_label(str(raw_label))
        threshold = float(arguments.get("peak_threshold", 0.02))
        rows = parse_table(table)
        summary = summary_structured(label, rows, threshold)
        summary_csv = self._write_path(str(output_dir / f"{label}_summary.csv"))
        trace_csv = self._write_path(str(output_dir / f"{label}_trace.csv"))
        write_csv(summary_csv, [summary_row(label, rows, threshold)])
        write_csv(trace_csv, rows)
        return {
            "summary": summary,
            "summary_csv": str(summary_csv),
            "trace_csv": str(trace_csv),
        }

    def _render_recipe(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request_path = Path(arguments["request_file"])
        output = Path(arguments["output"])
        if not request_path.is_absolute() or not output.is_absolute():
            raise McpError("recipe request_file and output must be absolute paths", code=-32602)
        request_path = self._read_path(str(request_path))
        checked = self._write_path(str(output))
        root = next(root for root in self.write_roots if checked.is_relative_to(root))
        checked, _ = checked_recipe_output(root, output)
        request = load_recipe_request(request_path)
        rendered = render_recipe(
            request.recipe_id,
            request.parameters,
            version=request.recipe_version,
            renderer=arguments.get("renderer", RecipeRenderer.CANONICAL_JSON.value),
            instance_id=arguments.get("instance_id"),
        )
        try:
            atomic_create_text(
                checked,
                rendered.content,
                path_guard=lambda candidate: checked_recipe_output(root, candidate),
            )
        except FileExistsError as exc:
            raise InvalidInputError("recipe output already exists; choose a new artifact path") from exc
        if sha256_file(checked) != rendered.sha256:
            raise InvalidInputError("written recipe output failed SHA-256 verification")
        return {
            "recipe_id": request.recipe_id,
            "recipe_version": request.recipe_version,
            "artifact_path": str(checked),
            "renderer_id": rendered.renderer.value,
            "media_type": rendered.media_type,
            "sha256": rendered.sha256,
            "byte_count": rendered.byte_count,
            "output_fields": sorted(rendered.result.output),
            "support_level": rendered.result.descriptor.support_level.value,
            "claim_boundary": list(rendered.result.descriptor.claim_boundary),
            "written": True,
            "will_execute": False,
            "physics_accepted": False,
        }

    def tool_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = self._validate_tool_arguments(name, arguments)
        handlers: dict[str, Callable[[], Any]] = {
            "list_recipes": lambda: {
                "recipes": [
                    {
                        "recipe_id": item.recipe_id,
                        "recipe_version": item.recipe_version,
                        "summary": item.summary,
                        "support_level": item.support_level.value,
                    }
                    for item in list_recipes()
                ],
                "will_execute": False,
                "physics_accepted": False,
            },
            "inspect_recipe": lambda: {
                **inspect_recipe(arguments["recipe_id"], version=arguments.get("version")).to_payload(),
                "provenance": provenance_for(arguments["recipe_id"]),
            },
            "render_recipe": lambda: self._render_recipe(arguments),
            "list_allowed_roots": lambda: {
                "read_roots": [str(root) for root in self.read_roots],
                "write_roots": [str(root) for root in self.write_roots],
                "allowed_roots": [str(root) for root in self.read_roots],
            },
            "audit_project_artifacts": lambda: audit_project_artifacts(
                self._read_path(str(arguments["project_root"])),
                large_file_mb=int(arguments.get("large_file_mb", 25)),
            ),
            "parse_sweep_table": lambda: self._parse_sweep(arguments),
            "gate_status": lambda: GateLedger(
                self._read_path(str(arguments["project_root"]))
            ).summary(),
        }
        if name == "create_project_scaffold":
            root = self._write_path(str(arguments["project_root"]))
            result = create_project_scaffold(
                root,
                profile=WorkflowProfile(str(arguments.get("profile", "custom-device-first"))),
                device_family=str(arguments.get("device_family", "waveguide")),
            )
            result["created_folders"] = result["directories"]
            result["created_files"] = result["written"]
        elif name == "validate_contract":
            model = load_contract(
                self._read_path(str(arguments["contract_file"])),
                str(arguments["expected_type"]) if arguments.get("expected_type") else None,
            )
            status = redact_text(model.status)
            if len(status) > 128:
                status = status[:125] + "..."
            result = {
                "valid": True,
                "projection": "bounded-redacted",
                "contract": {
                    "contract_type": model.contract_type,
                    "schema_version": model.schema_version,
                    "stable_id": model.stable_id,
                    "status": status,
                    "validity": model.validity.value,
                },
            }
        elif name == "inspect_project":
            root = self._read_path(str(arguments["project_root"]))
            result = ProjectStatusService(
                root,
                read_roots=self.read_roots,
            ).inspect().to_payload()
        elif name == "validate_circuit":
            manifest = self._read_path(str(arguments["manifest"]))
            payload, data = validate_manifest(
                manifest,
                check_data=not bool(arguments.get("structure_only", False)),
                allowed_roots=self.read_roots,
            )
            result = {
                "valid": True,
                "manifest": str(manifest),
                "instance_count": len(payload["instances"]),
                "component_count": len(payload["components"]),
                "data_checked": bool(data),
            }
        elif name == "compose_circuit":
            manifest = self._read_path(str(arguments["manifest"]))
            output = self._write_path(str(arguments["output"]))
            payload, component_data = validate_manifest(
                manifest,
                allowed_roots=self.read_roots,
            )
            rows, summary = compose(payload, component_data)
            write_composition(output, rows)
            if arguments.get("summary"):
                summary_path = self._write_path(str(arguments["summary"]))
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(strict_json(summary, indent=2) + "\n", encoding="utf-8")
            result = {"valid": True, "output": str(output), "summary": summary}
        elif name == "run_java_batch":
            if arguments.get("dry_run", True) is not True or arguments.get("allow_execute", False):
                raise McpError("MCP exposes plan rendering only; execution flags are rejected", code=-32602)
            java_file = self._read_path(str(arguments["java_file"]))
            output_mph = self._write_path(str(arguments["output_mph"]))
            batch_log = self._write_path(str(arguments["batch_log"]))
            runtime_dir = self._write_path(str(arguments["runtime_dir"]))
            solver_root_source = "argument" if arguments.get("solver_root") else "env:PHOTONIC_SOLVER_ROOT"
            if not arguments.get("solver_root") and not os.environ.get("PHOTONIC_SOLVER_ROOT"):
                solver_root_source = "unset"
            result = build_java_batch_plan(
                java_file=java_file,
                output_mph=output_mph,
                batch_log=batch_log,
                runtime_dir=runtime_dir,
                timeout_s=int(arguments.get("timeout_s", 3600)),
                allowed_roots=_unique_roots([*self.read_roots, *self.write_roots]),
                solver_root_source=solver_root_source,
            )
            result["execution_enabled"] = False
        elif name in handlers:
            result = handlers[name]()
        else:
            raise McpError(f"unknown tool: {name}", code=-32602)
        return {
            "content": [{"type": "text", "text": strict_json(result, indent=2)}],
            "structuredContent": result,
            "isError": False,
        }

    def handle(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            raise McpError("invalid request: expected a JSON object", code=-32600)
        if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            raise McpError("invalid JSON-RPC request", code=-32600)
        if "id" in request and request.get("id") is not None and request_id(request) is None:
            raise McpError("invalid JSON-RPC request id", code=-32600)
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise McpError("params must be an object", code=-32602)
        method = request["method"]
        identifier = request_id(request)
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": identifier,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {
                        "resources": {"listChanged": False},
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            }
        if method == "resources/list":
            result: Any = {"resources": self.resource_list()}
        elif method == "resources/read":
            result = {"contents": self.resource_read(str(params.get("uri", "")))}
        elif method == "tools/list":
            result = {"tools": self.tool_list()}
        elif method == "tools/call":
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise McpError("tool arguments must be an object", code=-32602)
            result = self.tool_call(str(params.get("name", "")), arguments)
        else:
            raise McpError(f"unknown method: {method}", code=-32601)
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def parse_roots(values: list[str], environment_name: str) -> list[Path]:
    raw_values = [*values, *os.environ.get(environment_name, "").split(os.pathsep)]
    return _unique_roots([Path(value) for value in raw_values if value.strip()])


def default_skill_root() -> Path:
    configured = os.environ.get("PHOTONIC_SKILL_ROOT")
    if configured:
        return Path(configured)
    packaged = Path(__file__).resolve().parents[1] / "data" / "skill"
    if (packaged / "references").is_dir() and (packaged / "agents").is_dir():
        return packaged
    working = Path.cwd()
    if (working / "SKILL.md").is_file() and (working / "references").is_dir():
        return working
    raise RuntimeError(
        "packaged MCP skill resources are missing; reinstall photonic-workflow "
        "or set PHOTONIC_SKILL_ROOT to a reviewed skill checkout"
    )


def main(argv: list[str] | None = None) -> int:
    # MCP stdio is UTF-8 regardless of the Windows console/redirected locale.
    # StringIO test transports have no reconfigure method and already use str.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="stdio MCP transport for photonic-workflow.")
    parser.add_argument("--skill-root", type=Path, default=default_skill_root())
    parser.add_argument("--allow-root", action="append", default=[], help="Legacy writable/readable root.")
    parser.add_argument("--read-root", action="append", default=[])
    parser.add_argument("--write-root", action="append", default=[])
    parser.add_argument("--enable-execution", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    legacy = parse_roots(args.allow_root, "PHOTONIC_MCP_ALLOWED_ROOTS")
    server = PhotonicMcpServer(
        args.skill_root,
        read_roots=_unique_roots([*legacy, *parse_roots(args.read_root, "PHOTONIC_MCP_READ_ROOTS")]),
        write_roots=_unique_roots([*legacy, *parse_roots(args.write_root, "PHOTONIC_MCP_WRITE_ROOTS")]),
    )
    for raw in sys.stdin:
        request: Any = None
        try:
            request = json.loads(raw, parse_constant=reject_json_constant)
            response = server.handle(request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}}
        except McpError as exc:
            response = {"jsonrpc": "2.0", "id": request_id(request), "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id(request),
                "error": {"code": -32602, "message": str(exc)},
            }
        if response is not None:
            try:
                encoded = strict_json(response)
            except (TypeError, ValueError):
                encoded = strict_json(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32000, "message": "response is not strict JSON"},
                    }
                )
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
