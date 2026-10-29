"""Explicit local Lumerical execution and solver-independent migration tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from .api import envelope, strict_json
from .exceptions import ExitCode
from .native_devices import load_native_json


def _emit(command: str, data: dict[str, Any], json_output: bool) -> None:
    status = data.get("status", "success")
    code = ExitCode.TIMEOUT if status == "timeout" else (
        ExitCode.EXECUTION_FAILURE
        if status in {"failed", "error", "execution_failure", "cleanup_failed"} else ExitCode.SUCCESS
    )
    click.echo(strict_json(envelope(command=command, data=data, ok=code == 0,
                                   status=status, exit_code=code) if json_output else data))
    if code:
        raise click.exceptions.Exit(code)


@click.group("lumerical")
def lumerical_group() -> None:
    """Run local optical devices and share recipes, evidence, circuits and optimization."""


@lumerical_group.command("discover")
@click.option("--install-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def discover(install_root: Path | None, json_output: bool) -> None:
    from .lumerical import discover_install

    _emit("photonic lumerical discover", discover_install(install_root), json_output)


@lumerical_group.command("plan")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--install-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def plan(request: Path, install_root: Path | None, json_output: bool) -> None:
    from .lumerical import plan_run

    _emit("photonic lumerical plan", plan_run(load_native_json(request), install_root=install_root), json_output)


@lumerical_group.command("run")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--install-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--timeout", "timeout_s", type=click.FloatRange(5, 7200), default=180.0, show_default=True)
@click.option("--threads", type=click.IntRange(1, 16), default=2, show_default=True)
@click.option("--license-server", help="Use port@host only in this run's child environment.")
@click.option("--local-license", is_flag=True,
              help="Temporarily use the existing localhost license manager; preserve system settings.")
@click.option("--json", "json_output", is_flag=True)
def run(request: Path, output: Path, install_root: Path | None,
        timeout_s: float, threads: int, license_server: str | None, local_license: bool, json_output: bool) -> None:
    from .lumerical import run_request

    _emit("photonic lumerical run", run_request(load_native_json(request), output,
          install_root=install_root, timeout_s=timeout_s, threads=threads,
          license_server=license_server, local_license=local_license), json_output)


@lumerical_group.command("import-sparameters")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--project-root", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--target-time-dependence", type=click.Choice(["exp(-iwt)", "exp(+iwt)"]))
@click.option("--json", "json_output", is_flag=True)
def import_sparameters(source: Path, output: Path, project_root: Path,
                       target_time_dependence: str | None, json_output: bool) -> None:
    from .lumerical_exchange import export_lumerical_sparameters

    _emit("photonic lumerical import-sparameters", export_lumerical_sparameters(
        source, output, project_root=project_root, target_time_dependence=target_time_dependence), json_output)


@lumerical_group.command("export-geometry")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--height-um", type=click.FloatRange(min=0, min_open=True), required=True)
@click.option("--core-index", type=click.FloatRange(min=0, min_open=True), required=True)
@click.option("--json", "json_output", is_flag=True)
def export_geometry(request: Path, output: Path, height_um: float, core_index: float, json_output: bool) -> None:
    from .lumerical_geometry import export_native_geometry

    _emit("photonic lumerical export-geometry", export_native_geometry(load_native_json(request), output,
          height_um=height_um, core_index=core_index), json_output)


@lumerical_group.command("device-export")
@click.argument("receipt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--project-root", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--passivity-tolerance", type=click.FloatRange(0, 0.05),
              help="Explicit circuit input tolerance; retains raw S and the default 1e-6 when omitted.")
@click.option("--json", "json_output", is_flag=True)
def device_export(receipt: Path, output: Path, project_root: Path,
                  passivity_tolerance: float | None, json_output: bool) -> None:
    """Export a complete, hash-verified native source sweep to existing circuit data."""
    from .lumerical.workflow import export_device_run

    _emit("photonic lumerical device-export", export_device_run(
        receipt, output, project_root=project_root, passivity_tolerance=passivity_tolerance), json_output)


@lumerical_group.command("compare-devices")
@click.argument("coarse", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("fine", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def compare_devices(coarse: Path, fine: Path, json_output: bool) -> None:
    """Compare same-device powers across mesh/PML settings; no implicit phase alignment."""
    from .lumerical.workflow import compare_device_runs

    _emit("photonic lumerical compare-devices", compare_device_runs(coarse, fine), json_output)


@lumerical_group.command("inspect-result")
@click.argument("receipt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def inspect_result(receipt: Path, json_output: bool) -> None:
    """Verify a native device receipt and return compact diagnostics without large arrays."""
    from .lumerical.inspection import inspect_device_run

    _emit("photonic lumerical inspect-result", inspect_device_run(receipt), json_output)


@lumerical_group.command("plan-benchmark")
@click.argument("family", type=click.Choice(["straight", "directional-coupler"]))
@click.option("--power-tolerance", type=click.FloatRange(0, 0.2, min_open=True), default=0.03, show_default=True)
@click.option("--json", "json_output", is_flag=True)
def plan_benchmark(family: str, power_tolerance: float, json_output: bool) -> None:
    """Freeze matching COMSOL/FDTD controls and an explicit power-comparison budget."""
    from .lumerical.parity import make_benchmark_plan

    _emit("photonic lumerical plan-benchmark",
          make_benchmark_plan(family, power_tolerance=power_tolerance), json_output)


@lumerical_group.command("compare-solvers")
@click.argument("comsol_receipt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("lumerical_receipt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--power-tolerance", type=click.FloatRange(0, 0.2, min_open=True), required=True)
@click.option("--json", "json_output", is_flag=True)
def compare_solvers(comsol_receipt: Path, lumerical_receipt: Path,
                    power_tolerance: float, json_output: bool) -> None:
    """Compare complete matched native matrices by power; no cross-solver phase fit."""
    from .lumerical.parity import compare_solver_runs

    _emit("photonic lumerical compare-solvers", compare_solver_runs(
        comsol_receipt, lumerical_receipt, power_tolerance=power_tolerance), json_output)


@lumerical_group.command("optimize-step")
@click.argument("config", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--execute", is_flag=True, help="Run the one budgeted native candidate; default writes a plan only.")
@click.option("--install-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--license-server")
@click.option("--local-license", is_flag=True)
@click.option("--threads", type=click.IntRange(1, 16), default=2, show_default=True)
@click.option("--json", "json_output", is_flag=True)
def optimization_step(config: Path, output: Path, execute: bool, install_root: Path | None,
                      license_server: str | None, local_license: bool, threads: int, json_output: bool) -> None:
    """Ask/evaluate/tell through the shared frozen OptimizationSpec and Trial contracts."""
    from .lumerical.workflow import optimize_step

    result = optimize_step(config, output, execute=execute, install_root=install_root, local_license=local_license,
                           license_server=license_server, threads=threads)
    _emit("photonic lumerical optimize-step", result, json_output)
