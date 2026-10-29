"""Data generation and supervised-launch controls; no native solver executes."""

import builtins
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from photonic_workflow import native_backend as backend


def straight():
    return {
        "family": "straight",
        "parameters": {},
        "bbox_um": [0, 8, -1.5, 1.5],
        "primitives": [
            {"tag": "wg", "type": "rectangle", "x": 0, "y": -0.15, "width": 8, "height": 0.3, "group": "core"}
        ],
        "ports": [
            {"name": "left", "side": "left", "center_um": [0, 0], "width_um": 0.3, "window_um": 1.6},
            {"name": "right", "side": "right", "center_um": [8, 0], "width_um": 0.3, "window_um": 1.6},
        ],
        "expected_core_area_um2": 2.4,
        "expected_core_components": 1,
        "model_level": "2d-scalar-index-surrogate",
        "limitations": [],
    }


def fake_solver(tmp_path):
    directory = tmp_path / "synthetic-install" / "bin" / "win64"
    directory.mkdir(parents=True)
    for name in ("comsolcompile.exe", "comsolbatch.exe"):
        (directory / name).write_bytes(b"not executable; launch is mocked")
    return directory.parent.parent


def fake_launch(
    *,
    compile_code=0,
    batch_code=0,
    terminal=None,
    make_class=True,
    checkpoint=True,
    mutate_bundle=False,
    stage="configure",
):
    terminal = terminal if terminal is not None else "PIC COMPLETE " + stage

    def launch(command, folder, log, timeout):
        assert timeout > 0
        assert isinstance(command, list)
        if log.name == "compile.log":
            if make_class:
                (folder / "NativePic.class").write_bytes(b"synthetic compiled fixture; not native" * 4)
            if mutate_bundle:
                with (folder.parent / "NativePic.java").open("a", encoding="utf-8") as stream:
                    stream.write("// mutation after compile")
            code = compile_code
            log.write_text("synthetic compiler fixture", encoding="utf-8")
        else:
            if checkpoint:
                checkpoint_name = {"configure": "configured.mph", "modes": "selected_modes.mph", "solve": "driven.mph"}[
                    stage
                ]
                (folder / checkpoint_name).write_bytes(b"synthetic checkpoint; no native result" * 10)
            log.write_text(
                f"PIC STAGE {stage}\nPIC GEOMETRY_PASS\nPIC PORTS_PASS\n" + terminal + "\n", encoding="utf-8"
            )
            code = batch_code
        return {
            "exit_code": code,
            "stdout": log.name,
            "seconds": 0.01,
            "timed_out": False,
            "owned_processes_exited": True,
            "argv": command,
        }

    return launch


def run_fixture(tmp_path, monkeypatch, **scenario):
    bundle = tmp_path / "bundle"
    backend.prepare_native_bundle(bundle, straight(), {"stage": "configure"})
    import psutil

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(()))
    monkeypatch.setattr(backend, "_launch", fake_launch(**scenario))
    return backend.run_native_bundle(bundle, fake_solver(tmp_path), timeout_s=30, compile_timeout_s=10, cores=2)


def test_bundle_round_trip_and_no_overwrite(tmp_path):
    output = tmp_path / "bundle"
    manifest = backend.prepare_native_bundle(output, straight(), {"wavelengths_nm": [1500, 1550, 1600]})
    result = backend.verify_native_bundle(output)
    assert result["manifest"] == manifest
    assert result["config"]["active_index"] == 2.6
    assert result["config"]["wavelengths_nm"] == [1500, 1550, 1600]
    assert manifest["native_execution"] is False
    with pytest.raises(FileExistsError):
        backend.prepare_native_bundle(output, straight())


def test_offline_preparation_does_not_require_optional_psutil(tmp_path, monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil deliberately unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    backend.prepare_native_bundle(tmp_path / "bundle", straight())
    assert backend.verify_native_bundle(tmp_path / "bundle")["config"]["stage"] == "solve"


@pytest.mark.parametrize("member", ["geometry.json", "config.json", "NativePic.java"])
def test_modified_input_rejected_without_executing(tmp_path, member):
    output = tmp_path / "bundle"
    backend.prepare_native_bundle(output, straight())
    with (output / member).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="member mismatch"):
        backend.verify_native_bundle(output)


def test_arbitrary_java_with_recomputed_manifest_is_rejected(tmp_path):
    output = tmp_path / "bundle"
    backend.prepare_native_bundle(output, straight())
    path = output / "NativePic.java"
    path.write_text("class NativePic { static { System.exit(0); } }", encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["files"]["NativePic.java"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="trusted generation"):
        backend.verify_native_bundle(output)


@pytest.mark.parametrize(
    "key,value",
    [
        ("wavelengths_nm", []),
        ("wavelengths_nm", [1550, 1550]),
        ("wavelengths_nm", [float("nan")]),
        ("wavelengths_nm", [True]),
        ("wavelengths_nm", [1800]),
        ("stage", "solve; arbitrary"),
        ("core_index", 1.4),
        ("active_extinction", -0.01),
        ("core_mesh_um", 0),
        ("cladding_mesh_um", 1),
        ("java", "System.exit(0)"),
        ("export_fields", "false"),
        ("export_fields", 0),
        ("export_fields", None),
        ("port_mesh_um", 0.004),
        ("port_mesh_um", 0.201),
        ("port_mesh_um", True),
        ("measure_mesh_area", "false"),
        ("measure_mesh_area", 0),
        ("measure_mesh_area", None),
    ],
)
def test_invalid_configuration_rejected(key, value):
    with pytest.raises(ValueError):
        backend.normalize_native_config({key: value})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda g: g["primitives"][0].update(tag='wg");System.exit(0);//'),
        lambda g: g["primitives"][0].update(x="0;System.exit(0)"),
        lambda g: g["primitives"][0].update(width=float("inf")),
        lambda g: g["primitives"][0].update(width=-1),
        lambda g: g["primitives"][0].update(group="unknown"),
        lambda g: g["primitives"][0].update(extra="untrusted expression"),
        lambda g: g["primitives"].append(copy.deepcopy(g["primitives"][0])),
        lambda g: g["ports"][0].update(center_um=[1, 0]),
        lambda g: g["ports"][0].update(window_um=10),
        lambda g: g["ports"][1].update(name="left"),
        lambda g: g.update(expected_core_components=True),
    ],
)
def test_invalid_primitive_or_port_rejected(mutation):
    geometry = straight()
    mutation(geometry)
    with pytest.raises(ValueError):
        backend.render_java(geometry, wavelengths_nm=[1550])


def test_same_face_port_overlap_is_rejected():
    geometry = straight()
    geometry["ports"][1].update(side="left", center_um=[0, 0.1])
    with pytest.raises(ValueError, match="separated"):
        backend.render_java(geometry, wavelengths_nm=[1550])


def test_metadata_is_data_and_all_primitive_types_render():
    geometry = straight()
    geometry["family"] = "ring-modulator"
    geometry["pn_response"] = {"comment": 'System.exit(0); "untrusted"', "voltage": 0}
    geometry["primitives"].extend(
        [
            {
                "tag": "annulus",
                "type": "ring",
                "cx": 4,
                "cy": 0.8,
                "outer_radius": 0.4,
                "inner_radius": 0.1,
                "group": "active",
            },
            {"tag": "triangle", "type": "polygon", "points": [[2, 1], [3, 1], [2.5, 1.3]], "group": "core"},
        ]
    )
    source = backend.render_java(geometry, wavelengths_nm=[1530, 1550, 1570], active_index=2.58)
    assert "System.exit" not in source
    assert "untrusted" not in source
    assert 'g.create("annulus","Difference")' in source
    assert 'g.create("triangle","Polygon")' in source
    assert "2.58" in source


def test_success_receipt_binds_actual_artifacts_but_is_not_physics_acceptance(tmp_path, monkeypatch):
    receipt = run_fixture(tmp_path, monkeypatch)
    assert receipt["status"] == "completed"
    assert receipt["physical_qualification"] == "not_established"
    folder = Path(receipt["run_directory"])
    assert (folder / "receipt.json").is_file()
    assert receipt["compile"]["exit_code"] == receipt["batch"]["exit_code"] == 0
    for artifact in receipt["artifacts"]:
        raw = (folder / artifact["path"]).read_bytes()
        assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()
        assert artifact["bytes"] == len(raw)


@pytest.mark.parametrize(
    "scenario",
    [
        {"compile_code": 1},
        {"make_class": False},
        {"batch_code": 1},
        {"checkpoint": False},
        {"terminal": "PIC COMPLETE configure_ERROR"},
        {"terminal": "PIC COMPLETE configure\nPIC COMPLETE configure"},
        {"terminal": "PIC COMPLETE configure\nPIC FAILED java.lang.IllegalStateException: rejected"},
        {"mutate_bundle": True},
    ],
)
def test_failure_retained_and_never_promoted(tmp_path, monkeypatch, scenario):
    receipt = run_fixture(tmp_path, monkeypatch, **scenario)
    assert receipt["status"] == "failed"
    assert receipt["error"]
    assert (Path(receipt["run_directory"]) / "receipt.json").is_file()
    if scenario.get("compile_code") or scenario.get("make_class") is False or scenario.get("mutate_bundle"):
        assert "batch" not in receipt


def test_each_execution_has_separate_run_directory(tmp_path, monkeypatch):
    receipt = run_fixture(tmp_path, monkeypatch)
    second = backend.run_native_bundle(receipt["bundle"], tmp_path / "synthetic-install", timeout_s=30)
    assert receipt["status"] == second["status"] == "completed"
    assert receipt["run_directory"] != second["run_directory"]


@pytest.mark.parametrize("kwargs", [{"cores": True}, {"cores": 0}, {"timeout_s": 0}, {"compile_timeout_s": 0}])
def test_invalid_execution_budget_fails_before_launch(tmp_path, kwargs):
    bundle = tmp_path / "bundle"
    backend.prepare_native_bundle(bundle, straight())
    with pytest.raises(ValueError):
        backend.run_native_bundle(bundle, **kwargs)


def test_concurrent_solver_blocks_before_creating_run(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    backend.prepare_native_bundle(bundle, straight())
    import psutil

    class Active:
        def __init__(self):
            self.info = {"name": "comsolbatch.exe"}

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter([Active()]))
    with pytest.raises(RuntimeError, match="concurrency is one"):
        backend.run_native_bundle(bundle, fake_solver(tmp_path))
    assert not list(bundle.glob("run-*"))


def test_supervisor_timeout_kills_its_owned_python_process(tmp_path):
    """Real process lifecycle test; this command never starts COMSOL."""
    result = backend._launch(
        [sys.executable, "-c", "import time; print('owned fixture', flush=True); time.sleep(30)"],
        tmp_path,
        tmp_path / "process.log",
        0.3,
    )
    assert result["timed_out"] is True
    assert result["owned_processes_exited"] is True
    assert result["exit_code"] != 0
    assert result["seconds"] < 10


def field_fixture():
    metadata = {
        "schema_version": "1.0",
        "artifact": "field.csv",
        "dataset": "dset5",
        "solution": "sol1",
        "source_axis_index": 0,
        "source_port": 1,
        "wavelength_nm": 1550.0,
        "coordinate_units": "um",
        "field_units": "V/m",
        "expressions": [
            "PortName",
            "c_const/freq/1[nm]",
            "x/1[um]",
            "y/1[um]",
            "real(ewfd.Ez)",
            "imag(ewfd.Ez)",
            "ewfd.normE^2",
        ],
        "refine": 1,
        "smooth": "none",
        "rows": 2,
        "coordinate_multiplicity": "retained",
    }
    row = "PIC FIELD_ROW 1.0,1550.0,0.0,0.0,3.0,4.0,25.0"
    return "\n".join([row, row, "PIC FIELD_META " + json.dumps(metadata), "PIC FIELD 1550.0 1 dset5 2"])


def test_native_field_extraction_preserves_repeated_coordinates():
    data, metadata = backend.extract_native_field(field_fixture())
    lines = data.decode().splitlines()
    assert len(lines) == 3
    assert lines[1] == lines[2] == "1.0,1550.0,0.0,0.0,3.0,4.0,25.0"
    assert metadata["rows"] == 2
    assert metadata["dataset"] == "dset5"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.replace("1550.0,0.0", "1549.0,0.0", 1),
        lambda s: s.replace("1.0,1550.0", "2.0,1550.0", 1),
        lambda s: s.replace("3.0,4.0,25.0", "3.0,nan,25.0", 1),
        lambda s: s.replace("3.0,4.0,25.0", "3.0,4.0,-25.0", 1),
        lambda s: s.replace('"rows": 2', '"rows": 3'),
        lambda s: s.replace('"coordinate_units": "um"', '"coordinate_units": "m"'),
        lambda s: s.replace('"source_port": 1', '"source_port": true'),
        lambda s: s.replace("PIC FIELD 1550.0 1 dset5 2", "PIC FIELD 1550.0 1 dset6 2"),
        lambda s: s.replace("PIC FIELD_ROW ", "PIC FIELD_ROW_ERROR ", 1),
        lambda s: s + "\n" + next(line for line in s.splitlines() if line.startswith("PIC FIELD_META")),
    ],
)
def test_native_field_identity_and_completeness_fail_closed(mutation):
    with pytest.raises(ValueError):
        backend.extract_native_field(mutation(field_fixture()))


def test_generated_java_checks_only_the_actual_scattering_source(tmp_path):
    """Compile the emitted numeric selector, without COMSOL or its API jars."""
    javac, java = shutil.which("javac"), shutil.which("java")
    if javac is None or java is None:
        pytest.skip("JDK unavailable for generated Java numeric controls")
    source = backend.render_java(straight(), wavelengths_nm=[1550])
    start = source.index("static double[] selectedSource(")
    end = source.index("static String dataset(", start)
    selector = source[start:end]
    program = (
        """public final class SourceSelectionProbe {
      static void require(boolean value,String message){
        if(!value)throw new IllegalStateException(message);
      }
      static void rejected(double[][] value,int index,int count){
        try {selectedSource(value,index,count);throw new AssertionError("accepted invalid source");}
        catch(IllegalStateException expected){}
      }
      public static void main(String[] args){
        double[][] partial={{0.25,Double.NaN},{-0.5,Double.NaN}};
        double[] selected=selectedSource(partial,0,2);
        if(selected[0]!=0.25||selected[1]!=-0.5)throw new AssertionError("wrong selected pair");
        rejected(partial,1,2);
        rejected(new double[][]{{0.25,Double.NaN},{Double.NaN,0}},0,2);
        rejected(partial,2,2);
        rejected(partial,0,3);
        rejected(new double[][]{{0.1},{0.2,0.3}},0,1);
        System.out.println("source controls passed");
      }
    """
        + selector
        + "\n}"
    )
    path = tmp_path / "SourceSelectionProbe.java"
    path.write_text(program, encoding="utf-8")
    subprocess.run([javac, "--release", "11", str(path)], check=True, capture_output=True, timeout=30)
    result = subprocess.run(
        [java, "-cp", str(tmp_path), "SourceSelectionProbe"], check=True, capture_output=True, text=True, timeout=30
    )
    assert result.stdout.strip() == "source controls passed"


def test_old_bundle_without_field_switch_retains_default_source_identity(tmp_path):
    bundle = tmp_path / "old-bundle"
    backend.prepare_native_bundle(bundle, straight())
    source = (bundle / "NativePic.java").read_bytes()
    config = json.loads((bundle / "config.json").read_bytes())
    del config["export_fields"]
    del config["port_mesh_um"]
    del config["measure_mesh_area"]
    (bundle / "config.json").write_bytes(backend._canonical(config))
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest["files"]["config.json"] = hashlib.sha256((bundle / "config.json").read_bytes()).hexdigest()
    (bundle / "manifest.json").write_bytes(backend._canonical(manifest))
    verified = backend.verify_native_bundle(bundle)
    assert verified["config"]["export_fields"] is True
    assert verified["config"]["port_mesh_um"] is None
    assert verified["config"]["measure_mesh_area"] is False
    assert backend.render_java(verified["geometry"], **verified["config"]).encode() == source


def test_solver_can_omit_large_raw_field_export(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    backend.prepare_native_bundle(bundle, straight(), {"stage": "solve", "export_fields": False})
    import psutil

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(()))
    monkeypatch.setattr(backend, "_launch", fake_launch(stage="solve"))
    receipt = backend.run_native_bundle(bundle, fake_solver(tmp_path), timeout_s=30)
    assert receipt["status"] == "completed"
    assert "field_derivation" not in receipt
    assert not (Path(receipt["run_directory"]) / "field.csv").exists()
    source = (bundle / "NativePic.java").read_text()
    assert "if(lambda==WAVES[0])exportField(m,ds,main,lambda);" not in source


def test_port_mesh_is_optional_and_bound_to_verified_generated_source(tmp_path):
    default = backend.render_java(straight(), wavelengths_nm=[1550])
    assert default == backend.render_java(straight(), wavelengths_nm=[1550], port_mesh_um=None)
    assert '"portSize"' not in default
    bundle = tmp_path / "port-mesh"
    backend.prepare_native_bundle(bundle, straight(), {"port_mesh_um": 0.01})
    verified = backend.verify_native_bundle(bundle)
    assert verified["config"]["port_mesh_um"] == 0.01
    assert '"portSize"' in (bundle / "NativePic.java").read_text()
    config = json.loads((bundle / "config.json").read_bytes())
    config["port_mesh_um"] = 0.02
    (bundle / "config.json").write_bytes(backend._canonical(config))
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest["files"]["config.json"] = hashlib.sha256((bundle / "config.json").read_bytes()).hexdigest()
    (bundle / "manifest.json").write_bytes(backend._canonical(manifest))
    with pytest.raises(ValueError, match="trusted generation"):
        backend.verify_native_bundle(bundle)


def test_mesh_area_measurement_is_optional_and_source_bound(tmp_path):
    default = backend.render_java(straight(), wavelengths_nm=[1550])
    assert default == backend.render_java(straight(), wavelengths_nm=[1550], measure_mesh_area=False)
    assert "AREA_MESH" not in default
    bundle = tmp_path / "curved-mesh-area"
    backend.prepare_native_bundle(bundle, straight(), {"measure_mesh_area": True})
    verified = backend.verify_native_bundle(bundle)
    assert verified["config"]["measure_mesh_area"] is True
    source = (bundle / "NativePic.java").read_text()
    assert "AREA_MESH_OPERATOR" in source
    assert '"intorder",8' in source
    assert 'getInt("intorder")==8' in source
    assert "intorderactive" not in source
    config = json.loads((bundle / "config.json").read_bytes())
    config["measure_mesh_area"] = False
    (bundle / "config.json").write_bytes(backend._canonical(config))
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    manifest["files"]["config.json"] = hashlib.sha256((bundle / "config.json").read_bytes()).hexdigest()
    (bundle / "manifest.json").write_bytes(backend._canonical(manifest))
    with pytest.raises(ValueError, match="trusted generation"):
        backend.verify_native_bundle(bundle)
