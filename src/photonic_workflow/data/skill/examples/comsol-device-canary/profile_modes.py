"""Offline preparation and read-only profile-bound selected-mode evidence validation."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ("DeviceCanary.java", "taper_profile.py", "run.py", "profile_modes.py")
BUNDLE_FILES = {"profile.json", "DeviceCanary.java", "manifest.json"}
DUPLICATE_RTOL = 1e-6
DUPLICATE_ATOL = 1e-12


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def safe(path, *, directory=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Symlink or junction path rejected")
    if directory and not path.is_dir():
        raise ValueError("Missing directory")
    return path


def module(name):
    spec = importlib.util.spec_from_file_location("profile_modes_" + name, HERE / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Unknown source anchor: " + old)
    return text.replace(old, new)


AUDIT = (
    '\n  static void profileAudit(Model m){\n    marker("P10_TABLE "+Arrays.dee'
    'pToString(m.component("c").geom("g").feature("core").getDoubleMatrix("ta'
    'ble")));\n    marker("P10_DOMAINS "+Arrays.toString(m.component("c").sele'
    'ction("allDomains").entities(2)));\n    for(String t:new String[]{"port1"'
    ',"port2","sctr"})marker("P10_PHYSICS "+t+" "+Arrays.toString(m.component'
    '("c").physics("ewfd").feature(t).selection().entities(1)));\n    for(int '
    'k=1;k<=2;k++){\n      String t="port"+k;\n      marker("P10_PORT_SETTINGS '
    '"+k+" type="+m.component("c").physics("ewfd").feature(t).getString("Port'
    'Type")+" name="+m.component("c").physics("ewfd").feature(t).getString("P'
    'ortName")+" phase="+m.component("c").physics("ewfd").feature(t).getStrin'
    'g("Thetap")+" Pin="+m.component("c").physics("ewfd").feature(t).getStrin'
    'g("Pin"));\n    }\n    for(String t:new String[]{"p1","p2","open"}){\n     '
    ' m.component("c").geom("g").measureFinal().selection().geom("g",1);\n    '
    '  m.component("c").geom("g").measureFinal().selection().set(m.component('
    '"c").selection(t).entities(1));\n      marker("P10_BOUNDARY_GEOMETRY "+t+'
    '" length="+m.component("c").geom("g").measureFinal().getVolume()+" bbox='
    '"+Arrays.toString(m.component("c").geom("g").measureFinal().getBoundingB'
    'ox()));\n    }\n    marker("P10_READBACK_COMPLETED");\n  }\n'
)


def render(width, length):
    profile, configured = module("taper_profile").render_profile(width, length)
    raw = canonical(profile)
    identity = digest(raw)
    text = configured.decode("utf-8")
    text = once(text, 'STAGE="configure"', 'STAGE="modes"')
    text = once(
        text,
        'Model m=build();sequence(m);m.save("configured.mph");',
        'Model m=build();profileAudit(m);sequence(m);m.save("configured.mph");',
    )
    text = once(text, "  public static void main(String[] args)", AUDIT + "\n  public static void main(String[] args)")
    text = once(
        text,
        'marker("STAGE "+STAGE+" SHAPE "+SHAPE);',
        'marker("PROFILE_IDENTITY ' + identity + '");marker("STAGE "+STAGE+" SHAPE "+SHAPE);',
    )
    anchor = 'require(lastStore!=null&&driveStart!=null,"Cannot safely split automatic sequence");'
    text = once(
        text,
        anchor,
        anchor
        + (
            "\n    require(Arrays.asList(tags).indexOf(lastStore)<"
            'Arrays.asList(tags).indexOf(driveStart),"Selected store must precede driven start");'
        ),
    )
    # Echo the actual store/step mapping so datasets are independently tied to it.
    text = once(
        text,
        'marker("SELECTED_DATASET port="+port+',
        'marker("P10_STORE port="+port+" tag="+tag+" solution="+stored);\n      marker("SELECTED_DATASET port="+port+',
    )
    source = text.encode("utf-8")
    manifest = {
        "schema_version": "profile-modes-bundle-v1",
        "profile_identity": identity,
        "profile_sha256": digest(raw),
        "source_sha256": digest(source),
        "parameters": {"center_width_um": profile["center_width_um"], "taper_length_um": profile["taper_length_um"]},
        "dependencies": {name: digest((HERE / name).read_bytes()) for name in FILES},
        "physics_accepted": False,
        "will_execute": False,
    }
    return raw, source, manifest


def prepare_bundle(output, center_width_um=0.34, taper_length_um=4.0):
    output = safe(output)
    if os.path.lexists(output):
        raise ValueError("Output must be new")
    raw, source, manifest = render(center_width_um, taper_length_um)
    output.mkdir()
    for name, data in [("profile.json", raw), ("DeviceCanary.java", source), ("manifest.json", canonical(manifest))]:
        with (output / name).open("xb") as stream:
            stream.write(data)
    return manifest


def verify_bundle(bundle):
    bundle = safe(bundle, directory=True)
    if {p.name for p in bundle.iterdir()} != BUNDLE_FILES:
        raise ValueError("Unknown or missing bundle files")
    for name in BUNDLE_FILES:
        safe(bundle / name)
        if not (bundle / name).is_file():
            raise ValueError("Bundle member is not a file")
    supplied = json.loads((bundle / "manifest.json").read_bytes())
    parameters = supplied.get("parameters", {})
    if set(parameters) != {"center_width_um", "taper_length_um"}:
        raise ValueError("Missing or unknown parameters")
    raw, source, expected = render(**{"width": parameters["center_width_um"], "length": parameters["taper_length_um"]})
    if supplied != expected or (bundle / "manifest.json").read_bytes() != canonical(expected):
        raise ValueError("Manifest or dependency mismatch")
    if (bundle / "profile.json").read_bytes() != raw or (bundle / "DeviceCanary.java").read_bytes() != source:
        raise ValueError("Profile or Java substitution")
    return expected


def _one(lines, prefix):
    values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(values) != 1:
        raise ValueError("Missing or duplicate readback " + prefix)
    return values[0]


def _array(value):
    return ast.literal_eval(value.replace("{", "[").replace("}", "]"))


def _close(actual, expected, tol):
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_close(a, b, tol) for a, b in zip(actual, expected, strict=False))
        )
    return isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual - expected) <= tol


def readbacks(text, profile):
    lines = text.splitlines()
    table = _array(_one(lines, "CANARY P10_TABLE "))
    if not _close(table, profile["vertices_um"], 1e-8):
        raise ValueError("Actual geometry table differs from profile")
    domains = set(_array(_one(lines, "CANARY P10_DOMAINS ")))
    parts = []
    for tag, sel, area, bbox, n in [
        ("coremat", "g_core_dom", profile["core_area_um2"], profile["core_bbox_um"], "2.6"),
        ("clad", "bg", profile["background_area_um2"], [0, 14, -2.5, 2.5], "1.45"),
    ]:
        value = _one(lines, "CANARY MATERIAL " + tag + " ")
        match = re.fullmatch(
            r"selection=(\w+) entities=(\[.*?\]) area=(\S+) bbox=(\[.*?\]) n=(\[.*?\]) ki=(\[.*?\])", value
        )
        if (
            not match
            or match[1] != sel
            or not _close(float(match[3]), area, 1e-6)
            or not _close(_array(match[4]), bbox, 1e-8)
        ):
            raise ValueError("Actual material geometry mismatch")
        if (
            not _array(match[2])
            or not _array(match[5])
            or not _array(match[6])
            or not all(abs(float(x) - float(n)) < 1e-12 for x in _array(match[5]))
            or any(float(x) != 0 for x in _array(match[6]))
        ):
            raise ValueError("Material readback mismatch")
        parts.append(set(_array(match[2])))
    if parts[0] & parts[1] or parts[0] | parts[1] != domains:
        raise ValueError("Domain partition mismatch")
    selections = {tag: set(_array(_one(lines, "CANARY BOUNDARY " + tag + " "))) for tag in ("p1", "p2", "open")}
    exterior = set(_array(_one(lines, "CANARY EXTERIOR_PARTITION_PASS ")))
    if (
        any(not v for v in selections.values())
        or any(selections[a] & selections[b] for a, b in [("p1", "p2"), ("p1", "open"), ("p2", "open")])
        or set.union(*selections.values()) != exterior
    ):
        raise ValueError("Exterior partition mismatch")
    for physics, selection in [("port1", "p1"), ("port2", "p2"), ("sctr", "open")]:
        if set(_array(_one(lines, "CANARY P10_PHYSICS " + physics + " "))) != selections[selection]:
            raise ValueError("Actual physics selection mismatch")
    for port, x in [(1, 0), (2, 14)]:
        if _one(lines, f"CANARY P10_PORT_SETTINGS {port} ") != f"type=Numeric name={port} phase=0 Pin=1[W/m]":
            raise ValueError("Actual port settings mismatch")
        value = _one(lines, f"CANARY P10_BOUNDARY_GEOMETRY p{port} ")
        m = re.fullmatch(r"length=(\S+) bbox=(\[.*\])", value)
        if not m or not _close(float(m[1]), 2.4, 1e-6) or not _close(_array(m[2]), [x, x, -1.2, 1.2], 1e-7):
            raise ValueError("Actual port window mismatch")
    value = _one(lines, "CANARY P10_BOUNDARY_GEOMETRY open ")
    m = re.fullmatch(r"length=(\S+) bbox=(\[.*\])", value)
    if not m or not _close(float(m[1]), 33.2, 1e-6) or not _close(_array(m[2]), [0, 14, -2.5, 2.5], 1e-7):
        raise ValueError("Actual open boundary geometry mismatch")
    if lines.count("CANARY P10_READBACK_COMPLETED") != 1:
        raise ValueError("Incomplete readback")


def duplicate_spreads(text):
    import numpy as np

    fields = {1: [], 2: []}
    for line in text.splitlines():
        if line.startswith("CANARY SELECTED_FIELD "):
            row = [float(x) for x in line.split(" ", 2)[2].split(",")]
            if len(row) != 6 or row[0] not in (1, 2) or not all(math.isfinite(x) for x in row):
                raise ValueError("Invalid field identity")
            fields[int(row[0])].append(row[1:])
    report = {}
    for port, rows in fields.items():
        if not rows:
            raise ValueError("Missing fields")
        a = np.asarray(rows)
        values = (a[:, 1] + 1j * a[:, 2], a[:, 3] + 1j * a[:, 4])
        report[str(port)] = {}
        for name, z in zip(("E", "H"), values, strict=False):
            spread = 0.0
            for y in np.unique(a[:, 0]):
                group = z[a[:, 0] == y]
                spread = max(spread, float(np.max(np.abs(group[:, None] - group[None, :]))))
            peak = float(np.max(np.abs(z)))
            limit = DUPLICATE_ATOL + DUPLICATE_RTOL * peak
            report[str(port)][name] = {
                "max_pair_spread": spread,
                "peak": peak,
                "limit": limit,
                "duplicate_rows": len(a) - len(np.unique(a[:, 0])),
            }
            if spread > limit:
                raise ValueError("Conflicting duplicate " + name + " field traces")
    return report


def validate_evidence(bundle, run_folder, receipt):
    return _validate_evidence(bundle, run_folder, receipt, verify_bundle(bundle))


def _validate_evidence(bundle, run_folder, receipt, manifest):
    """Shared current validator; callers must authenticate the supplied manifest."""
    bundle = safe(bundle, directory=True)
    run_folder = safe(run_folder, directory=True)
    receipt = safe(receipt)
    rec = json.loads(receipt.read_bytes())
    required = {
        "schema_version": "profile-modes-native-v1",
        "status": "native_completed",
        "stage": "modes",
        "profile_identity": manifest["profile_identity"],
        "bundle_manifest_sha256": digest((bundle / "manifest.json").read_bytes()),
        "source_sha256": manifest["source_sha256"],
        "compile_exit_code": 0,
        "batch_exit_code": 0,
    }
    if any(rec.get(k) != v or isinstance(rec.get(k), bool) for k, v in required.items()):
        raise ValueError("Native receipt identity/status mismatch")
    artifacts = rec.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Missing receipt artifact membership")
    membership = {}
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("Unknown receipt artifact fields")
        name = item["path"]
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or ":" in name
            or Path(name).is_absolute()
            or any(p in ("", "..", ".") for p in name.split("/"))
            or name in membership
        ):
            raise ValueError("Unsafe or duplicate receipt artifact path")
        member = safe(run_folder / name)
        if not member.is_file() or digest(member.read_bytes()) != item["sha256"]:
            raise ValueError("Receipt artifact content mismatch")
        membership[name] = item["sha256"]
    for name, key in [
        ("DeviceCanary.java", "source_sha256"),
        ("console.txt", "console_sha256"),
        ("selected_modes.mph", "selected_checkpoint_sha256"),
    ]:
        path = safe(run_folder / name)
        if (
            not path.is_file()
            or not path.stat().st_size
            or digest(path.read_bytes()) != rec.get(key)
            or membership.get(name) != rec.get(key)
        ):
            raise ValueError("Receipt artifact mismatch: " + name)
    text = (run_folder / "console.txt").read_text(encoding="utf-8", errors="strict")
    return _assess_evidence(
        manifest,
        json.loads((bundle / "profile.json").read_bytes()),
        text,
        run_folder,
        digest(receipt.read_bytes()),
        required["bundle_manifest_sha256"],
    )


def _reject_native_failures(text):
    fatal = re.compile(
        r"^(?:CANARY\s+\S*(?:FAIL(?:ED|URE)?|ERROR|EXCEPTION)(?:\b|_)|"
        r"(?:Exception|Error)(?: in thread|:|\s)|ERROR(?:\b|:)|"
        r"(?:[\w$]+\.)+[\w$]*(?:Exception|Error)(?::|\b)|Caused by:)",
        re.IGNORECASE,
    )
    if any(fatal.search(line.strip()) for line in text.splitlines()):
        raise ValueError("Native console contains explicit failure/exception evidence")


def _assess_evidence(
    manifest, profile, text, run_folder, receipt_hash, bundle_hash, *, console_path=None, checkpoint_path=None
):
    """Recompute current mode gates from authenticated raw data, never producer code."""
    _reject_native_failures(text)
    lines = text.splitlines()
    if (
        lines.count("CANARY PROFILE_IDENTITY " + manifest["profile_identity"]) != 1
        or sum(x.startswith("CANARY PROFILE_IDENTITY ") for x in lines) != 1
    ):
        raise ValueError("Runtime profile identity mismatch")
    forbidden = (
        "CANARY DRIVEN_",
        "CANARY SOURCE ",
        "CANARY S ",
        "CANARY POWER ",
        "CANARY RESUME_FROM_FROZEN",
        "CANARY ACTUAL_DATASET ",
        "CANARY NATIVE_COMPLETED",
    )
    if any(line.startswith(forbidden) for line in lines):
        raise ValueError("Forbidden driven evidence on selected-mode route")
    readbacks(text, profile)
    spreads = duplicate_spreads(text)
    legacy = module("run").analyze_modes(
        run_folder,
        "taper",
        manifest["source_sha256"],
        console_path=console_path,
        checkpoint_path=checkpoint_path,
    )
    for port in (1, 2):
        ds = legacy["datasets"].get(port)
        if ds is None:
            ds = legacy["datasets"].get(str(port))
        store = _one(lines, f"CANARY P10_STORE port={port} ")
        m = re.fullmatch(r"tag=(\w+) solution=(\w+)", store)
        if not m or ds is None or ds["solution"] != m[2]:
            raise ValueError("Store/dataset mode source mismatch")
        binding = _one(lines, f"CANARY BMA_BINDING {port}=")
        if binding != f"{port} shift=2.2 neigs=1":
            raise ValueError("Wrong selected mode binding")
    census = module("run").parse_rows(text)["CENSUS"]
    for port in (1, 2):
        bound = [r for r in census if r[0] == port and 1.45 < r[2] < 2.6 and abs(r[3]) < 1e-6]
        if len(bound) != 1:
            raise ValueError("Sampled census bound-branch count mismatch")
    if not legacy["accepted"]:
        raise ValueError("Selected-mode numerical gates rejected: " + str(legacy["gates"]))
    return {
        "schema_version": "profile-modes-evidence-v1",
        "profile_identity": manifest["profile_identity"],
        "mode_readiness": "accepted_for_profile_scoped_reuse",
        "physics_accepted": False,
        "sampled_census_is_completeness_proof": False,
        "duplicate_spreads": spreads,
        "mode_analysis": legacy,
        "receipt_sha256": receipt_hash,
        "bundle_manifest_sha256": bundle_hash,
        "limitations": [
            "No driven solve, device performance, visual acceptance, broadband or convergence claim.",
            "Receipt integrity is hash linkage, not a cryptographic attestation of native execution.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--center-width-um", type=float, default=0.34)
    p.add_argument("--taper-length-um", type=float, default=4.0)
    p = sub.add_parser("verify")
    p.add_argument("--bundle", type=Path, required=True)
    p = sub.add_parser("validate")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--run-folder", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (
            prepare_bundle(args.output, args.center_width_um, args.taper_length_um)
            if args.command == "prepare"
            else verify_bundle(args.bundle)
            if args.command == "verify"
            else validate_evidence(args.bundle, args.run_folder, args.receipt)
        )
    except (ValueError, OSError, UnicodeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
