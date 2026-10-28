"""Offline profile-bound driven preparation and diagnostic checks; no native execution.

Producer snapshots are authenticated DATA, never imported or executed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ("DeviceCanary.java", "taper_profile.py", "run.py", "profile_modes.py", "profile_driven.py")
BUNDLE_FILES = {"profile.json", "DeviceCanary.java", "input_modes.mph", "mode_origin.json", "manifest.json"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def modes():
    spec = importlib.util.spec_from_file_location("trusted_profile_modes", HERE / "profile_modes.py")
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def dependencies():
    return {name: digest((HERE / name).read_bytes()) for name in FILES}


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def decoded(value):
    if not isinstance(value, str):
        raise ValueError("Expected encoded artifact bytes")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid encoded artifact bytes") from exc


def artifact_membership(rec):
    artifacts = rec.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Missing artifact membership")
    result = {}
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("Invalid artifact fields")
        name, sha = item["path"], item["sha256"]
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or ":" in name
            or Path(name).is_absolute()
            or any(x in ("", ".", "..") for x in name.split("/"))
            or name in result
            or not isinstance(sha, str)
            or not re.fullmatch("[0-9a-f]{64}", sha)
        ):
            raise ValueError("Unsafe or duplicate artifact path/hash")
        result[name] = sha
    return result


class _Console:
    """Read interface consumed by the current trusted selected-mode analyzer."""

    def __init__(self, raw):
        self.raw = raw

    def read_bytes(self):
        return self.raw

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.raw.decode(encoding, errors)


def _origin_check(origin, checkpoint):
    helper = modes()
    if not isinstance(origin, dict) or set(origin) != {
        "schema_version",
        "mode_manifest",
        "mode_receipt",
        "mode_console",
        "producer_manifest",
        "producer_files",
        "historical",
        "validator_dependencies",
    }:
        raise ValueError("Unknown or missing origin fields")
    if origin["schema_version"] != "profile-driven-mode-origin-v1":
        raise ValueError("Unknown mode origin schema")
    if origin["validator_dependencies"] != dependencies():
        raise ValueError("Current validator dependency mismatch")
    manifest_raw = decoded(origin["mode_manifest"])
    receipt_raw = decoded(origin["mode_receipt"])
    console_raw = decoded(origin["mode_console"])
    manifest, receipt = json.loads(manifest_raw), json.loads(receipt_raw)
    if not isinstance(manifest, dict) or not isinstance(receipt, dict):
        raise ValueError("Mode manifest/receipt must be objects")
    params = manifest.get("parameters", {})
    if set(params) != {"center_width_um", "taper_length_um"}:
        raise ValueError("Unknown mode parameters")
    profile_raw, source, expected = helper.render(params["center_width_um"], params["taper_length_um"])
    # Only dependency identity may differ. Profile and native Java must be
    # independently reproducible with today's trusted generator, exactly.
    expected["dependencies"] = manifest.get("dependencies")
    if manifest != expected or manifest_raw != canonical(manifest):
        raise ValueError("Mode source/profile cannot be reproduced exactly")
    if origin["historical"] is True:
        producer_raw = decoded(origin["producer_manifest"])
        producer = json.loads(producer_raw)
        files = origin["producer_files"]
        if (
            not isinstance(producer, dict)
            or not isinstance(files, dict)
            or set(producer) != set(files)
            or not set(helper.FILES).issubset(producer)
            or any(
                not isinstance(k, str) or k in ("", ".", "..") or Path(k).name != k or ":" in k or "\\" in k
                for k in producer
            )
        ):
            raise ValueError("Invalid frozen producer census")
        if any(digest(decoded(files[name])) != sha for name, sha in producer.items()):
            raise ValueError("Frozen producer bytes do not match manifest")
        if manifest["dependencies"] != {name: producer[name] for name in helper.FILES}:
            raise ValueError("Producer dependency identity mismatch")
        if receipt.get("helper_sourcecopy_manifest_sha256") != digest(producer_raw):
            raise ValueError("Original receipt does not authenticate producer manifest")
        if artifact_membership(receipt).get("sourcecopy_manifest.json") != digest(producer_raw):
            raise ValueError("Producer manifest absent from original receipt")
    elif origin["historical"] is False:
        if origin["producer_manifest"] is not None or origin["producer_files"] != {}:
            raise ValueError("Unexpected producer snapshot")
        if manifest["dependencies"] != {name: dependencies()[name] for name in helper.FILES}:
            raise ValueError("Mode dependency mismatch; explicit historical snapshot required")
    else:
        raise ValueError("Historical flag must be boolean")
    required = {
        "schema_version": "profile-modes-native-v1",
        "status": "native_completed",
        "stage": "modes",
        "profile_identity": manifest["profile_identity"],
        "source_sha256": digest(source),
        "bundle_manifest_sha256": digest(manifest_raw),
        "console_sha256": digest(console_raw),
        "selected_checkpoint_sha256": digest(checkpoint.read_bytes()),
        "compile_exit_code": 0,
        "batch_exit_code": 0,
    }
    if any(receipt.get(k) != v or isinstance(receipt.get(k), bool) for k, v in required.items()):
        raise ValueError("Mode receipt identity/status/hash mismatch")
    members = artifact_membership(receipt)
    for name, key in (
        ("DeviceCanary.java", "source_sha256"),
        ("console.txt", "console_sha256"),
        ("selected_modes.mph", "selected_checkpoint_sha256"),
    ):
        if members.get(name) != required[key]:
            raise ValueError("Mode receipt missing required artifact")
    report = helper._assess_evidence(
        manifest,
        json.loads(profile_raw),
        console_raw.decode("utf-8"),
        checkpoint.parent,
        digest(receipt_raw),
        digest(manifest_raw),
        console_path=_Console(console_raw),
        checkpoint_path=checkpoint,
    )
    return profile_raw, source, report


def validate_mode_origin(mode_bundle, mode_run_folder, mode_receipt, *, producer_snapshot=None, producer_manifest=None):
    """Authenticate original artifacts; historical producer Python stays data.

    Every original receipt artifact is checked here. Bundles retain the raw
    selected-mode console, receipt and producer bytes needed to recompute the
    current mode criteria without the original run directory.
    """
    helper = modes()
    bundle = helper.safe(mode_bundle, directory=True)
    run = helper.safe(mode_run_folder, directory=True)
    receipt_path = helper.safe(mode_receipt)
    if {p.name for p in bundle.iterdir()} != helper.BUNDLE_FILES:
        raise ValueError("Unknown or missing mode bundle files")
    for name in helper.BUNDLE_FILES:
        helper.safe(bundle / name)
    manifest_raw = (bundle / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    if (producer_snapshot is None) != (producer_manifest is None):
        raise ValueError("Historical snapshot and producer manifest must be supplied together")
    historical = producer_snapshot is not None
    origin = {
        "schema_version": "profile-driven-mode-origin-v1",
        "mode_manifest": encoded(manifest_raw),
        "mode_receipt": encoded(receipt_path.read_bytes()),
        "mode_console": encoded(helper.safe(run / "console.txt").read_bytes()),
        "producer_manifest": None,
        "producer_files": {},
        "historical": historical,
        "validator_dependencies": dependencies(),
    }
    if historical:
        snapshot = helper.safe(producer_snapshot, directory=True)
        producer_raw = helper.safe(producer_manifest).read_bytes()
        producer = json.loads(producer_raw)
        if not isinstance(producer, dict):
            raise ValueError("Producer manifest must be an object")
        for name in producer:
            if (
                not isinstance(name, str)
                or name in ("", ".", "..")
                or Path(name).name != name
                or ":" in name
                or "\\" in name
            ):
                raise ValueError("Unsafe producer filename")
        if {p.name for p in snapshot.iterdir()} != set(producer):
            raise ValueError("Producer snapshot census mismatch")
        origin["producer_manifest"] = encoded(producer_raw)
        origin["producer_files"] = {name: encoded(helper.safe(snapshot / name).read_bytes()) for name in producer}
    # Keep the public mode verifier strict. This explicit route proves the
    # historical manifest independently, then reuses today's numerical checks.
    profile_raw, source, report = _origin_check(origin, helper.safe(run / "selected_modes.mph"))
    if (bundle / "profile.json").read_bytes() != profile_raw or (bundle / "DeviceCanary.java").read_bytes() != source:
        raise ValueError("Original mode bundle substitution")
    helper._validate_evidence(bundle, run, receipt_path, manifest)
    return origin, report


def _stores(origin):
    helper = modes()
    lines = decoded(origin["mode_console"]).decode("utf-8").splitlines()
    stores = []
    for port in (1, 2):
        value = helper._one(lines, f"CANARY P10_STORE port={port} ")
        match = re.fullmatch(r"tag=(\w+) solution=(\w+)", value)
        dataset = helper._one(lines, f"CANARY SELECTED_DATASET port={port} ")
        ds = re.fullmatch(r"dataset=(\w+) solution=(\w+) solnum=1", dataset)
        if not match or not ds or match[2] != ds[2]:
            raise ValueError("Invalid selected store identity")
        stores.append((match[1], match[2], ds[1]))
    return stores


def _sequence(origin):
    helper = modes()
    lines = decoded(origin["mode_console"]).decode("utf-8").splitlines()
    match = re.fullmatch(r"(\w+)/(\w+) future_driven_start=(\w+)", helper._one(lines, "CANARY RUN_TO_SELECTED "))
    if not match or match[2] != _stores(origin)[-1][0]:
        raise ValueError("Invalid frozen selected/driven sequence")
    return match[1], match[2], match[3]


def render(profile_raw, mode_source, origin, checkpoint_hash):
    helper = modes()
    profile = json.loads(profile_raw)
    identity = digest(canonical(origin))
    text = helper.once(mode_source.decode("utf-8"), 'STAGE="modes"', 'STAGE="solve"')
    text = helper.once(text, 'marker("PROFILE_IDENTITY ' + digest(profile_raw) + '");', "")
    text = helper.once(
        text,
        "    auditDomains(m);auditBoundary(m);",
        "    // Profile, materials, ports and stores were asserted before resumeDriven.",
    )
    table = json.dumps(profile["vertices_um"], separators=(",", ":")).replace("[", "{").replace("]", "}")
    store_java = (
        "new String[][]{" + ",".join("{" + ",".join('"' + v + '"' for v in row) + "}" for row in _stores(origin)) + "}"
    )
    sequence_java = "new String[]{" + ",".join('"' + v + '"' for v in _sequence(origin)) + "}"
    audit = (
        """
  static final String[][] FROZEN_STORES=__STORES__;
  static final String[] FROZEN_SEQUENCE=__SEQUENCE__;
  static void profileDrivenAudit(Model m){
    auditDomains(m);auditBoundary(m);profileAudit(m);
    double[][] expected=__TABLE__, actual=m.component("c").geom("g").feature("core").getDoubleMatrix("table");
    require(actual.length==expected.length,"Persisted profile vertex count");
    for(int i=0;i<expected.length;i++){
      require(actual[i].length==2,"Persisted profile dimension");
      for(int j=0;j<2;j++)require(Math.abs(actual[i][j]-expected[i][j])<=1e-8,"Persisted profile coordinates");
    }
    require(Arrays.equals(m.study("std").feature().tags(),new String[]{"bma1","bma2","drive"}),
      "Persisted study identity");
    for(int k=1;k<=2;k++){
      String t="port"+k;
      require("Numeric".equals(m.component("c").physics("ewfd").feature(t).getString("PortType")),
        "Persisted port type");
      require((""+k).equals(m.component("c").physics("ewfd").feature(t).getString("PortName")),"Persisted port order");
      require("0".equals(m.component("c").physics("ewfd").feature(t).getString("Thetap")),"Persisted port phase");
      require("1[W/m]".equals(m.component("c").physics("ewfd").feature(t).getString("Pin")),
        "Persisted input normalization");
      require("on".equals(m.component("c").physics("ewfd").feature(t).getString("PortExcitation")),
        "Persisted source excitation");
      require(ids(m.component("c").physics("ewfd").feature(t).selection().entities(1)).equals(
        ids(m.component("c").selection("p"+k).entities(1))),"Persisted port selection");
      require((""+k).equals(m.study("std").feature("bma"+k).getString("PortName")),"Persisted BMA binding");
      require("BoundaryModeAnalysis".equals(m.study("std").feature("bma"+k).getType()),"Persisted BMA type");
      require("f0".equals(m.study("std").feature("bma"+k).getString("modeFreq")),"Persisted BMA frequency");
      require("2.2".equals(m.study("std").feature("bma"+k).getString("shift"))&&
        m.study("std").feature("bma"+k).getInt("neigs")==1,"Persisted BMA settings");
      m.component("c").geom("g").measureFinal().selection().geom("g",1);
      m.component("c").geom("g").measureFinal().selection().set(m.component("c").selection("p"+k).entities(1));
      require(Math.abs(m.component("c").geom("g").measureFinal().getVolume()-2.4)<1e-6,
        "Persisted port span");
      double x=k==1?0:14;double[] b=m.component("c").geom("g").measureFinal().getBoundingBox(), e={x,x,-1.2,1.2};
      require(b.length==4,"Persisted port box dimension");
      for(int j=0;j<4;j++)require(Math.abs(b[j]-e[j])<1e-7,"Persisted port window");
    }
    m.component("c").geom("g").measureFinal().selection().geom("g",1);
    m.component("c").geom("g").measureFinal().selection().set(m.component("c").selection("open").entities(1));
    require(Math.abs(m.component("c").geom("g").measureFinal().getVolume()-33.2)<1e-6,"Persisted open span");
    double[] b=m.component("c").geom("g").measureFinal().getBoundingBox(), e={0,14,-2.5,2.5};
    require(b.length==4,"Persisted open box dimension");
    for(int j=0;j<4;j++)require(Math.abs(b[j]-e[j])<1e-7,"Persisted open window");
    require(ids(m.component("c").physics("ewfd").feature("sctr").selection().entities(1)).equals(
      ids(m.component("c").selection("open").entities(1))),"Persisted open physics selection");
    require("RefractiveIndex".equals(
      m.component("c").physics("ewfd").feature("wee1").getString("DisplacementFieldModel")),
      "Persisted material field model");
    require("FrequencyDomainSourceSweep".equals(m.study("std").feature("drive").getType()),
      "Persisted source sweep type");
    require("f0".equals(m.study("std").feature("drive").getString("plist")),"Persisted source frequency");
    frozenStores(m,"P11_STORE");marker("P11_PROFILE_VALIDATED");
  }
  static void frozenStores(Model m,String label){
    String driven=null;
    for(String s:m.sol().tags())if("std".equals(m.sol(s).study())&&m.sol(s).feature().tags().length>0){
      require(driven==null,"Ambiguous persisted sequence");driven=s;
    }
    require(FROZEN_SEQUENCE[0].equals(driven),"Persisted solver identity");
    String[] tags=m.sol(driven).feature().tags();int stores=0,drive=-1,last=-1;
    for(int i=0;i<tags.length;i++){
      String t=tags[i];
      if("StudyStep".equals(m.sol(driven).feature(t).getType())&&
        "drive".equals(m.sol(driven).feature(t).getString("studystep"))){
        require(drive==-1&&FROZEN_SEQUENCE[2].equals(t),"Persisted driven start identity");drive=i;
      }
      if("StoreSolution".equals(m.sol(driven).feature(t).getType())){
        require(stores<2,"Extra persisted store");String[] e=FROZEN_STORES[stores];
        require(e[0].equals(t)&&e[1].equals(m.sol(driven).feature(t).getString("sol"))&&
          e[2].equals(dataset(m,e[1])),"Persisted selected store mapping");
        marker(label+" port="+(stores+1)+" tag="+t+" solution="+e[1]+" dataset="+e[2]);stores++;last=i;
      }
    }
    require(stores==2&&drive>last,"Frozen stores must precede driven start");
    require(FROZEN_SEQUENCE[1].equals(tags[last]),"Persisted last selected store");
  }
""".replace("__STORES__", store_java)
        .replace("__SEQUENCE__", sequence_java)
        .replace("__TABLE__", "new double[][]" + table)
    )
    text = helper.once(
        text, "  public static void main(String[] args)", audit + "\n  public static void main(String[] args)"
    )
    text = helper.once(
        text,
        'm.modelPath(".");resumeDriven(m);return m;',
        'm.modelPath(".");profileDrivenAudit(m);marker("PROFILE_IDENTITY '
        + digest(profile_raw)
        + '");marker("MODE_ORIGIN_IDENTITY '
        + identity
        + '");marker("P11_INPUT_CHECKPOINT '
        + checkpoint_hash
        + '");resumeDriven(m);return m;',
    )
    text = helper.once(
        text, '    marker("NATIVE_COMPLETED");', '    frozenStores(m,"P11_STORE_AFTER");marker("NATIVE_COMPLETED");'
    )
    return text.encode("utf-8")


def _manifest(profile_raw, source, origin, checkpoint_hash):
    return {
        "schema_version": "profile-driven-bundle-v1",
        "stage": "solve",
        "will_execute": False,
        "physics_accepted": False,
        "profile_identity": digest(profile_raw),
        "profile_sha256": digest(profile_raw),
        "source_sha256": digest(source),
        "input_checkpoint_sha256": checkpoint_hash,
        "mode_origin_identity": digest(canonical(origin)),
        "dependencies": dependencies(),
    }


def prepare_bundle(
    output, mode_bundle, mode_run_folder, mode_receipt, *, producer_snapshot=None, producer_manifest=None
):
    helper = modes()
    output = helper.safe(output)
    if os.path.lexists(output):
        raise ValueError("Output must be new")
    origin, _report = validate_mode_origin(
        mode_bundle,
        mode_run_folder,
        mode_receipt,
        producer_snapshot=producer_snapshot,
        producer_manifest=producer_manifest,
    )
    checkpoint_path = helper.safe(Path(mode_run_folder) / "selected_modes.mph")
    checkpoint = checkpoint_path.read_bytes()
    profile_raw, mode_source, _report = _origin_check(origin, checkpoint_path)
    source = render(profile_raw, mode_source, origin, digest(checkpoint))
    manifest = _manifest(profile_raw, source, origin, digest(checkpoint))
    output.mkdir()
    for name, raw in (
        ("profile.json", profile_raw),
        ("DeviceCanary.java", source),
        ("input_modes.mph", checkpoint),
        ("mode_origin.json", canonical(origin)),
        ("manifest.json", canonical(manifest)),
    ):
        with (output / name).open("xb") as stream:
            stream.write(raw)
    return manifest


def verify_bundle(bundle):
    helper = modes()
    bundle = helper.safe(bundle, directory=True)
    if {p.name for p in bundle.iterdir()} != BUNDLE_FILES:
        raise ValueError("Unknown or missing driven bundle files")
    for name in BUNDLE_FILES:
        if not helper.safe(bundle / name).is_file():
            raise ValueError("Bundle member is not a regular file")
    origin_raw = (bundle / "mode_origin.json").read_bytes()
    origin = json.loads(origin_raw)
    if origin_raw != canonical(origin):
        raise ValueError("Origin serialization mismatch")
    checkpoint = bundle / "input_modes.mph"
    profile_raw, mode_source, _report = _origin_check(origin, checkpoint)
    source = render(profile_raw, mode_source, origin, digest(checkpoint.read_bytes()))
    manifest = _manifest(profile_raw, source, origin, digest(checkpoint.read_bytes()))
    if (
        (bundle / "profile.json").read_bytes() != profile_raw
        or (bundle / "DeviceCanary.java").read_bytes() != source
        or (bundle / "manifest.json").read_bytes() != canonical(manifest)
    ):
        raise ValueError("Driven bundle source/profile/manifest substitution")
    return manifest


def validate_evidence(bundle, run_folder, receipt):
    helper = modes()
    manifest = verify_bundle(bundle)
    bundle, run = helper.safe(bundle, directory=True), helper.safe(run_folder, directory=True)
    rec = json.loads(helper.safe(receipt).read_bytes())
    required = {
        "schema_version": "profile-driven-native-v1",
        "status": "native_completed",
        "stage": "solve",
        "profile_identity": manifest["profile_identity"],
        "mode_origin_identity": manifest["mode_origin_identity"],
        "bundle_manifest_sha256": digest((bundle / "manifest.json").read_bytes()),
        "source_sha256": manifest["source_sha256"],
        "input_checkpoint_sha256": manifest["input_checkpoint_sha256"],
        "compile_exit_code": 0,
        "batch_exit_code": 0,
    }
    if not isinstance(rec, dict) or any(rec.get(k) != v or isinstance(rec.get(k), bool) for k, v in required.items()):
        raise ValueError("Driven receipt identity/status mismatch")
    members = artifact_membership(rec)
    for name, sha in members.items():
        member = helper.safe(run / name)
        if not member.is_file() or digest(member.read_bytes()) != sha:
            raise ValueError("Driven receipt artifact hash mismatch: " + name)
    for name, key in (
        ("DeviceCanary.java", "source_sha256"),
        ("input_modes.mph", "input_checkpoint_sha256"),
        ("driven_checkpoint.mph", "driven_checkpoint_sha256"),
        ("console.txt", "console_sha256"),
    ):
        member = helper.safe(run / name)
        if not member.is_file() or not member.stat().st_size or members.get(name) != rec.get(key):
            raise ValueError("Driven receipt missing artifact: " + name)
    if (run / "driven_checkpoint.mph").stat().st_size < 1024:
        raise ValueError("Driven checkpoint is incomplete")
    text = (run / "console.txt").read_text(encoding="utf-8", errors="strict")
    helper._reject_native_failures(text)
    lines = text.splitlines()
    for prefix, value in (
        ("CANARY STAGE ", "solve SHAPE taper"),
        ("CANARY PROFILE_IDENTITY ", manifest["profile_identity"]),
        ("CANARY MODE_ORIGIN_IDENTITY ", manifest["mode_origin_identity"]),
        ("CANARY P11_INPUT_CHECKPOINT ", manifest["input_checkpoint_sha256"]),
    ):
        if helper._one(lines, prefix) != value:
            raise ValueError("Driven runtime identity mismatch")
    for marker in ("P11_PROFILE_VALIDATED", "DRIVEN_CHECKPOINT_SAVED", "NATIVE_COMPLETED"):
        if lines.count("CANARY " + marker) != 1:
            raise ValueError("Missing/duplicate driven completion marker")
    if any(
        line.startswith(("CANARY MODES_COMPLETED", "CANARY SELECTED_", "CANARY CENSUS ", "CANARY RUN_TO_SELECTED "))
        for line in lines
    ):
        raise ValueError("Unexpected mode recomputation on driven route")
    resume = helper._one(lines, "CANARY RESUME_FROM_FROZEN ")
    solver, _store, drive = _sequence(json.loads((bundle / "mode_origin.json").read_bytes()))
    if resume != solver + "/" + drive:
        raise ValueError("Invalid resume identity")
    actual_dataset = re.fullmatch(
        r"(\w+) solution=(\w+) pnames=(\[.*?\]) pvalues=(\[.*\])", helper._one(lines, "CANARY ACTUAL_DATASET ")
    )
    if not actual_dataset or actual_dataset[2] != solver or actual_dataset[3] != "[freq, PortName]":
        raise ValueError("Missing actual driven dataset")
    axis = helper._array(actual_dataset[4])
    frequency = 299792458 / (1550e-9)
    if (
        not isinstance(axis, list)
        or len(axis) != 4
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in axis)
        or not all(math.isclose(axis[i], frequency, rel_tol=1e-12) for i in (0, 2))
        or abs(axis[1] - 1.0) > 1e-9
        or abs(axis[3] - 2.0) > 1e-9
    ):
        raise ValueError("Actual driven frequency/source axis mismatch")
    if lines.index("CANARY P11_PROFILE_VALIDATED") >= lines.index("CANARY RESUME_FROM_FROZEN " + resume):
        raise ValueError("Profile readback must precede resume")
    for prefix in ("CANARY PROFILE_IDENTITY ", "CANARY MODE_ORIGIN_IDENTITY ", "CANARY P11_INPUT_CHECKPOINT "):
        position = next(i for i, line in enumerate(lines) if line.startswith(prefix))
        if (
            not lines.index("CANARY P11_PROFILE_VALIDATED")
            < position
            < lines.index("CANARY RESUME_FROM_FROZEN " + resume)
        ):
            raise ValueError("Runtime identities must follow actual readback and precede resume")
    helper.readbacks(text, json.loads((bundle / "profile.json").read_bytes()))
    if lines.index("CANARY P10_READBACK_COMPLETED") >= lines.index("CANARY P11_PROFILE_VALIDATED"):
        raise ValueError("Actual readback must precede profile validation")
    origin = json.loads((bundle / "mode_origin.json").read_bytes())
    for port, (tag, solution, dataset) in enumerate(_stores(origin), 1):
        for prefix in ("P11_STORE", "P11_STORE_AFTER"):
            if (
                helper._one(lines, f"CANARY {prefix} port={port} ")
                != f"tag={tag} solution={solution} dataset={dataset}"
            ):
                raise ValueError("Selected mode stores changed during driven resume")
    rows = helper.module("run").parse_rows(text)
    if len(rows["SOURCE"]) != 2 or any(
        r[:2] != [float(i), float(i)] or abs(r[2] - 1550) > 1e-7 for i, r in enumerate(rows["SOURCE"], 1)
    ):
        raise ValueError("Actual sources/wavelength mismatch")
    positions = {(int(row), int(source)) for source, row, _index, _re, _im in rows["S"]}
    if len(rows["S"]) != 4 or positions != {(1, 1), (1, 2), (2, 1), (2, 2)}:
        raise ValueError("Incomplete or duplicate physical complex S")
    if len(rows["POWER"]) != 2 or {r[0] for r in rows["POWER"]} != {1, 2}:
        raise ValueError("Missing raw power records")
    s = {(int(row), int(source)): complex(re_, im) for source, row, _index, re_, im in rows["S"]}
    diagnostics = []
    for source, flux, qh, p1, p2, n1, n2 in rows["POWER"]:
        source = int(source)
        if not all(1.45 < n < 2.6 for n in (n1, n2)):
            raise ValueError("Invalid driven selected effective index")
        reflection = abs(s[source, source]) * abs(s[source, source])
        transmission = abs(s[3 - source, source]) * abs(s[3 - source, source])
        diagnostics.append(
            {
                "source": source,
                "R": reflection,
                "T": transmission,
                "port1_net_outward_W_per_m": p1,
                "port2_net_outward_W_per_m": p2,
                "net_port_flux_W_per_m": p1 + p2,
                "open_signed_flux_W_per_m": flux,
                "material_Qh_W_per_m": qh,
                "closed_surface_residual_W_per_m": p1 + p2 + flux + qh,
                "one_minus_R_minus_T": 1 - reflection - transmission,
                "modal_plus_open_Qh_residual_assuming_unit_incoming": 1 - reflection - transmission - flux - qh,
            }
        )
    if not all(math.isfinite(v) for row in diagnostics for v in row.values()):
        raise ValueError("Nonfinite derived diagnostic")
    return {
        "schema_version": "profile-driven-evidence-v1",
        "evidence_integrity": "validated",
        "profile_identity": manifest["profile_identity"],
        "mode_origin_identity": manifest["mode_origin_identity"],
        "receipt_sha256": digest(helper.safe(receipt).read_bytes()),
        "physics_accepted": False,
        "physical_qualification": "not_established",
        "diagnostics": diagnostics,
        "complex_S": [
            {"row": row, "column": col, "real": z.real, "imag": z.imag} for (row, col), z in sorted(s.items())
        ],
        "assumptions": [
            "2D scalar bulk-index surrogate, one wavelength 1550 nm, fixed mesh and exterior numeric ports.",
            "R/T use raw native complex S and declared 1 W/m mode normalization; no fit or incoming-matrix inversion.",
            "Port and open flux are signed outward; Qh is the native all-domain material integral.",
            "1-R-T is only a modal deficit; it does not identify radiation, absorption or complete missing power.",
            "Modal closure conditionally assumes actual unit incoming power; "
            "no physical acceptance threshold is applied.",
            "Receipt hashes establish artifact linkage, not cryptographic attestation of native execution.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode-bundle", type=Path, required=True)
    p.add_argument("--mode-run-folder", type=Path, required=True)
    p.add_argument("--mode-receipt", type=Path, required=True)
    p.add_argument("--producer-snapshot", type=Path)
    p.add_argument("--producer-manifest", type=Path)
    p = sub.add_parser("verify")
    p.add_argument("--bundle", type=Path, required=True)
    p = sub.add_parser("validate")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--run-folder", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_bundle(
                args.output,
                args.mode_bundle,
                args.mode_run_folder,
                args.mode_receipt,
                producer_snapshot=args.producer_snapshot,
                producer_manifest=args.producer_manifest,
            )
        elif args.command == "verify":
            result = verify_bundle(args.bundle)
        else:
            result = validate_evidence(args.bundle, args.run_folder, args.receipt)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
