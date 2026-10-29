"""Exercise the installed wheel's Lumerical migration path without a license.

Run with the wheel installation directory on PYTHONPATH, outside the checkout.
The output is a new directory containing inspectable geometry and circuit data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from importlib.resources import files
from pathlib import Path

import numpy as np

import photonic_workflow
from photonic_workflow.circuits import compose, validate_manifest, write_composition
from photonic_workflow.lumerical import plan_run
from photonic_workflow.lumerical.device_geometry import build_device_geometry
from photonic_workflow.lumerical.materials import sample_material_model
from photonic_workflow.lumerical.workflow import optimize_step
from photonic_workflow.lumerical_exchange import export_lumerical_sparameters
from photonic_workflow.lumerical_geometry import export_native_geometry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--installed-root", type=Path, required=True)
    args = parser.parse_args()
    package = Path(photonic_workflow.__file__).resolve()
    if not package.is_relative_to(args.installed_root.resolve()):
        raise RuntimeError(f"Wrong package imported: {package}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    resource = Path(str(files("photonic_workflow").joinpath("data/skill/examples/lumerical")))
    mode = json.loads((resource / "mode-waveguide.json").read_text())
    plan = plan_run(mode)
    assert not plan["execution"] and not plan["physics_accepted"]
    device_plans = {}
    for family in ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch", "ring", "ring-modulator"):
        device_request = {"schema_version": "1.0", "operation": "fdtd-device", "parameters": {"family": family}}
        device_plans[family] = plan_run(device_request)
        assert not device_plans[family]["execution"]
        assert len(build_device_geometry(family, {})["ports"]) >= 2
    silicon = sample_material_model({"model": "li-silicon-1980", "temperature_k": 293.15},
                                    np.linspace(1.5e-6, 1.6e-6, 5))
    assert np.all(np.asarray(silicon["n_real"]) > 3)
    opt_inputs = output / "optimization-inputs"
    opt_inputs.mkdir()
    for name in ("device-coupler.json", "device-optimization-spec.json"):
        (opt_inputs / name).write_bytes((resource / name).read_bytes())
    opt_config = json.loads((resource / "device-optimization.json").read_text())
    opt_config["trials_dir"] = "trials"
    (opt_inputs / "config.json").write_text(json.dumps(opt_config), encoding="utf-8")
    proposal = optimize_step(opt_inputs / "config.json", output / "optimization-plan")
    assert proposal["status"] == "planned" and not proposal["will_execute"]
    assert not (opt_inputs / "trials").exists()
    geometries = {}
    for family in ("straight", "crossing", "directional-coupler", "mmi2x2", "ybranch"):
        request = {"schema_version": "1.0", "family": family, "parameters": {}}
        geometries[family] = export_native_geometry(
            request, output / family, height_um=0.22, core_index=3.476,
        )
    source = resource / "sparameters.json"
    receipt = export_lumerical_sparameters(source, Path("device.csv"), project_root=output)
    assert (output / receipt["source"]["artifact_path"]).read_bytes() == source.read_bytes()
    manifest = {
        "schema_version": "1.0", "conventions": receipt["conventions"],
        "components": {"native": receipt["component"]},
        "instances": {"first": {"component": "native"}, "second": {"component": "native"}},
        "connections": [["first:right", "second:left"]],
        "external_ports": {"in": "first:left", "out": "second:right"},
    }
    assembly = output / "assembly.json"
    assembly.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    model, data = validate_manifest(assembly, project_root=output)
    rows, summary = compose(model, data)
    observed = {float(row["wavelength_nm"]): complex(float(row["s_real"]), float(row["s_imag"]))
                for row in rows if row["out_port"] == "out" and row["in_port"] == "in"}
    np.testing.assert_allclose([observed[1540], observed[1560]], [(0.5 + 0.3j) ** 2, (0.6 + 0.2j) ** 2])
    write_composition(output / "cascade.csv", rows)
    result = {
        "status": "passed", "package_path": str(package), "native_execution": False,
        "physics_accepted": False, "geometry_families": list(geometries),
        "device_plan_families": list(device_plans),
        "shared_material_model_loaded": True, "shared_optimization_plan_loaded": True,
        "raw_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "complex_cascade_matches_independent_product": True, "circuit_summary": summary,
        "fixture_kind": "synthetic nonreciprocal complex data; not a solved device",
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
