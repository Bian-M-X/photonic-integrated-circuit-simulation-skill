"""Explicit complex-amplitude exchange from Lumerical to assembly-v1.

This is a data conversion, not a solver or a modal calibration. The transport
deliberately requires a complete matrix and an explicit array order. A native
monitor's power trace or an unexplained squeezed array is not an S matrix.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
from numbers import Integral, Real
from pathlib import Path
from typing import Any

from .circuits import MODEL_LEVELS, REQUIRED_COLUMNS
from .exceptions import InvalidInputError, SecurityViolationError
from .models.io import atomic_create_text
from .recipes.artifacts import checked_recipe_output

_TIME_CONVENTIONS = {"exp(+iwt)", "exp(-iwt)"}
_ROOT_FIELDS = {
    "schema_version", "producer", "model_level", "passive", "spectral_axis",
    "channels", "conventions", "s_matrices",
}
_CHANNEL_FIELDS = {
    "id", "port", "mode", "incoming_direction", "outgoing_direction", "reference_plane",
}
_LIMITATIONS = [
    "Import preserves declared complex amplitudes; no solver execution or physical acceptance is inferred.",
    "No mode normalization, reference-plane shift, modal-gauge alignment, interpolation or de-embedding is performed.",
    "Complete declared channels do not establish modal completeness, convergence or continuous-band validity.",
    "Do not combine this component with another time convention, basis or reference plane without explicit alignment.",
]


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidInputError(f"{label} must be an object")
    if set(value) != keys:
        raise InvalidInputError(
            f"{label} fields mismatch; missing={sorted(keys - set(value))}, "
            f"unknown={sorted(set(value) - keys, key=str)}"
        )
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InvalidInputError(f"{label} must be a finite real number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise InvalidInputError(f"{label} must be a finite real number") from exc
    if not math.isfinite(result):
        raise InvalidInputError(f"{label} must be a finite real number")
    if isinstance(value, Integral) and int(value) != result:
        raise InvalidInputError(f"{label} integer cannot be represented losslessly as binary64")
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"{label} must be a non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidInputError(f"{label} must be valid UTF-8 text") from exc
    return value


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InvalidInputError(f"non-finite JSON number: {value}")


def _read_source(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = Path(path).read_bytes()
        payload = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_json_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidInputError(f"cannot read Lumerical S-parameter JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidInputError("Lumerical S-parameter JSON must be an object")
    return raw, payload


def load_lumerical_sparameters(path: Path) -> dict[str, Any]:
    """Read the explicit v1 transport, rejecting duplicate and nonfinite tokens."""
    return _read_source(path)[1]


def normalize_lumerical_sparameters(
    payload: dict[str, Any], *, target_time_dependence: str | None = None,
) -> dict[str, Any]:
    """Validate v1 and jointly sort spectral samples and their complete matrices.

    The default retains the declared phasor convention. An explicit target of
    the opposite sign conjugates all amplitudes and records that conversion;
    callers must use the correspondingly conjugated modal field basis.
    """
    data = _exact(payload, _ROOT_FIELDS, "Lumerical S-parameter transport")
    if data["schema_version"] != "1.0":
        raise InvalidInputError("schema_version must be exactly '1.0'")
    producer = _exact(data["producer"], {"product", "version"}, "producer")
    if not isinstance(producer["product"], str) or producer["product"] not in {"FDTD", "MODE", "INTERCONNECT"}:
        raise InvalidInputError("producer.product must be FDTD, MODE or INTERCONNECT")
    _text(producer["version"], "producer.version")
    if not isinstance(data["model_level"], str) or data["model_level"] not in MODEL_LEVELS:
        raise InvalidInputError(f"model_level must be one of {sorted(MODEL_LEVELS)}")
    if not isinstance(data["passive"], bool):
        raise InvalidInputError("passive must be a declared boolean; it is not inferred from S")
    conventions = _exact(
        data["conventions"],
        {"time_dependence", "sparameter_normalization", "matrix_axes", "amplitude_encoding"},
        "conventions",
    )
    source_time = conventions["time_dependence"]
    if not isinstance(source_time, str) or source_time not in _TIME_CONVENTIONS:
        raise InvalidInputError("time_dependence must be exp(+iwt) or exp(-iwt)")
    if target_time_dependence is not None and (
        not isinstance(target_time_dependence, str) or target_time_dependence not in _TIME_CONVENTIONS
    ):
        raise InvalidInputError("target_time_dependence must be exp(+iwt) or exp(-iwt)")
    target_time = source_time if target_time_dependence is None else target_time_dependence
    if conventions["sparameter_normalization"] != "power-wave":
        raise InvalidInputError("only declared complex power-wave amplitudes are supported")
    if conventions["matrix_axes"] != ["spectral", "outgoing", "incoming"]:
        raise InvalidInputError("matrix_axes must be exactly [spectral, outgoing, incoming]")
    if conventions["amplitude_encoding"] != "real-imaginary":
        raise InvalidInputError("amplitude_encoding must be real-imaginary; power traces are not complex S")

    channels = data["channels"]
    if not isinstance(channels, list) or not channels:
        raise InvalidInputError("channels must be a non-empty array")
    ids: list[str] = []
    physical_modes: set[tuple[str, str]] = set()
    for index, channel in enumerate(channels):
        _exact(channel, _CHANNEL_FIELDS, f"channels[{index}]")
        for key in _CHANNEL_FIELDS:
            _text(channel[key], f"channels[{index}].{key}")
        if ":" in channel["id"]:
            raise InvalidInputError("channel id must not contain ':' (assembly endpoint delimiter)")
        if channel["id"] in ids:
            raise InvalidInputError(f"duplicate channel id: {channel['id']}")
        ids.append(channel["id"])
        physical_mode = (channel["port"], channel["mode"])
        if physical_mode in physical_modes:
            raise InvalidInputError(f"duplicate physical port/mode channel: {physical_mode}")
        physical_modes.add(physical_mode)
        if channel["incoming_direction"] == channel["outgoing_direction"]:
            raise InvalidInputError("incoming_direction and outgoing_direction must differ")

    axis = _exact(data["spectral_axis"], {"quantity", "unit", "values"}, "spectral_axis")
    quantity, unit = axis["quantity"], axis["unit"]
    if not ((quantity == "frequency" and unit == "Hz") or
            (quantity == "wavelength" and unit in ("m", "nm"))):
        raise InvalidInputError("spectral_axis requires frequency/Hz or wavelength/m or wavelength/nm")
    if not isinstance(axis["values"], list) or not axis["values"]:
        raise InvalidInputError("spectral_axis.values must be a non-empty one-dimensional array")
    values = [_number(value, "spectral_axis.values") for value in axis["values"]]
    if any(value <= 0 for value in values) or len(set(values)) != len(values):
        raise InvalidInputError("spectral_axis.values must be positive and contain no duplicates")
    wavelengths = [
        (299792458.0 / value * 1e9 if quantity == "frequency" else value * (1e9 if unit == "m" else 1.0))
        for value in values
    ]
    if any(not math.isfinite(wavelength) or wavelength <= 0 for wavelength in wavelengths):
        raise InvalidInputError("wavelength conversion produced a nonfinite or nonpositive wavelength")
    if len(set(wavelengths)) != len(wavelengths):
        raise InvalidInputError("distinct source samples collide after wavelength conversion")
    order = sorted(range(len(values)), key=wavelengths.__getitem__)
    matrices = data["s_matrices"]
    if not isinstance(matrices, list) or len(matrices) != len(values):
        raise InvalidInputError("one complete S matrix is required per spectral sample")
    validated = []
    for matrix in matrices:
        if not isinstance(matrix, list) or len(matrix) != len(channels):
            raise InvalidInputError("S matrix has incorrect outgoing-channel count")
        rows = []
        for row in matrix:
            if not isinstance(row, list) or len(row) != len(channels):
                raise InvalidInputError("S matrix has incorrect incoming-channel count")
            amplitudes = []
            for amplitude in row:
                if not isinstance(amplitude, list) or len(amplitude) != 2:
                    raise InvalidInputError("S amplitudes must be [real, imaginary] pairs")
                real, imaginary = [_number(value, "S amplitude") for value in amplitude]
                amplitudes.append([real, -imaginary if target_time != source_time else imaginary])
            rows.append(amplitudes)
        validated.append(rows)
    conversions = []
    if target_time != source_time:
        conversions.append({
            "operation": "complex-conjugation", "source_time_dependence": source_time,
            "target_time_dependence": target_time,
            "basis_requirement": "Correspondingly conjugate modal field bases; no modal-gauge alignment is inferred.",
        })
    return {
        "schema_version": "1.0", "producer": copy.deepcopy(producer),
        "model_level": data["model_level"], "passive": data["passive"],
        "wavelengths_nm": [wavelengths[index] for index in order],
        "s_matrices": [validated[index] for index in order],
        "port_order": ids, "channels": copy.deepcopy(channels),
        "conventions": {"wavelength_unit": "nm", "sparameter_normalization": "power-wave",
                        "time_dependence": target_time},
        "source_spectral_axis": copy.deepcopy(axis), "source_sample_order": order,
        "conversions": conversions, "physics_accepted": False, "will_execute": False,
        "limitations": _LIMITATIONS.copy(),
    }


def dataset_from_arrays(
    s_parameters: Any, *, spectral_axis: dict[str, Any], channels: list[dict[str, str]],
    producer: dict[str, str], model_level: str, passive: bool, time_dependence: str,
) -> dict[str, Any]:
    """Pack an explicitly arranged native NumPy complex array without squeezing.

    ``s_parameters`` must already have shape (spectral, outgoing, incoming).
    Native S11/S21 monitor dictionaries require caller-selected channel mapping;
    this helper never guesses a monitor name, dimension, transpose or phase.
    """
    import numpy as np

    try:
        matrix = np.asarray(s_parameters)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError("s_parameters must be a rectangular numeric array") from exc
    if matrix.dtype.kind not in "fc" or matrix.ndim != 3:
        raise InvalidInputError("s_parameters must be a numeric array with axes (spectral, outgoing, incoming)")
    if not np.isfinite(matrix).all():
        raise InvalidInputError("s_parameters must contain only finite amplitudes")
    payload = {
        "schema_version": "1.0", "producer": copy.deepcopy(producer),
        "model_level": model_level, "passive": passive,
        "spectral_axis": copy.deepcopy(spectral_axis), "channels": copy.deepcopy(channels),
        "conventions": {"time_dependence": time_dependence, "sparameter_normalization": "power-wave",
                        "matrix_axes": ["spectral", "outgoing", "incoming"],
                        "amplitude_encoding": "real-imaginary"},
        "s_matrices": np.stack((matrix.real, matrix.imag), axis=-1).tolist(),
    }
    normalize_lumerical_sparameters(payload)
    return payload


def _scattering_csv(data: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(REQUIRED_COLUMNS)
    for wavelength, matrix in zip(data["wavelengths_nm"], data["s_matrices"], strict=True):
        for out_index, out_port in enumerate(data["port_order"]):
            for in_index, in_port in enumerate(data["port_order"]):
                real, imaginary = matrix[out_index][in_index]
                writer.writerow((wavelength, out_port, in_port, real, imaginary))
    return output.getvalue()


def export_lumerical_sparameters(
    source_file: Path, output_csv: Path, *, project_root: Path,
    target_time_dependence: str | None = None,
) -> dict[str, Any]:
    """Create new assembly CSV, metadata and raw-source artifacts; never replace.

    ``component.sparameters`` in the receipt is relative to ``project_root``;
    put the assembly manifest there or adjust that path explicitly. The raw
    source JSON is unchanged and archived byte-for-byte with a SHA-256 hash.
    """
    source = Path(source_file).resolve()
    raw_source, payload = _read_source(source)
    data = normalize_lumerical_sparameters(payload, target_time_dependence=target_time_dependence)
    root = Path(project_root).resolve()
    output, relative_output = checked_recipe_output(root, Path(output_csv))
    metadata_path, relative_metadata = checked_recipe_output(root, output.with_suffix(output.suffix + ".metadata.json"))
    raw_path, relative_raw = checked_recipe_output(root, output.with_suffix(output.suffix + ".source.json"))
    for path in (output, metadata_path, raw_path):
        if path.exists():
            raise InvalidInputError(f"output already exists: {path}")
    text = _scattering_csv(data)
    csv_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    component = {
        "ports": data["port_order"],
        "port_modes": {channel["id"]: channel["mode"] for channel in data["channels"]},
        "model_level": data["model_level"], "passive": data["passive"],
        "reference_plane": "; ".join(
            f"{channel['id']}: {channel['reference_plane']}" for channel in data["channels"]
        ),
        "sparameters": relative_output,
    }
    metadata = {
        **data, "s_matrices": {"artifact_path": relative_output, "sha256": csv_hash},
        "source": {"path": str(source), "artifact_path": relative_raw,
                   "sha256": hashlib.sha256(raw_source).hexdigest(), "raw_preserved": True},
        "component": component,
    }
    metadata_text = json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    # UTF-8 decoding without stripping a BOM, and newline='\n' in the writer,
    # reproduce the original bytes, including BOM, CRLF and trailing whitespace.
    artifacts = [(raw_path, raw_source.decode("utf-8")), (metadata_path, metadata_text), (output, text)]
    created: list[tuple[Path, bytes]] = []
    try:
        for path, contents in artifacts:
            atomic_create_text(path, contents, path_guard=lambda candidate: checked_recipe_output(root, candidate))
            created.append((path, contents.encode("utf-8")))
    except Exception:
        # Each create is atomic and refuses overwrite. Roll back only unchanged
        # files created by this call; preserve evidence modified by another actor.
        for path, expected_bytes in reversed(created):
            try:
                checked_recipe_output(root, path)
                if path.read_bytes() == expected_bytes:
                    path.unlink()
            except (OSError, InvalidInputError, SecurityViolationError):
                pass
        raise
    return {
        "artifact_path": relative_output, "sha256": csv_hash,
        "metadata_path": relative_metadata,
        "metadata_sha256": hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
        "source": metadata["source"], "component": component, "conventions": data["conventions"],
        "channel_count": len(data["port_order"]), "wavelength_count": len(data["wavelengths_nm"]),
        "conversions": data["conversions"], "physics_accepted": False, "will_execute": False,
        "limitations": _LIMITATIONS.copy(),
    }


__all__ = [
    "dataset_from_arrays", "export_lumerical_sparameters", "load_lumerical_sparameters",
    "normalize_lumerical_sparameters",
]
