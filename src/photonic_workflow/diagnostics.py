"""Solver-free, conditional audits of exported observations (never gate promotion).

The versioned request format is intentionally separate from persisted G/M contracts
and the legacy two-port recipe. Caller declarations are not independent evidence.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .exceptions import InvalidInputError


def _object(value: Any, fields: str, label: str) -> dict[str, Any]:
    expected = set(fields.split())
    if not isinstance(value, dict) or set(value) != expected:
        raise InvalidInputError(f"{label} requires exactly: {', '.join(sorted(expected))}")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInputError(f"{label} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InvalidInputError(f"{label} is outside the numeric range") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise InvalidInputError(f"{label} must be finite" + (" and positive" if positive else ""))
    return result


def _nonnegative(value: Any, label: str) -> float:
    result = _number(value, label)
    if result < 0:
        raise InvalidInputError(f"{label} must be nonnegative")
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"{label} must be nonempty text")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise InvalidInputError(f"{label} must be a nonempty array")
    return value


def _unique_text(value: Any, label: str) -> list[str]:
    result = [_text(x, label) for x in _list(value, label)]
    if len(set(result)) != len(result):
        raise InvalidInputError(f"{label} contains duplicates")
    return result


def _complex(value: Any) -> complex:
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidInputError("complex values must be [real, imag]")
    return complex(_number(value[0], "real"), _number(value[1], "imag"))


def _result(checks: dict[str, Any], **details: Any) -> dict[str, Any]:
    states = {item["status"] for item in checks.values()}
    status = "fail" if "fail" in states else "blocked" if "blocked" in states else "pass"
    if states == {"not_applicable"}:
        status = "not_applicable"
    return {
        "schema_version": "1.0", "status": status, "physics_accepted": False,
        "evidence_level": "caller_supplied_observations", "checks": checks, **details,
    }


def _check(value: bool, reason: str) -> dict[str, Any]:
    return {"status": "pass" if value else "fail", "reason": reason}


def scattering_audit(data: dict[str, Any]) -> dict[str, Any]:
    """Assemble N channels by source identity; never infer missing or unused columns."""
    _object(data, "channels source_map columns wavelength_nm assumptions tolerance", "scattering")
    channels = _unique_text(data["channels"], "channels")
    if len(channels) > 64:
        raise InvalidInputError("diagnostic supports at most 64 channels")
    wavelength = _number(data["wavelength_nm"], "wavelength_nm", positive=True)
    tol = _nonnegative(data["tolerance"], "tolerance")
    assumptions = _object(data["assumptions"],
                          "passive reciprocal lossless complete_channels power_orthonormal "
                          "source_independent_basis reciprocity_paired_basis evidence", "assumptions")
    for key, value in assumptions.items():
        if key != "evidence" and value is not None and type(value) is not bool:
            raise InvalidInputError(f"{key} must be true, false or null (unknown)")
    if not isinstance(assumptions["evidence"], list):
        raise InvalidInputError("evidence must be an array of reviewed evidence references")
    for ref in assumptions["evidence"]:
        _text(ref, "evidence reference")
    mapping = data["source_map"]
    if not isinstance(mapping, dict) or set(mapping) != set(channels):
        raise InvalidInputError("source_map must map every channel to a unique source ID")
    _unique_text(list(mapping.values()), "source_map values")
    columns = _list(data["columns"], "columns")
    if len(columns) != len(channels):
        raise InvalidInputError("one complete column is required per input channel")
    matrix = np.empty((len(channels), len(channels)), dtype=complex)
    seen: set[str] = set()
    contexts: set[tuple[str, str, str]] = set()
    for col in columns:
        _object(col, "input_channel source_id model_id basis_id dataset_id wavelength_nm values", "column")
        channel = _text(col["input_channel"], "input_channel")
        if channel not in mapping or channel in seen or col["source_id"] != mapping[channel]:
            raise InvalidInputError("missing, duplicate or inconsistent source/channel mapping")
        if _number(col["wavelength_nm"], "column wavelength", positive=True) != wavelength:
            raise InvalidInputError("column wavelength differs from requested snapshot")
        contexts.add(tuple(_text(col[k], k) for k in ("model_id", "basis_id", "dataset_id")))
        values = _list(col["values"], "column values")
        if len(values) != len(channels):
            raise InvalidInputError("each source needs every output channel, including reflections")
        matrix[:, channels.index(channel)] = [_complex(v) for v in values]
        seen.add(channel)
    # Raw numerical diagnostics remain visible even when a physical inference is blocked.
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            sigma = float(np.linalg.svd(matrix, compute_uv=False)[0])
            symmetry = float(np.linalg.norm(matrix - matrix.T, ord="fro"))
            unitary = float(np.linalg.norm(matrix.conj().T @ matrix - np.eye(len(channels)), ord="fro"))
            powers = np.sum(np.abs(matrix) ** 2, axis=0).tolist()
    except np.linalg.LinAlgError as exc:
        raise InvalidInputError("matrix singular-value diagnostic did not converge") from exc
    if not all(math.isfinite(x) for x in (sigma, symmetry, unitary, *powers)):
        raise InvalidInputError("matrix diagnostics overflowed")
    common = (assumptions["power_orthonormal"] is True
              and assumptions["source_independent_basis"] is True
              and bool(assumptions["evidence"]) and len(contexts) == 1)

    def conditional(flag: bool | None, prerequisites: bool, passed: bool, reason: str) -> dict[str, Any]:
        if flag is False:
            return {"status": "not_applicable", "reason": reason}
        if flag is None or not prerequisites:
            return {"status": "blocked", "reason": "missing applicable assumption or reviewed basis evidence"}
        return _check(passed, reason)

    checks = {
        "passivity": conditional(assumptions["passive"], common, sigma <= 1 + tol,
                                 "contraction only for a declared passive power-wave model"),
        "reciprocity": conditional(assumptions["reciprocal"],
                                   common and assumptions["reciprocity_paired_basis"] is True,
                                   symmetry <= tol, "S=S^T requires reciprocal paired port conventions"),
        "unitarity": conditional(assumptions["lossless"],
                                 common and assumptions["complete_channels"] is True,
                                 unitary <= tol, "unitarity requires losslessness and all outgoing channels"),
    }
    return _result(checks, channels=channels, source_map=mapping,
                   raw_metrics={"sigma_max": sigma, "symmetry_frobenius": symmetry,
                                "unitarity_frobenius": unitary, "column_power": powers},
                   assumptions=assumptions, common_context=len(contexts) == 1,
                   limitations=["No independent gauge proof, power closure, convergence or gate promotion.",
                                "Cross-context columns require a separately audited alignment before this audit."])


def phase_audit(data: dict[str, Any]) -> dict[str, Any]:
    """Retain strict phase and separately report an explicitly chosen amplitude policy."""
    _object(data, "reference candidate amplitude_floor phase_tolerance_rad complex_tolerance policy_id", "phase")
    _text(data["policy_id"], "policy_id")
    floor = _nonnegative(data["amplitude_floor"], "amplitude_floor")
    phase_tol = _nonnegative(data["phase_tolerance_rad"], "phase_tolerance_rad")
    complex_tol = _nonnegative(data["complex_tolerance"], "complex_tolerance")
    reference = [_complex(v) for v in _list(data["reference"], "reference")]
    candidate = [_complex(v) for v in _list(data["candidate"], "candidate")]
    if len(reference) != len(candidate):
        raise InvalidInputError("phase comparison arrays must have identical lengths and ordering")
    rows = []
    for ref, actual in zip(reference, candidate, strict=True):
        defined = ref != 0 and actual != 0
        # Subtract arguments rather than divide or multiply tiny/large complex numbers.
        phase = abs(math.remainder(math.atan2(actual.imag, actual.real)
                                   - math.atan2(ref.imag, ref.real), 2 * math.pi)) if defined else None
        difference = actual - ref
        error = math.hypot(difference.real, difference.imag)
        if not math.isfinite(error):
            raise InvalidInputError("complex difference overflowed")
        rows.append({"absolute_complex_error": error, "raw_phase_error_rad": phase,
                     "phase_defined": defined,
                     "phase_applicable": defined and min(math.hypot(ref.real, ref.imag),
                                                           math.hypot(actual.real, actual.imag)) >= floor})
    strict = [r["raw_phase_error_rad"] for r in rows if r["phase_defined"]]
    eligible = [r["raw_phase_error_rad"] for r in rows if r["phase_applicable"]]
    strict_check = _check(all(p <= phase_tol for p in strict), "original all-entry phase retained")
    if len(strict) < len(rows) and strict_check["status"] == "pass":
        strict_check = {"status": "blocked", "reason": "phase undefined at an exact zero"}
    checks = {"strict_phase": strict_check,
              "absolute_complex": _check(all(r["absolute_complex_error"] <= complex_tol for r in rows),
                                         "absolute complex error at identical ordered comparison points")}
    return _result(checks, rows=rows, policy_id=data["policy_id"],
                   conditioned_phase={"status": ("pass" if all(p <= phase_tol for p in eligible) else "fail")
                                      if eligible else "not_applicable", "eligible_count": len(eligible)},
                   limitations=["Amplitude conditioning never replaces the strict verdict or a historical protocol."])


def geometry_audit(data: dict[str, Any]) -> dict[str, Any]:
    """Audit final 2D domain readbacks against independently specified semantic regions."""
    _object(data, "length_unit domains regions expected_neff actual_neff", "geometry")
    if data["length_unit"] != "um":
        raise InvalidInputError("geometry readback must explicitly convert lengths to um and areas to um^2")
    domains: dict[int, dict[str, Any]] = {}
    for domain in _list(data["domains"], "domains"):
        _object(domain, "id area_um2 bbox_um material", "domain")
        ident = domain["id"]
        if type(ident) is not int or ident < 1 or ident in domains:
            raise InvalidInputError("domain IDs must be unique positive integers")
        _number(domain["area_um2"], "area_um2", positive=True)
        _bounds(domain["bbox_um"], 4, "bbox_um")
        _text(domain["material"], "material")
        domains[ident] = domain
    checks: dict[str, Any] = {}
    claimed: set[int] = set()
    names: set[str] = set()
    for region in _list(data["regions"], "regions"):
        _object(region, "name domain_ids material area_interval_um2 bbox_interval_um", "region")
        name = _text(region["name"], "region name")
        if name in names:
            raise InvalidInputError("duplicate semantic region name")
        names.add(name)
        ids = _list(region["domain_ids"], "domain_ids")
        if any(type(i) is not int or i not in domains for i in ids) or len(set(ids)) != len(ids):
            raise InvalidInputError("semantic region has missing or duplicate domain IDs")
        if claimed.intersection(ids):
            raise InvalidInputError("semantic regions must form a disjoint final-domain partition")
        claimed.update(ids)
        expected_material = _text(region["material"], "expected material")
        area_range = _bounds(region["area_interval_um2"], 2, "area interval")
        if area_range[0] < 0:
            raise InvalidInputError("area interval cannot be negative")
        bbox_range = _bounds(region["bbox_interval_um"], 4, "bbox interval")
        selected = [domains[i] for i in ids]
        area = _number(sum(d["area_um2"] for d in selected), "summed region area", positive=True)
        bbox = [min(d["bbox_um"][0] for d in selected), max(d["bbox_um"][1] for d in selected),
                min(d["bbox_um"][2] for d in selected), max(d["bbox_um"][3] for d in selected)]
        checks[f"{name}:material"] = _check(all(d["material"] == expected_material for d in selected),
                                            "final material assignment matches semantic region")
        checks[f"{name}:area"] = _check(area_range[0] <= area <= area_range[1],
                                        "final measured area lies in independently specified interval")
        checks[f"{name}:bbox"] = _check(bbox_range[0] <= bbox[0] <= bbox[1] <= bbox_range[1]
                                        and bbox_range[2] <= bbox[2] <= bbox[3] <= bbox_range[3],
                                        "final measured bounding box lies within allowed envelope")
    checks["domain_coverage"] = _check(claimed == set(domains), "every final domain has a semantic region")
    expected = data["expected_neff"]
    actual = data["actual_neff"]
    if expected is None:
        if actual is not None:
            _number(actual, "actual_neff")
        checks["port_neff"] = {"status": "not_applicable", "reason": "geometry-only scope; mode audit not requested"}
    else:
        low, high = _bounds(expected, 2, "expected_neff")
        checks["port_neff"] = ({"status": "blocked", "reason": "requested mode readback missing"}
                               if actual is None else _check(low <= _number(actual, "actual_neff") <= high,
                                                            "mode index within independent baseline interval"))
    return _result(checks, domain_count=len(domains), region_count=len(names),
                   limitations=["2D exported readback only; does not measure geometry, topology or material tensors.",
                                "Do not infer semantic mapping or expected bounds from the assigned material."])


def _bounds(value: Any, count: int, label: str) -> list[float]:
    values = [_number(v, label) for v in _list(value, label)]
    if len(values) != count or any(values[i] > values[i + 1] for i in range(0, count, 2)):
        raise InvalidInputError(f"{label} needs {count} ordered interval endpoints")
    return values


def audit_request(payload: dict[str, Any]) -> dict[str, Any]:
    _object(payload, "schema_version kind data", "diagnostic request")
    if payload["schema_version"] != "1.0":
        raise InvalidInputError("unsupported diagnostic schema_version")
    dispatch = {"scattering": scattering_audit, "phase": phase_audit, "geometry": geometry_audit}
    kind = _text(payload["kind"], "kind")
    if kind not in dispatch:
        raise InvalidInputError(f"unknown diagnostic kind: {kind}")
    return {"kind": kind, **dispatch[kind](payload["data"])}


def load_diagnostic_request(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise InvalidInputError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        if path.stat().st_size > 2_000_000:
            raise InvalidInputError("diagnostic request exceeds 2 MB")
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                          parse_constant=lambda v: (_ for _ in ()).throw(InvalidInputError(f"nonfinite JSON: {v}")))
    except (OSError, ValueError, RecursionError) as exc:
        raise InvalidInputError(f"cannot read diagnostic request: {exc}") from exc
