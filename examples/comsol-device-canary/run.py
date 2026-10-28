"""Review-first, serial COMSOL canary. Local paths stay in private run receipts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re as regex
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import numpy as np
import psutil


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def mode_definition_sha(java_bytes):
    anchor = b"  static void resumeDriven(Model m)"
    if java_bytes.count(anchor) != 1:
        raise ValueError("Unknown original Java mode-definition boundary")
    return hashlib.sha256(java_bytes.split(anchor)[0]).hexdigest()


def write(p, value):
    p.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def table(p, columns, data):
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(data)


def parse_rows(text):
    widths = {"S": 5, "POWER": 7, "SOURCE": 3, "FIELD": 10, "MODE1": 8, "MODE2": 8, "CENSUS": 4}
    rows = {k: [] for k in widths}
    for line in text.splitlines():
        for key in rows:
            prefix = f"CANARY {key} "
            if line.startswith(prefix):
                row = [float(v) for v in line[len(prefix) :].split(",")]
                if len(row) != widths[key] or not all(math.isfinite(v) for v in row):
                    raise ValueError(f"Invalid {key} width/nonfinite")
                integers = {
                    "S": (0, 1, 2),
                    "POWER": (0,),
                    "SOURCE": (0, 1),
                    "FIELD": (0,),
                    "MODE1": (0,),
                    "MODE2": (0,),
                    "CENSUS": (0, 1),
                }[key]
                if any(row[i] != int(row[i]) for i in integers):
                    raise ValueError(f"Noninteger {key} identity")
                if row[0] not in (1.0, 2.0):
                    raise ValueError(f"Unknown {key} source/port")
                if key == "S" and (row[1] not in (1.0, 2.0) or row[2] != row[0]):
                    raise ValueError("Wrong S row/source mapping")
                if key == "SOURCE" and row[0] != row[1]:
                    raise ValueError("Wrong native source identity")
                if key == "CENSUS" and not 0 <= row[1] <= 5:
                    raise ValueError("Census eigenpair index outside sampled 0..5")
                if key == "CENSUS" and any(r[:2] == row[:2] for r in rows[key]):
                    raise ValueError("Duplicate census port/eigenpair")
                rows[key].append(row)
    for key in ("POWER", "SOURCE"):
        sources = [r[0] for r in rows[key]]
        if len(sources) != len(set(sources)):
            raise ValueError(f"Duplicate {key} source")
    return rows


def stage_identity(text, stage, shape):
    return shape in ("straight", "taper") and [
        line for line in text.splitlines() if line.startswith("CANARY STAGE ")
    ] == [f"CANARY STAGE {stage} SHAPE {shape}"]


def validate_mode_evidence(folder, shape, accepted, checkpoint, original_source=None, producer=None):
    """Read-only validation; the recorded producer need not be today's parser."""
    original_source = original_source or folder / "mode_exporter.java"
    producer = producer or folder / "accepted_parser.py"
    if not original_source.is_file():
        original_source = folder.parent / "original-source.java"
    if not producer.is_file():
        producer = folder.parent / "runner-source.py"
    if not original_source.is_file() or not producer.is_file():
        raise ValueError("Missing bound selected-mode producer/source")
    prior_console = folder / "predrive_console.txt"
    mode_folder = folder
    if not prior_console.is_file():
        prior_console = folder / "console.txt"
    if (accepted.get("accepted") is not True or accepted.get("shape") != shape
        or sha(original_source) != accepted.get("original_java_sha256")
        or sha(producer) != accepted.get("parser_sha256")
        or sha(prior_console) != accepted.get("native_console_sha256")
        or sha(checkpoint) != accepted.get("selected_checkpoint_sha256")):
        raise ValueError("Mismatched accepted mode report/producer/console/checkpoint/source")
    recomputed = analyze_modes(mode_folder, shape, sha(original_source),
        console_path=prior_console, checkpoint_path=checkpoint)
    for key in ("shape", "accepted", "analytic_neff", "observations", "reflected_mode_overlaps",
                "datasets", "original_java_sha256", "native_console_sha256", "selected_checkpoint_sha256"):
        if json.loads(json.dumps(recomputed[key])) != accepted.get(key):
            raise ValueError(f"Selected-mode report differs from raw evidence: {key}")
    definition = mode_definition_sha(original_source.read_bytes())
    if accepted.get("mode_definition_sha256", definition) != definition:
        raise ValueError("Wrong accepted mode-definition hash")
    return recomputed, definition


def analyze(folder: Path, shape: str, report_name="analysis.json", output_folder=None):
    text = (folder / "console.txt").read_text(encoding="utf-8", errors="replace")
    rows = parse_rows(text)
    destination = output_folder or folder
    if report_name:
        destination.mkdir(parents=True, exist_ok=True)
    result = {
        "shape": shape,
        "execution": "pass" if text.splitlines().count("CANARY NATIVE_COMPLETED") == 1 else "fail",
        "physical_qualification": "not_established",
        "gates": {},
    }

    def gate(k, b, detail=None):
        result["gates"][k] = {"status": "pass" if b else "fail", "detail": detail}

    gate("terminal_marker", result["execution"] == "pass")
    gate("stage_shape_identity", stage_identity(text, "solve", shape))
    gate(
        "configuration",
        "CANARY MATERIAL_AUDIT_PASS" in text.splitlines()
        and any(regex.fullmatch(r"CANARY EXTERIOR_PARTITION_PASS(?: \[[\d, ]+\])?", line) for line in text.splitlines())
        and any(line in ("CANARY CONFIGURATION_PASS", "CANARY CONFIGURATION_PASS persisted_checkpoint_readback",
                         "CANARY CONFIGURATION_PASS no_mesh_no_mode_no_driven") for line in text.splitlines()),
    )
    gate(
        "mode_census",
        {(r[0], r[1]) for r in rows["CENSUS"]} == {(float(p), float(i)) for p in (1, 2) for i in range(6)},
    )
    result["gates"]["pre_driven_mode_acceptance"] = {
        "status": "blocked",
        "detail": (
            "Missing independently accepted and hash-bound selected-mode resume evidence."
        ),
    }
    accepted_path = folder / "accepted_mode_report.json"
    if accepted_path.is_file() and (folder / "input_modes.mph").is_file():
        try:
            accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
            prior, definition = validate_mode_evidence(folder, shape, accepted, folder / "input_modes.mph")
            current_source = folder.parent / "original-source.java"
            binding = json.loads((folder / "resume_binding.json").read_text(encoding="utf-8"))
            if (binding.get("accepted_mode_report_sha256") != sha(accepted_path)
                or binding.get("mode_definition_sha256") != definition
                or binding.get("selected_checkpoint_sha256") != sha(folder / "input_modes.mph")
                or binding.get("mode_exporter_original_java_sha256") != accepted["original_java_sha256"]
                or not current_source.is_file()
                or mode_definition_sha(current_source.read_bytes()) != definition
                or "CANARY RESUME_FROM_FROZEN sol1/st3" not in text.splitlines()):
                raise ValueError("Wrong report/checkpoint/mode-definition resume binding")
            gate("pre_driven_mode_acceptance", True, "Hash-bound selected-mode evidence independently recomputed")
            gate("mode_census", prior["gates"]["sampled_census"], "Inherited from hash-bound pre-driven native console")
        except Exception as ex:
            gate("pre_driven_mode_acceptance", False, str(ex))
    gate(
        "actual_source_lambda", len(rows["SOURCE"]) == 2 and rows["SOURCE"] == [[1.0, 1.0, 1550.0], [2.0, 2.0, 1550.0]]
    )
    # Wavelength is compared with tolerance rather than formatted text or filenames.
    result["gates"]["actual_source_lambda"]["status"] = (
        "pass"
        if len(rows["SOURCE"]) == 2
        and all(int(r[0]) == int(r[1]) == i + 1 and abs(r[2] - 1550) < 1e-7 for i, r in enumerate(rows["SOURCE"]))
        else "fail"
    )
    s = np.full((2, 2), complex(np.nan, np.nan))
    positions = set()
    for source, row, index, re, im in rows["S"]:
        pos = (int(row) - 1, int(source) - 1)
        if pos in positions or index != source:
            raise ValueError("Duplicate/wrong source physical S position")
        positions.add(pos)
        s[pos] = complex(re, im)
    gate("complete_physical_positions", positions == {(0, 0), (0, 1), (1, 0), (1, 1)} and bool(np.isfinite(s).all()))
    if report_name:
        table(destination / "scattering.csv", ["source", "row", "source_solution_index", "real", "imag"], rows["S"])
    if report_name:
        table(
            destination / "power.csv",
            [
                "source",
                "nonport_outward_W_per_m",
                "absorption_W_per_m",
                "port1_net_outward_W_per_m",
                "port2_net_outward_W_per_m",
                "neff1",
                "neff2",
            ],
            rows["POWER"],
        )
    power = []
    for source, flux, absorb, p1, p2, _n1, _n2 in rows["POWER"]:
        j = int(source) - 1
        powers = np.abs(s[:, j]) ** 2
        closure = 1 - float(powers.sum()) - flux - absorb
        reflection = float(powers[j])
        transmission = float(powers[1 - j])
        net_residual = p1 + p2 + flux + absorb
        power.append(
            dict(
                source=int(source),
                Pin_W_per_m=1.0,
                transmission=transmission,
                reflection=reflection,
                nonport_signed_flux_W_per_m=flux,
                absorption_W_per_m=absorb,
                closure=closure,
                independent_closed_surface_residual=net_residual,
            )
        )
        gate(
            f"power_source_{int(source)}",
            abs(closure) <= (0.01 if shape == "straight" else 0.02)
            and abs(net_residual) <= (0.01 if shape == "straight" else 0.02)
            and abs(absorb) <= 1e-8
            and transmission >= (0.98 if shape == "straight" else 0.90)
            and (shape != "straight" or reflection <= 0.01),
            power[-1],
        )
    gate("power_cardinality", len(power) == 2)
    # Every field row carries actual source and wavelength, exported by native Eval.
    for key in ("FIELD", "MODE1", "MODE2"):
        a = np.array(rows[key])
        if report_name:
            table(
                destination / f"{key.lower()}.csv",
                (
                    ["source", "wavelength_nm", "x_um", "y_um", "E2", "log10_E2", "Ez_re", "Ez_im", "Poavx", "Poavy"]
                    if key == "FIELD"
                    else ["source", "wavelength_nm", "x_um", "y_um",
                          "Ez_mode_re", "Ez_mode_im", "Hy_mode_re", "Hy_mode_im"]
                ),
                rows[key],
            )
        gate(
            f"export_{key}",
            a.ndim == 2
            and a.shape[0] > 10
            and bool(np.isfinite(a).all())
            and set(a[:, 0]) == {1.0, 2.0}
            and bool(np.all(np.abs(a[:, 1] - 1550) < 1e-7)),
        )
    gate("cross_source_mode_basis", False, "Mode comparison not completed")
    gate("pre_post_mode_basis", False, "Required pre-driven profiles missing or comparison incomplete")
    # E polar and H axial under x-reflection: Ez unchanged, Hy reverses.
    try:
        modes = []
        for key in ("MODE1", "MODE2"):
            a = np.array(rows[key])
            profiles = []
            for source in (1, 2):
                b = a[a[:, 0] == source]
                if len(b) < 11:
                    raise ValueError("Insufficient per-source modal profile")
                yy = np.unique(b[:, 3])
                profiles.append((yy, np.array([[np.mean(b[b[:, 3] == y, c]) for c in range(4, 8)] for y in yy])))
            if not np.array_equal(profiles[0][0], profiles[1][0]) or not np.allclose(
                profiles[0][1], profiles[1][1], rtol=1e-7, atol=1e-10
            ):
                raise ValueError("Port mode basis changed across source solutions")
            prior = folder / f"predrive_mode_port{key[-1]}.csv"
            if not prior.is_file():
                raise ValueError("Missing required pre-driven mode profile")
            if prior.is_file():
                old = np.loadtxt(prior, delimiter=",", skiprows=1)
                if old.ndim != 2 or old.shape[1] != 5 or not np.isfinite(old).all():
                    raise ValueError("Invalid pre-driven mode CSV")
                # CSVs are derived evidence: compare them to the bound native rows.
                prior_text = (folder / "predrive_console.txt").read_text(encoding="utf-8")
                prefix = "CANARY SELECTED_FIELD "
                raw = np.asarray([[float(v) for v in line[len(prefix):].split(",")][1:]
                    for line in prior_text.splitlines() if line.startswith(prefix)
                    and float(line[len(prefix):].split(",")[0]) == int(key[-1])])
                if old.shape != raw.shape or not np.array_equal(old, raw):
                    raise ValueError("Pre-driven CSV differs from hash-bound native field rows")
                old_y = np.unique(old[:, 0])
                old_z = np.array([[np.mean(old[old[:, 0] == y, c]) for c in range(1, 5)] for y in old_y])
                current_y, current_z = profiles[0]
                for re_col, im_col in ((0, 1), (2, 3)):
                    original = old_z[:, re_col] + 1j * old_z[:, im_col]
                    current = np.interp(old_y, current_y, current_z[:, re_col]) + 1j * np.interp(
                        old_y, current_y, current_z[:, im_col]
                    )
                    relative = np.linalg.norm(current - original) / np.linalg.norm(original)
                    if not math.isfinite(relative) or relative > 0.01:
                        raise ValueError("Same-port pre-driven mode basis not preserved")
            a = a[a[:, 0] == 1]
            yy = np.unique(a[:, 3])
            z = np.array([[np.mean(a[a[:, 3] == y, c]) for c in range(4, 8)] for y in yy])
            modes.append((yy, z[:, 0] + 1j * z[:, 1], z[:, 2] + 1j * z[:, 3]))
        gate("cross_source_mode_basis", True)
        gate("pre_post_mode_basis", True)
        y = np.linspace(-1.2, 1.2, 1001)

        def interp(mode, k):
            return np.interp(y, mode[0], mode[k].real) + 1j * np.interp(y, mode[0], mode[k].imag)

        e1, e2 = interp(modes[0], 1), interp(modes[1], 1)
        h1, h2 = interp(modes[0], 2), -interp(modes[1], 2)

        def overlap(a, b):
            return np.vdot(a, b) / np.sqrt(np.vdot(a, a).real * np.vdot(b, b).real)

        ce, ch = overlap(e1, e2), overlap(h1, h2)
        edge = max(float(max(np.abs(e1[[0, -1]])) / max(np.abs(e1))), float(max(np.abs(e2[[0, -1]])) / max(np.abs(e2))))
        # Reject complex arbitrary relative phases; do not manufacture a transformed S.
        basis = any(abs(ce - sign) <= 0.01 and abs(ch - sign) <= 0.01 for sign in (1, -1))
        basis = basis and abs(np.angle(ce / ch)) <= 0.01
        gate("mode_window_decay", edge <= 0.01, {"edge_to_peak_E_amplitude": edge})
        gate(
            "common_reflected_E_H_basis",
            basis,
            {
                "electric_overlap": [ce.real, ce.imag],
                "axial_magnetic_overlap": [ch.real, ch.imag],
                "phase_action": "none; Thetap=0 native basis retained",
            },
        )
        if basis and np.isfinite(s).all():
            reciprocity = float(np.linalg.norm(s - s.T))
            sigma = float(np.linalg.svd(s, compute_uv=False)[0])
            gate(
                "complex_diagnostics",
                reciprocity <= 0.02 and sigma <= 1.02,
                {"reciprocity_frobenius": reciprocity, "sigma_max": sigma},
            )
        else:
            result["gates"]["complex_diagnostics"] = {
                "status": "blocked",
                "detail": "Unproved common basis; raw S retained only as diagnostics",
            }
    except Exception as ex:
        result["gates"]["common_reflected_E_H_basis"] = {"status": "fail", "detail": str(ex)}
        result["gates"]["complex_diagnostics"] = {"status": "blocked"}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.tri import Triangulation

        a = np.array(rows["FIELD"])
        for j in (1, 2):
            b = a[a[:, 0] == j]
            xy, ii = np.unique(b[:, 2:4], axis=0, return_index=True)
            b = b[ii]
            triang = Triangulation(xy[:, 0], xy[:, 1])
            fig, axs = plt.subplots(2, 1, figsize=(11, 5))
            for ax, col, title in zip(axs, (4, 5), ("linear |E|²", "log10 |E|²"), strict=False):
                im = ax.tripcolor(triang, b[:, col], shading="gouraud")
                fig.colorbar(im, ax=ax)
                ax.set(
                    xlim=(0, 14),
                    ylim=(-2.5, 2.5),
                    xlabel="x (um)",
                    ylabel="y (um)",
                    title=f"{shape}, source {j}, actual 1550 nm: {title}",
                )
                xs = [0, 5, 7, 9, 14]
                hs = [0.15, 0.15, 0.15 if shape == "straight" else 0.17, 0.15, 0.15]
                ax.plot(xs, hs, "w-", lw=0.7)
                ax.plot(xs, [-x for x in hs], "w-", lw=0.7)
                ax.plot([0, 0], [-1.2, 1.2], "r-", lw=2)
                ax.plot([14, 14], [-1.2, 1.2], "r-", lw=2)
            fig.tight_layout()
            if report_name:
                fig.savefig(destination / f"field_source{j}.png", dpi=140)
            plt.close(fig)
        gate("field_views", True)
    except Exception as ex:
        gate("field_views", False, str(ex))
    result["pass"] = all(g["status"] == "pass" for g in result["gates"].values())
    if report_name:
        write(destination / report_name, result)
    return result


def analyze_modes(
    folder: Path, shape: str, original_sha: str, report_name=None, *, console_path=None, checkpoint_path=None
):
    """Pure read-only recomputation. Callers persist reports in a new output directory."""
    if report_name is not None:
        raise ValueError("analyze_modes is read-only; persist the returned report explicitly")
    console_path = console_path or folder / "console.txt"
    text = console_path.read_text(encoding="utf-8", errors="replace")
    scalar, fields, datasets = {}, {1: [], 2: []}, {}
    for line in text.splitlines():
        if line.startswith("CANARY SELECTED_DATASET "):
            tokens = [p.split("=", 1) for p in line.split()[2:]]
            if (any(len(p) != 2 or not p[1] for p in tokens)
                or len(tokens) != 4 or {p[0] for p in tokens} != {"port", "dataset", "solution", "solnum"}):
                raise ValueError("Incomplete or ambiguous selected dataset identity")
            parts = dict(tokens)
            port = int(parts["port"])
            if port in datasets or port not in (1, 2) or parts["solnum"] != "1":
                raise ValueError("Duplicate/unknown selected dataset identity")
            datasets[port] = parts
        for kind, width in (("SELECTED_SCALAR", 5), ("SELECTED_FIELD", 6)):
            prefix = f"CANARY {kind} "
            if line.startswith(prefix):
                values = [float(v) for v in line[len(prefix) :].split(",")]
                if len(values) != width or not all(math.isfinite(v) for v in values):
                    raise ValueError("Invalid selected-mode native row")
                port = values[0]
                if port not in (1.0, 2.0):
                    raise ValueError("Unknown selected port")
                if kind == "SELECTED_SCALAR":
                    if port in scalar:
                        raise ValueError("Duplicate selected scalar")
                    scalar[int(port)] = values[1:]
                else:
                    fields[int(port)].append(values[1:])
    v = 2 * math.pi / 1.55 * 0.15 * math.sqrt(2.6**2 - 1.45**2)
    lo, hi = 0.0, min(v, math.pi / 2)
    for _ in range(100):
        u = (lo + hi) / 2
        if u * math.tan(u) > math.sqrt(max(0, v * v - u * u)):
            hi = u
        else:
            lo = u
    analytic_neff = math.sqrt(2.6**2 - (u / 0.15 / (2 * math.pi / 1.55)) ** 2)
    gates = {}
    gates["terminal"] = text.splitlines().count("CANARY MODES_COMPLETED") == 1
    gates["stage_shape_identity"] = stage_identity(text, "modes", shape)
    gates["run_to_only"] = "CANARY SELECTED_RUN_TO_COMPLETED" in text.splitlines() and not any(
        x in text for x in ("CANARY SOURCE ", "CANARY DRIVEN_CHECKPOINT_SAVED", "CANARY RESUME_FROM_FROZEN")
    )
    gates["selected_identity"] = set(scalar) == set(datasets) == {1, 2} and (
        datasets.get(1, {}).get("solution") != datasets.get(2, {}).get("solution")
        and datasets.get(1, {}).get("dataset") != datasets.get(2, {}).get("dataset")
    )
    census = parse_rows(text)["CENSUS"]
    gates["sampled_census"] = {(r[0], r[1]) for r in census} == {(float(p), float(i)) for p in (1, 2) for i in range(6)}
    profiles = {}
    observations = {}
    for port in (1, 2):
        if port not in scalar or len(fields[port]) < 11:
            gates[f"port_{port}"] = False
            continue
        neff, imag, wave, power = scalar[port]
        a = np.asarray(fields[port])
        yy = np.unique(a[:, 0])
        z = np.array([[np.mean(a[a[:, 0] == y, c]) for c in range(1, 5)] for y in yy])
        electric, magnetic = z[:, 0] + 1j * z[:, 1], z[:, 2] + 1j * z[:, 3]
        peak = float(np.max(np.abs(electric)))
        edge = float(max(abs(electric[0]), abs(electric[-1])) / peak) if peak > 0 else float("inf")
        # Modern numeric port fields are outgoing: left -x has Hy=+neff/Z0*Ez.
        expected_h = (1 if port == 1 else -1) * neff / 376.730313668 * electric
        maxwell_error = float(np.linalg.norm(magnetic - expected_h) / np.linalg.norm(expected_h))
        observations[str(port)] = {
            "neff": neff,
            "imag_neff": imag,
            "wavelength_nm": wave,
            "native_outward_power_W_per_m": power,
            "edge_E_fraction": edge,
            "outgoing_Maxwell_relative_error": maxwell_error,
        }
        gates[f"port_{port}"] = (
            abs(neff - analytic_neff) <= 0.003
            and abs(imag) <= 1e-6
            and abs(wave - 1550) <= 1e-7
            and abs(power - 1) <= 0.01
            and edge <= 0.01
            and maxwell_error <= 0.02
            and len(yy) >= 11
            and abs(yy[0] + 1.2) <= 1e-6
            and abs(yy[-1] - 1.2) <= 1e-6
        )
        profiles[port] = (yy, electric, magnetic)
    overlaps = {}
    if set(profiles) == {1, 2}:
        grid = np.linspace(-1.2, 1.2, 1001)
        interpolated = {}
        for port, (yy, electric, magnetic) in profiles.items():
            interpolated[port] = tuple(
                np.interp(grid, yy, f.real) + 1j * np.interp(grid, yy, f.imag) for f in (electric, magnetic)
            )

        def overlap(a, b):
            return np.vdot(a, b) / np.sqrt(np.vdot(a, a).real * np.vdot(b, b).real)

        ce = overlap(interpolated[1][0], interpolated[2][0])
        ch = overlap(interpolated[1][1], -interpolated[2][1])
        gates["common_polar_axial_basis"] = bool(
            any(abs(ce - sign) <= 0.01 and abs(ch - sign) <= 0.01 for sign in (1, -1))
            and abs(np.angle(ce / ch)) <= 0.01
        )
        overlaps = {"electric": [ce.real, ce.imag], "axial_magnetic": [ch.real, ch.imag]}
    else:
        gates["common_polar_axial_basis"] = False
    checkpoint = checkpoint_path or folder / "selected_modes.mph"
    gates["checkpoint"] = checkpoint.is_file() and checkpoint.stat().st_size >= 1024
    gates = {name: bool(passed) for name, passed in gates.items()}
    report = {
        "schema_version": "1.0",
        "shape": shape,
        "accepted": all(gates.values()),
        "gates": gates,
        "model_level": "2D_scalar_bulk_index_surrogate",
        "analytic_neff": analytic_neff,
        "observations": observations,
        "reflected_mode_overlaps": overlaps,
        "datasets": datasets,
        "original_java_sha256": original_sha,
        "parser_sha256": sha(Path(__file__)),
        "native_console_sha256": sha(console_path),
        "selected_checkpoint_sha256": sha(checkpoint) if checkpoint.is_file() else None,
        "sampled_census_is_completeness_proof": False,
        "physical_qualification": "not_established",
    }
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--solver-root",
        type=Path,
        default=Path(os.environ["PHOTONIC_SOLVER_ROOT"]) if os.environ.get("PHOTONIC_SOLVER_ROOT") else None,
    )
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--campaign-start-epoch", type=float)
    ap.add_argument("--compile-timeout", type=float, default=90)
    ap.add_argument("--total-budget", type=float, default=600)
    ap.add_argument("--stop-after", choices=("configure", "modes", "solve"), default="configure")
    ap.add_argument("--shape", choices=("straight", "taper"), default="straight")
    ap.add_argument("--restart", type=Path)
    ap.add_argument("--mode-report", type=Path)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("Output must be new")
    if not 30 <= args.compile_timeout <= 90:
        ap.error("Compiler timeout must be within 30..90 seconds")
    if not 120 <= args.total_budget <= 1200:
        ap.error("Total native budget must be within 120..1200 seconds")
    if args.campaign_start_epoch is not None and (
        not math.isfinite(args.campaign_start_epoch) or args.campaign_start_epoch > time.time()
    ):
        ap.error("Campaign epoch must be finite and in the past")
    if args.solver_root is None:
        ap.error("Use --solver-root or PHOTONIC_SOLVER_ROOT")
    for f in ("comsolcompile.exe", "comsolbatch.exe"):
        if not (args.solver_root / "bin/win64" / f).is_file():
            ap.error("Missing official entrypoint")
    source = Path(__file__).with_name("DeviceCanary.java")
    frozen = source.read_bytes()
    source_digest = hashlib.sha256(frozen).hexdigest()
    if args.stop_after == "solve":
        if not args.restart or not args.mode_report:
            ap.error("Driven resume requires --restart and --mode-report from accepted fresh modes")
        mode_report = json.loads(args.mode_report.read_text(encoding="utf-8"))
        old_source = args.mode_report.parent.parent / "original-source.java"
        try:
            _, definition = validate_mode_evidence(args.mode_report.parent, args.shape, mode_report,
                args.restart, original_source=old_source)
            if definition != mode_definition_sha(frozen):
                raise ValueError("Mode definition changed since selected-mode solve")
        except Exception as ex:
            ap.error(f"Unknown or mismatched accepted selected-mode checkpoint: {ex}")
    args.output.mkdir(parents=True)
    plan = {
        "processors": 4,
        "concurrency": 1,
        "total_native_wall_seconds": args.total_budget,
        "repair_limit": "external campaign contract; never reset by retry",
        "sequence": [f"{args.shape}_{s}" for s in ("configure", "solve")],
        "stop_after": args.stop_after,
        "source_sha256": source_digest,
        "runner_sha256": sha(Path(__file__)),
        "will_execute": args.execute,
        "license_or_physics_proven": False,
        "public_command_shape": (
            "comsolcompile <fresh source>; comsolbatch -np 4 -prefsdir <unique> "
            "-configuration <unique> -tmpdir <unique> -inputfile <fresh class> "
            "-outputfile <fresh model> -batchlog <fresh log>"
        ),
    }
    write(args.output / "plan.json", plan)
    (args.output / "original-source.java").write_bytes(frozen)
    shutil.copy2(Path(__file__), args.output / "runner-source.py")
    review = {
        "source_sha256": source_digest,
        "review": "self_review_not_runtime_evidence",
        "fresh_original_geometry": True,
        "no_private_checkpoint": True,
        "configuration_before_mesh": True,
        "two_sources_same_model": True,
        "explicit_semantic_material_partition": True,
        "actual_dataset_and_source_labels": True,
        "independent_flux_and_absorption": True,
        "checkpoint_before_postprocess": True,
        "known_limit": (
            "Selected-mode acceptance precedes checkpoint resume; post-driven profiles are compared "
            "against the frozen selected-mode evidence and across both sources. "
            "Six-pair census is sampled, not a full-spectrum completeness proof. "
            "No PML or convergence claim."
        ),
    }
    write(args.output / "source_review.json", review)
    if not args.execute:
        print(json.dumps(plan))
        return 0

    def other_native():
        found = []
        for proc in psutil.process_iter(["pid", "name"]):
            name = (proc.info["name"] or "").lower()
            is_native = "comsol" in name
            if "java" in name:
                try:
                    is_native = "comsol" in " ".join(proc.cmdline()).lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    raise RuntimeError("Cannot exclude active Java COMSOL backend") from None
            if is_native:
                found.append(proc.pid)
        return found

    active = other_native()
    if active:
        write(
            args.output / "blocked.json",
            {"reason": "Other COMSOL processes are active; none terminated", "pids": active},
        )
        return 1
    campaign_epoch = args.campaign_start_epoch or time.time()
    started = time.monotonic() - (time.time() - campaign_epoch)
    records = []
    status = {
        "status": "running",
        "stages": records,
        "repairs": [],
        "native_budget_seconds": args.total_budget,
        "processors": 4,
        "termination": "not_needed",
        "campaign_start_epoch": campaign_epoch,
        "supervision_scope": "sampled descendants, not a Windows Job containment proof",
    }

    def save():
        status["elapsed_seconds"] = time.monotonic() - started
        write(args.output / "receipt.json", status)

    def launch(command, cwd, log, cap):
        remaining = args.total_budget - (time.monotonic() - started) - 60
        if remaining <= 0:
            raise TimeoutError("No remaining supervised native budget")
        t = time.monotonic()
        active = other_native()
        if active:
            raise RuntimeError("Other COMSOL process remains active; concurrency gate blocked")
        with log.open("w", encoding="utf-8") as out:
            p = subprocess.Popen(
                [str(x) for x in command],
                cwd=cwd,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            owned = {}
            try:
                root = psutil.Process(p.pid)
                owned[(root.pid, root.create_time())] = root
                deadline = t + min(cap, remaining)
                telemetry = []
                while p.poll() is None:
                    with suppress(psutil.NoSuchProcess):
                        for child in root.children(recursive=True):
                            owned[(child.pid, child.create_time())] = child
                    if not telemetry or time.monotonic() - t >= telemetry[-1]["elapsed"] + 5:
                        telemetry.append(
                            {
                                "elapsed": time.monotonic() - t,
                                "sampled_pids": list(proc.pid for proc in owned.values() if proc.is_running()),
                            }
                        )
                        write(cwd / "process_telemetry.json", telemetry)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Owned process exceeded bounded timeout")
                    time.sleep(0.2)
                code = p.returncode
                _, alive = psutil.wait_procs(list(owned.values()), timeout=5)
                if alive:
                    raise RuntimeError("Native parent ended with surviving sampled descendants")
            finally:
                if p.poll() is None:
                    p.kill()
                for proc in reversed(list(owned.values())):
                    with suppress(psutil.NoSuchProcess):
                        if proc.is_running():
                            proc.kill()
                p.wait(timeout=10)
                _, alive = psutil.wait_procs(list(owned.values()), timeout=10)
                status["termination"] = (
                    "sampled_owned_exit_confirmed" if not alive else "sampled_owned_exit_unconfirmed"
                )
                status["remaining_owned_pids"] = [proc.pid for proc in alive]
                save()
        return code, time.monotonic() - t

    try:
        for shape in (args.shape,):
            stages = (
                ("solve",)
                if args.stop_after == "solve"
                else (("configure",) if args.stop_after == "configure" else ("configure", "modes"))
            )
            for stage in stages:
                folder = args.output / f"{shape}_{stage}"
                folder.mkdir()
                if stage == "solve":
                    shutil.copy2(args.restart, folder / "input_modes.mph")
                    shutil.copy2(args.mode_report, folder / "accepted_mode_report.json")
                    shutil.copy2(args.mode_report.parent / "console.txt", folder / "predrive_console.txt")
                    for port in (1, 2):
                        shutil.copy2(
                            args.mode_report.parent / f"selected_mode_port{port}.csv",
                            folder / f"predrive_mode_port{port}.csv",
                        )
                    shutil.copy2(old_source, folder / "mode_exporter.java")
                    shutil.copy2(args.mode_report.parent.parent / "runner-source.py", folder / "accepted_parser.py")
                    rec_restart_hash = sha(folder / "input_modes.mph")
                    write(folder / "resume_binding.json", {
                        "accepted_mode_report_sha256": sha(folder / "accepted_mode_report.json"),
                        "selected_checkpoint_sha256": rec_restart_hash,
                        "mode_definition_sha256": definition,
                        "mode_exporter_original_java_sha256": mode_report["original_java_sha256"],
                    })
                render = frozen.decode("utf-8").replace("__STAGE__", stage).replace("__SHAPE__", shape)
                java = folder / "DeviceCanary.java"
                java.write_text(render, encoding="utf-8")
                rec = {"shape": shape, "stage": stage, "source_sha256": sha(java), "status": "started"}
                if stage == "solve":
                    rec["frozen_restart_sha256"] = rec_restart_hash
                    rec["mode_definition_sha256"] = mode_definition_sha(frozen)
                    rec["mode_exporter_original_java_sha256"] = mode_report["original_java_sha256"]
                stage_epoch = time.time()
                records.append(rec)
                save()
                for name in ("compiler_config", "compiler_workspace", "compiler_prefs", "compiler_tmp"):
                    (folder / name).mkdir()
                code, elapsed = launch(
                    [
                        args.solver_root / "bin/win64/comsolcompile.exe",
                        "-configuration",
                        (folder / "compiler_config").resolve(),
                        "-data",
                        (folder / "compiler_workspace").resolve(),
                        "-prefsdir",
                        (folder / "compiler_prefs").resolve(),
                        "-tmpdir",
                        (folder / "compiler_tmp").resolve(),
                        java.resolve(),
                    ],
                    folder,
                    folder / "compile.txt",
                    args.compile_timeout,
                )
                rec["compile"] = {"exit_code": code, "elapsed_seconds": elapsed}
                compiled = java.with_suffix(".class")
                if (
                    code
                    or not compiled.is_file()
                    or compiled.stat().st_size < 32
                    or compiled.stat().st_mtime < stage_epoch
                ):
                    raise RuntimeError("Compile failed or no fresh class")
                rec["class_sha256"] = sha(compiled)
                for name in ("prefs", "config", "tmp", "workspace"):
                    (folder / name).mkdir()
                cmd = [
                    args.solver_root / "bin/win64/comsolbatch.exe",
                    "-np",
                    "4",
                    "-prefsdir",
                    (folder / "prefs").resolve(),
                    "-configuration",
                    (folder / "config").resolve(),
                    "-data",
                    (folder / "workspace").resolve(),
                    "-tmpdir",
                    (folder / "tmp").resolve(),
                    "-inputfile",
                    compiled.resolve(),
                    "-outputfile",
                    (folder / "model.mph").resolve(),
                    "-batchlog",
                    (folder / "native.log").resolve(),
                ]
                code, elapsed = launch(cmd, folder, folder / "console.txt", 90 if stage == "configure" else 240)
                rec["batch"] = {"exit_code": code, "elapsed_seconds": elapsed}
                text = (folder / "console.txt").read_text(encoding="utf-8", errors="replace")
                expected = {
                    "configure": "CANARY CONFIGURATION_COMPLETED",
                    "modes": "CANARY MODES_COMPLETED",
                    "solve": "CANARY NATIVE_COMPLETED",
                }[stage]
                lines = text.splitlines()
                native_log = (folder / "native.log").read_text(encoding="utf-8", errors="replace")
                write(
                    folder / "native_log_summary.json",
                    {
                        "native_log_tail": native_log[-5000:],
                        "terminal_exact": lines.count(expected) == 1,
                        "stage_exact": stage_identity(text, stage, shape),
                    },
                )
                artifact = folder / ("driven_checkpoint.mph" if stage == "solve" else "configured.mph")
                if (
                    code
                    or lines.count(expected) != 1
                    or not stage_identity(text, stage, shape)
                    or not artifact.is_file()
                    or artifact.stat().st_size < 1024
                    or artifact.stat().st_mtime < stage_epoch
                ):
                    raise RuntimeError("Native internal failure or missing exact fresh artifacts/marker")
                rec["configured_sha256"] = sha(artifact)
                if stage == "configure":
                    if "CANARY MESH_COMPLETE" in text or "CANARY CENSUS" in text:
                        raise RuntimeError("Configuration unexpectedly solved")
                    rec["status"] = "pass"
                elif stage == "modes":
                    report = analyze_modes(folder, shape, source_digest)
                    write(folder / "mode_analysis.json", report)
                    for port in (1, 2):
                        prefix = "CANARY SELECTED_FIELD "
                        values = [[float(v) for v in line[len(prefix):].split(",")]
                            for line in text.splitlines() if line.startswith(prefix)]
                        table(folder / f"selected_mode_port{port}.csv",
                            ["y_um", "Ez_re", "Ez_im", "Hy_re", "Hy_im"],
                            [r[1:] for r in values if r[0] == port])
                    rec["status"] = "pass" if report["accepted"] else "fail"
                    if not report["accepted"]:
                        raise RuntimeError("Independent pre-driven selected-mode gate rejected; driven not run")
                else:
                    if not (folder / "driven_checkpoint.mph").is_file():
                        raise RuntimeError("Missing driven checkpoint")
                    result = analyze(folder, shape)
                    rec["status"] = "pass" if result["pass"] else "fail"
                    if not result["pass"]:
                        raise RuntimeError("Independent canary acceptance failed; downstream stage not run")
                print(f"{shape}/{stage}: {rec['status']}", flush=True)
                save()
        status["status"] = "pass"
        status["scope_acceptance"] = "pass"
        status["plan_acceptance"] = "blocked" if args.stop_after != "solve" else "see_analysis"
    except Exception as ex:
        status["status"] = "partial"
        status["error"] = str(ex)
        if records and records[-1]["status"] == "started":
            records[-1]["status"] = "fail"
        print(f"Stopped: {ex}", flush=True)
    finally:
        done = {(r["shape"], r["stage"]) for r in records}
        for shape in ("straight", "taper"):
            for stage in ("configure", "solve"):
                if (shape, stage) not in done:
                    records.append({"shape": shape, "stage": stage, "status": "not_run"})
        status["physical_qualification"] = "not_established"
        status["artifacts"] = [
            {"path": str(p.relative_to(args.output)), "sha256": sha(p)}
            for p in args.output.rglob("*")
            if p.is_file() and not any(t in p.parts for t in ("prefs", "config", "tmp")) and p.name != "receipt.json"
        ]
        save()
    return 0 if status["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
