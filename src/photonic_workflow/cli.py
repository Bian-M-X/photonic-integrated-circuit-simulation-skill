from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

from . import __version__
from .adoption import BACKEND_ADOPTION_DEFINITIONS, BackendAdoptionStore
from .api import envelope, strict_json
from .application import ProjectStatusService
from .audit import audit_project_artifacts
from .capabilities import core_capability_reports, optional_capability_reports
from .circuits import AssemblyError, compose, validate_manifest, write_composition
from .compact_models import compare_model_cards, release_model_card, validate_model_card
from .config import load_project_config, resolved_allowed_roots
from .device_models import evaluate_device, list_models, scattering_csv
from .diagnostics import audit_request, load_diagnostic_request
from .exceptions import (
    ExitCode,
    InvalidInputError,
    PhotonicWorkflowError,
    UnavailableCapabilityError,
)
from .gates import GateLedger
from .layouts import compare_layout_manifests, normalize_layout_manifest
from .models import (
    BackendAdoptionCheck,
    BackendAdoptionTarget,
    CapabilityReport,
    ContractBase,
    ExtractedNetlist,
    GateName,
    GateStatus,
    ImplementationStatus,
    LayoutManifest,
    LogicalNetlist,
    MeasurementManifest,
    ModelCard,
    OptimizationSpec,
    OptimizationTrial,
    PackagingConstraint,
    PdkManifest,
    PromotionDecision,
    SimulationNetlist,
    StatisticalVariationModel,
    TapeoutManifest,
    TestPlan,
    Validity,
    WorkflowProfile,
)
from .models.io import (
    atomic_create_text,
    contract_payload,
    load_contract,
    revalidate_internal,
    write_contract,
)
from .native_cli import native_group
from .optimization import plan_optimization, suggest_candidate
from .packaging import assert_tapeout_editable
from .pdk import validate_pdk_manifest
from .project import create_project_scaffold
from .provenance import sha256_file
from .recipes import (
    RecipeRenderer,
    inspect_recipe,
    list_recipes,
    load_recipe_request,
    provenance_for,
    render_recipe,
)
from .recipes.artifacts import checked_recipe_output as _checked_recipe_output
from .solvers import build_java_batch_plan
from .workflows import backannotate_waveguide_lengths, compare_netlists, validate_netlist


def _emit(
    command: str,
    data: Any,
    *,
    json_output: bool,
    ok: bool = True,
    status: str = "success",
    exit_code: int | ExitCode = ExitCode.SUCCESS,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> None:
    payload = envelope(
        command=command,
        data=data,
        ok=ok,
        status=status,
        exit_code=exit_code,
        warnings=warnings,
        errors=errors,
    )
    click.echo(strict_json(payload if json_output else data))


def _typed(path: Path, expected: str, cls: type[ContractBase]) -> ContractBase:
    model = load_contract(path, expected)
    if not isinstance(model, cls):
        raise InvalidInputError(f"expected {expected}, got {type(model).__name__}")
    return model


def _project(project_root: Path | None) -> tuple[Path, Any, list[Path]]:
    root, config = load_project_config(project_root)
    return root, config, resolved_allowed_roots(root, config)


def _deep_compare(left: Any, right: Any, prefix: str = "") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"path": prefix or "$", "left": left, "right": right}]
    if isinstance(left, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(left.keys() | right.keys()):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in left:
                differences.append({"path": path, "left": "<missing>", "right": right[key]})
            elif key not in right:
                differences.append({"path": path, "left": left[key], "right": "<missing>"})
            else:
                differences.extend(_deep_compare(left[key], right[key], path))
        return differences
    if isinstance(left, list):
        if left == right:
            return []
        return [{"path": prefix or "$", "left": left, "right": right}]
    return [] if left == right else [{"path": prefix or "$", "left": left, "right": right}]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="photonic")
def cli() -> None:
    """Run auditable integrated-photonic design-closure workflows."""


@cli.command("init")
@click.argument("project_root", type=click.Path(path_type=Path), default=".")
@click.option(
    "--profile",
    type=click.Choice([item.value for item in WorkflowProfile], case_sensitive=False),
    default=WorkflowProfile.CUSTOM_DEVICE_FIRST.value,
    show_default=True,
)
@click.option("--device-family", default="waveguide", show_default=True)
@click.option("--project-name")
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def init_command(
    project_root: Path,
    profile: str,
    device_family: str,
    project_name: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    result = create_project_scaffold(
        project_root,
        profile=WorkflowProfile(profile),
        device_family=device_family,
        project_name=project_name,
        dry_run=dry_run,
    )
    _emit("photonic init", result, json_output=json_output)


@cli.command("check")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def check_command(project_root: Path | None, json_output: bool) -> None:
    root, config, allowed_roots = _project(project_root)
    data = {
        "project_root": str(root),
        "config": config.model_dump(mode="json"),
        "allowed_root_count": len(allowed_roots),
        "core_capabilities": [contract_payload(report) for report in core_capability_reports()],
        "gate_summary": GateLedger(root).summary(),
    }
    _emit("photonic check", data, json_output=json_output)


@cli.command("doctor")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option(
    "--load-configured-adapters",
    is_flag=True,
    help="Import only adapter entry points explicitly allowlisted in photonic.toml.",
)
@click.option("--json", "json_output", is_flag=True)
def doctor_command(
    project_root: Path | None,
    load_configured_adapters: bool,
    json_output: bool,
) -> None:
    root, config, _ = _project(project_root)
    data: dict[str, Any] = {
        "project_root": str(root),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "core": [contract_payload(report) for report in core_capability_reports()],
        "optional": [contract_payload(report) for report in optional_capability_reports()],
        "configured_profile": config.profile.value,
        "commercial_concurrency": config.commercial_concurrency,
    }
    try:
        from .adapters.registry import registry_for_project

        registry = registry_for_project(
            config,
            load_entry_points=load_configured_adapters,
        )
        data["adapters"] = [contract_payload(item) for item in registry.descriptors()]
        data["configured_adapter_entrypoints"] = config.adapter_entrypoint_allowlist
        data["loaded_adapter_entrypoints"] = list(registry.loaded_entry_points())
        data["loaded_adapter_providers"] = [
            provider.as_dict() for provider in registry.loaded_providers()
        ]
    except (ImportError, AttributeError) as exc:
        data["adapters"] = []
        data["adapter_registry_warning"] = str(exc)
    _emit("photonic doctor", data, json_output=json_output)


@cli.command("status")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def status_command(project_root: Path | None, json_output: bool) -> None:
    root, _, allowed = _project(project_root)
    data = ProjectStatusService(
        root,
        read_roots=allowed,
    ).inspect().to_payload()
    _emit("photonic status", data, json_output=json_output)


@cli.command("inspect")
@click.argument("target", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def inspect_command(target: Path, json_output: bool) -> None:
    if target.is_dir() and (target / "photonic.toml").is_file():
        root, config, _ = _project(target)
        data = {
            "kind": "project",
            "root": str(root),
            "config": config.model_dump(mode="json"),
            "gates": GateLedger(root).summary(),
        }
    else:
        model = load_contract(target)
        data = contract_payload(model)
    _emit("photonic inspect", data, json_output=json_output)


@cli.group("pdk")
def pdk_group() -> None:
    """Validate public or alias-only PDK manifests."""


@pdk_group.command("validate")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def pdk_validate(manifest: Path, json_output: bool) -> None:
    model = _typed(manifest, "PdkManifest", PdkManifest)
    _emit("photonic pdk validate", validate_pdk_manifest(model), json_output=json_output)


@pdk_group.command("inspect")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def pdk_inspect(manifest: Path, json_output: bool) -> None:
    _emit("photonic pdk inspect", contract_payload(load_contract(manifest, "PdkManifest")), json_output=json_output)


@cli.group("component")
def component_group() -> None:
    """Inspect versioned component and PCell contracts."""


@component_group.command("inspect")
@click.argument("contract", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def component_inspect(contract: Path, json_output: bool) -> None:
    model = load_contract(contract)
    if model.contract_type not in {"ComponentContract", "PCellContract", "DeviceContract"}:
        raise InvalidInputError("component inspect expects ComponentContract, PCellContract or DeviceContract")
    _emit("photonic component inspect", contract_payload(model), json_output=json_output)


@cli.group("model")
def model_group() -> None:
    """Manage compact-model cards without invoking a solver implicitly."""


@model_group.command("ingest")
@click.argument("card", type=click.Path(exists=True, path_type=Path))
@click.argument("destination", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def model_ingest(card: Path, destination: Path, dry_run: bool, json_output: bool) -> None:
    model = _typed(card, "ModelCard", ModelCard)
    data = {
        "dry_run": dry_run,
        "source": str(card.resolve()),
        "destination": str(destination.resolve()),
        "model_card": contract_payload(model),
    }
    if not dry_run:
        write_contract(destination, model)
    _emit("photonic model ingest", data, json_output=json_output)


@model_group.command("inspect")
@click.argument("card", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def model_inspect(card: Path, json_output: bool) -> None:
    _emit("photonic model inspect", contract_payload(load_contract(card, "ModelCard")), json_output=json_output)


@model_group.command("validate")
@click.argument("card", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def model_validate(card: Path, json_output: bool) -> None:
    model = _typed(card, "ModelCard", ModelCard)
    _emit("photonic model validate", validate_model_card(model), json_output=json_output)


@model_group.command("compare")
@click.argument("left", type=click.Path(exists=True, path_type=Path))
@click.argument("right", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def model_compare(left: Path, right: Path, json_output: bool) -> None:
    left_model = _typed(left, "ModelCard", ModelCard)
    right_model = _typed(right, "ModelCard", ModelCard)
    _emit("photonic model compare", compare_model_cards(left_model, right_model), json_output=json_output)


@model_group.command("build")
@click.argument("card", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=True)
@click.option("--json", "json_output", is_flag=True)
def model_build(card: Path, dry_run: bool, json_output: bool) -> None:
    model = _typed(card, "ModelCard", ModelCard)
    if not dry_run:
        raise UnavailableCapabilityError("model build requires an explicitly configured Evaluation API backend")
    _emit(
        "photonic model build",
        {
            "dry_run": True,
            "model_card_id": model.stable_id,
            "producer": model.producer,
            "fidelity": model.fidelity.value,
            "will_execute": False,
        },
        json_output=json_output,
    )


@model_group.command("release")
@click.argument("card", type=click.Path(exists=True, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def model_release(card: Path, output: Path, dry_run: bool, json_output: bool) -> None:
    released = release_model_card(_typed(card, "ModelCard", ModelCard))
    if not dry_run:
        write_contract(output, released)
    _emit(
        "photonic model release",
        {"dry_run": dry_run, "output": str(output.resolve()), "card": contract_payload(released)},
        json_output=json_output,
    )


@cli.group("sparams")
def sparams_group() -> None:
    """Validate canonical complex long-form S-parameter data."""


@sparams_group.command("validate")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--structure-only", is_flag=True)
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def sparams_validate(
    manifest: Path,
    structure_only: bool,
    project_root: Path | None,
    json_output: bool,
) -> None:
    payload, data = validate_manifest(
        manifest,
        check_data=not structure_only,
        project_root=project_root,
    )
    _emit(
        "photonic sparams validate",
        {
            "valid": True,
            "component_count": len(payload["components"]),
            "data_checked": not structure_only,
            "wavelength_count": (
                len(next(iter(data.values())).wavelengths_nm) if data else None
            ),
        },
        json_output=json_output,
    )


@cli.group("circuit")
def circuit_group() -> None:
    """Validate and compose legacy assembly v1 circuit manifests."""


@circuit_group.command("validate")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def circuit_validate(manifest: Path, project_root: Path | None, json_output: bool) -> None:
    payload, data = validate_manifest(manifest, project_root=project_root)
    _emit(
        "photonic circuit validate",
        {
            "valid": True,
            "instances": len(payload["instances"]),
            "connections": len(payload["connections"]),
            "external_ports": list(payload["external_ports"]),
            "wavelengths_nm": list(next(iter(data.values())).wavelengths_nm),
        },
        json_output=json_output,
    )


@circuit_group.command("compose")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--summary", type=click.Path(path_type=Path))
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def circuit_compose(
    manifest: Path,
    output: Path,
    summary: Path | None,
    project_root: Path | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    payload, data = validate_manifest(manifest, project_root=project_root)
    rows, summary_payload = compose(payload, data)
    if not dry_run:
        write_composition(output, rows)
        if summary:
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(strict_json(summary_payload) + "\n", encoding="utf-8")
    _emit(
        "photonic circuit compose",
        {
            "dry_run": dry_run,
            "output": str(output.resolve()),
            "row_count": len(rows),
            "summary": summary_payload,
        },
        json_output=json_output,
    )


@cli.group("netlist")
def netlist_group() -> None:
    """Validate, compare and backannotate logical/extracted/simulation netlists."""


@netlist_group.command("validate")
@click.argument("netlist", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def netlist_validate(netlist: Path, json_output: bool) -> None:
    model = load_contract(netlist)
    if not isinstance(model, (LogicalNetlist, ExtractedNetlist, SimulationNetlist)):
        raise InvalidInputError("netlist validate expects a logical, extracted or simulation netlist")
    _emit("photonic netlist validate", validate_netlist(model), json_output=json_output)


@netlist_group.command("compare")
@click.argument("intended", type=click.Path(exists=True, path_type=Path))
@click.argument("extracted", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def netlist_compare(intended: Path, extracted: Path, json_output: bool) -> None:
    left = load_contract(intended)
    right = _typed(extracted, "ExtractedNetlist", ExtractedNetlist)
    if not isinstance(left, (LogicalNetlist, SimulationNetlist)):
        raise InvalidInputError("intended netlist must be LogicalNetlist or SimulationNetlist")
    _emit("photonic netlist compare", compare_netlists(left, right), json_output=json_output)


@netlist_group.command("extract")
@click.argument("layout_manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=True)
@click.option("--json", "json_output", is_flag=True)
def netlist_extract(layout_manifest: Path, dry_run: bool, json_output: bool) -> None:
    layout = _typed(layout_manifest, "LayoutManifest", LayoutManifest)
    if not dry_run:
        raise UnavailableCapabilityError("netlist extraction requires a configured KLayout/GDSFactory adapter")
    _emit(
        "photonic netlist extract",
        {
            "dry_run": True,
            "layout_manifest_id": layout.stable_id,
            "backend": layout.backend,
            "will_execute": False,
            "required_capability": "layout-to-netlist",
        },
        json_output=json_output,
    )


@netlist_group.command("backannotate")
@click.argument("simulation_netlist", type=click.Path(exists=True, path_type=Path))
@click.argument("lengths_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def netlist_backannotate(
    simulation_netlist: Path,
    lengths_json: Path,
    output: Path,
    dry_run: bool,
    json_output: bool,
) -> None:
    model = _typed(simulation_netlist, "SimulationNetlist", SimulationNetlist)
    payload = json.loads(lengths_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidInputError("lengths JSON must be an object keyed by instance name")
    annotated = backannotate_waveguide_lengths(model, {key: float(value) for key, value in payload.items()})
    if not dry_run:
        write_contract(output, annotated)
    _emit(
        "photonic netlist backannotate",
        {"dry_run": dry_run, "output": str(output.resolve()), "netlist": contract_payload(annotated)},
        json_output=json_output,
    )


@cli.group("layout")
def layout_group() -> None:
    """Normalize and compare backend-neutral LayoutManifest contracts."""


@layout_group.command("normalize")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def layout_normalize(manifest: Path, output: Path, dry_run: bool, json_output: bool) -> None:
    normalized = normalize_layout_manifest(_typed(manifest, "LayoutManifest", LayoutManifest))
    if not dry_run:
        write_contract(output, normalized)
    _emit(
        "photonic layout normalize",
        {"dry_run": dry_run, "output": str(output.resolve()), "manifest": contract_payload(normalized)},
        json_output=json_output,
    )


@layout_group.command("compare-backends")
@click.argument("left", type=click.Path(exists=True, path_type=Path))
@click.argument("right", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def layout_compare(left: Path, right: Path, json_output: bool) -> None:
    left_model = _typed(left, "LayoutManifest", LayoutManifest)
    right_model = _typed(right, "LayoutManifest", LayoutManifest)
    _emit(
        "photonic layout compare-backends",
        compare_layout_manifests(left_model, right_model),
        json_output=json_output,
    )
@cli.group("device")
def device_group() -> None:
    """Evaluate declared analytic/reduced device models without a field solver."""


@device_group.command("list")
@click.option("--json", "json_output", is_flag=True)
def device_list(json_output: bool) -> None:
    _emit("photonic device list", {"models": list_models()}, json_output=json_output)


def _device_request(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise InvalidInputError(f"non-finite JSON number: {value}")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise InvalidInputError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=unique_keys,
    )


@device_group.command("evaluate")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def device_evaluate(request: Path, json_output: bool) -> None:
    _emit(
        "photonic device evaluate",
        evaluate_device(_device_request(request)),
        json_output=json_output,
    )


@device_group.command("export")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--project-root", type=click.Path(path_type=Path), required=True)
@click.option("--json", "json_output", is_flag=True)
def device_export(request: Path, output: Path, project_root: Path, json_output: bool) -> None:
    result = evaluate_device(_device_request(request))
    root, _, _ = _project(project_root)
    target, relative = _checked_recipe_output(root, output)
    try:
        atomic_create_text(
            target,
            scattering_csv(result),
            path_guard=lambda candidate: _checked_recipe_output(root, candidate),
        )
    except FileExistsError as exc:
        raise InvalidInputError(f"device output already exists: {relative}") from exc
    _emit(
        "photonic device export",
        {
            "artifact_path": relative,
            "metadata_path_base": "project-root; rebase sparameters for a nested assembly manifest",
            "sha256": sha256_file(target),
            "model": result["model"],
            "convention": result["convention"],
            "component": {
                "ports": result["port_order"],
                "port_modes": dict.fromkeys(result["port_order"], "declared-single-mode"),
                "model_level": result["model_level"],
                "reference_plane": "local physical port planes; see evaluated model metadata",
                "sparameters": relative,
                "passive": True,
            },
            "physics_accepted": False,
            "will_execute": False,
        },
        json_output=json_output,
    )


@cli.group("recipe")
def recipe_group() -> None:
    """Inspect and render deterministic, non-executing modeling recipes."""


@recipe_group.command("list")
@click.option("--json", "json_output", is_flag=True)
def recipe_list(json_output: bool) -> None:
    _emit(
        "photonic recipe list",
        {"recipes": [item.to_payload() for item in list_recipes()]},
        json_output=json_output,
    )


@recipe_group.command("inspect")
@click.argument("recipe_id")
@click.option("--version")
@click.option("--json", "json_output", is_flag=True)
def recipe_inspect(recipe_id: str, version: str | None, json_output: bool) -> None:
    descriptor = inspect_recipe(recipe_id, version=version)
    _emit(
        "photonic recipe inspect",
        {**descriptor.to_payload(), "provenance": provenance_for(recipe_id)},
        json_output=json_output,
    )


@recipe_group.command("render")
@click.argument("recipe_id")
@click.option(
    "--input",
    "input_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--renderer",
    type=click.Choice([item.value for item in RecipeRenderer], case_sensitive=True),
    default=RecipeRenderer.CANONICAL_JSON.value,
    show_default=True,
)
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--instance-id")
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def recipe_render(
    recipe_id: str,
    input_path: Path,
    renderer: str,
    output: Path | None,
    project_root: Path | None,
    instance_id: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    if output is not None and project_root is None:
        raise InvalidInputError("--output requires --project-root")
    request = load_recipe_request(input_path)
    if request.recipe_id != recipe_id:
        raise InvalidInputError(
            f"CLI recipe ID {recipe_id!r} does not match request "
            f"{request.recipe_id!r}"
        )
    rendered = render_recipe(
        recipe_id,
        request.parameters,
        version=request.recipe_version,
        renderer=renderer,
        instance_id=instance_id,
    )

    output_path: Path | None = None
    relative_output: str | None = None
    if output is not None:
        assert project_root is not None
        root, _, _ = _project(project_root)
        output_path, relative_output = _checked_recipe_output(root, output)
        if not dry_run:
            try:
                atomic_create_text(
                    output_path,
                    rendered.content,
                    path_guard=lambda candidate: _checked_recipe_output(
                        root,
                        candidate,
                    ),
                )
            except FileExistsError as exc:
                raise InvalidInputError(
                    f"recipe output already exists: {relative_output}"
                ) from exc
            if sha256_file(output_path) != rendered.sha256:
                raise InvalidInputError("written recipe output failed SHA-256 verification")

    data = rendered.to_payload(include_content=output is None or dry_run)
    data.update(
        {
            "dry_run": dry_run,
            "written": bool(output_path is not None and not dry_run),
            "artifact_path": relative_output,
        }
    )
    _emit("photonic recipe render", data, json_output=json_output)


@cli.group("solver")
def solver_group() -> None:
    """Probe and render bounded solver plans."""


@solver_group.command("check")
@click.option("--json", "json_output", is_flag=True)
def solver_check(json_output: bool) -> None:
    solver_root = os.environ.get("PHOTONIC_SOLVER_ROOT")
    required = {
        "batch": bool(solver_root and (Path(solver_root) / "bin" / "win64" / "comsolbatch.exe").is_file()),
        "compiler": bool(solver_root and (Path(solver_root) / "bin" / "win64" / "comsolcompile.exe").is_file()),
    }
    diagnostics = {
        "desktop": bool(solver_root and (Path(solver_root) / "bin" / "win64" / "comsol.exe").is_file()),
    }
    report = CapabilityReport(
        stable_id="capability:comsol-native-java-batch",
        name="COMSOL native Java batch",
        source="local filesystem alias probe",
        status="probed",
        validity="valid",
        capability="comsol-native-java-batch",
        implementation=ImplementationStatus.IMPLEMENTED,
        availability="available" if all(required.values()) else "unavailable",
        features={**required, **diagnostics, "solver_root_redacted": bool(solver_root)},
        reasons=[] if all(required.values()) else ["PHOTONIC_SOLVER_ROOT is unset or lacks comsolcompile/comsolbatch"],
        probe_method="version-insensitive official-entrypoint probe; no solver or license execution",
    )
    _emit("photonic solver check", contract_payload(report), json_output=json_output)


@solver_group.command("plan")
@click.argument("java_file", type=click.Path(path_type=Path))
@click.option("--output-mph", type=click.Path(path_type=Path), required=True)
@click.option("--batch-log", type=click.Path(path_type=Path), required=True)
@click.option("--runtime-dir", type=click.Path(path_type=Path), required=True)
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--timeout-s", type=click.IntRange(1, 604800), default=3600)
@click.option("--json", "json_output", is_flag=True)
def solver_plan(
    java_file: Path,
    output_mph: Path,
    batch_log: Path,
    runtime_dir: Path,
    project_root: Path | None,
    timeout_s: int,
    json_output: bool,
) -> None:
    root, _, allowed = _project(project_root)
    plan = build_java_batch_plan(
        java_file=(root / java_file if not java_file.is_absolute() else java_file),
        output_mph=(root / output_mph if not output_mph.is_absolute() else output_mph),
        batch_log=(root / batch_log if not batch_log.is_absolute() else batch_log),
        runtime_dir=(root / runtime_dir if not runtime_dir.is_absolute() else runtime_dir),
        timeout_s=timeout_s,
        allowed_roots=allowed,
    )
    _emit("photonic solver plan", plan, json_output=json_output)


@cli.group("optimize")
def optimize_group() -> None:
    """Plan and inspect checkpointable optimization campaigns."""


@optimize_group.command("plan")
@click.argument("spec", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def optimize_plan(spec: Path, json_output: bool) -> None:
    model = _typed(spec, "OptimizationSpec", OptimizationSpec)
    _emit("photonic optimize plan", plan_optimization(model), json_output=json_output)


@optimize_group.command("suggest")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--trials", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True)
@click.option("--pool-size", type=click.IntRange(64, 4096), default=1024, show_default=True)
@click.option("--local-radius", type=click.FloatRange(min=0, max=1, min_open=True), default=0.25, show_default=True)
@click.option("--json", "json_output", is_flag=True)
def optimize_suggest(spec: Path, trials: Path, pool_size: int, local_radius: float, json_output: bool) -> None:
    """Suggest one continuous candidate from frozen trials; read-only, no solver."""
    model = _typed(spec, "OptimizationSpec", OptimizationSpec)
    trial_files = sorted(trials.glob("*.json"))
    if len(trial_files) > 512:
        raise InvalidInputError("suggest reads at most 512 trial files")
    history = [_typed(path, "OptimizationTrial", OptimizationTrial) for path in trial_files]
    data = suggest_candidate(model, history, pool_size=pool_size, local_radius=local_radius)
    _emit("photonic optimize suggest", data, json_output=json_output)


def _optimization_execution_unavailable(command: str, spec: Path, json_output: bool) -> None:
    model = _typed(spec, "OptimizationSpec", OptimizationSpec)
    data = plan_optimization(model)
    data.update(
        {
            "will_execute": False,
            "availability": "unavailable",
            "reason": "Phase A provides the Evaluation API contract and plan only",
        }
    )
    _emit(
        command,
        data,
        json_output=json_output,
        ok=False,
        status="unavailable_capability",
        exit_code=ExitCode.UNAVAILABLE_CAPABILITY,
        errors=[data["reason"]],
    )
    raise click.exceptions.Exit(int(ExitCode.UNAVAILABLE_CAPABILITY))


@optimize_group.command("run")
@click.argument("spec", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=True)
@click.option("--json", "json_output", is_flag=True)
def optimize_run(spec: Path, dry_run: bool, json_output: bool) -> None:
    if dry_run:
        optimize_plan.callback(spec, json_output)  # type: ignore[attr-defined]
        return
    _optimization_execution_unavailable("photonic optimize run", spec, json_output)


@optimize_group.command("resume")
@click.argument("spec", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=True)
@click.option("--json", "json_output", is_flag=True)
def optimize_resume(spec: Path, dry_run: bool, json_output: bool) -> None:
    if dry_run:
        data = plan_optimization(_typed(spec, "OptimizationSpec", OptimizationSpec))
        data["resume"] = True
        _emit("photonic optimize resume", data, json_output=json_output)
        return
    _optimization_execution_unavailable("photonic optimize resume", spec, json_output)


@optimize_group.command("inspect")
@click.argument("spec", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def optimize_inspect(spec: Path, json_output: bool) -> None:
    _emit(
        "photonic optimize inspect",
        contract_payload(load_contract(spec, "OptimizationSpec")),
        json_output=json_output,
    )


@optimize_group.command("promote")
@click.argument("decision", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def optimize_promote(decision: Path, json_output: bool) -> None:
    model = _typed(decision, "PromotionDecision", PromotionDecision)
    _emit(
        "photonic optimize promote",
        {
            "decision": contract_payload(model),
            "will_execute": False,
            "required_next_action": "run the declared target-fidelity comparison through a configured adapter",
        },
        json_output=json_output,
    )


@optimize_group.command("compare")
@click.argument("left", type=click.Path(exists=True, path_type=Path))
@click.argument("right", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def optimize_compare(left: Path, right: Path, json_output: bool) -> None:
    left_payload = contract_payload(load_contract(left))
    right_payload = contract_payload(load_contract(right))
    _emit(
        "photonic optimize compare",
        {"differences": _deep_compare(left_payload, right_payload)},
        json_output=json_output,
    )


@cli.group("variation")
def variation_group() -> None:
    """Validate process-corner and statistical-variation contracts."""


@variation_group.command("validate")
@click.argument("model", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def variation_validate(model: Path, json_output: bool) -> None:
    variation = _typed(model, "StatisticalVariationModel", StatisticalVariationModel)
    invented = not variation.foundry_supplied and bool(variation.variables)
    data = {
        "valid": not invented,
        "foundry_supplied": variation.foundry_supplied,
        "variable_count": len(variation.variables),
        "warning": (
            "non-foundry distributions cannot be promoted as fabrication-yield evidence"
            if invented
            else None
        ),
    }
    _emit("photonic variation validate", data, json_output=json_output)


@cli.group("package")
def package_group() -> None:
    """Inspect packaging constraints."""


@package_group.command("inspect")
@click.argument("constraint", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def package_inspect(constraint: Path, json_output: bool) -> None:
    model = _typed(constraint, "PackagingConstraint", PackagingConstraint)
    _emit("photonic package inspect", contract_payload(model), json_output=json_output)


@cli.group("testplan")
def testplan_group() -> None:
    """Inspect test plans; real instruments remain dry-run by default."""


@testplan_group.command("inspect")
@click.argument("plan", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def testplan_inspect(plan: Path, json_output: bool) -> None:
    model = _typed(plan, "TestPlan", TestPlan)
    _emit("photonic testplan inspect", contract_payload(model), json_output=json_output)


@cli.group("tapeout")
def tapeout_group() -> None:
    """Inspect or freeze a tapeout manifest."""


@tapeout_group.command("inspect")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def tapeout_inspect(manifest: Path, json_output: bool) -> None:
    model = _typed(manifest, "TapeoutManifest", TapeoutManifest)
    _emit("photonic tapeout inspect", contract_payload(model), json_output=json_output)


@tapeout_group.command("freeze")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def tapeout_freeze(manifest: Path, output: Path, dry_run: bool, json_output: bool) -> None:
    model = _typed(manifest, "TapeoutManifest", TapeoutManifest)
    assert_tapeout_editable(model)
    payload = model.model_dump()
    payload.update(
        {
            "frozen": True,
            "frozen_at": datetime.now(UTC),
            "status": "frozen",
            "validity": Validity.VALID,
            "revision": str(int(model.revision) + 1) if model.revision.isdigit() else model.revision,
        }
    )
    frozen = revalidate_internal(TapeoutManifest, payload)
    if not dry_run:
        write_contract(output, frozen)
    _emit(
        "photonic tapeout freeze",
        {"dry_run": dry_run, "output": str(output.resolve()), "manifest": contract_payload(frozen)},
        json_output=json_output,
    )


@cli.group("measurement")
def measurement_group() -> None:
    """Inspect measurement manifests and evidence linkage."""


@measurement_group.command("inspect")
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def measurement_inspect(manifest: Path, json_output: bool) -> None:
    model = _typed(manifest, "MeasurementManifest", MeasurementManifest)
    _emit("photonic measurement inspect", contract_payload(model), json_output=json_output)


@cli.group("gate")
def gate_group() -> None:
    """Manage device, measurement, and backend-adoption gates."""


@gate_group.command("list")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def gate_list(project_root: Path | None, json_output: bool) -> None:
    root, _, _ = _project(project_root)
    _emit("photonic gate list", GateLedger(root).summary(), json_output=json_output)


@gate_group.command("set")
@click.argument("gate", type=click.Choice([item.value for item in GateName], case_sensitive=False))
@click.argument("status", type=click.Choice([item.value for item in GateStatus], case_sensitive=False))
@click.option(
    "--evidence",
    multiple=True,
    help=(
        "Repeat CHECK=PROJECT_RELATIVE_PATH for pass; use "
        "applicability=PROJECT_RELATIVE_PATH for not_applicable."
    ),
)
@click.option("--metric", multiple=True, help="KEY=VALUE")
@click.option("--reason", default="")
@click.option("--next-action", default="")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def gate_set(
    gate: str,
    status: str,
    evidence: tuple[str, ...],
    metric: tuple[str, ...],
    reason: str,
    next_action: str,
    project_root: Path | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    root, _, _ = _project(project_root)
    metrics: dict[str, float | str] = {}
    for item in metric:
        if "=" not in item:
            raise InvalidInputError("--metric must use KEY=VALUE")
        key, value = item.split("=", 1)
        try:
            metrics[key] = float(value)
        except ValueError:
            metrics[key] = value
    record = GateLedger(root).update(
        GateName(gate.upper()),
        GateStatus(status.lower()),
        evidence=list(evidence),
        metrics=metrics,
        reason=reason,
        next_action=next_action,
        dry_run=dry_run,
    )
    _emit(
        "photonic gate set",
        {"dry_run": dry_run, "record": contract_payload(record)},
        json_output=json_output,
    )


@gate_group.group("adoption")
def gate_adoption_group() -> None:
    """Manage independent Phase B and Phase C backend adoption gates."""


def _adoption_store(project_root: Path | None) -> BackendAdoptionStore:
    root, _, allowed = _project(project_root)
    return BackendAdoptionStore(root, allowed_roots=allowed)


@gate_adoption_group.command("init")
@click.argument(
    "target",
    type=click.Choice(
        [item.value for item in BackendAdoptionTarget],
        case_sensitive=False,
    ),
)
@click.option("--source", default="photonic gate adoption init", show_default=True)
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def gate_adoption_init(
    target: str,
    source: str,
    project_root: Path | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    record = _adoption_store(project_root).initialize(
        BackendAdoptionTarget(target),
        source=source,
        dry_run=dry_run,
    )
    _emit(
        "photonic gate adoption init",
        {"dry_run": dry_run, "record": contract_payload(record)},
        json_output=json_output,
    )


@gate_adoption_group.command("list")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def gate_adoption_list(project_root: Path | None, json_output: bool) -> None:
    store = _adoption_store(project_root)
    targets: list[dict[str, Any]] = []
    for target, definition in BACKEND_ADOPTION_DEFINITIONS.items():
        initialized = store.exists(target)
        record = store.load(target) if initialized else None
        targets.append(
            {
                "target": target.value,
                "phase": definition.phase.value,
                "initialized": initialized,
                "status": (
                    record.status.value if record is not None else GateStatus.BLOCKED.value
                ),
                "validity": (
                    record.validity.value if record is not None else Validity.UNKNOWN.value
                ),
                "required_check_count": len(definition.required_checks),
                "path": f"verification/adoption/{target.value}.json",
            }
        )
    _emit(
        "photonic gate adoption list",
        {"targets": targets},
        json_output=json_output,
    )


@gate_adoption_group.command("inspect")
@click.argument(
    "target",
    type=click.Choice(
        [item.value for item in BackendAdoptionTarget],
        case_sensitive=False,
    ),
)
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def gate_adoption_inspect(
    target: str,
    project_root: Path | None,
    json_output: bool,
) -> None:
    record = _adoption_store(project_root).load(BackendAdoptionTarget(target))
    _emit(
        "photonic gate adoption inspect",
        {"record": contract_payload(record)},
        json_output=json_output,
    )


@gate_adoption_group.command("record")
@click.argument(
    "target",
    type=click.Choice(
        [item.value for item in BackendAdoptionTarget],
        case_sensitive=False,
    ),
)
@click.argument(
    "check",
    type=click.Choice(
        [item.value for item in BackendAdoptionCheck],
        case_sensitive=False,
    ),
)
@click.argument(
    "status",
    type=click.Choice(
        [GateStatus.PASS.value, GateStatus.FAIL.value, GateStatus.BLOCKED.value],
        case_sensitive=False,
    ),
)
@click.option("--evidence", multiple=True)
@click.option("--reason", required=True)
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def gate_adoption_record(
    target: str,
    check: str,
    status: str,
    evidence: tuple[str, ...],
    reason: str,
    project_root: Path | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    record = _adoption_store(project_root).record(
        BackendAdoptionTarget(target),
        BackendAdoptionCheck(check),
        GateStatus(status),
        evidence=list(evidence),
        reason=reason,
        dry_run=dry_run,
    )
    _emit(
        "photonic gate adoption record",
        {"dry_run": dry_run, "record": contract_payload(record)},
        json_output=json_output,
    )


@gate_adoption_group.command("evaluate")
@click.argument(
    "target",
    type=click.Choice(
        [item.value for item in BackendAdoptionTarget],
        case_sensitive=False,
    ),
)
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def gate_adoption_evaluate(
    target: str,
    project_root: Path | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    record = _adoption_store(project_root).evaluate(
        BackendAdoptionTarget(target),
        dry_run=dry_run,
    )
    _emit(
        "photonic gate adoption evaluate",
        {"dry_run": dry_run, "record": contract_payload(record)},
        json_output=json_output,
    )


@cli.group("audit")
def audit_group() -> None:
    """Audit repository or project artifacts."""


@audit_group.command("diagnostics")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--fail-on-issues", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def audit_diagnostics(request: Path, fail_on_issues: bool, json_output: bool) -> None:
    """Read-only conditional scattering, phase or final-geometry checks; no solver or gate writes."""
    result = audit_request(load_diagnostic_request(request))
    acceptable = result["status"] in {"pass", "not_applicable"}
    code = ExitCode.ACCEPTANCE_REJECTED if fail_on_issues and not acceptable else ExitCode.SUCCESS
    _emit("photonic audit diagnostics", result, json_output=json_output,
          ok=acceptable, status=result["status"], exit_code=code)
    if code:
        raise click.exceptions.Exit(int(code))


@audit_group.command("artifacts")
@click.argument("project_root", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--large-file-mb", type=click.IntRange(1), default=25)
@click.option("--fail-on-issues", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def audit_artifacts(
    project_root: Path,
    large_file_mb: int,
    fail_on_issues: bool,
    json_output: bool,
) -> None:
    result = audit_project_artifacts(project_root, large_file_mb=large_file_mb)
    _emit(
        "photonic audit artifacts",
        result,
        json_output=json_output,
        ok=result["finding_count"] == 0,
        status="success" if result["finding_count"] == 0 else "findings",
        exit_code=(ExitCode.SECURITY_VIOLATION if fail_on_issues and result["finding_count"] else ExitCode.SUCCESS),
    )
    if fail_on_issues and result["finding_count"]:
        raise click.exceptions.Exit(int(ExitCode.SECURITY_VIOLATION))


@cli.group("report")
def report_group() -> None:
    """Render bounded project status reports."""


@report_group.command("status")
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def report_status(project_root: Path | None, json_output: bool) -> None:
    status_command.callback(project_root, json_output)  # type: ignore[attr-defined]


@cli.group("matlab")
def matlab_group() -> None:
    """Probe MATLAB and render controlled batch plans."""


def _matlab_adapter(
    executable_alias: str | None = None,
    *,
    project_root: Path | None = None,
    allowed_roots: list[Path] | None = None,
    inventory: Path | None = None,
) -> Any:
    from .adapters.matlab.runtime import MatlabRuntimeAdapter

    return MatlabRuntimeAdapter(
        executable_alias=executable_alias or "matlab",
        project_root=project_root,
        allowed_roots=allowed_roots,
        inventory=inventory,
    )


@matlab_group.command("check")
@click.option("--executable", default="matlab")
@click.option(
    "--inventory",
    type=click.Path(exists=True, path_type=Path),
    help="Structured inventory captured by the fixed local MATLAB probe.",
)
@click.option("--deep", is_flag=True, help="Request a deep probe; Phase A reports it as unverified.")
@click.option("--json", "json_output", is_flag=True)
def matlab_check(executable: str, inventory: Path | None, deep: bool, json_output: bool) -> None:
    adapter = _matlab_adapter(executable, inventory=inventory)
    report = adapter.check()
    if deep:
        report.provenance.append(
            "deep execution was requested but not started; use an explicitly authorized fixed-wrapper smoke"
        )
    available = getattr(report, "availability", None)
    available_value = available.value if hasattr(available, "value") else str(available)
    is_available = available_value == "available"
    exit_code = ExitCode.SUCCESS if is_available else ExitCode.UNAVAILABLE_CAPABILITY
    _emit(
        "photonic matlab check",
        contract_payload(report),
        json_output=json_output,
        ok=is_available,
        status="success" if is_available else "unavailable_capability",
        exit_code=exit_code,
        errors=[] if is_available else list(getattr(report, "reasons", [])),
    )
    if not is_available:
        raise click.exceptions.Exit(int(exit_code))


@matlab_group.command("doctor")
@click.option("--executable", default="matlab")
@click.option("--inventory", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def matlab_doctor(executable: str, inventory: Path | None, json_output: bool) -> None:
    adapter = _matlab_adapter(executable, inventory=inventory)
    report = adapter.check()
    _emit(
        "photonic matlab doctor",
        {
            "environment": contract_payload(report),
            "descriptor": contract_payload(adapter.descriptor),
        },
        json_output=json_output,
    )


@matlab_group.command("products")
@click.option("--executable", default="matlab")
@click.option("--inventory", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def matlab_products(executable: str, inventory: Path | None, json_output: bool) -> None:
    report = _matlab_adapter(executable, inventory=inventory).check()
    _emit(
        "photonic matlab products",
        [contract_payload(item) for item in report.products],
        json_output=json_output,
    )


@matlab_group.command("toolboxes")
@click.option("--executable", default="matlab")
@click.option("--inventory", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def matlab_toolboxes(executable: str, inventory: Path | None, json_output: bool) -> None:
    report = _matlab_adapter(executable, inventory=inventory).check()
    _emit(
        "photonic matlab toolboxes",
        [contract_payload(item) for item in report.community_toolboxes],
        json_output=json_output,
    )


@matlab_group.command("sessions")
@click.option("--json", "json_output", is_flag=True)
def matlab_sessions(json_output: bool) -> None:
    from .adapters.matlab.engine import MatlabEngineAdapter

    report = MatlabEngineAdapter(inspect_shared_sessions=True).check()
    _emit("photonic matlab sessions", contract_payload(report), json_output=json_output)


@matlab_group.command("plan")
@click.argument("run_spec", type=click.Path(exists=True, path_type=Path))
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def matlab_plan(run_spec: Path, project_root: Path | None, json_output: bool) -> None:
    root, config, allowed = _project(project_root)
    spec = load_contract(run_spec, "MatlabRunSpec")
    plan = _matlab_adapter(
        config.matlab_executable_alias,
        project_root=root,
        allowed_roots=allowed,
    ).plan(spec)
    _emit("photonic matlab plan", plan.public_payload(), json_output=json_output)


@matlab_group.command("run")
@click.argument("run_spec", type=click.Path(exists=True, path_type=Path))
@click.option("--project-root", type=click.Path(path_type=Path))
@click.option(
    "--execute/--dry-run",
    default=False,
    help="Execute only when the adapter route has been locally verified; default is dry-run.",
)
@click.option("--json", "json_output", is_flag=True)
def matlab_run(
    run_spec: Path,
    project_root: Path | None,
    execute: bool,
    json_output: bool,
) -> None:
    root, config, allowed = _project(project_root)
    spec = load_contract(run_spec, "MatlabRunSpec")
    adapter = _matlab_adapter(
        config.matlab_executable_alias,
        project_root=root,
        allowed_roots=allowed,
    )
    plan = adapter.plan(spec)
    if not execute:
        _emit(
            "photonic matlab run",
            plan.public_payload(),
            json_output=json_output,
        )
        return
    result = adapter.execute(plan)
    _emit("photonic matlab run", contract_payload(result), json_output=json_output)


@matlab_group.command("test")
@click.option("--json", "json_output", is_flag=True)
def matlab_test(json_output: bool) -> None:
    _emit(
        "photonic matlab test",
        {
            "availability": "unverified",
            "will_execute": False,
            "reason": "MATLAB smoke and matlab.unittest belong to Phase B on an authorized MATLAB runner",
        },
        json_output=json_output,
        ok=False,
        status="unavailable_capability",
        exit_code=ExitCode.UNAVAILABLE_CAPABILITY,
    )
    raise click.exceptions.Exit(int(ExitCode.UNAVAILABLE_CAPABILITY))


@matlab_group.command("inspect")
@click.argument("result", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def matlab_inspect(result: Path, json_output: bool) -> None:
    from .adapters.matlab.results import load_matlab_result

    parsed = load_matlab_result(result)
    _emit("photonic matlab inspect", contract_payload(parsed), json_output=json_output)


cli.add_command(native_group)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        result = cli.main(args=arguments, prog_name="photonic", standalone_mode=False)
        return int(result) if isinstance(result, int) else int(ExitCode.SUCCESS)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        return int(ExitCode.INVALID_INPUT)
    except AssemblyError as exc:
        error: Exception = InvalidInputError(str(exc))
    except (PhotonicWorkflowError, ValidationError, json.JSONDecodeError, OSError, ValueError) as exc:
        error = exc
    exit_code = (
        error.exit_code
        if isinstance(error, PhotonicWorkflowError)
        else ExitCode.INVALID_INPUT
    )
    if "--json" in arguments:
        click.echo(
            strict_json(
                envelope(
                    command="photonic " + " ".join(item for item in arguments if item != "--json"),
                    data={},
                    ok=False,
                    status=ExitCode(exit_code).name.lower(),
                    exit_code=exit_code,
                    errors=[str(error)],
                )
            )
        )
    else:
        click.echo(f"ERROR: {error}", err=True)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
