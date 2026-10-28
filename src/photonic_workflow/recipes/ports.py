"""Configuration-only port-window recipes for 2D effective-index models."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

from photonic_workflow.exceptions import InvalidInputError


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InvalidInputError(f"{name} must be a real number")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise InvalidInputError(f"{name} must be representable as a finite number") from exc
    if not math.isfinite(result):
        raise InvalidInputError(f"{name} must be finite")
    return result


def segmented_port_window_plan(
    x_min_um: float,
    x_max_um: float,
    y_min_um: float,
    y_max_um: float,
    port_center_y_um: float,
    port_half_height_um: float,
    selection_tolerance_um: float = 0.008,
) -> dict[str, object]:
    """Plan segmented cladding and two exterior port selections.

    The horizontal background slabs create explicit y-cuts at the lower and
    upper edges of the local modal cross-section window.  The window must not
    be an arbitrary full exterior side shared by unrelated guides or open
    background.  The plan also requires the two port selections to be
    subtracted from the complete exterior scattering-boundary set.

    This function performs no geometry build and no solver execution.  Entity
    counts and zero overlap with the scattering set must be checked after a
    backend builds the geometry.
    """

    x_min = _finite("x_min_um", x_min_um)
    x_max = _finite("x_max_um", x_max_um)
    y_min = _finite("y_min_um", y_min_um)
    y_max = _finite("y_max_um", y_max_um)
    port_center = _finite("port_center_y_um", port_center_y_um)
    port_half_height = _finite("port_half_height_um", port_half_height_um)
    tolerance = _finite("selection_tolerance_um", selection_tolerance_um)
    if x_min >= x_max:
        raise InvalidInputError("x_min_um must be smaller than x_max_um")
    if y_min >= y_max:
        raise InvalidInputError("y_min_um must be smaller than y_max_um")
    if port_half_height <= 0.0:
        raise InvalidInputError("port_half_height_um must be positive")
    if tolerance <= 0.0:
        raise InvalidInputError("selection_tolerance_um must be positive")
    if 2.0 * tolerance >= x_max - x_min:
        raise InvalidInputError("selection_tolerance_um is too large for the x span")

    port_y_min = port_center - port_half_height
    port_y_max = port_center + port_half_height
    if not (y_min < port_y_min < port_y_max < y_max):
        raise InvalidInputError(
            "port window must lie strictly inside the vertical background span"
        )

    background_slabs = (
        {
            "id": "background_lower",
            "bounds_um": (x_min, x_max, y_min, port_y_min),
        },
        {
            "id": "background_port",
            "bounds_um": (x_min, x_max, port_y_min, port_y_max),
        },
        {
            "id": "background_upper",
            "bounds_um": (x_min, x_max, port_y_max, y_max),
        },
    )
    port_windows = (
        {
            "id": "port_1_boundary",
            "side": "left",
            "bounds_um": (
                x_min - tolerance,
                x_min + tolerance,
                port_y_min,
                port_y_max,
            ),
        },
        {
            "id": "port_2_boundary",
            "side": "right",
            "bounds_um": (
                x_max - tolerance,
                x_max + tolerance,
                port_y_min,
                port_y_max,
            ),
        },
    )
    scattering_boundary_difference = {
        "add": (
            "exterior_top",
            "exterior_bottom",
            "exterior_left",
            "exterior_right",
        ),
        "subtract": ("port_1_boundary", "port_2_boundary"),
        "result": "scattering_boundaries",
    }
    entity_count_rules = (
        {
            "metric": "background_slab_domain_count",
            "operator": "eq",
            "expected": 3,
        },
        {
            "metric": "port_1_boundary_count",
            "operator": "gte",
            "expected": 1,
        },
        {
            "metric": "port_2_boundary_count",
            "operator": "gte",
            "expected": 1,
        },
        {
            "metric": "scattering_boundary_count",
            "operator": "gte",
            "expected": 1,
        },
        {
            "metric": "port_boundary_count_symmetry",
            "operator": "eq",
            "left_metric": "port_1_boundary_count",
            "right_metric": "port_2_boundary_count",
        },
        {
            "metric": "port_scattering_overlap_count",
            "operator": "eq",
            "expected": 0,
        },
        {
            "metric": "port_port_overlap_count",
            "operator": "eq",
            "expected": 0,
        },
        {
            "metric": "exterior_boundary_missing_count",
            "operator": "eq",
            "expected": 0,
        },
        {
            "metric": "nonexterior_boundary_selected_count",
            "operator": "eq",
            "expected": 0,
        },
    )
    return {
        "claim_level": "configuration-only-2d-eim",
        "length_unit": "um",
        "will_execute": False,
        "background_slabs": background_slabs,
        "port_windows": port_windows,
        "scattering_boundary_difference": scattering_boundary_difference,
        "entity_count_rules": entity_count_rules,
    }


def _boundary_ids(name: str, values: Sequence[int]) -> tuple[int, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InvalidInputError(f"{name} must be an array of positive boundary IDs")
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidInputError(
                f"{name} must contain only positive integer boundary IDs"
            )
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise InvalidInputError(f"{name} contains duplicate boundary IDs")
    return tuple(normalized)


def audit_exterior_boundary_partition(
    *,
    exterior_boundary_ids: Sequence[int],
    port_boundary_ids: Mapping[str, Sequence[int]],
    open_boundary_ids: Sequence[int],
) -> dict[str, object]:
    """Fail closed unless ports and open boundaries exactly partition the exterior.

    Keys in ``port_boundary_ids`` identify physical cross-section faces, not
    individual modal channels. Several modal Port features may share one face;
    group their identical boundary selection under one physical-face key before
    this audit and validate channel identities/normalization separately. Never
    merge genuinely distinct, overlapping physical faces to bypass this check.

    ``open_boundary_ids`` represents the scattering/radiation or PML-facing
    exterior selection.  This is a pure post-geometry entity audit: it does not
    decide whether a port window contains the correct modal support and it does
    not execute a solver.
    """

    exterior = set(_boundary_ids("exterior_boundary_ids", exterior_boundary_ids))
    if not exterior:
        raise InvalidInputError("exterior_boundary_ids must not be empty")
    if not isinstance(port_boundary_ids, Mapping) or not port_boundary_ids:
        raise InvalidInputError("port_boundary_ids must contain at least one port")

    normalized_ports: dict[str, tuple[int, ...]] = {}
    occupied: set[int] = set()
    for raw_name, raw_ids in port_boundary_ids.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise InvalidInputError("every port selection needs a nonblank name")
        ids = _boundary_ids(f"port_boundary_ids[{raw_name!r}]", raw_ids)
        if not ids:
            raise InvalidInputError(f"port {raw_name!r} must select at least one boundary")
        overlap = occupied.intersection(ids)
        if overlap:
            raise InvalidInputError(
                f"port selections overlap on boundary IDs: {sorted(overlap)}"
            )
        normalized_ports[raw_name] = ids
        occupied.update(ids)

    open_ids = set(_boundary_ids("open_boundary_ids", open_boundary_ids))
    port_open_overlap = occupied.intersection(open_ids)
    selected = occupied.union(open_ids)
    missing = exterior - selected
    nonexterior = selected - exterior
    if port_open_overlap or missing or nonexterior:
        raise InvalidInputError(
            "exterior boundary partition failed; "
            f"port_open_overlap={sorted(port_open_overlap)}, "
            f"missing={sorted(missing)}, nonexterior={sorted(nonexterior)}"
        )

    return {
        "status": "pass",
        "claim_level": "configuration-only-boundary-selection",
        "will_execute": False,
        "exterior_boundary_count": len(exterior),
        "port_boundary_count": len(occupied),
        "open_boundary_count": len(open_ids),
        "port_count": len(normalized_ports),
        "port_boundary_ids": normalized_ports,
        "open_boundary_ids": tuple(sorted(open_ids)),
        "port_open_overlap_count": 0,
        "exterior_boundary_missing_count": 0,
        "nonexterior_boundary_selected_count": 0,
    }


_SEGMENTED_PORT_PARAMETER_KEYS = frozenset(
    {
        "x_min_um",
        "x_max_um",
        "y_min_um",
        "y_max_um",
        "port_center_y_um",
        "port_half_height_um",
        "selection_tolerance_um",
    }
)


def evaluate_segmented_port_window(parameters: Mapping[str, Any]) -> dict[str, object]:
    """Evaluate the catalog-facing recipe and reject every unknown key."""

    if not isinstance(parameters, Mapping):
        raise InvalidInputError("parameters must be an object")
    unknown = set(parameters) - _SEGMENTED_PORT_PARAMETER_KEYS
    if unknown:
        raise InvalidInputError(
            f"unknown segmented-port-window parameter(s): {sorted(unknown)}"
        )
    required = _SEGMENTED_PORT_PARAMETER_KEYS - {"selection_tolerance_um"}
    missing = required - set(parameters)
    if missing:
        raise InvalidInputError(
            f"missing segmented-port-window parameter(s): {sorted(missing)}"
        )
    return segmented_port_window_plan(
        x_min_um=parameters["x_min_um"],
        x_max_um=parameters["x_max_um"],
        y_min_um=parameters["y_min_um"],
        y_max_um=parameters["y_max_um"],
        port_center_y_um=parameters["port_center_y_um"],
        port_half_height_um=parameters["port_half_height_um"],
        selection_tolerance_um=parameters.get("selection_tolerance_um", 0.008),
    )


__all__ = [
    "audit_exterior_boundary_partition",
    "evaluate_segmented_port_window",
    "segmented_port_window_plan",
]
