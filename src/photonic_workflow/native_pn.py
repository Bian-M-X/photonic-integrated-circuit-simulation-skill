"""Verified generation, serial native execution and calibration of a PN Poisson probe.

Only fixed generated Java is executable. Bundle data cannot supply commands,
source, expressions or imports. Native results verify the prescribed-depletion
Poisson approximation; they do not establish SOI drift-diffusion accuracy.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import native_backend as backend
from .exceptions import InvalidInputError
from .ring_modulator import depletion_response, poisson_reference, render_pn_java

_COMPLETION = "PN COMPLETED prescribed_depletion_poisson_not_drift_diffusion"
_INPUTS = {"NativePn.java", "pn.json"}
_ARTIFACTS = {"NativePn.java", "NativePn.class", "compile.log", "console.log", "native.log",
              "pn_checkpoint.mph", "model.mph"}


def _strict_json(raw: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise InvalidInputError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise InvalidInputError(f"Nonfinite JSON value: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _identity(parameters: dict[str, float]) -> str:
    return hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare_pn_bundle(output: str | Path, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a new data/source bundle; never compile or invoke a native process."""
    p = depletion_response(parameters)["parameters"]
    source = render_pn_java(p).encode("utf-8")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "pn.json").write_bytes(backend._canonical(p))
    (output / "NativePn.java").write_bytes(source)
    manifest = {
        "schema_version": "1.0", "family": "pn-depletion-poisson", "stage": "stationary",
        "model_level": "1d-prescribed-abrupt-depletion-poisson", "native_execution": False,
        "pn_identity": _identity(p),
        "files": {name: backend._sha(output / name) for name in sorted(_INPUTS)},
    }
    (output / "manifest.json").write_bytes(backend._canonical(manifest))
    return manifest


def verify_pn_bundle(bundle: str | Path) -> dict[str, Any]:
    """Verify exact input members and regenerate source with the trusted renderer."""
    bundle = Path(bundle)
    for name in (*sorted(_INPUTS), "manifest.json"):
        if (bundle / name).is_symlink() or not (bundle / name).is_file():
            raise InvalidInputError(f"PN bundle requires a regular file: {name}")
    manifest = _strict_json((bundle / "manifest.json").read_bytes())
    wanted = {"schema_version", "family", "stage", "model_level", "native_execution", "pn_identity", "files"}
    if (not isinstance(manifest, dict) or set(manifest) != wanted or manifest["schema_version"] != "1.0"
            or manifest["family"] != "pn-depletion-poisson" or manifest["stage"] != "stationary"
            or manifest["model_level"] != "1d-prescribed-abrupt-depletion-poisson"
            or manifest["native_execution"] is not False or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != _INPUTS):
        raise InvalidInputError("Invalid PN bundle manifest")
    for name, digest in manifest["files"].items():
        if not isinstance(digest, str) or backend._sha(bundle / name) != digest:
            raise InvalidInputError(f"PN bundle member mismatch: {name}")
    parameters = depletion_response(_strict_json((bundle / "pn.json").read_bytes()))["parameters"]
    if manifest["pn_identity"] != _identity(parameters):
        raise InvalidInputError("PN bundle identity mismatch")
    if (bundle / "NativePn.java").read_bytes() != render_pn_java(parameters).encode("utf-8"):
        raise InvalidInputError("PN source differs from trusted generation")
    return {"manifest": manifest, "parameters": parameters, "manifest_sha256": backend._sha(bundle / "manifest.json")}


def parse_pn_output(text: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse exact native records; preserve complete numerical failures as checks."""
    response = depletion_response(parameters)
    p = response["parameters"]
    records: dict[str, list[str]] = {}
    for line in text.splitlines():
        if line.startswith("PN "):
            key, _, value = line[3:].partition(" ")
            records.setdefault(key, []).append(value)
    if records.get("COMPLETED") != [_COMPLETION[13:]] or records.get("IDENTITY") != [_identity(p)]:
        raise InvalidInputError("Missing, duplicate or mismatched PN identity/completion")
    if "FAILED" in records or re.search(r"\b(?:java\.[\w.]+Exception|java\.[\w.]+Error)\b", text):
        raise InvalidInputError("Native PN output contains a fatal record")

    def one(key: str) -> str:
        values = records.get(key, [])
        if len(values) != 1:
            raise InvalidInputError(f"Missing or duplicate PN {key}")
        return values[0]

    def numbers(value: str, separator: str = ",") -> list[float]:
        try:
            items = [float(item) for item in value.split(separator)]
        except ValueError as exc:
            raise InvalidInputError("Malformed PN numeric record") from exc
        if not all(math.isfinite(item) for item in items):
            raise InvalidInputError("Nonfinite PN numeric record")
        return items

    if one("UNIT") != "um" or _strict_json(one("UNIT_CODEPOINTS")) not in ([117, 109], [181, 109], [956, 109]):
        raise InvalidInputError("Native PN geometry units are not identified as micrometres")
    dataset = one("DATASET").split()
    if len(dataset) != 3 or dataset[1] != "SOLUTION" or not all(re.fullmatch(r"[A-Za-z]\w*", value)
                                                                            for value in (dataset[0], dataset[2])):
        raise InvalidInputError("Invalid PN dataset/solution identity")
    contacts = {}
    for record in records.get("CONTACT", []):
        side, _, raw = record.partition(" ")
        entities = _strict_json(raw)
        if (side not in {"left", "right"} or side in contacts or not isinstance(entities, list)
                or len(entities) != 1 or type(entities[0]) is not int or entities[0] <= 0):
            raise InvalidInputError("Invalid PN contact identity")
        contacts[side] = entities[0]
    if set(contacts) != {"left", "right"} or contacts["left"] == contacts["right"]:
        raise InvalidInputError("Missing or overlapping PN contacts")
    readback = _strict_json(one("READBACK"))
    if (not isinstance(readback, list) or len(readback) != 16
            or any(isinstance(value, bool) or not isinstance(value, (float, int))
                   or not math.isfinite(float(value)) for value in readback)):
        raise InvalidInputError("Invalid PN readback shape or values")
    for marker, indexes in (("XP", (8,)), ("XN", (9,)), ("POTENTIAL", (11,)),
                            ("CHARGE", (12, 13, 14)), ("CAPACITANCE", (15,))):
        values = numbers(one(marker))
        if values != [readback[index] for index in indexes]:
            raise InvalidInputError(f"PN {marker} summary differs from actual readback")
    if one("FIELD") != "sampled_actual_solution_gradient":
        raise InvalidInputError("PN field sampling identity is missing")
    rows = []
    for raw in records.get("SAMPLE", []):
        fields = numbers(raw)
        if len(fields) != 5 or fields[0] != len(rows):
            raise InvalidInputError("Missing, duplicate or out-of-order PN sample")
        rows.append({"x_um": fields[1], "potential_v": fields[2],
                     "field_v_per_m": fields[3], "charge_c_per_m3": fields[4]})
    if len(rows) != 101:
        raise InvalidInputError("Native PN requires exactly 101 actual sample rows")
    expected_inputs = [p[key] for key in ("acceptor_cm3", "donor_cm3", "intrinsic_cm3", "temperature_k",
                                         "relative_permittivity", "reverse_bias_v", "p_region_width_um",
                                         "n_region_width_um")]
    if any(not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
           for actual, expected in zip(readback[:8], expected_inputs, strict=True)):
        raise InvalidInputError("Native PN parameter readback differs from requested inputs")
    positions = [-p["p_region_width_um"] + (p["p_region_width_um"] + p["n_region_width_um"]) * index / 100
                 for index in range(101)]
    for row, wanted in zip(rows, positions, strict=True):
        if abs(row["x_um"] - wanted) > 1e-8:
            raise InvalidInputError("Native PN sample coordinates or geometry scale differ from the requested grid")
    # Compare continuous potential/field at requested coordinates. Charge has
    # one-sided traces at three interfaces; it is not tested exactly on a jump.
    expected_rows = poisson_reference(p, positions)["rows"]
    potential_error = max(abs(a["potential_v"] - b["potential_v"]) for a, b in zip(rows, expected_rows, strict=True))
    field_error = max(abs(a["field_v_per_m"] - b["field_v_per_m"])
                      for a, b in zip(rows, expected_rows, strict=True))
    charged_pairs = [(a, b) for a, b in zip(rows, expected_rows, strict=True)
                     if min(abs(a["x_um"] - jump) for jump in (-response["xp_um"], 0, response["xn_um"])) > 1e-8]
    charge_error = max(abs(a["charge_c_per_m3"] - b["charge_c_per_m3"]) for a, b in charged_pairs)
    sheet = response["charge_per_area_c_per_m2"]
    checks = {
        "depletion_widths": all(math.isclose(readback[i], response[key], rel_tol=1e-7, abs_tol=1e-10)
                                for i, key in ((8, "xp_um"), (9, "xn_um"))),
        "built_in_and_total_potential": all(math.isclose(readback[i], response[key], rel_tol=1e-8, abs_tol=1e-9)
                                            for i, key in ((10, "built_in_voltage_v"), (11, "potential_drop_v"))),
        "sampled_potential": potential_error <= 1e-5,
        "sampled_field": field_error <= 10 + response["peak_field_v_per_m"] * 1e-4,
        "sampled_charge": charge_error <= 1e-5 * max(p["acceptor_cm3"], p["donor_cm3"]) * 1e6 * 1.602176634e-19,
        "positive_charge_quadrature": math.isclose(readback[12], sheet, rel_tol=1e-5, abs_tol=1e-10),
        "negative_charge_quadrature": math.isclose(readback[13], -sheet, rel_tol=1e-5, abs_tol=1e-10),
        "charge_neutrality": abs(readback[14]) <= 1e-10 + sheet * 1e-5,
        "depletion_law_capacitance": math.isclose(readback[15], response["capacitance_per_area_f_per_m2"],
                                                 rel_tol=1e-5, abs_tol=1e-10),
    }
    return {
        "schema_version": "1.0", "family": "pn-depletion-poisson", "parameters": p,
        "model_level": "1d-prescribed-abrupt-depletion-poisson", "dataset": dataset[0], "solution": dataset[2],
        "checks": checks, "benchmark_passed": all(checks.values()), "physics_accepted": False,
        "max_potential_error_v": potential_error, "max_field_error_v_per_m": field_error,
        "max_charge_density_error_c_per_m3": charge_error, "native_readback": readback, "samples": rows,
        "response": response,
        "limits": "Prescribed-charge electrostatics only; no drift-diffusion, SOI modal overlap or RF qualification.",
    }


def run_pn_bundle(
    bundle: str | Path, solver_root: str | Path | None = None, *,
    timeout_s: float = 180, compile_timeout_s: float = 60, cores: int = 4,
) -> dict[str, Any]:
    """Run one already-authorized PN probe and preserve all outcomes privately."""
    timeout_s = backend._number(timeout_s, "PN shared timeout", 15, 180)
    compile_timeout_s = backend._number(compile_timeout_s, "PN compile timeout", 5, 60)
    if isinstance(cores, bool) or not isinstance(cores, int) or not 1 <= cores <= 4:
        raise InvalidInputError("PN cores must lie in 1..4")
    verified = verify_pn_bundle(bundle)
    bundle = Path(bundle).resolve()
    root_value = solver_root or os.environ.get("PHOTONIC_SOLVER_ROOT")
    if not root_value:
        raise InvalidInputError("Provide solver_root or PHOTONIC_SOLVER_ROOT")
    executables = {kind: Path(root_value).resolve() / "bin" / "win64" / f"comsol{kind}.exe"
                   for kind in ("compile", "batch")}
    if not all(path.is_file() for path in executables.values()):
        raise InvalidInputError("Native PN compile/batch launcher was not found")
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("Native PN supervision requires photonic-workflow[comsol]") from exc
    for process in psutil.process_iter(["name"]):
        with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            if (process.info["name"] or "").lower() in {"comsol.exe", "comsolbatch.exe", "comsolcompile.exe",
                                                       "comsolmphserver.exe"}:
                raise RuntimeError("Another native COMSOL process is active; concurrency is one")
    folder = bundle / ("run-" + uuid.uuid4().hex[:12])
    folder.mkdir()
    shutil.copyfile(bundle / "NativePn.java", folder / "NativePn.java")
    receipt: dict[str, Any] = {
        "schema_version": "1.0", "family": "pn-depletion-poisson", "stage": "stationary", "status": "failed",
        "bundle": str(bundle), "run_directory": str(folder), "manifest_sha256": verified["manifest_sha256"],
        "java_sha256": backend._sha(folder / "NativePn.java"), "pn_identity": verified["manifest"]["pn_identity"],
        "launchers": {kind: {"path": str(path), "sha256": backend._sha(path)} for kind, path in executables.items()},
        "timeout_s": timeout_s, "compile_timeout_s": compile_timeout_s, "cores": cores,
        "physical_qualification": "not_established", "artifacts": [],
    }
    started = time.monotonic()
    try:
        for name in ("compiler_config", "compiler_workspace", "compiler_prefs", "compiler_tmp",
                     "config", "workspace", "prefs", "tmp"):
            (folder / name).mkdir()
        compile_command = [str(executables["compile"])]
        for flag, subdir in (("-configuration", "compiler_config"), ("-data", "compiler_workspace"),
                             ("-prefsdir", "compiler_prefs"), ("-tmpdir", "compiler_tmp")):
            compile_command.extend((flag, str(folder / subdir)))
        compile_command.append(str(folder / "NativePn.java"))
        receipt["compile"] = backend._launch(compile_command, folder, folder / "compile.log",
                                            min(timeout_s, compile_timeout_s))
        compiled = folder / "NativePn.class"
        if (receipt["compile"]["exit_code"] != 0 or receipt["compile"]["timed_out"]
                or not receipt["compile"]["owned_processes_exited"] or not compiled.is_file()
                or compiled.stat().st_size < 32):
            raise RuntimeError("PN compilation failed, missing fresh class, or compiler processes survived")
        receipt["class_sha256"] = backend._sha(compiled)
        if (verify_pn_bundle(bundle)["manifest_sha256"] != verified["manifest_sha256"]
                or backend._sha(folder / "NativePn.java") != receipt["java_sha256"]):
            raise InvalidInputError("PN input or run source changed during compilation")
        remaining = timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("PN shared wall budget was exhausted after compilation")
        command = [str(executables["batch"]), "-np", str(cores)]
        for flag, subdir in (("-configuration", "config"), ("-data", "workspace"),
                             ("-prefsdir", "prefs"), ("-tmpdir", "tmp")):
            command.extend((flag, str(folder / subdir)))
        command.extend(("-inputfile", str(compiled), "-outputfile", str(folder / "model.mph"),
                        "-batchlog", str(folder / "native.log")))
        receipt["batch"] = backend._launch(command, folder, folder / "console.log", remaining)
        text = (folder / "console.log").read_text(encoding="utf-8", errors="replace")
        if (receipt["batch"]["exit_code"] != 0 or receipt["batch"]["timed_out"]
                or not receipt["batch"]["owned_processes_exited"] or text.splitlines().count(_COMPLETION) != 1
                or any(line.startswith("PN FAILED") for line in text.splitlines())):
            raise RuntimeError("PN native process or exact completion checks failed")
        checkpoint = folder / "pn_checkpoint.mph"
        if not checkpoint.is_file() or checkpoint.stat().st_size < 256:
            raise RuntimeError("Missing nonempty PN checkpoint")
        assessment = parse_pn_output(text, verified["parameters"])
        receipt["benchmark_passed"] = assessment["benchmark_passed"]
        receipt["status"] = "completed"
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - started
        for name in sorted(_ARTIFACTS):
            path = folder / name
            if path.is_file():
                receipt["artifacts"].append({"path": name, "sha256": backend._sha(path), "bytes": path.stat().st_size})
        (folder / "receipt.json").write_bytes(backend._canonical(receipt))
    return receipt


def calibrate_pn_run(receipt_path: str | Path) -> dict[str, Any]:
    """Bind the numerical comparison to unchanged raw/source/class/checkpoint bytes."""
    receipt_path = Path(receipt_path).resolve()
    root = receipt_path.parent
    receipt = _strict_json(receipt_path.read_bytes())
    if (receipt.get("status") != "completed" or receipt.get("family") != "pn-depletion-poisson"
            or receipt.get("stage") != "stationary" or Path(receipt.get("run_directory", "")).resolve() != root):
        raise InvalidInputError("PN calibration requires a completed identified stationary receipt")
    bundle = Path(receipt["bundle"]).resolve()
    verified = verify_pn_bundle(bundle)
    if (receipt["manifest_sha256"] != verified["manifest_sha256"]
            or receipt.get("pn_identity") != verified["manifest"]["pn_identity"]):
        raise InvalidInputError("PN receipt refers to different bundle bytes")
    seen = set()
    for artifact in receipt["artifacts"]:
        name = artifact["path"]
        if name not in _ARTIFACTS or name in seen:
            raise InvalidInputError("Invalid or duplicate PN receipt artifact")
        seen.add(name)
        path = root / name
        if path.is_symlink() or path.stat().st_size != artifact["bytes"] or backend._sha(path) != artifact["sha256"]:
            raise InvalidInputError("PN receipt member has changed")
    if not {"NativePn.java", "NativePn.class", "console.log", "pn_checkpoint.mph"}.issubset(seen):
        raise InvalidInputError("PN receipt must bind source, class, console and checkpoint")
    if (backend._sha(root / "NativePn.java") != receipt["java_sha256"]
            or (root / "NativePn.java").read_bytes() != (bundle / "NativePn.java").read_bytes()
            or backend._sha(root / "NativePn.class") != receipt["class_sha256"]):
        raise InvalidInputError("PN execution source/class differs from identified bundle")
    for stage in ("compile", "batch"):
        record = receipt[stage]
        if (record.get("exit_code") != 0 or record.get("timed_out") is not False
                or record.get("owned_processes_exited") is not True):
            raise InvalidInputError("PN process did not finish successfully")
    text = (root / "console.log").read_text(encoding="utf-8", errors="replace")
    result = parse_pn_output(text, verified["parameters"])
    result["provenance"] = {
        "receipt_sha256": backend._sha(receipt_path), "manifest_sha256": verified["manifest_sha256"],
        "java_sha256": receipt["java_sha256"], "class_sha256": receipt["class_sha256"],
        "source": "Local native receipt, not independently authenticated experimental evidence.",
    }
    return result


__all__ = ["calibrate_pn_run", "parse_pn_output", "prepare_pn_bundle", "run_pn_bundle", "verify_pn_bundle"]
