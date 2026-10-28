"""Offline flux/quadrature audit. This module never launches a native process."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess  # noqa: F401 - Explicit hook for tests prohibiting native process launch.
from collections import Counter
from pathlib import Path

ORDERS = (2, 4, 6, 8)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _entities(value):
    result = json.loads(value)
    _require(isinstance(result, list) and result and all(type(x) is int and x > 0 for x in result),
             "Invalid entity list")
    _require(len(set(result)) == len(result), "Duplicate entity")
    return tuple(sorted(result))


def parse_audit(text, *, stage="audit", shape="straight"):
    """Parse a complete fixed-1550-nm, unit-Pin two-source diagnostic.

    Malformed/incomplete evidence raises ValueError; failed numerical gates are
    returned as false. Acceptance covers only the explicitly reported gates.
    Explicit stage selection permits replay of historical postprocess/solve logs.
    It does not authenticate the console or associate it with a checkpoint.
    """
    _require(stage in ("audit", "postprocess", "solve") and shape == "straight", "Unsupported audit identity")
    lines = text.splitlines()
    def rows(key):
        prefix = f"CANARY {key} "
        return [line[len(prefix):] for line in lines if line.startswith(prefix)]
    _require(rows("STAGE") == [f"{stage} SHAPE {shape}"], "Wrong/duplicate stage identity")
    _require(lines.count("CANARY FLUX_AUDIT_COMPLETED") == 1, "Missing/duplicate terminal marker")
    repeats = 2 if stage == "solve" else 1
    _require(lines.count("CANARY MATERIAL_AUDIT_PASS") == repeats, "Wrong material audit count")
    partition = [line for line in lines if re.fullmatch(r"CANARY EXTERIOR_PARTITION_PASS(?: \[[\d, ]+\])?", line)]
    _require(len(partition) == repeats and len(set(partition)) == 1, "Wrong exterior audit count/identity")
    _require(len(rows("FLUX_DATASET")) == 1 and re.fullmatch(r"\w+ solution=sol1", rows("FLUX_DATASET")[0]),
             "Missing/ambiguous driven dataset")

    selections = {}
    for name in ("p1", "p2", "open"):
        matches = [v[len(name) + 1:] for v in rows("BOUNDARY") if v.startswith(name + " ")]
        _require(len(matches) == repeats, f"Wrong {name} boundary count")
        sets = [_entities(v) for v in matches]
        _require(len(set(sets)) == 1, "Changed boundary identity")
        selections[name] = sets[0]
    _require(len(rows("BOUNDARY")) == 3 * repeats, "Unknown boundary selection")
    all_edges = [edge for entities in selections.values() for edge in entities]
    _require(len(set(all_edges)) == len(all_edges), "Boundary selections overlap")
    if "[" in partition[0]:
        _require(_entities(partition[0][partition[0].index("["):]) == tuple(sorted(all_edges)),
                 "Incomplete exterior partition")

    bounds = {}
    for row in rows("FLUX_SELECTION"):
        match = re.fullmatch(r"port=([12]) entities=(\[.*?\]) normal_x=(-?1) bbox_um=(\[.*\])", row)
        _require(match is not None, "Malformed port selection")
        p = int(match[1])
        _require(p not in bounds and _entities(match[2]) == selections[f"p{p}"]
                 and int(match[3]) == (-1 if p == 1 else 1), "Wrong port entities/orientation")
        box = json.loads(match[4])
        expected = [0 if p == 1 else 14] * 2 + [-1.2, 1.2]
        _require(len(box) == 4 and all(math.isfinite(x) and abs(x-y) <= 1e-6
                                      for x,y in zip(box, expected, strict=True)),
                 "Wrong/nonfinite port bounds")
        bounds[p] = box
    _require(set(bounds) == {1, 2}, "Incomplete port selections")

    def numeric(key, width, identities):
        result = {}
        for row in rows(key):
            values = [float(v) for v in row.split(",")]
            _require(len(values) == width and all(math.isfinite(v) for v in values), f"Invalid {key} width/nonfinite")
            _require(all(values[i] == int(values[i]) for i in range(identities)), f"Noninteger {key} identity")
            identity = tuple(int(v) for v in values[:identities])
            _require(identity not in result, f"Duplicate {key} identity")
            result[identity] = values[identities:]
        return result
    sources = numeric("FLUX_SOURCE", 3, 2)
    _require(set(sources) == {(1, 1), (2, 2)} and all(abs(v[0]-1550) <= 1e-7 for v in sources.values()),
             "Wrong source/wavelength identity")
    scattering = numeric("FLUX_S", 4, 2)
    pairs = {(s, p) for s in (1, 2) for p in (1, 2)}
    _require(set(scattering) == pairs, "Incomplete S grid")
    powers = numeric("FLUX_ORDER", 8, 3)
    controls = numeric("QUAD_CONTROL", 7, 3)
    grid = {(s, p, q) for s, p in pairs for q in ORDERS}
    _require(set(powers) == grid and set(controls) == grid, "Incomplete/unknown source-port-order grid")
    for s in (1, 2):
        for q in ORDERS:
            _require(powers[s,1,q][3:] == powers[s,2,q][3:], "Inconsistent source-wide open/absorption copies")

    # Actual numerical nodes must cover six evaluations at every quadrature order.
    evaluations = Counter()
    tags = set()
    for row in rows("QUAD_EVAL"):
        m = re.fullmatch(r"(quadEval\d+) selection=(\w+) dimension=([12]) "
                         r"intorderactive=true order=(\d+) entities=(\[.*\])", row)
        _require(m is not None, "Invalid quadrature readback")
        tag, sel, dim, q = m[1], m[2], int(m[3]), int(m[4])
        _require(tag not in tags and q in ORDERS and sel in ("p1", "p2", "open", "allDomains"),
                 "Duplicate/unknown quadrature node")
        tags.add(tag)
        _require(dim == (2 if sel == "allDomains" else 1), "Wrong quadrature dimension")
        entities = _entities(m[5])
        if sel not in selections:
            selections[sel] = entities
        _require(entities == selections[sel], "Wrong quadrature entities")
        evaluations[q, sel] += 1
    expected = Counter({(q, sel): count for q in ORDERS for sel, count in
                        (("open", 1), ("allDomains", 1), ("p1", 2), ("p2", 2))})
    _require(evaluations == expected, "Incomplete quadrature evaluation grid")
    coupling_rows = rows("CPL_IDENTITY")
    _require(len(coupling_rows) == 4, "Missing/duplicate coupling readback")
    if coupling_rows:
        seen = set()
        for row in coupling_rows:
            m = re.fullmatch(r"(intp1|intp2|intopen|intabs) dimension=([12]) selection=(\w+) "
                             r"entities=(\[.*?\]) method=integration", row)
            _require(m is not None, "Wrong coupling identity")
            name, dim, sel = m[1], int(m[2]), m[3]
            expected_sel = {"intp1":"p1", "intp2":"p2", "intopen":"open", "intabs":"allDomains"}[name]
            _require(name not in seen and sel == expected_sel and dim == (2 if sel == "allDomains" else 1)
                     and _entities(m[4]) == selections[sel], "Wrong coupling entities/dimension")
            seen.add(name)
        _require(len(seen) == 4, "Incomplete coupling readback")

    control_errors = {}
    for (s, p, q), (value, reference, ymin, ymax) in controls.items():
        _require(abs(ymin-bounds[p][2]) <= 1e-12 and abs(ymax-bounds[p][3]) <= 1e-12,
                 "Positive-control domain differs from port")
        exact = 1e-6 * (math.exp(30*ymax)-math.exp(30*ymin)) / 30
        _require(math.isfinite(exact) and exact > 0 and abs(reference-exact)/exact <= 1e-12,
                 "Wrong analytic positive-control reference")
        control_errors[s, p, q] = abs(value-exact)/exact
    comparisons = []
    for s, p in sorted(pairs):
        re_s, im_s = scattering[s, p]
        modal = re_s*re_s + im_s*im_s - (1 if s == p else 0)
        _require(math.isfinite(modal), "Nonfinite derived modal power")
        comparisons.append({"source": s, "port": p,
            "q6_q8_max_power_difference": max(abs(a-b) for a,b in zip(powers[s,p,6], powers[s,p,8], strict=True)),
            "poav_explicit_max_difference": max(abs(powers[s,p,q][0]-powers[s,p,q][1]) for q in ORDERS),
            "q2_control_relative_error": control_errors[s,p,2],
            "q8_control_relative_error": control_errors[s,p,8],
            "q8_mode_power": powers[s,p,8][2],
            "q8_mode_power_normalization_error": abs(powers[s,p,8][2]-1),
            "q8_flux": powers[s,p,8][0], "modal_net_flux": modal,
            "q8_flux_modal_gap": powers[s,p,8][0]-modal})
    _require(all(math.isfinite(v) for row in comparisons for v in row.values()), "Nonfinite derived comparison")
    gates = {
        "mode_power_normalized": all(c["q8_mode_power_normalization_error"] <= 1e-8 for c in comparisons),
        "quadrature_effective": all(c["q2_control_relative_error"] > 1e-8 and
                                    c["q8_control_relative_error"] < c["q2_control_relative_error"] and
                                    c["q8_control_relative_error"] <= 1e-5 for c in comparisons),
        "q6_q8_power_stable": all(c["q6_q8_max_power_difference"] <= 1e-5 for c in comparisons),
        "poav_explicit_consistent": all(c["poav_explicit_max_difference"] <= 1e-8 for c in comparisons),
        "receiving_flux_modal_gap": all(abs(c["q8_flux_modal_gap"]) <= 1e-3
                                        for c in comparisons if c["source"] != c["port"]),
    }
    post = all(gates[k] for k in ("mode_power_normalized", "quadrature_effective",
                                 "q6_q8_power_stable", "poav_explicit_consistent"))
    return {"accepted": post and gates["receiving_flux_modal_gap"], "postprocessing_pass": post,
            "flux_gap_pass": gates["receiving_flux_modal_gap"], "gates": gates, "comparisons": comparisons,
            "stage": stage, "shape": shape, "scope": "offline postprocessing and receiving flux/modal gap only",
            "physical_qualification": "not_established", "mesh_convergence": "not_established",
            "q8_mode_power_max_normalization_error": max(c["q8_mode_power_normalization_error"] for c in comparisons),
            "mode_power_scope": "q8 mode normalization readback only; independent driven Pin not established",
            "checkpoint_console_association": "not_verified", "native_execution": "not_performed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--console", type=Path, help="Parse an existing console offline; absent means dry-run")
    parser.add_argument("--stage", choices=("audit", "postprocess", "solve"), default="audit")
    args = parser.parse_args()
    # Validate the requested frozen input before output creation or any other work.
    try:
        _require(re.fullmatch(r"[0-9a-fA-F]{64}", args.checkpoint_sha256) is not None, "Invalid checkpoint SHA256")
        digest = _sha256(args.checkpoint)
        _require(digest == args.checkpoint_sha256.lower(), "Checkpoint SHA256 mismatch")
        plan = {"mode": "offline" if args.console else "dryrun", "native_execution": "not_supported",
                "checkpoint_sha256": digest, "checkpoint_console_association": "not_verified",
                "output": str(args.output), "stage": args.stage}
        if not args.console:
            print(json.dumps(plan, allow_nan=False))
            return 0
        console_bytes = args.console.read_bytes()
        report = parse_audit(console_bytes.decode("utf-8", errors="strict"), stage=args.stage)
        report["input_binding"] = {**plan, "console_sha256": hashlib.sha256(console_bytes).hexdigest(),
                                   "checkpoint_binding_scope": "specified file only; no receipt association verified"}
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "audit.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps(report, allow_nan=False))
        return 0 if report["accepted"] else 1
    except (OSError, ValueError, OverflowError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
