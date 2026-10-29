"""Public application service for deterministic built-in modeling recipes."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from photonic_workflow.exceptions import IncompatibleVersionError, InvalidInputError

from .catalog import recipe_definition, recipe_definitions
from .renderers import (
    COMSOL_RECIPE_BINDINGS,
    MAX_COMSOL_CIRCULAR_VERTICES,
    MAX_COMSOL_EULER_SAMPLES,
)
from .types import (
    RECIPE_REQUEST_SCHEMA_VERSION,
    JSONValue,
    RecipeDescriptor,
    RecipeRenderer,
    RecipeRequest,
    RecipeResult,
    RenderedRecipe,
)

_REQUEST_KEYS = {"schema_version", "recipe_id", "recipe_version", "parameters"}
MAX_RECIPE_REQUEST_BYTES = 2_000_000
MAX_RECIPE_JSON_DEPTH = 64
def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInputError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InvalidInputError(f"non-finite JSON number is not allowed: {value}")


def _validate_json(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
) -> JSONValue:
    if depth > MAX_RECIPE_JSON_DEPTH:
        raise InvalidInputError(
            f"recipe JSON exceeds maximum nesting depth {MAX_RECIPE_JSON_DEPTH}"
        )
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidInputError(f"non-finite number is not allowed at {path}")
        return value
    if isinstance(value, (list, tuple)):
        return [
            _validate_json(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidInputError(f"JSON object key is not a string at {path}")
            normalized[key] = _validate_json(
                item,
                path=f"{path}.{key}",
                depth=depth + 1,
            )
        return normalized
    raise InvalidInputError(
        f"unsupported non-JSON value at {path}: {type(value).__name__}"
    )


def parse_recipe_request(text: str) -> RecipeRequest:
    """Parse one request with duplicate-key and non-finite-number rejection."""

    if not isinstance(text, str):
        raise InvalidInputError("recipe request must be text")
    if len(text.encode("utf-8")) > MAX_RECIPE_REQUEST_BYTES:
        raise InvalidInputError(
            f"recipe request exceeds {MAX_RECIPE_REQUEST_BYTES} UTF-8 bytes"
        )
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except InvalidInputError:
        raise
    except (RecursionError, ValueError) as exc:
        raise InvalidInputError(f"invalid recipe request JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidInputError("recipe request root must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_KEYS)
    missing = sorted(_REQUEST_KEYS - set(payload))
    if unknown:
        raise InvalidInputError(
            "unknown recipe request root keys: " + ", ".join(unknown)
        )
    if missing:
        raise InvalidInputError(
            "missing recipe request root keys: " + ", ".join(missing)
        )
    schema_version = payload["schema_version"]
    if schema_version != RECIPE_REQUEST_SCHEMA_VERSION:
        raise IncompatibleVersionError(
            "recipe request schema "
            f"{schema_version!r} is incompatible; expected "
            f"{RECIPE_REQUEST_SCHEMA_VERSION!r}"
        )
    recipe_id = payload["recipe_id"]
    recipe_version = payload["recipe_version"]
    parameters = payload["parameters"]
    if not isinstance(recipe_id, str) or not isinstance(recipe_version, str):
        raise InvalidInputError("recipe_id and recipe_version must be strings")
    normalized = _validate_json(parameters, path="$.parameters")
    if not isinstance(normalized, dict):
        raise InvalidInputError("recipe parameters must be a JSON object")
    return RecipeRequest(
        schema_version=RECIPE_REQUEST_SCHEMA_VERSION,
        recipe_id=recipe_id,
        recipe_version=recipe_version,
        parameters=normalized,
    )


def load_recipe_request(path: Path) -> RecipeRequest:
    try:
        if path.stat().st_size > MAX_RECIPE_REQUEST_BYTES:
            raise InvalidInputError(
                f"recipe request exceeds {MAX_RECIPE_REQUEST_BYTES} bytes: {path}"
            )
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InvalidInputError(f"recipe request not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise InvalidInputError(f"recipe request is not valid UTF-8: {path}") from exc
    return parse_recipe_request(text)


def list_recipes() -> tuple[RecipeDescriptor, ...]:
    return tuple(item.descriptor for item in recipe_definitions())


def inspect_recipe(
    recipe_id: str,
    *,
    version: str | None = None,
) -> RecipeDescriptor:
    descriptor = recipe_definition(recipe_id).descriptor
    _require_version(descriptor, version)
    return descriptor


def _apply_parameter_contract(
    descriptor: RecipeDescriptor,
    parameters: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    specs = {spec.name: spec for spec in descriptor.parameter_contract}
    unknown = set(parameters) - set(specs)
    missing = {
        spec.name
        for spec in descriptor.parameter_contract
        if spec.required and spec.name not in parameters
    }
    if missing or unknown:
        raise InvalidInputError(
            "recipe parameter fields mismatch; "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    normalized = deepcopy(parameters)
    for spec in descriptor.parameter_contract:
        if spec.name not in normalized:
            if spec.has_default:
                normalized[spec.name] = deepcopy(spec.default)
            else:
                continue
        value = normalized[spec.name]
        spec.validate_value(value)
    return normalized


def _require_version(
    descriptor: RecipeDescriptor,
    requested: str | None,
) -> None:
    if requested is not None and requested != descriptor.recipe_version:
        raise IncompatibleVersionError(
            f"recipe {descriptor.recipe_id!r} version {requested!r} is incompatible; "
            f"available version is {descriptor.recipe_version!r}"
        )


def evaluate_recipe(
    recipe_id: str,
    parameters: Mapping[str, JSONValue],
    *,
    version: str | None = None,
) -> RecipeResult:
    definition = recipe_definition(recipe_id)
    _require_version(definition.descriptor, version)
    normalized = _validate_json(dict(parameters), path="$.parameters")
    assert isinstance(normalized, dict)
    normalized = _apply_parameter_contract(definition.descriptor, normalized)
    raw_output = definition.evaluator(deepcopy(normalized))
    output = _validate_json(raw_output, path="$.output")
    if not isinstance(output, dict):
        raise InvalidInputError(
            f"recipe {recipe_id!r} evaluator did not return a JSON object"
        )
    return RecipeResult(
        descriptor=definition.descriptor,
        parameters=normalized,
        output=output,
    )


def _canonical_json(value: JSONValue) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _preflight_comsol_parameters(
    recipe_id: str,
    parameters: Mapping[str, JSONValue],
) -> None:
    if recipe_id == "geometry.circular-route":
        vertices = parameters.get("vertices_um")
        if isinstance(vertices, (list, tuple)) and len(vertices) > MAX_COMSOL_CIRCULAR_VERTICES:
            raise InvalidInputError(
                "COMSOL circular-route renderer supports at most "
                f"{MAX_COMSOL_CIRCULAR_VERTICES} vertices"
            )
    elif recipe_id == "geometry.symmetric-euler-bend":
        samples = parameters.get("samples", 64)
        if isinstance(samples, int) and not isinstance(samples, bool) and samples > MAX_COMSOL_EULER_SAMPLES:
            raise InvalidInputError(
                "COMSOL Euler renderer supports at most "
                f"{MAX_COMSOL_EULER_SAMPLES} samples"
            )


def render_recipe(
    recipe_id: str,
    parameters: Mapping[str, JSONValue],
    *,
    version: str | None = None,
    renderer: str | RecipeRenderer = RecipeRenderer.CANONICAL_JSON,
    instance_id: str | None = None,
    height_um: float | None = None,
    core_index: float | None = None,
) -> RenderedRecipe:
    try:
        selected_renderer = RecipeRenderer(renderer)
    except ValueError as exc:
        raise InvalidInputError(f"unknown recipe renderer: {renderer}") from exc
    descriptor = inspect_recipe(recipe_id, version=version)
    if selected_renderer not in descriptor.renderers:
        raise InvalidInputError(
            f"recipe {recipe_id!r} does not support renderer "
            f"{selected_renderer.value!r}"
        )
    if selected_renderer != RecipeRenderer.LUMERICAL_LSF_FRAGMENT and (height_um is not None or core_index is not None):
        raise InvalidInputError("height_um and core_index are accepted only by the Lumerical LSF renderer")
    if selected_renderer == RecipeRenderer.COMSOL_JAVA_FRAGMENT:
        _preflight_comsol_parameters(recipe_id, parameters)
    elif selected_renderer == RecipeRenderer.LUMERICAL_LSF_FRAGMENT:
        from .renderers import MAX_LUMERICAL_CIRCULAR_VERTICES

        vertices = parameters.get("vertices_um")
        if (recipe_id == "geometry.circular-route" and isinstance(vertices, list | tuple)
                and len(vertices) > MAX_LUMERICAL_CIRCULAR_VERTICES):
            raise InvalidInputError(
                f"Lumerical circular-route renderer supports at most {MAX_LUMERICAL_CIRCULAR_VERTICES} vertices"
            )
    result = evaluate_recipe(recipe_id, parameters, version=version)
    renderer_options = None
    if selected_renderer == RecipeRenderer.CANONICAL_JSON:
        if instance_id is not None:
            raise InvalidInputError(
                "instance_id is accepted only by native fragment renderers"
            )
        content = _canonical_json(cast(JSONValue, result.to_payload()))
        media_type = "application/json"
        suffix = ".json"
    elif selected_renderer == RecipeRenderer.COMSOL_JAVA_FRAGMENT:
        if instance_id is None:
            raise InvalidInputError(
                "COMSOL Java rendering requires an explicit safe instance_id"
            )
        from photonic_workflow.adapters.comsol.recipes import (
            render_comsol_java_fragment,
        )

        fragment = render_comsol_java_fragment(
            recipe_id=COMSOL_RECIPE_BINDINGS[result.descriptor.recipe_id],
            recipe_version=result.descriptor.recipe_version,
            parameters=deepcopy(result.parameters),
            output=deepcopy(result.output),
            instance_id=instance_id,
        )
        content = fragment.content
        if not isinstance(content, str) or not content.strip():
            raise InvalidInputError("COMSOL recipe renderer returned empty content")
        if not content.endswith("\n"):
            content += "\n"
        media_type = "text/x-java-source"
        suffix = ".java"
    else:
        from .lumerical import lumerical_geometry_plan, render_lumerical_lsf_fragment

        plan = lumerical_geometry_plan(
            result, instance_id=instance_id, height_um=height_um, core_index=core_index,
        )
        content = render_lumerical_lsf_fragment(plan)
        media_type = "text/x-lumerical-lsf"
        suffix = ".lsf"
        renderer_options = {"height_um": plan["height_um"], "core_index": plan["core_index"]}
    return RenderedRecipe(
        result=result,
        renderer=selected_renderer,
        content=content,
        media_type=media_type,
        suggested_suffix=suffix,
        instance_id=instance_id,
        renderer_options=renderer_options,
    )


__all__ = [
    "MAX_RECIPE_JSON_DEPTH",
    "MAX_RECIPE_REQUEST_BYTES",
    "evaluate_recipe",
    "inspect_recipe",
    "list_recipes",
    "load_recipe_request",
    "parse_recipe_request",
    "render_recipe",
]
