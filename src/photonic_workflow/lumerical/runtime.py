"""Bounded native Lumerical operations, isolated from the calling process.

Installation discovery and planning do not import vendor code or consume licenses.
Execution creates a new hidden session and records observations without promoting
a device evidence gate. Vendor files are referenced, never copied or modified.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..exceptions import InvalidInputError, UnavailableCapabilityError

_MODE_DEFAULTS = {
    "wavelength_m": 1.55e-6,
    "width_m": 0.5e-6,
    "height_m": 0.22e-6,
    "core_index": 3.476,
    "clad_index": 1.444,
    "span_y_m": 3e-6,
    "span_z_m": 2.5e-6,
    "mesh_cells": 100,
    "trial_modes": 4,
}
_FDTD_DEFAULTS = {
    "wavelength_start_m": 1.5e-6,
    "wavelength_stop_m": 1.6e-6,
    "background_index": 1.444,
    "length_m": 6e-6,
    "span_y_m": 1e-6,
    "mesh_accuracy": 3,
    "frequency_points": 5,
    "simulation_time_s": 1.2e-12,
}
_LIMITS = [
    "Diagnostic operation; physics_accepted remains false and no gates are changed.",
    "A successful API session does not establish broadband or mesh/PML convergence.",
    "MODE, FDTD, EME, DEVICE and INTERCONNECT require separate validation.",
]


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _number(value: Any, name: str, low: float, high: float, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInputError(f"{name} must be a finite number")
    if not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise InvalidInputError(f"{name} must be {'an integer ' if integer else ''}in [{low}, {high}]")
    return int(value) if integer else float(value)


def validate_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a strict versioned request; executable fields are not accepted."""
    if not isinstance(payload, dict) or set(payload) - {"schema_version", "operation", "parameters"}:
        raise InvalidInputError("Expected only schema_version, operation and parameters")
    if payload.get("schema_version") != "1.0":
        raise InvalidInputError("Lumerical request schema_version must be 1.0")
    operation = payload.get("operation")
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        raise InvalidInputError("parameters must be an object")
    if operation == "mode-waveguide":
        if set(parameters) - _MODE_DEFAULTS.keys():
            raise InvalidInputError("Unknown MODE parameter")
        p = _MODE_DEFAULTS | parameters
        for key in ("wavelength_m", "width_m", "height_m", "span_y_m", "span_z_m"):
            p[key] = _number(p[key], key, 10e-9, 100e-6)
        for key in ("core_index", "clad_index"):
            p[key] = _number(p[key], key, 1, 10)
        p["mesh_cells"] = _number(p["mesh_cells"], "mesh_cells", 20, 800, integer=True)
        p["trial_modes"] = _number(p["trial_modes"], "trial_modes", 1, 20, integer=True)
        if p["core_index"] <= p["clad_index"]:
            raise InvalidInputError("MODE diagnostic requires core_index > clad_index")
        if p["span_y_m"] <= p["width_m"] or p["span_z_m"] <= p["height_m"]:
            raise InvalidInputError("MODE cross section must contain the core")
    elif operation == "fdtd-uniform":
        if set(parameters) - _FDTD_DEFAULTS.keys():
            raise InvalidInputError("Unknown FDTD parameter")
        p = _FDTD_DEFAULTS | parameters
        for key in ("wavelength_start_m", "wavelength_stop_m", "length_m", "span_y_m"):
            p[key] = _number(p[key], key, 100e-9, 100e-6)
        p["background_index"] = _number(p["background_index"], "background_index", 1, 5)
        p["mesh_accuracy"] = _number(p["mesh_accuracy"], "mesh_accuracy", 1, 6, integer=True)
        p["frequency_points"] = _number(p["frequency_points"], "frequency_points", 1, 101, integer=True)
        p["simulation_time_s"] = _number(p["simulation_time_s"], "simulation_time_s", 100e-15, 20e-12)
        if p["wavelength_stop_m"] <= p["wavelength_start_m"]:
            raise InvalidInputError("FDTD wavelength_stop_m must exceed wavelength_start_m")
        if p["length_m"] < 3 * p["wavelength_stop_m"] / p["background_index"]:
            raise InvalidInputError("FDTD length must span at least three medium wavelengths")
    elif operation == "geometry-readback":
        if set(parameters) - {"native_request", "height_um", "core_index"} or "native_request" not in parameters:
            raise InvalidInputError("geometry-readback requires native_request and optional height_um/core_index")
        from ..lumerical_geometry import migrate_geometry

        p = {
            "native_request": parameters["native_request"],
            "height_um": _number(parameters.get("height_um", 0.22), "height_um", 0.001, 20),
            "core_index": _number(parameters.get("core_index", 3.476), "core_index", 1, 10),
        }
        # Validate geometry before any process or license is used.
        migrate_geometry(p["native_request"], height_um=p["height_um"], core_index=p["core_index"])
    elif operation == "fdtd-device":
        from .device import validate_device_parameters

        p = validate_device_parameters(parameters)
    else:
        raise InvalidInputError("operation must be mode-waveguide, fdtd-uniform, geometry-readback or fdtd-device")
    return {"schema_version": "1.0", "operation": operation, "parameters": p}


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(value) for value in re.findall(r"\d+", str(path)))


def discover_install(root: Path | str | None = None) -> dict[str, Any]:
    """Locate parent/version/product roots without importing or executing vendor code."""
    if root is not None:
        roots = [Path(root).expanduser()]
    elif os.environ.get("PHOTONIC_LUMERICAL_ROOT"):
        roots = [Path(os.environ["PHOTONIC_LUMERICAL_ROOT"]).expanduser()]
    else:
        roots = [Path("D:/Apps/Lumerical"), Path("C:/Program Files/Lumerical"), Path("C:/Program Files/ANSYS Inc")]
    candidates: list[Path] = []
    for candidate in roots:
        candidates.extend([candidate, candidate / "Lumerical"])
        if candidate.is_dir():
            for version in sorted(candidate.glob("v*"), key=_version_key, reverse=True):
                candidates.extend([version / "Lumerical", version])
    product_root = next(
        (candidate.resolve() for candidate in candidates if (candidate / "api/python/lumapi.py").is_file()), None
    )
    if product_root is None:
        return {
            "available": False,
            "searched_roots": [str(path.absolute()) for path in roots],
            "api_imported": False,
            "license_checked": False,
            "limitations": ["No local api/python/lumapi.py found. Set --install-root or PHOTONIC_LUMERICAL_ROOT."],
        }
    version = product_root / "VERSION"
    products = {
        name: (product_root / "bin" / filename).is_file()
        for name, filename in {
            "MODE": "mode-solutions.exe",
            "FDTD": "fdtd-solutions.exe",
            "DEVICE": "device.exe",
            "INTERCONNECT": "interconnect.exe",
        }.items()
    }
    return {
        "available": True,
        "product_root": str(product_root),
        "lumapi_path": str(product_root / "api/python/lumapi.py"),
        "version": version.read_text(encoding="utf-8").strip() if version.is_file() else "unknown",
        "products_present": products,
        "engines_present": {"FDTD": (product_root / "bin/fdtd-engine.exe").is_file()},
        "api_imported": False,
        "license_checked": False,
        "limitations": ["Product executable presence does not establish API, license or solver readiness."],
    }


def plan_run(payload: dict[str, Any], *, install_root: Path | str | None = None) -> dict[str, Any]:
    request = validate_request(payload)
    model = "model.lms" if request["operation"] == "mode-waveguide" else "model.fsp"
    observation = "geometry.json" if request["operation"] == "geometry-readback" else "raw.npz"
    outputs = ["request.json", "result.json", "receipt.json", "worker.log", "progress.json", model, observation]
    if request["operation"] == "fdtd-device":
        outputs = ["request.json", "result.json", "receipt.json", "worker.log", "progress.json",
                   "geometry.json", "source_dataset.json", "sparameters.csv", "sparameters.csv.metadata.json",
                   "sparameters.csv.source.json", "source_*.fsp", "raw.npz"]
    return {
        "request": request,
        "install": discover_install(install_root),
        "product": "MODE" if request["operation"] == "mode-waveguide" else "FDTD",
        "execution": False,
        "license_checked": False,
        "physics_accepted": False,
        "concurrency": 1,
        "hidden_session": True,
        "outputs": outputs,
        "limitations": _LIMITS,
    }


def _check_output(path: Path) -> Path:
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise InvalidInputError("Lumerical output cannot traverse symlinks or junctions")
    if path.exists():
        raise InvalidInputError("Lumerical output directory must be new")
    return path


def _supervise(
    command: list[str], output: Path, timeout_s: float, *, env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        import psutil
    except ImportError as error:
        raise UnavailableCapabilityError("Native supervision requires photonic-workflow[lumerical] (psutil)") from error
    started = time.monotonic()
    owned: dict[tuple[int, float], Any] = {}
    timed_out = False
    with (output / "worker.log").open("wb") as stream:
        process = subprocess.Popen(
            command,
            cwd=output,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=env,
        )
        root = psutil.Process(process.pid)
        owned[(root.pid, root.create_time())] = root
        try:
            while process.poll() is None:
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    for child in root.children(recursive=True):
                        owned[(child.pid, child.create_time())] = child
                if time.monotonic() - started >= timeout_s:
                    timed_out = True
                    break
                time.sleep(0.1)
        finally:
            # Process objects retain creation time: psutil refuses a recycled PID.
            if timed_out or process.poll() is None:
                for child in reversed(list(owned.values())):
                    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        child.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            _, alive = psutil.wait_procs(list(owned.values()), timeout=2)
            for child in alive:
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.kill()
            _, alive = psutil.wait_procs(alive, timeout=3)
    return {
        "exit_code": process.poll(),
        "timed_out": timed_out,
        "owned_processes_exited": not alive,
        "elapsed_seconds": time.monotonic() - started,
    }


def run_request(
    payload: dict[str, Any],
    output: Path | str,
    *,
    install_root: Path | str | None = None,
    timeout_s: float = 180,
    threads: int = 2,
    license_server: str | None = None,
    local_license: bool = False,
) -> dict[str, Any]:
    """Execute one authorized fixed operation, with wall timeout and owned-process cleanup."""
    request = validate_request(payload)
    timeout_s = float(_number(timeout_s, "timeout_s", 5, 7200))
    threads = int(_number(threads, "threads", 1, 16, integer=True))
    if not isinstance(local_license, bool):
        raise InvalidInputError("local_license must be boolean")
    if local_license and license_server is not None:
        raise InvalidInputError("Use either local_license or license_server, not both")
    if license_server is not None and (
        not isinstance(license_server, str)
        or not re.fullmatch(r"[0-9]{1,5}@[A-Za-z0-9_.-]{1,253}", license_server)
        or not 1 <= int(license_server.split("@", 1)[0]) <= 65535
    ):
        raise InvalidInputError("license_server must be a port@host endpoint")
    if local_license:
        from .local_license import local_license_session

        folder = _check_output(Path(output))
        with local_license_session(install_root, folder.with_name(folder.name + "-license")) as local:
            receipt = run_request(payload, folder, install_root=install_root, timeout_s=timeout_s,
                                  threads=threads, license_server=local["endpoint"])
        receipt["local_license"] = local
        (folder / "receipt.json").write_text(_json(receipt), encoding="utf-8")
        return receipt
    install = discover_install(install_root)
    if not install["available"]:
        raise UnavailableCapabilityError("Lumerical installation not found")
    product = "MODE" if request["operation"] == "mode-waveguide" else "FDTD"
    if not install["products_present"][product]:
        raise UnavailableCapabilityError(f"{product} executable not found in the selected installation")
    if request["operation"] in {"fdtd-uniform", "fdtd-device"} and not install["engines_present"]["FDTD"]:
        raise UnavailableCapabilityError("FDTD local CPU engine is missing in the selected installation")
    folder = _check_output(Path(output))
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "request.json").write_text(_json(request), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "photonic_workflow.lumerical.worker",
        str(folder / "request.json"),
        str(folder),
        install["lumapi_path"],
        str(threads),
    ]
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "operation": request["operation"],
        "product": product,
        "started_at": datetime.now(UTC).isoformat(),
        "install": install,
        "python": sys.version,
        "python_executable": sys.executable,
        "run_directory": str(folder),
        "timeout_s": timeout_s,
        "threads": threads,
        "license_endpoint_source": "explicit-child-environment" if license_server else "existing-vendor-configuration",
        "native_execution": False,
        "worker_launched": False,
        "solve_invoked": False,
        "solve_completed": False,
        "physics_accepted": False,
        "limitations": _LIMITS,
        "producer_sha256": {
            "runtime.py": _sha(Path(__file__)),
            "worker.py": _sha(Path(__file__).with_name("worker.py")),
            "lumapi.py": _sha(Path(install["lumapi_path"])),
        },
    }
    if request["operation"] == "fdtd-device":
        for name in ("device.py", "device_geometry.py", "materials.py"):
            path = Path(__file__).with_name(name)
            if path.is_file():
                receipt["producer_sha256"][name] = _sha(path)
        package = Path(__file__).parent.parent
        for name in ("native_geometry.py", "ring_modulator.py", "recipes/materials.py", "lumerical_exchange.py"):
            receipt["producer_sha256"][name] = _sha(package / name)
    try:
        worker_env = None
        if license_server:
            worker_env = dict(os.environ, ANSYSLMD_LICENSE_FILE=license_server)
        execution = _supervise(command, folder, timeout_s, env=worker_env)
        receipt["worker_launched"] = True
        receipt["execution"] = execution
        result_path = folder / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        progress_path = folder / "progress.json"
        progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.is_file() else {}
        receipt["progress"] = progress
        receipt["native_execution"] = bool(progress.get("session_opened"))
        receipt["solve_invoked"] = bool(progress.get("solve_invoked"))
        receipt["solve_completed"] = bool(progress.get("solve_completed"))
        receipt["license_status"] = result.get("license_status", progress.get("license_status", "not_checked"))
        receipt["result"] = result
        if execution["timed_out"]:
            receipt["status"] = "timeout"
        elif execution["exit_code"] != 0 or not result.get("completed"):
            receipt["status"] = "failed"
        elif not execution["owned_processes_exited"]:
            receipt["status"] = "cleanup_failed"
        else:
            receipt["status"] = "completed"
        if receipt["status"] == "completed" and request["operation"] == "fdtd-device":
            from ..lumerical_exchange import export_lumerical_sparameters

            receipt["result"]["exchange"] = export_lumerical_sparameters(
                folder / "source_dataset.json", folder / "sparameters.csv", project_root=folder,
            )
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(error).__name__}: {error}"
    receipt["artifacts"] = {
        path.relative_to(folder).as_posix(): {"sha256": _sha(path), "bytes": path.stat().st_size}
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "receipt.json"
    }
    (folder / "receipt.json").write_text(_json(receipt), encoding="utf-8")
    return receipt
