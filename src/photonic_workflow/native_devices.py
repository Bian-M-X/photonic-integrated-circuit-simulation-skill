"""Native family requests and receipt-bound scattering calibration.

Preparation is solver-free. Running is an explicit, separate backend operation.
Native results retain their actual model level and never promote a G/M gate.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from .exceptions import InvalidInputError

FAMILIES = ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch", "ring", "ring-modulator")


def _number(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInputError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise InvalidInputError(f"{label} must be a finite number") from error
    if not math.isfinite(result) or not low <= result <= high:
        raise InvalidInputError(f"{label} must be in [{low}, {high}]")
    return result


def _object(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed:
        raise InvalidInputError(f"{label} must be an object with only {sorted(allowed)}")
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_native_json(path: Path | str) -> dict[str, Any]:
    def invalid(value: str) -> None:
        raise InvalidInputError(f"nonfinite JSON value: {value}")

    result = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)
    if not isinstance(result, dict):
        raise InvalidInputError("native request/receipt must be a JSON object")
    return result


def native_catalog() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "families": list(FAMILIES),
        "model_level": "2d-scalar-index-surrogate",
        "stages": ["configure", "modes", "solve"],
        "preparation_executes_solver": False,
        "execution": "Explicit photonic native run; local licensed COMSOL required.",
        "physics_accepted": False,
    }


def native_request(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    allowed = {
        "schema_version",
        "family",
        "parameters",
        "wavelengths_nm",
        "materials",
        "mesh",
        "stage",
        "pn",
        "export_fields",
        "measure_mesh_area",
    }
    _object(request, allowed, "native request")
    if request.get("schema_version") != "1.0" or request.get("family") not in FAMILIES:
        raise InvalidInputError("native request requires schema_version '1.0' and a known family")
    family = request["family"]
    parameters = request.get("parameters", {})
    if not isinstance(parameters, dict):
        raise InvalidInputError("parameters must be an object")
    if family in ("ring", "ring-modulator"):
        from .ring_modulator import build_ring_geometry

        geometry = build_ring_geometry(parameters)
        geometry["family"] = family
    else:
        from .native_geometry import build_geometry

        geometry = build_geometry(family, parameters)
    wavelengths = request.get("wavelengths_nm", [1550.0])
    if not isinstance(wavelengths, list) or not 1 <= len(wavelengths) <= 128:
        raise InvalidInputError("wavelengths_nm must have 1 to 128 distinct increasing values")
    wavelengths = [_number(w, "wavelength_nm", 1200.0, 1700.0) for w in wavelengths]
    if any(a >= b for a, b in pairwise(wavelengths)):
        raise InvalidInputError("wavelengths_nm must be distinct and increasing")
    materials = _object(request.get("materials", {}), {"core_index", "cladding_index"}, "materials")
    ncore = _number(materials.get("core_index", 2.6), "core_index", 1.01, 4.5)
    nclad = _number(materials.get("cladding_index", 1.45), "cladding_index", 1.0, 4.49)
    if ncore <= nclad:
        raise InvalidInputError("core_index must exceed cladding_index")
    # Exact cutoff of the second bound branch for a symmetric scalar slab port.
    # This controls modal coverage at the straight port, not the 3D SOI stack.
    maximum_width = wavelengths[0] / 1000.0 / (2 * math.sqrt(ncore * ncore - nclad * nclad))
    if any(port["width_um"] >= maximum_width for port in geometry["ports"]):
        raise InvalidInputError("a port supports additional scalar slab modes; this backend selects only one per face")
    mesh = _object(request.get("mesh", {}), {"core_mesh_um", "cladding_mesh_um", "port_mesh_um"}, "mesh")
    stage = request.get("stage", "solve")
    if stage not in ("configure", "modes", "solve"):
        raise InvalidInputError("unknown native stage")
    if not isinstance(request.get("export_fields", True), bool):
        raise InvalidInputError("export_fields must be a boolean")
    if not isinstance(request.get("measure_mesh_area", family in ("ring", "ring-modulator")), bool):
        raise InvalidInputError("measure_mesh_area must be a boolean")
    config = {
        "wavelengths_nm": wavelengths,
        "core_index": ncore,
        "cladding_index": nclad,
        "active_index": ncore,
        "active_extinction": 0.0,
        "core_mesh_um": _number(mesh.get("core_mesh_um", 0.08), "core_mesh_um", 0.01, 0.2),
        "cladding_mesh_um": _number(mesh.get("cladding_mesh_um", 0.28), "cladding_mesh_um", 0.03, 0.6),
        "stage": stage,
        "export_fields": request.get("export_fields", True),
        "measure_mesh_area": request.get("measure_mesh_area", family in ("ring", "ring-modulator")),
        "port_mesh_um": (
            None if mesh.get("port_mesh_um") is None else _number(mesh["port_mesh_um"], "port_mesh_um", 0.005, 0.2)
        ),
    }
    if family == "ring-modulator":
        from .ring_modulator import depletion_response

        if not isinstance(request.get("pn", {}), dict):
            raise InvalidInputError("pn must be an object")
        pn = dict(request.get("pn", {}))
        width = geometry["parameters"]["width_um"]
        circumference = 2 * math.pi * geometry["parameters"]["radius_um"]
        pn.setdefault("optical_width_um", width)
        pn.setdefault("junction_length_um", circumference)
        response = depletion_response(pn)
        normalized_pn = response["parameters"]
        if not math.isclose(normalized_pn["optical_width_um"], width, rel_tol=1e-10):
            raise InvalidInputError("PN optical_width_um must match the ring width")
        if not math.isclose(normalized_pn["junction_length_um"], circumference, rel_tol=1e-10):
            raise InvalidInputError("PN junction_length_um must match the ring circumference")
        geometry["pn_response"] = response
        # The native solver supplies lateral modal overlap. Here the declared
        # factor covers only confinement/corrections absent from the 2D model;
        # the returned perturbation is applied to its uniform effective core.
        config["active_index"] = ncore + response["delta_n_eff"]
        config["active_extinction"] = response["absolute_k_eff"]
    elif "pn" in request:
        raise InvalidInputError("pn is only valid for ring-modulator")
    return geometry, config


def parse_native_output(text: str, geometry: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Validate actual source/wavelength axes before constructing any matrix."""
    records: dict[str, list[list[str]]] = {}
    for line in text.splitlines():
        if line.startswith("PIC "):
            fields = line.split()
            records.setdefault(fields[1], []).append(fields[2:])
    stage = config["stage"]
    for name, wanted in (("STAGE", [[stage]]), ("COMPLETE", [[stage]])):
        if records.get(name) != wanted:
            raise InvalidInputError(f"missing or duplicate PIC {name} {stage}")
    for name in ("GEOMETRY_PASS", "PORTS_PASS"):
        if records.get(name) != [[]]:
            raise InvalidInputError(f"missing or duplicate PIC {name}")
    units = records.get("UNIT_CODEPOINTS", [])
    if len(units) != 1:
        raise InvalidInputError("missing or duplicate native geometry unit")
    try:
        codepoints = json.loads(" ".join(units[0]))
    except (ValueError, TypeError) as error:
        raise InvalidInputError("invalid native geometry unit codepoints") from error
    if codepoints not in ([117, 109], [181, 109], [956, 109]):
        raise InvalidInputError("native geometry unit is not micrometres")
    nports = len(geometry["ports"])
    wavelengths = config["wavelengths_nm"]

    def area_rows(name: str) -> dict[str, float]:
        values: dict[str, float] = {}
        for fields in records.get(name, []):
            if len(fields) != 2 or fields[0] in values:
                raise InvalidInputError("invalid or duplicate native area record")
            values[fields[0]] = _number(float(fields[1]), "native area", 0.0, 1e8)
        return values

    render_areas = area_rows("AREA")
    if set(render_areas) != {"core", "active", "bg", "all"}:
        raise InvalidInputError("native rendering area records are incomplete")
    mesh_areas = area_rows("AREA_MESH")
    curved = any(p["type"] == "ring" for p in geometry["primitives"])
    if mesh_areas and (stage != "solve" or not config.get("measure_mesh_area", False)):
        raise InvalidInputError("unexpected mesh-area observations for this native configuration")
    if stage == "solve" and config.get("measure_mesh_area", False) and not mesh_areas:
        raise InvalidInputError("configured native mesh-area observations are missing")
    areas = mesh_areas or render_areas
    if stage == "solve" and curved and not mesh_areas:
        raise InvalidInputError("curved native calibration requires independent mesh-area integration")
    if set(areas) != {"core", "active", "bg", "all"}:
        raise InvalidInputError("native material/domain areas are incomplete")
    if areas["active"] > areas["core"] + 1e-7:
        raise InvalidInputError("native active area exceeds core area")
    if stage == "solve" and curved:
        active_area = sum(
            math.pi * (p["outer_radius"] ** 2 - p["inner_radius"] ** 2)
            for p in geometry["primitives"]
            if p["group"] == "active" and p["type"] == "ring"
        )
        if not math.isclose(areas["active"], active_area, rel_tol=2e-5, abs_tol=1e-5):
            raise InvalidInputError("native active-ring area differs from the specified annulus")
    expected = geometry.get("expected_core_area_um2")
    if expected is not None and not math.isclose(areas["core"], expected, rel_tol=2e-5, abs_tol=1e-5):
        raise InvalidInputError("native core area differs from the emitted primitive union")
    box = geometry["bbox_um"]
    boxarea = (box[1] - box[0]) * (box[3] - box[2])
    if not math.isclose(areas["all"], boxarea, rel_tol=2e-5, abs_tol=1e-5) or not math.isclose(
        areas["core"] + areas["bg"], areas["all"], rel_tol=2e-5, abs_tol=1e-5
    ):
        raise InvalidInputError("native domain partition does not close")
    widths: dict[int, float] = {}
    for fields in records.get("CORE_END", []):
        if len(fields) != 2 or int(fields[0]) in widths:
            raise InvalidInputError("invalid or duplicate actual core end")
        widths[int(fields[0])] = float(fields[1])
    if set(widths) != set(range(1, nports + 1)):
        raise InvalidInputError("native core ends incomplete")
    for index, port in enumerate(geometry["ports"], 1):
        if not math.isclose(widths[index], port["width_um"], rel_tol=1e-5, abs_tol=1e-6):
            raise InvalidInputError("actual native port core width mismatch")
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "family": geometry["family"],
        "stage": stage,
        "model_level": geometry["model_level"],
        "port_order": [p["name"] for p in geometry["ports"]],
        "wavelengths_nm": wavelengths,
        "areas_um2": areas,
        "render_areas_um2": render_areas,
        "area_measurement": "native curved finite-element integral"
        if records.get("AREA_MESH")
        else "native rendering mesh",
        "geometry_readback": "passed",
        "physics_accepted": False,
        "s_matrices": [],
        "diagnostics": [],
        "phase_basis": "raw native numeric-port basis; cross-run gauge alignment is not established",
        "geometry_sha256": hashlib.sha256(
            (
                json.dumps(geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
            ).encode()
        ).hexdigest(),
        "materials": {
            key: config[key] for key in ("core_index", "cladding_index", "active_index", "active_extinction")
        },
    }
    if stage == "configure":
        if any(records.get(name) for name in ("S", "SOURCE", "FLUX", "MODE", "MODE_ANCHOR", "MODE_POWER")):
            raise InvalidInputError("non-driven native stage contains driven records")
        return result

    def table(name: str, arity: int, keys: int) -> dict[tuple[float, ...], list[float]]:
        parsed: dict[tuple[float, ...], list[float]] = {}
        for fields in records.get(name, []):
            if len(fields) != arity:
                raise InvalidInputError(f"invalid PIC {name} record")
            values = [float(v) for v in fields]
            if not all(math.isfinite(v) for v in values):
                raise InvalidInputError(f"nonfinite PIC {name} record")
            key = tuple(values[:keys])
            if key in parsed:
                raise InvalidInputError(f"duplicate PIC {name} record")
            parsed[key] = values[keys:]
        return parsed

    srows = table("S", 5, 3)
    sources = table("SOURCE", 3, 2)
    modes = table("MODE", 4, 2)
    anchors = table("MODE_ANCHOR", 4, 2)
    mode_powers = table("MODE_POWER", 3, 2)
    expected_axes = {
        (w, source, receive) for w in wavelengths for source in range(1, nports + 1) for receive in range(1, nports + 1)
    }
    expected_modes = {(w, port) for w in wavelengths for port in range(1, nports + 1)}
    if any(set(rows) != expected_modes for rows in (modes, anchors, mode_powers)):
        raise InvalidInputError("native selected modes, anchors or normalization powers incomplete")
    for key, neff in modes.items():
        if not config["cladding_index"] < neff[0] < config["core_index"] or abs(neff[1]) > 1e-5:
            raise InvalidInputError("a selected port branch is not a bound lossless mode")
        if math.hypot(*anchors[key]) <= 1e-20:
            raise InvalidInputError("a selected port mode has a zero phase anchor")
        if abs(mode_powers[key][0] - 1.0) >= 1e-3:
            raise InvalidInputError("selected mode power normalization failed")
    result["selected_modes"] = [
        {
            "wavelength_nm": w,
            "port": p,
            "neff": modes[(w, p)],
            "anchor": anchors[(w, p)],
            "outward_power": mode_powers[(w, p)][0],
        }
        for w in wavelengths
        for p in range(1, nports + 1)
    ]
    if stage == "modes":
        if any(records.get(name) for name in ("S", "SOURCE", "FLUX")):
            raise InvalidInputError("non-driven native stage contains driven records")
        return result
    if set(srows) != expected_axes:
        raise InvalidInputError("native S must contain every wavelength/source/receiver exactly once")
    if set(sources) != expected_modes:
        raise InvalidInputError("native actual source axes incomplete")
    for (_, source), actual in sources.items():
        if actual != [source]:
            raise InvalidInputError("actual native source identity differs from the expected column")
    fluxes: dict[tuple[float, int, str], float] = {}
    for fields in records.get("FLUX", []):
        if len(fields) != 4:
            raise InvalidInputError("invalid native flux record")
        key = (float(fields[0]), int(fields[1]), fields[2])
        value = float(fields[3])
        if key in fluxes or not math.isfinite(value):
            raise InvalidInputError("duplicate/nonfinite native flux record")
        fluxes[key] = value
    expected_fluxes = {
        (w, s, face)
        for w in wavelengths
        for s in range(1, nports + 1)
        for face in ([f"p{k}" for k in range(1, nports + 1)] + ["open", "abs"])
    }
    if set(fluxes) != expected_fluxes:
        raise InvalidInputError("native signed flux axes incomplete")
    for wavelength in wavelengths:
        matrix = np.array(
            [
                [complex(*srows[(wavelength, source, receive)]) for source in range(1, nports + 1)]
                for receive in range(1, nports + 1)
            ]
        )
        powers = np.abs(matrix) ** 2
        residuals = []
        for source in range(1, nports + 1):
            flux = [fluxes[(wavelength, source, f"p{k}")] for k in range(1, nports + 1)]
            modal_net = powers[:, source - 1].copy()
            modal_net[source - 1] -= 1.0
            residuals.append(
                {
                    "source": source,
                    "guided_power_sum": float(np.sum(powers[:, source - 1])),
                    "max_port_flux_modal_gap": float(np.max(np.abs(np.array(flux) - modal_net))),
                    "signed_power_balance": sum(flux)
                    + fluxes[(wavelength, source, "open")]
                    + fluxes[(wavelength, source, "abs")],
                    "open_flux": fluxes[(wavelength, source, "open")],
                    "absorbed_power": fluxes[(wavelength, source, "abs")],
                }
            )
        result["s_matrices"].append([[[v.real, v.imag] for v in row] for row in matrix])
        result["diagnostics"].append(
            {
                "wavelength_nm": wavelength,
                "columns": residuals,
                "max_power_reciprocity_gap": float(np.max(np.abs(powers - powers.T))),
                "max_singular_value": float(np.linalg.svd(matrix, compute_uv=False)[0]),
            }
        )
    return result


def calibrate_native_run(receipt_path: Path | str) -> dict[str, Any]:
    """Bind raw output to an identified local generated-source execution receipt."""
    from .native_backend import verify_native_bundle

    receipt_path = Path(receipt_path).resolve()
    root = receipt_path.parent
    receipt = load_native_json(receipt_path)
    if receipt.get("status") != "completed":
        raise InvalidInputError("native calibration requires a completed receipt")
    bundle = Path(receipt["bundle"]).resolve()
    verify_native_bundle(bundle)
    manifest = (bundle / "manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != receipt["manifest_sha256"]:
        raise InvalidInputError("receipt refers to different bundle bytes")
    seen: set[str] = set()
    for artifact in receipt["artifacts"]:
        relative = artifact["path"]
        path = (root / relative).resolve()
        if root not in path.parents or relative in seen:
            raise InvalidInputError("invalid native receipt member path")
        seen.add(relative)
        raw = path.read_bytes()
        if len(raw) != artifact["bytes"] or hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
            raise InvalidInputError("native receipt member has changed")
    if not {"console.log", "NativePic.java", "NativePic.class"}.issubset(seen):
        raise InvalidInputError("native receipt does not bind source, executable and raw console")
    java_hash = hashlib.sha256((root / "NativePic.java").read_bytes()).hexdigest()
    bundle_java_hash = hashlib.sha256((bundle / "NativePic.java").read_bytes()).hexdigest()
    if java_hash != receipt["java_sha256"] or java_hash != bundle_java_hash:
        raise InvalidInputError("executed Java differs from the identified bundle source")
    class_hash = hashlib.sha256((root / "NativePic.class").read_bytes()).hexdigest()
    if class_hash != receipt.get("class_sha256"):
        raise InvalidInputError("compiled class identity differs from receipt")
    geometry = load_native_json(bundle / "geometry.json")
    config = load_native_json(bundle / "config.json")
    if receipt.get("family") != geometry["family"] or receipt.get("stage") != config["stage"]:
        raise InvalidInputError("native receipt family/stage differs from the bundle")
    result = parse_native_output((root / "console.log").read_text(encoding="utf-8", errors="replace"), geometry, config)
    result["provenance"] = {
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "manifest_sha256": receipt["manifest_sha256"],
        "java_sha256": receipt["java_sha256"],
        "source": "local native receipt; not independently authenticated experimental evidence",
    }
    return result


def native_scattering_csv(result: dict[str, Any]) -> str:
    ports = result["port_order"]
    if result.get("stage") != "solve" or not result.get("s_matrices"):
        raise InvalidInputError("native scattering export requires a complete driven result")
    if len(ports) != len(set(ports)) or not 2 <= len(ports) <= 4:
        raise InvalidInputError("invalid native export port order")
    try:
        matrix_array = np.array(result["s_matrices"], dtype=float)
    except (ValueError, TypeError, OverflowError) as error:
        raise InvalidInputError("native export requires complete finite complex S matrices") from error
    if matrix_array.shape != (len(result["wavelengths_nm"]), len(ports), len(ports), 2) or not np.all(
        np.isfinite(matrix_array)
    ):
        raise InvalidInputError("native export requires complete finite complex S matrices")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("wavelength_nm", "out_port", "in_port", "s_real", "s_imag"))
    for wavelength, matrix in zip(result["wavelengths_nm"], result["s_matrices"], strict=True):
        for receive, row in enumerate(matrix):
            for source, value in enumerate(row):
                writer.writerow((wavelength, ports[receive], ports[source], *value))
    return output.getvalue()


def compare_native_meshes(coarse: dict[str, Any], fine: dict[str, Any]) -> dict[str, Any]:
    """Compare power only: cross-model complex modal gauges need separate alignment."""
    for key in ("family", "port_order", "wavelengths_nm", "model_level", "geometry_sha256", "materials"):
        if key not in coarse or key not in fine or coarse[key] != fine[key]:
            raise InvalidInputError(f"mesh comparison {key} differs")
    try:
        a = np.array(coarse["s_matrices"], dtype=float)
        b = np.array(fine["s_matrices"], dtype=float)
    except (ValueError, TypeError, OverflowError) as error:
        raise InvalidInputError("mesh comparison requires complete finite complex S matrices") from error
    nports = len(coarse["port_order"])
    expected_shape = (len(coarse["wavelengths_nm"]), nports, nports, 2)
    if (
        a.shape != expected_shape
        or b.shape != expected_shape
        or not np.all(np.isfinite(a))
        or not np.all(np.isfinite(b))
    ):
        raise InvalidInputError("mesh comparison requires complete same-shape complex S arrays")
    difference = np.abs(np.sum(a * a, axis=-1) - np.sum(b * b, axis=-1))
    return {
        "max_absolute_power_change": float(np.max(difference)),
        "per_wavelength_max_power_change": np.max(difference, axis=(1, 2)).tolist(),
        "complex_phase_convergence": "not asserted; cross-run modal gauge is separate",
        "physics_accepted": False,
    }
