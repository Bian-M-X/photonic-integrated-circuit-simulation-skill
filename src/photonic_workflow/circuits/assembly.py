from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from photonic_workflow.security import ensure_within_allowed_roots

REQUIRED_COLUMNS = ("wavelength_nm", "out_port", "in_port", "s_real", "s_imag")
MODEL_LEVELS = {"analytic", "reduced", "full-wave-2d-eim", "full-wave-3d", "measured"}


class AssemblyError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentData:
    ports: tuple[str, ...]
    wavelengths_nm: tuple[float, ...]
    matrices: dict[float, Any]


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssemblyError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AssemblyError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AssemblyError("manifest root must be a JSON object")
    return payload


def endpoint_parts(endpoint: str) -> tuple[str, str]:
    if not isinstance(endpoint, str) or endpoint.count(":") != 1:
        raise AssemblyError(f"endpoint must be 'instance:port': {endpoint!r}")
    instance, port = endpoint.split(":", 1)
    if not instance or not port:
        raise AssemblyError(f"endpoint must be 'instance:port': {endpoint!r}")
    return instance, port


def component_for_endpoint(manifest: dict[str, Any], endpoint: str) -> tuple[dict[str, Any], str]:
    instance_name, port = endpoint_parts(endpoint)
    instances = manifest["instances"]
    if instance_name not in instances:
        raise AssemblyError(f"unknown instance in endpoint {endpoint!r}")
    component_name = instances[instance_name].get("component")
    component = manifest["components"].get(component_name)
    if component is None:
        raise AssemblyError(f"instance {instance_name!r} references unknown component {component_name!r}")
    if port not in component.get("ports", []):
        raise AssemblyError(f"unknown port in endpoint {endpoint!r}")
    return component, port


def validate_structure(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")

    conventions = manifest.get("conventions")
    if not isinstance(conventions, dict):
        errors.append("conventions must be an object")
    else:
        if conventions.get("wavelength_unit") != "nm":
            errors.append("conventions.wavelength_unit must be 'nm'")
        if conventions.get("sparameter_normalization") != "power-wave":
            errors.append("conventions.sparameter_normalization must be 'power-wave'")
        if conventions.get("time_dependence") not in {"exp(+iwt)", "exp(-iwt)"}:
            errors.append("conventions.time_dependence must be 'exp(+iwt)' or 'exp(-iwt)'")

    components = manifest.get("components")
    instances = manifest.get("instances")
    connections = manifest.get("connections")
    external_ports = manifest.get("external_ports")
    if not isinstance(components, dict) or not components:
        errors.append("components must be a non-empty object")
        components = {}
    if not isinstance(instances, dict) or not instances:
        errors.append("instances must be a non-empty object")
        instances = {}
    if not isinstance(connections, list):
        errors.append("connections must be an array")
        connections = []
    if not isinstance(external_ports, dict) or not external_ports:
        errors.append("external_ports must be a non-empty object")
        external_ports = {}

    for name, component in components.items():
        if not isinstance(name, str) or not name:
            errors.append("component names must be non-empty strings")
        if not isinstance(component, dict):
            errors.append(f"component {name!r} must be an object")
            continue
        ports = component.get("ports")
        if not isinstance(ports, list) or not ports or any(not isinstance(port, str) or not port for port in ports):
            errors.append(f"component {name!r}.ports must be a non-empty string array")
            ports = []
        if len(ports) != len(set(ports)):
            errors.append(f"component {name!r} has duplicate ports")
        modes = component.get("port_modes")
        if not isinstance(modes, dict) or set(modes) != set(ports):
            errors.append(f"component {name!r}.port_modes must define exactly every port")
        elif any(not isinstance(mode, str) or not mode.strip() for mode in modes.values()):
            errors.append(f"component {name!r}.port_modes values must be non-empty strings")
        if component.get("model_level") not in MODEL_LEVELS:
            errors.append(f"component {name!r}.model_level must be one of {sorted(MODEL_LEVELS)}")
        if not isinstance(component.get("reference_plane"), str) or not component.get("reference_plane"):
            errors.append(f"component {name!r}.reference_plane must be a non-empty string")
        sparameters = component.get("sparameters")
        if not isinstance(sparameters, str) or not sparameters:
            errors.append(f"component {name!r}.sparameters must be a relative CSV path")
        elif Path(sparameters).is_absolute():
            errors.append(f"component {name!r}.sparameters must be relative to the manifest")
        if "passive" in component and not isinstance(component["passive"], bool):
            errors.append(f"component {name!r}.passive must be a boolean")

    for name, instance in instances.items():
        if not isinstance(name, str) or not name:
            errors.append("instance names must be non-empty strings")
        if not isinstance(instance, dict) or instance.get("component") not in components:
            errors.append(f"instance {name!r} must reference a known component")

    used: dict[str, str] = {}
    for index, connection in enumerate(connections):
        label = f"connection[{index}]"
        if not isinstance(connection, list) or len(connection) != 2:
            errors.append(f"{label} must contain exactly two endpoints")
            continue
        left, right = connection
        try:
            left_component, left_port = component_for_endpoint(manifest, left)
            right_component, right_port = component_for_endpoint(manifest, right)
            left_mode = left_component["port_modes"][left_port]
            right_mode = right_component["port_modes"][right_port]
            if left_mode != right_mode:
                errors.append(f"{label} mode mismatch: {left_mode!r} != {right_mode!r}")
        except (AssemblyError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"{label}: {exc}")
            continue
        if left == right:
            errors.append(f"{label} cannot connect an endpoint to itself")
        for endpoint in (left, right):
            if endpoint in used:
                errors.append(f"endpoint {endpoint!r} is reused by {label} and {used[endpoint]}")
            used[endpoint] = label

    for external_name, endpoint in external_ports.items():
        label = f"external_ports.{external_name}"
        if not isinstance(external_name, str) or not external_name:
            errors.append("external port names must be non-empty strings")
        try:
            component_for_endpoint(manifest, endpoint)
        except (AssemblyError, TypeError, AttributeError) as exc:
            errors.append(f"{label}: {exc}")
            continue
        if endpoint in used:
            errors.append(f"endpoint {endpoint!r} is reused by {label} and {used[endpoint]}")
        used[endpoint] = label

    all_endpoints: set[str] = set()
    for instance_name, instance in instances.items():
        component = components.get(instance.get("component"), {}) if isinstance(instance, dict) else {}
        for port in component.get("ports", []):
            all_endpoints.add(f"{instance_name}:{port}")
    dangling = sorted(all_endpoints - set(used))
    if dangling:
        errors.append(f"unconnected instance ports: {', '.join(dangling)}")
    return errors


def import_numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise AssemblyError("NumPy is required for S-parameter validation and composition") from exc
    return np


def discover_project_root(manifest_path: Path) -> Path:
    manifest_path = manifest_path.resolve()
    for candidate in (manifest_path.parent, *manifest_path.parents):
        if (candidate / "photonic.toml").is_file() or (candidate / "PROJECT.md").is_file():
            return candidate
    if manifest_path.parent.name.lower() == "circuits":
        return manifest_path.parent.parent
    return manifest_path.parent


def resolve_sparameter_path(
    manifest_path: Path,
    relative_path: str,
    project_root: Path | None = None,
    *,
    allowed_roots: Sequence[Path] | None = None,
) -> Path:
    root = (project_root or discover_project_root(manifest_path)).resolve()
    resolved = (manifest_path.parent / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AssemblyError(
            f"S-parameter path resolves outside manifest directory or discovered project root: {relative_path}"
        ) from exc
    if allowed_roots is not None:
        resolved = ensure_within_allowed_roots(resolved, allowed_roots)
    return resolved


def load_component_data(
    manifest_path: Path,
    name: str,
    component: dict[str, Any],
    *,
    project_root: Path | None = None,
    allowed_roots: Sequence[Path] | None = None,
) -> ComponentData:
    np = import_numpy()
    csv_path = resolve_sparameter_path(
        manifest_path,
        component["sparameters"],
        project_root,
        allowed_roots=allowed_roots,
    )
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) not in (REQUIRED_COLUMNS, (*REQUIRED_COLUMNS, "power")):
                raise AssemblyError(
                    f"{name}: {csv_path} columns must be {', '.join(REQUIRED_COLUMNS)}"
                    " with only an optional trailing derived power column"
                )
            raw_rows = list(reader)
    except FileNotFoundError as exc:
        raise AssemblyError(f"{name}: S-parameter file not found: {csv_path}") from exc

    ports = tuple(component["ports"])
    port_index = {port: index for index, port in enumerate(ports)}
    matrices: dict[float, Any] = {}
    seen: set[tuple[float, str, str]] = set()
    for line_number, row in enumerate(raw_rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise AssemblyError(f"{name}: malformed CSV row at {csv_path}:{line_number}")
        try:
            wavelength = float(row["wavelength_nm"])
            out_port = row["out_port"]
            in_port = row["in_port"]
            real = float(row["s_real"])
            imag = float(row["s_imag"])
        except (TypeError, ValueError) as exc:
            raise AssemblyError(f"{name}: invalid numeric data at {csv_path}:{line_number}") from exc
        if not all(math.isfinite(value) for value in (wavelength, real, imag)):
            raise AssemblyError(f"{name}: non-finite S-parameter data at {csv_path}:{line_number}")
        if wavelength <= 0:
            raise AssemblyError(f"{name}: wavelength must be positive at {csv_path}:{line_number}")
        if "power" in row:
            try:
                power = float(row["power"])
            except (TypeError, ValueError) as exc:
                raise AssemblyError(f"{name}: invalid derived power at {csv_path}:{line_number}") from exc
            derived_power = real * real + imag * imag
            if (
                not math.isfinite(power)
                or not math.isfinite(derived_power)
                or power < 0
                or not math.isclose(power, derived_power, rel_tol=1e-9, abs_tol=1e-12)
            ):
                raise AssemblyError(f"{name}: inconsistent derived power at {csv_path}:{line_number}")
        value = complex(real, imag)
        if out_port not in port_index or in_port not in port_index:
            raise AssemblyError(f"{name}: unknown CSV port at {csv_path}:{line_number}")
        key = (wavelength, out_port, in_port)
        if key in seen:
            raise AssemblyError(f"{name}: duplicate S entry {key} at {csv_path}:{line_number}")
        seen.add(key)
        matrix = matrices.setdefault(wavelength, np.zeros((len(ports), len(ports)), dtype=complex))
        matrix[port_index[out_port], port_index[in_port]] = value

    if not matrices:
        raise AssemblyError(f"{name}: no S-parameter rows in {csv_path}")
    expected_pairs = {(out_port, in_port) for out_port in ports for in_port in ports}
    for wavelength in matrices:
        actual_pairs = {(out_port, in_port) for wl, out_port, in_port in seen if wl == wavelength}
        missing = expected_pairs - actual_pairs
        if missing:
            raise AssemblyError(f"{name}: incomplete S matrix at {wavelength:g} nm; missing {sorted(missing)}")
        if component.get("passive", True):
            try:
                sigma_max = float(np.linalg.svd(matrices[wavelength], compute_uv=False)[0])
            except np.linalg.LinAlgError as exc:
                raise AssemblyError(f"{name}: SVD failed at {wavelength:g} nm") from exc
            if not math.isfinite(sigma_max):
                raise AssemblyError(f"{name}: non-finite singular value at {wavelength:g} nm")
            if sigma_max > 1.000001:
                raise AssemblyError(
                    f"{name}: passive model has singular value {sigma_max:.6g} > 1 at {wavelength:g} nm"
                )
    wavelengths = tuple(sorted(matrices))
    return ComponentData(ports=ports, wavelengths_nm=wavelengths, matrices=matrices)


def load_all_component_data(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    project_root: Path | None = None,
    allowed_roots: Sequence[Path] | None = None,
) -> dict[str, ComponentData]:
    data = {
        name: load_component_data(
            manifest_path,
            name,
            component,
            project_root=project_root,
            allowed_roots=allowed_roots,
        )
        for name, component in manifest["components"].items()
    }
    grids = {item.wavelengths_nm for item in data.values()}
    if len(grids) != 1:
        detail = "; ".join(f"{name}={list(item.wavelengths_nm)}" for name, item in data.items())
        raise AssemblyError(f"component wavelength grids must match exactly: {detail}")
    return data


def validate_manifest(
    manifest_path: Path,
    check_data: bool = True,
    *,
    project_root: Path | None = None,
    allowed_roots: Sequence[Path] | None = None,
) -> tuple[dict[str, Any], dict[str, ComponentData]]:
    manifest_path = (
        ensure_within_allowed_roots(manifest_path, allowed_roots)
        if allowed_roots is not None
        else manifest_path.resolve()
    )
    manifest = load_manifest(manifest_path)
    errors = validate_structure(manifest)
    if errors:
        raise AssemblyError("manifest validation failed:\n- " + "\n- ".join(errors))
    component_data = (
        load_all_component_data(
            manifest_path,
            manifest,
            project_root=project_root,
            allowed_roots=allowed_roots,
        )
        if check_data
        else {}
    )
    return manifest, component_data


def compose(
    manifest: dict[str, Any],
    component_data: dict[str, ComponentData],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    np = import_numpy()
    global_endpoints: list[str] = []
    slices: dict[str, slice] = {}
    offset = 0
    for instance_name, instance in manifest["instances"].items():
        component = component_data[instance["component"]]
        slices[instance_name] = slice(offset, offset + len(component.ports))
        global_endpoints.extend(f"{instance_name}:{port}" for port in component.ports)
        offset += len(component.ports)
    endpoint_index = {endpoint: index for index, endpoint in enumerate(global_endpoints)}

    internal_endpoints = [endpoint for pair in manifest["connections"] for endpoint in pair]
    external_names = list(manifest["external_ports"])
    external_endpoints = [manifest["external_ports"][name] for name in external_names]
    internal_idx = [endpoint_index[endpoint] for endpoint in internal_endpoints]
    external_idx = [endpoint_index[endpoint] for endpoint in external_endpoints]

    connection_matrix = np.zeros((len(internal_idx), len(internal_idx)), dtype=complex)
    internal_position = {endpoint: index for index, endpoint in enumerate(internal_endpoints)}
    for left, right in manifest["connections"]:
        left_i = internal_position[left]
        right_i = internal_position[right]
        connection_matrix[left_i, right_i] = 1.0
        connection_matrix[right_i, left_i] = 1.0

    wavelengths = next(iter(component_data.values())).wavelengths_nm
    output_rows: list[dict[str, Any]] = []
    sigma_values: list[float] = []
    reciprocity_errors: list[float] = []
    for wavelength in wavelengths:
        system_s = np.zeros((offset, offset), dtype=complex)
        for instance_name, instance in manifest["instances"].items():
            instance_slice = slices[instance_name]
            system_s[instance_slice, instance_slice] = component_data[instance["component"]].matrices[wavelength]

        see = system_s[np.ix_(external_idx, external_idx)]
        if internal_idx:
            sei = system_s[np.ix_(external_idx, internal_idx)]
            sie = system_s[np.ix_(internal_idx, external_idx)]
            sii = system_s[np.ix_(internal_idx, internal_idx)]
            lhs = np.eye(len(internal_idx), dtype=complex) - connection_matrix @ sii
            if not np.all(np.isfinite(lhs)):
                raise AssemblyError(f"non-finite internal network matrix at {wavelength:g} nm")
            try:
                internal_sigma = np.linalg.svd(lhs, compute_uv=False)
            except np.linalg.LinAlgError as exc:
                raise AssemblyError(f"internal network SVD failed at {wavelength:g} nm") from exc
            if not np.all(np.isfinite(internal_sigma)):
                raise AssemblyError(f"non-finite internal network singular values at {wavelength:g} nm")
            rank_tolerance = np.finfo(float).eps * max(lhs.shape) * internal_sigma[0]
            if internal_sigma[-1] <= rank_tolerance:
                raise AssemblyError(f"singular internal network at {wavelength:g} nm: "
                                    "numerical rank deficiency")
            try:
                internal_response = np.linalg.solve(lhs, connection_matrix @ sie)
            except np.linalg.LinAlgError as exc:
                raise AssemblyError(f"singular internal network at {wavelength:g} nm") from exc
            external_s = see + sei @ internal_response
        else:
            external_s = see

        if not np.all(np.isfinite(external_s)):
            raise AssemblyError(f"non-finite external S matrix at {wavelength:g} nm")
        try:
            sigma_values.append(float(np.linalg.svd(external_s, compute_uv=False)[0]))
        except np.linalg.LinAlgError as exc:
            raise AssemblyError(f"external SVD failed at {wavelength:g} nm") from exc
        reciprocity_errors.append(float(np.max(np.abs(external_s - external_s.T))))
        for out_index, out_name in enumerate(external_names):
            for in_index, in_name in enumerate(external_names):
                value = external_s[out_index, in_index]
                output_rows.append(
                    {
                        "wavelength_nm": f"{wavelength:.12g}",
                        "out_port": out_name,
                        "in_port": in_name,
                        "s_real": f"{value.real:.17g}",
                        "s_imag": f"{value.imag:.17g}",
                        "power": f"{abs(value) ** 2:.17g}",
                    }
                )

    summary = {
        "schema_version": "1.0",
        "wavelength_count": len(wavelengths),
        "wavelength_min_nm": min(wavelengths),
        "wavelength_max_nm": max(wavelengths),
        "external_ports": external_names,
        "instance_count": len(manifest["instances"]),
        "connection_count": len(manifest["connections"]),
        "max_network_singular_value": max(sigma_values),
        "max_reciprocity_error": max(reciprocity_errors),
        "claim_boundary": "circuit-level composition; promote critical subassemblies to full-wave validation",
    }
    return output_rows, summary


def write_composition(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("wavelength_nm", "out_port", "in_port", "s_real", "s_imag", "power"),
        )
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and compose hierarchical photonic S-parameter networks.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate an assembly manifest and component S matrices")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--structure-only", action="store_true")
    validate.add_argument("--project-root", type=Path)
    compose_parser = subparsers.add_parser("compose", help="compose component S matrices into an external S matrix")
    compose_parser.add_argument("manifest", type=Path)
    compose_parser.add_argument("--output", type=Path, required=True)
    compose_parser.add_argument("--summary", type=Path)
    compose_parser.add_argument("--project-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest, component_data = validate_manifest(
            args.manifest,
            check_data=not getattr(args, "structure_only", False),
            project_root=args.project_root,
        )
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "manifest": str(args.manifest.resolve()),
                        "data_checked": not args.structure_only,
                    },
                    indent=2,
                )
            )
            return 0
        rows, summary = compose(manifest, component_data)
        write_composition(args.output, rows)
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"valid": True, "output": str(args.output.resolve()), "summary": summary}, indent=2))
        return 0
    except AssemblyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
