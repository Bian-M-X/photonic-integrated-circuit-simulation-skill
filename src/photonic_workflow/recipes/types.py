"""Strict, transport-neutral types for deterministic modeling recipes."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.security import validate_stable_id

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
RecipeEvaluator: TypeAlias = Callable[
    [Mapping[str, JSONValue]],
    dict[str, JSONValue],
]

RECIPE_REQUEST_SCHEMA_VERSION = "1.0"
_PARAMETER_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class ParameterJsonType(StrEnum):
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    STRING = "string"
    ARRAY = "array"
    OBJECT = "object"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """Machine-readable public parameter contract for one recipe field."""

    name: str
    json_type: ParameterJsonType
    unit: str
    required: bool
    description: str
    has_default: bool = False
    default: JSONValue = None
    minimum: float | int | None = None
    exclusive_minimum: float | int | None = None
    maximum: float | int | None = None
    exclusive_maximum: float | int | None = None
    enum: tuple[JSONScalar, ...] = ()
    items: str | None = None
    min_items: int | None = None
    max_items: int | None = None
    multiple_of: int | None = None

    def __post_init__(self) -> None:
        if not _PARAMETER_NAME_RE.fullmatch(self.name):
            raise InvalidInputError(f"invalid recipe parameter name: {self.name!r}")
        if not self.unit.strip() or not self.description.strip():
            raise InvalidInputError(
                f"parameter {self.name!r} needs non-empty unit and description"
            )
        if self.required and self.has_default:
            raise InvalidInputError(
                f"required parameter {self.name!r} must not declare a default"
            )
        if not self.has_default and self.default is not None:
            raise InvalidInputError(
                f"parameter {self.name!r} has a default without has_default=true"
            )
        if self.enum and len(set(self.enum)) != len(self.enum):
            raise InvalidInputError(f"parameter {self.name!r} enum contains duplicates")
        if self.min_items is not None and self.min_items < 0:
            raise InvalidInputError(f"parameter {self.name!r} min_items must be non-negative")
        if self.max_items is not None and self.max_items < 0:
            raise InvalidInputError(f"parameter {self.name!r} max_items must be non-negative")
        if (
            self.min_items is not None
            and self.max_items is not None
            and self.min_items > self.max_items
        ):
            raise InvalidInputError(f"parameter {self.name!r} has inverted item bounds")
        if self.multiple_of is not None and self.multiple_of <= 0:
            raise InvalidInputError(f"parameter {self.name!r} multiple_of must be positive")
        lower_bounds = [item for item in (self.minimum, self.exclusive_minimum) if item is not None]
        upper_bounds = [item for item in (self.maximum, self.exclusive_maximum) if item is not None]
        if len(lower_bounds) > 1 or len(upper_bounds) > 1:
            raise InvalidInputError(
                f"parameter {self.name!r} must use only one lower and upper bound"
            )
        if lower_bounds and upper_bounds and lower_bounds[0] >= upper_bounds[0]:
            raise InvalidInputError(f"parameter {self.name!r} has inverted bounds")
        if self.has_default:
            self.validate_value(self.default)

    def validate_value(self, value: JSONValue) -> None:
        type_matches = {
            ParameterJsonType.NUMBER: (
                not isinstance(value, bool) and isinstance(value, (int, float))
            ),
            ParameterJsonType.INTEGER: (
                not isinstance(value, bool) and isinstance(value, int)
            ),
            ParameterJsonType.BOOLEAN: isinstance(value, bool),
            ParameterJsonType.STRING: isinstance(value, str),
            ParameterJsonType.ARRAY: isinstance(value, list),
            ParameterJsonType.OBJECT: isinstance(value, dict),
        }[self.json_type]
        if not type_matches:
            raise InvalidInputError(
                f"recipe parameter {self.name!r} must have JSON type "
                f"{self.json_type.value}"
            )
        if self.enum and value not in self.enum:
            raise InvalidInputError(
                f"recipe parameter {self.name!r} is not in its allowed enum"
            )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                raise InvalidInputError(
                    f"recipe parameter {self.name!r} is below its minimum"
                )
            if self.exclusive_minimum is not None and value <= self.exclusive_minimum:
                raise InvalidInputError(
                    f"recipe parameter {self.name!r} is not above its exclusive minimum"
                )
            if self.maximum is not None and value > self.maximum:
                raise InvalidInputError(
                    f"recipe parameter {self.name!r} is above its maximum"
                )
            if self.exclusive_maximum is not None and value >= self.exclusive_maximum:
                raise InvalidInputError(
                    f"recipe parameter {self.name!r} is not below its exclusive maximum"
                )
        if self.min_items is not None and isinstance(value, list) and len(value) < self.min_items:
            raise InvalidInputError(
                f"recipe parameter {self.name!r} has fewer than {self.min_items} items"
            )
        if self.max_items is not None and isinstance(value, list) and len(value) > self.max_items:
            raise InvalidInputError(
                f"recipe parameter {self.name!r} has more than {self.max_items} items"
            )
        if (
            self.multiple_of is not None
            and isinstance(value, int)
            and value % self.multiple_of
        ):
            raise InvalidInputError(
                f"recipe parameter {self.name!r} must be a multiple of "
                f"{self.multiple_of}"
            )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "json_type": self.json_type.value,
            "unit": self.unit,
            "required": self.required,
            "description": self.description,
            "has_default": self.has_default,
            "default": deepcopy(self.default),
            "minimum": self.minimum,
            "exclusive_minimum": self.exclusive_minimum,
            "maximum": self.maximum,
            "exclusive_maximum": self.exclusive_maximum,
            "enum": list(self.enum),
            "items": self.items,
            "min_items": self.min_items,
            "max_items": self.max_items,
            "multiple_of": self.multiple_of,
        }


class RecipeSupportLevel(StrEnum):
    """Evidence about recipe code or configuration, never physical acceptance."""

    DOCUMENTED = "documented"
    UNIT_TESTED = "unit-tested"
    CONFIGURATION_AUDITED = "configuration-audited"


class RecipeRenderer(StrEnum):
    CANONICAL_JSON = "canonical-json"
    COMSOL_JAVA_FRAGMENT = "comsol-java-fragment"
    LUMERICAL_LSF_FRAGMENT = "lumerical-lsf-fragment"


@dataclass(frozen=True, slots=True)
class RecipeDescriptor:
    recipe_id: str
    recipe_version: str
    title: str
    summary: str
    support_level: RecipeSupportLevel
    renderers: tuple[RecipeRenderer, ...]
    parameter_contract: tuple[ParameterSpec, ...]
    claim_boundary: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_stable_id(self.recipe_id)
        if not self.recipe_version.strip():
            raise InvalidInputError("recipe_version must not be empty")
        if not self.title.strip() or not self.summary.strip():
            raise InvalidInputError("recipe title and summary must not be empty")
        if not self.renderers or len(set(self.renderers)) != len(self.renderers):
            raise InvalidInputError("recipe renderers must be unique and non-empty")
        if not self.parameter_contract:
            raise InvalidInputError(
                "recipe parameter_contract must contain parameter specifications"
            )
        parameter_names = [item.name for item in self.parameter_contract]
        if len(set(parameter_names)) != len(parameter_names):
            raise InvalidInputError("recipe parameter_contract contains duplicate names")
        if not self.claim_boundary or any(not item.strip() for item in self.claim_boundary):
            raise InvalidInputError("recipe claim_boundary must contain non-empty statements")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "title": self.title,
            "summary": self.summary,
            "support_level": self.support_level.value,
            "renderers": [item.value for item in self.renderers],
            "parameter_contract": [item.to_payload() for item in self.parameter_contract],
            "claim_boundary": list(self.claim_boundary),
            "will_execute": False,
            "physics_accepted": False,
        }


@dataclass(frozen=True, slots=True)
class RecipeDefinition:
    descriptor: RecipeDescriptor
    evaluator: RecipeEvaluator

    def __post_init__(self) -> None:
        if not callable(self.evaluator):
            raise InvalidInputError(
                f"recipe evaluator is not callable: {self.descriptor.recipe_id}"
            )


@dataclass(frozen=True, slots=True)
class RecipeRequest:
    recipe_id: str
    recipe_version: str
    parameters: dict[str, JSONValue]
    schema_version: Literal["1.0"] = RECIPE_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECIPE_REQUEST_SCHEMA_VERSION:
            raise InvalidInputError(
                "recipe request schema_version must be "
                f"{RECIPE_REQUEST_SCHEMA_VERSION!r}"
            )
        validate_stable_id(self.recipe_id)
        if not self.recipe_version.strip():
            raise InvalidInputError("recipe_version must not be empty")
        if not isinstance(self.parameters, dict):
            raise InvalidInputError("recipe parameters must be a JSON object")


@dataclass(frozen=True, slots=True)
class RecipeResult:
    descriptor: RecipeDescriptor
    parameters: dict[str, JSONValue]
    output: dict[str, JSONValue]

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "recipe_id": self.descriptor.recipe_id,
            "recipe_version": self.descriptor.recipe_version,
            "support_level": self.descriptor.support_level.value,
            "parameters": deepcopy(self.parameters),
            "output": deepcopy(self.output),
            "claim_boundary": list(self.descriptor.claim_boundary),
            "will_execute": False,
            "physics_accepted": False,
        }


@dataclass(frozen=True, slots=True)
class RenderedRecipe:
    result: RecipeResult
    renderer: RecipeRenderer
    content: str
    media_type: str
    suggested_suffix: str
    instance_id: str | None = None
    renderer_options: dict[str, JSONValue] | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def byte_count(self) -> int:
        return len(self.content.encode("utf-8"))

    def to_payload(self, *, include_content: bool = True) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            **self.result.to_payload(),
            "renderer_id": self.renderer.value,
            "media_type": self.media_type,
            "suggested_suffix": self.suggested_suffix,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "instance_id": self.instance_id,
        }
        if include_content:
            payload["content"] = self.content
        if self.renderer_options is not None:
            payload["renderer_options"] = deepcopy(self.renderer_options)
        return payload


__all__ = [
    "RECIPE_REQUEST_SCHEMA_VERSION",
    "JSONScalar",
    "JSONValue",
    "ParameterJsonType",
    "ParameterSpec",
    "RecipeDefinition",
    "RecipeDescriptor",
    "RecipeRenderer",
    "RecipeRequest",
    "RecipeResult",
    "RecipeSupportLevel",
    "RenderedRecipe",
]
