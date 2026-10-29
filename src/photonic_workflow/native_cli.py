"""Explicit local native solver commands, separate from the plan-only MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from .api import envelope, strict_json
from .exceptions import UnavailableCapabilityError
from .models.io import atomic_create_text
from .native_devices import (
    calibrate_native_run,
    compare_native_meshes,
    load_native_json,
    native_catalog,
    native_request,
    native_scattering_csv,
)


def _emit(command: str, data: dict[str, Any], json_output: bool, *, ok: bool = True) -> None:
    click.echo(
        strict_json(
            envelope(
                command=command,
                data=data,
                ok=ok,
                status="success" if ok else "execution_failure",
                exit_code=0 if ok else 5,
            )
            if json_output
            else data
        )
    )
    if not ok:
        raise click.exceptions.Exit(5)


@click.group("native")
def native_group() -> None:
    """Prepare, explicitly run and inspect fixed local COMSOL device models."""


@native_group.command("list")
@click.option("--json", "json_output", is_flag=True)
def list_native(json_output: bool) -> None:
    _emit("photonic native list", native_catalog(), json_output)


@native_group.command("prepare")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--json", "json_output", is_flag=True)
def prepare_native(request: Path, output: Path, json_output: bool) -> None:
    from .native_backend import prepare_native_bundle

    geometry, config = native_request(load_native_json(request))
    manifest = prepare_native_bundle(output, geometry, config)
    _emit("photonic native prepare", {"bundle": str(output.resolve()), "manifest": manifest}, json_output)


@native_group.command("verify")
@click.argument("bundle", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def verify_native(bundle: Path, json_output: bool) -> None:
    from .native_backend import verify_native_bundle

    result = verify_native_bundle(bundle)
    _emit(
        "photonic native verify",
        {
            "manifest_sha256": result["manifest_sha256"],
            "family": result["geometry"]["family"],
            "stage": result["config"]["stage"],
            "native_execution": False,
        },
        json_output,
    )


@native_group.command("run")
@click.argument("bundle", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--solver-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--timeout", "timeout_s", type=click.FloatRange(15, 7200), default=600.0, show_default=True)
@click.option("--cores", type=click.IntRange(1, 16), default=4, show_default=True)
@click.option("--json", "json_output", is_flag=True)
def run_native(bundle: Path, solver_root: Path | None, timeout_s: float, cores: int, json_output: bool) -> None:
    from .native_backend import run_native_bundle

    try:
        receipt = run_native_bundle(bundle, solver_root, timeout_s=timeout_s, cores=cores)
    except RuntimeError as error:
        raise UnavailableCapabilityError(str(error)) from error
    _emit(
        "photonic native run",
        {
            "status": receipt["status"],
            "stage": receipt["stage"],
            "family": receipt["family"],
            "receipt": str(Path(receipt["run_directory"]) / "receipt.json"),
            "elapsed_seconds": receipt["elapsed_seconds"],
            "error": receipt.get("error"),
            "native_execution": True,
            "physics_accepted": False,
        },
        json_output,
        ok=receipt["status"] == "completed",
    )


@native_group.command("calibrate")
@click.argument("receipt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--csv-output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def calibrate_native(receipt: Path, output: Path | None, csv_output: Path | None, json_output: bool) -> None:
    result = calibrate_native_run(receipt)
    if csv_output is not None:
        atomic_create_text(csv_output, native_scattering_csv(result))
    if output is not None:
        atomic_create_text(output, strict_json(result) + "\n")
    _emit("photonic native calibrate", result, json_output)


@native_group.command("compare")
@click.argument("coarse", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("fine", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def compare_native(coarse: Path, fine: Path, json_output: bool) -> None:
    _emit(
        "photonic native compare", compare_native_meshes(load_native_json(coarse), load_native_json(fine)), json_output
    )


@native_group.command("pn-response")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def pn_response(request: Path, json_output: bool) -> None:
    from .ring_modulator import depletion_response

    _emit("photonic native pn-response", depletion_response(load_native_json(request)), json_output)


@native_group.command("pn-prepare")
@click.argument("request", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--json", "json_output", is_flag=True)
def pn_prepare(request: Path, output: Path, json_output: bool) -> None:
    from .native_pn import prepare_pn_bundle

    _emit("photonic native pn-prepare", prepare_pn_bundle(output, load_native_json(request)), json_output)


@native_group.command("pn-run")
@click.argument("bundle", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--solver-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--timeout", "timeout_s", type=click.FloatRange(15, 180), default=180.0, show_default=True)
@click.option("--cores", type=click.IntRange(1, 4), default=4, show_default=True)
@click.option("--json", "json_output", is_flag=True)
def pn_run(bundle: Path, solver_root: Path | None, timeout_s: float, cores: int, json_output: bool) -> None:
    from .native_pn import run_pn_bundle

    try:
        receipt = run_pn_bundle(bundle, solver_root, timeout_s=timeout_s, cores=cores)
    except RuntimeError as error:
        raise UnavailableCapabilityError(str(error)) from error
    _emit("photonic native pn-run", receipt, json_output, ok=receipt["status"] == "completed")


@native_group.command("pn-calibrate")
@click.argument("receipt", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
def pn_calibrate(receipt: Path, json_output: bool) -> None:
    from .native_pn import calibrate_pn_run

    _emit("photonic native pn-calibrate", calibrate_pn_run(receipt), json_output)
