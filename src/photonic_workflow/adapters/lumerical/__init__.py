"""Built-in discovery/planning adapter; execution stays with the explicit CLI."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from photonic_workflow.exceptions import InvalidInputError, UnavailableCapabilityError
from photonic_workflow.lumerical.runtime import discover_install, plan_run, validate_request
from photonic_workflow.models import AvailabilityStatus, CapabilityReport, RunSpec
from photonic_workflow.recipes.artifacts import checked_recipe_output
from photonic_workflow.security import ensure_within_allowed_roots

from ..base import Adapter, AdapterPlan, PlannedFile
from ..descriptors import EXTERNAL_DESCRIPTOR_BY_NAME

DESCRIPTOR = EXTERNAL_DESCRIPTOR_BY_NAME["lumerical"]


class LumericalAdapter(Adapter):
    """Filesystem probe and fixed-operation dry plan without vendor imports.

    A registered factory makes check/plan available. It does not enable the
    generic adapter execution ABI or prove that a product license is usable.
    """

    descriptor = DESCRIPTOR

    def __init__(
        self, *, project_root: Path, runtime_directory: Path, install_root: Path,
        allowed_roots: Sequence[Path] | None = None,
    ) -> None:
        self.allowed_roots = tuple(Path(root).resolve() for root in (allowed_roots or (project_root,)))
        self.project_root = ensure_within_allowed_roots(Path(project_root), self.allowed_roots)
        self.install_root = ensure_within_allowed_roots(Path(install_root), self.allowed_roots)
        runtime = Path(runtime_directory)
        runtime = runtime if runtime.is_absolute() else self.project_root / runtime
        request, _ = checked_recipe_output(self.project_root, runtime / "request.json")
        self.runtime_directory = ensure_within_allowed_roots(request.parent, self.allowed_roots)
        if self.runtime_directory == self.project_root:
            raise InvalidInputError("runtime_directory must be isolated below the project root")

    def _discover(self) -> dict:
        # Match the shared discovery candidates, checking linked metadata before
        # the filesystem probe can read through an installation alias.
        candidates = [self.install_root, self.install_root / "Lumerical"]
        if self.install_root.is_dir():
            for version in self.install_root.glob("v*"):
                candidates.extend((version / "Lumerical", version))
        for candidate in candidates:
            for relative in ("api/python/lumapi.py", "VERSION", "bin/mode-solutions.exe",
                             "bin/fdtd-solutions.exe", "bin/device.exe", "bin/interconnect.exe",
                             "bin/fdtd-engine.exe"):
                ensure_within_allowed_roots(candidate / relative, self.allowed_roots)
        return discover_install(self.install_root)

    def check(self) -> CapabilityReport:
        observed = self._discover()
        present = observed["available"] is True
        availability = AvailabilityStatus.UNVERIFIED if present else AvailabilityStatus.UNAVAILABLE
        products = observed.get("products_present", {})
        return CapabilityReport(
            stable_id="capability:lumerical", name="Ansys Lumerical local planning",
            source="allowlisted local filesystem probe; no vendor code or license checkout",
            status=availability.value, validity="unknown", capability="lumerical",
            implementation=self.descriptor.implementation, availability=availability,
            version=observed.get("version"),
            features={"installation_files_present": present, "api_imported": False,
                      "license_checked": False, "session_started": False,
                      "generic_execution_enabled": False,
                      **{f"{name.lower()}_executable_present": products.get(name, False)
                         for name in ("MODE", "FDTD", "DEVICE", "INTERCONNECT")}},
            reasons=["File discovery does not establish API, license or solver availability.",
                     "Generic adapter supports check/plan only; licensed execution uses photonic lumerical run."],
            probe_method="filesystem-only discovery of an explicitly configured installation root",
        )

    def plan(self, run_spec: RunSpec) -> AdapterPlan:
        if not isinstance(run_spec, RunSpec) or run_spec.adapter != self.descriptor.adapter:
            raise InvalidInputError("LumericalAdapter requires a RunSpec selecting adapter='lumerical'")
        if not run_spec.dry_run:
            raise UnavailableCapabilityError("Generic Lumerical adapter is plan-only; use dry_run=true")
        if run_spec.worker_count != 1:
            raise InvalidInputError("Lumerical adapter planning supports exactly one serial worker")
        if set(run_spec.inputs) != {"request", "threads"}:
            raise InvalidInputError("Lumerical RunSpec inputs require exactly request and threads")
        threads = run_spec.inputs["threads"]
        if type(threads) is not int or not 1 <= threads <= 16:
            raise InvalidInputError("Lumerical threads must be an integer in [1, 16]")
        if not 5 <= run_spec.timeout_s <= 7200:
            raise InvalidInputError("Lumerical timeout_s must be in [5, 7200]")
        request = validate_request(run_spec.inputs["request"])
        if run_spec.operation != request["operation"]:
            raise InvalidInputError("RunSpec operation must match the fixed Lumerical request operation")
        observed = self._discover()
        shared_plan = plan_run(request, install_root=self.install_root)
        request_file, _ = checked_recipe_output(self.project_root, self.runtime_directory / "request.json")
        native = self.runtime_directory / "native"
        if request_file.exists() or native.exists():
            raise InvalidInputError("Lumerical planned request/native output must be new")
        expected = [native / name for name in shared_plan["outputs"] if name != "source_*.fsp"]
        if request["operation"] == "fdtd-device":
            from photonic_workflow.lumerical.device_geometry import build_device_geometry

            geometry = build_device_geometry(
                request["parameters"]["family"], request["parameters"]["geometry_parameters"],
            )
            expected.extend(native / f"source-{index + 1:02d}.fsp" for index in range(len(geometry["ports"])))
        for raw in run_spec.expected_artifacts:
            expected.append(checked_recipe_output(native, Path(raw))[0])
        for path in expected:
            checked_recipe_output(self.project_root, path)
        command = (sys.executable, "-B", "-m", "photonic_workflow.cli", "lumerical", "run", str(request_file),
                   "--output", str(native), "--install-root", str(self.install_root),
                   "--timeout", str(run_spec.timeout_s), "--threads", str(threads), "--json")
        return AdapterPlan(
            adapter=self.descriptor.adapter, operation=run_spec.operation, dry_run=True,
            command=command, working_directory=self.runtime_directory, timeout_s=run_spec.timeout_s,
            expected_artifacts=tuple(dict.fromkeys(expected)),
            generated_files=(PlannedFile(request_file, json.dumps(request, indent=2, allow_nan=False) + "\n",
                                         "application/json"),),
            environment=(("PYTHONPATH", str(Path(__file__).resolve().parents[3])),),
            implementation=self.descriptor.implementation,
            availability=AvailabilityStatus.UNVERIFIED if observed["available"] else AvailabilityStatus.UNAVAILABLE,
            reasons=("Dry plan only: no files, vendor imports, sessions or license checkouts were created.",
                     "Execution remains unavailable through the generic adapter and MCP.",
                     "Review the explicit CLI plan and local-license options before a licensed run."),
            sensitive_command_indexes=(6, 8, 10), sensitive_environment_keys=("PYTHONPATH",),
        )


__all__ = ["DESCRIPTOR", "LumericalAdapter"]
