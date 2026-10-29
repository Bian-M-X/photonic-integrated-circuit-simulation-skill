"""Immutable catalog of reviewed, built-in modeling recipes."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

from photonic_workflow.exceptions import InvalidInputError

from .renderers import COMSOL_RECIPE_BINDINGS, LUMERICAL_RECIPE_IDS
from .types import (
    JSONValue,
    ParameterJsonType,
    ParameterSpec,
    RecipeDefinition,
    RecipeDescriptor,
    RecipeRenderer,
    RecipeSupportLevel,
)

_NO_PHYSICS_CLAIM = (
    "The recipe performs deterministic code or configuration work only.",
    "It does not execute a solver or accept a physical result.",
)

def _p(
    name: str,
    json_type: ParameterJsonType,
    unit: str,
    *,
    required: bool,
    description: str,
    **constraints: object,
) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        json_type=json_type,
        unit=unit,
        required=required,
        description=description,
        **constraints,  # type: ignore[arg-type]
    )


_CIRCULAR_ROUTE_PARAMETERS = (
    _p(
        "vertices_um",
        ParameterJsonType.ARRAY,
        "um",
        required=True,
        description="Ordered two-dimensional route vertices.",
        items="array[number, number]",
        min_items=2,
    ),
    _p(
        "radius_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Exact tangent circular-bend radius.",
        exclusive_minimum=0.0,
    ),
    _p(
        "width_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Waveguide core width; must also be smaller than twice the radius.",
        exclusive_minimum=0.0,
    ),
)
_SYMMETRIC_EULER_PARAMETERS = (
    _p(
        "turn_angle_deg",
        ParameterJsonType.NUMBER,
        "degree",
        required=True,
        description="Signed nonzero turn with magnitude strictly below 180 degrees.",
    ),
    _p(
        "minimum_radius_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Minimum radius at the bend midpoint.",
        exclusive_minimum=0.0,
    ),
    _p(
        "width_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Waveguide core width; must be smaller than twice the radius.",
        exclusive_minimum=0.0,
    ),
    _p(
        "samples",
        ParameterJsonType.INTEGER,
        "count",
        required=False,
        description="Even centerline sample count for pure evaluation.",
        has_default=True,
        default=64,
        minimum=8,
        maximum=4096,
        multiple_of=2,
    ),
)
_SEGMENTED_PORT_PARAMETERS = (
    *(
        _p(
            name,
            ParameterJsonType.NUMBER,
            "um",
            required=True,
            description=description,
        )
        for name, description in (
            ("x_min_um", "Left simulation extent."),
            ("x_max_um", "Right simulation extent."),
            ("y_min_um", "Lower simulation extent."),
            ("y_max_um", "Upper simulation extent."),
            ("port_center_y_um", "Vertical center of both port windows."),
        )
    ),
    _p(
        "port_half_height_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Positive half-height of the port-bearing middle slab.",
        exclusive_minimum=0.0,
    ),
    _p(
        "selection_tolerance_um",
        ParameterJsonType.NUMBER,
        "um",
        required=False,
        description="Positive coordinate tolerance for boundary selections.",
        has_default=True,
        default=0.008,
        exclusive_minimum=0.0,
    ),
)
_LI_SILICON_PARAMETERS = (
    _p(
        "wavelength_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Vacuum wavelength inside the Li 1980 source range.",
        minimum=1.2,
        maximum=14.0,
    ),
    _p(
        "temperature_k",
        ParameterJsonType.NUMBER,
        "K",
        required=False,
        description="Absolute temperature inside the Li 1980 source range.",
        has_default=True,
        default=293.15,
        minimum=100.0,
        maximum=750.0,
    ),
)
_MALITSON_SILICA_PARAMETERS = (
    _p(
        "wavelength_um",
        ParameterJsonType.NUMBER,
        "um",
        required=True,
        description="Vacuum wavelength inside the Malitson source range.",
        minimum=0.21,
        maximum=3.71,
    ),
)
_TWO_PORT_PARAMETERS = (
    _p(
        "source_conditioned_entries",
        ParameterJsonType.ARRAY,
        "dimensionless_complex_power_wave",
        required=True,
        description="Exactly four complete source-conditioned S-matrix entries.",
        items="object",
        min_items=4,
        max_items=4,
    ),
    _p(
        "power_ledgers",
        ParameterJsonType.ARRAY,
        "W_and_dimensionless_fraction",
        required=True,
        description="Exactly two source-column power ledgers.",
        items="object",
        min_items=2,
        max_items=2,
    ),
    _p(
        "model_instance_id",
        ParameterJsonType.STRING,
        "none",
        required=True,
        description="Caller-declared identity of the single model instance.",
    ),
    _p(
        "phase_basis_id",
        ParameterJsonType.STRING,
        "none",
        required=True,
        description="Caller-declared common phase and port-mode basis identity.",
    ),
    _p(
        "phase_basis_frozen",
        ParameterJsonType.BOOLEAN,
        "none",
        required=True,
        description="Must be exactly true; this is a caller declaration, not independent evidence.",
        enum=(True,),
    ),
    _p(
        "nonport_flux_sign_convention",
        ParameterJsonType.STRING,
        "none",
        required=True,
        description="Required sign convention for non-port exterior power flux.",
        enum=("positive_outward",),
    ),
    _p(
        "material_absorption_sign_convention",
        ParameterJsonType.STRING,
        "none",
        required=True,
        description="Required sign convention for material absorption power.",
        enum=("positive_absorbed",),
    ),
    *(
        _p(
            name,
            ParameterJsonType.NUMBER,
            "dimensionless",
            required=False,
            description=description,
            has_default=True,
            default=default,
            minimum=0.0,
        )
        for name, default, description in (
            ("arithmetic_tolerance", 1e-10, "Arithmetic consistency tolerance."),
            ("closure_tolerance", 1e-3, "Power-closure diagnostic tolerance."),
            ("reciprocity_tolerance", 1e-3, "Complex reciprocity diagnostic tolerance."),
            ("passivity_tolerance", 1e-6, "Largest-singular-value diagnostic tolerance."),
            ("unitarity_tolerance", 1e-3, "Hermitian unitarity diagnostic tolerance."),
        )
    ),
)


def _circular_route(parameters: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    from .geometry import evaluate_circular_route

    return cast(dict[str, JSONValue], evaluate_circular_route(dict(parameters)))


def _symmetric_euler_bend(parameters: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    from .geometry import evaluate_symmetric_euler_bend

    return cast(
        dict[str, JSONValue],
        evaluate_symmetric_euler_bend(dict(parameters)),
    )


def _segmented_port_window(parameters: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    from .ports import evaluate_segmented_port_window

    return cast(
        dict[str, JSONValue],
        evaluate_segmented_port_window(dict(parameters)),
    )


def _li_silicon(parameters: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    from .materials import evaluate_li_silicon_1980

    return evaluate_li_silicon_1980(parameters)


def _malitson_silica(parameters: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    from .materials import evaluate_malitson_fused_silica_1965

    return evaluate_malitson_fused_silica_1965(parameters)


def _two_port_common_basis(parameters: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    from .scattering import evaluate_two_port_common_basis

    return evaluate_two_port_common_basis(parameters)


def _descriptor(
    recipe_id: str,
    title: str,
    summary: str,
    support_level: RecipeSupportLevel,
    *,
    parameter_contract: tuple[ParameterSpec, ...],
    claim_boundary: tuple[str, ...] = _NO_PHYSICS_CLAIM,
) -> RecipeDescriptor:
    renderers = (RecipeRenderer.CANONICAL_JSON,)
    if recipe_id in COMSOL_RECIPE_BINDINGS:
        renderers += (RecipeRenderer.COMSOL_JAVA_FRAGMENT,)
    if recipe_id in LUMERICAL_RECIPE_IDS:
        renderers += (RecipeRenderer.LUMERICAL_LSF_FRAGMENT,)
    return RecipeDescriptor(
        recipe_id=recipe_id,
        recipe_version="1.0.0",
        title=title,
        summary=summary,
        support_level=support_level,
        renderers=renderers,
        parameter_contract=parameter_contract,
        claim_boundary=claim_boundary,
    )


_DEFINITIONS = (
    RecipeDefinition(
        _descriptor(
            "geometry.circular-route",
            "Analytic circular route",
            "Compute tangent circular bends and exact centerline length.",
            RecipeSupportLevel.UNIT_TESTED,
            parameter_contract=_CIRCULAR_ROUTE_PARAMETERS,
        ),
        _circular_route,
    ),
    RecipeDefinition(
        _descriptor(
            "geometry.symmetric-euler-bend",
            "Symmetric Euler bend",
            "Compute a symmetric curvature-ramped Euler bend and its offsets.",
            RecipeSupportLevel.UNIT_TESTED,
            parameter_contract=_SYMMETRIC_EULER_PARAMETERS,
        ),
        _symmetric_euler_bend,
    ),
    RecipeDefinition(
        _descriptor(
            "waveguide.segmented-port-window",
            "Segmented waveguide port window",
            "Plan background/cladding slabs and boundary-selection windows around two ports.",
            RecipeSupportLevel.CONFIGURATION_AUDITED,
            parameter_contract=_SEGMENTED_PORT_PARAMETERS,
            claim_boundary=(
                *_NO_PHYSICS_CLAIM,
                "A valid segmentation plan is not modal or driven-field evidence.",
            ),
        ),
        _segmented_port_window,
    ),
    RecipeDefinition(
        _descriptor(
            "materials.li-silicon-1980",
            "Li 1980 silicon dispersion",
            "Evaluate the reviewed bulk silicon dispersion formula inside its envelope.",
            RecipeSupportLevel.UNIT_TESTED,
            parameter_contract=_LI_SILICON_PARAMETERS,
            claim_boundary=(
                *_NO_PHYSICS_CLAIM,
                "Bulk dispersion does not validate a waveguide mode, PML, mesh, or driven field.",
            ),
        ),
        _li_silicon,
    ),
    RecipeDefinition(
        _descriptor(
            "materials.malitson-fused-silica-1965",
            "Malitson 1965 fused-silica dispersion",
            "Evaluate the reviewed fused-silica Sellmeier formula inside its envelope.",
            RecipeSupportLevel.UNIT_TESTED,
            parameter_contract=_MALITSON_SILICA_PARAMETERS,
            claim_boundary=(
                *_NO_PHYSICS_CLAIM,
                "Bulk dispersion does not validate a waveguide mode, PML, mesh, or driven field.",
            ),
        ),
        _malitson_silica,
    ),
    RecipeDefinition(
        _descriptor(
            "scattering.two-port-common-basis",
            "Two-port common-basis source columns",
            "Plan a complete two-port source-column mapping on one frozen modal basis.",
            RecipeSupportLevel.CONFIGURATION_AUDITED,
            parameter_contract=_TWO_PORT_PARAMETERS,
            claim_boundary=(
                *_NO_PHYSICS_CLAIM,
                "The mapping does not establish solve feasibility, convergence, or broadband phase.",
            ),
        ),
        _two_port_common_basis,
    ),
)

_BY_ID_MUTABLE = {item.descriptor.recipe_id: item for item in _DEFINITIONS}
if len(_BY_ID_MUTABLE) != len(_DEFINITIONS):
    raise RuntimeError("built-in recipe catalog contains duplicate recipe IDs")

RECIPE_CATALOG: Mapping[str, RecipeDefinition] = MappingProxyType(
    dict(sorted(_BY_ID_MUTABLE.items()))
)


def recipe_definitions() -> tuple[RecipeDefinition, ...]:
    return tuple(RECIPE_CATALOG.values())


def recipe_definition(recipe_id: str) -> RecipeDefinition:
    try:
        return RECIPE_CATALOG[recipe_id]
    except KeyError as exc:
        raise InvalidInputError(f"unknown modeling recipe: {recipe_id}") from exc


__all__ = ["RECIPE_CATALOG", "recipe_definition", "recipe_definitions"]
