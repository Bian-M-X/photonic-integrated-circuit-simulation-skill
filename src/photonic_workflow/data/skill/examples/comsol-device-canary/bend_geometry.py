"""Prepare and verify a geometry-only native bend probe; never starts COMSOL."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from photonic_workflow.recipes import geometry as recipe_geometry

HERE = Path(__file__).resolve().parent
BUNDLE_FILES = {"geometry.json", "geometry_fragment.java", "BendGeometryProbe.java", "manifest.json"}
PARAMETERS = {"turn_angle_deg", "minimum_radius_um", "width_um", "samples"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def serialized(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def safe(path, *, directory=False):
    path = Path(path).absolute()
    for member in (path, *path.parents):
        if member.is_symlink() or (hasattr(member, "is_junction") and member.is_junction()):
            raise ValueError("Symlink or junction path rejected")
    if directory and not path.is_dir():
        raise ValueError("Missing bundle directory")
    return path


def profile_module():
    # This fixed sibling belongs to the installed/checked-out tool, not the bundle.
    spec = importlib.util.spec_from_file_location("bend_geometry_profile", HERE / "bend_profile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dependencies():
    return {
        "bend_geometry.py": digest(Path(__file__).read_bytes()),
        "bend_profile.py": digest((HERE / "bend_profile.py").read_bytes()),
        "photonic_workflow.recipes.geometry": digest(Path(recipe_geometry.__file__).read_bytes()),
    }


JAVA = r"""import com.comsol.model.*;
import com.comsol.model.util.*;
import java.util.*;

/** Geometry/material-selection diagnostic only; no physics, mesh or study. */
public final class BendGeometryProbe {
  static void marker(String value) { System.out.println("BEND_GEOMETRY " + value); }
  static Set<Integer> ids(int[] values) {
    Set<Integer> answer = new TreeSet<>(); for(int value : values) answer.add(value); return answer;
  }
  static int[] intersection(int[] first,int[] second) {
    Set<Integer> common=ids(first); common.retainAll(ids(second));
    int[] answer=new int[common.size()]; int index=0; for(int value:common) answer[index++]=value; return answer;
  }
  static void rectangle(GeomSequence g,String tag,double y,double height) {
    g.create(tag,"Rectangle"); g.feature(tag).set("pos",new double[]{0,y});
    g.feature(tag).set("size",new double[]{14,height});
  }
  static void box(Model m,String tag,double x0,double x1) {
    m.component("c").selection().create(tag,"Box");
    m.component("c").selection(tag).set("entitydim",1);
    m.component("c").selection(tag).set("condition","inside");
    m.component("c").selection(tag).set("xmin",x0); m.component("c").selection(tag).set("xmax",x1);
    m.component("c").selection(tag).set("ymin",-1.201); m.component("c").selection(tag).set("ymax",1.201);
  }
  static void material(Model m,String tag,String selection,String n) {
    m.component("c").material().create(tag,"Common");
    m.component("c").material(tag).selection().named(selection);
    m.component("c").material(tag).propertyGroup().create("RefractiveIndex","Refractive index");
    m.component("c").material(tag).propertyGroup("RefractiveIndex").set("n",new String[]{n});
    m.component("c").material(tag).propertyGroup("RefractiveIndex").set("ki",new String[]{"0"});
  }
  static void measure(Model m,String kind,String tag,String selection,int dimension) {
    int[] entities=m.component("c").selection(selection).entities(dimension);
    double value=0; double[] bounds=new double[]{};
    if(entities.length>0) {
      m.component("c").geom("g").measureFinal().selection().geom("g",dimension);
      m.component("c").geom("g").measureFinal().selection().set(entities);
      value=m.component("c").geom("g").measureFinal().getVolume();
      bounds=m.component("c").geom("g").measureFinal().getBoundingBox();
    }
    marker("RECORD {\"kind\":\""+kind+"\",\"tag\":\""+tag+"\",\"entitydim\":"+dimension+
      ",\"entities\":"+Arrays.toString(entities)+",\"measure\":"+value+",\"bbox\":"+Arrays.toString(bounds)+"}");
  }
  static double[] numeric(String[] strings) {
    double[] values=new double[strings.length];
    for(int i=0;i<strings.length;i++) values[i]=Double.parseDouble(strings[i]); return values;
  }
  static void materialReadback(Model m,String tag) {
    int[] entities=m.component("c").material(tag).selection().entities(2);
    double[] n=numeric(m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("n"));
    double[] ki=numeric(m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("ki"));
    marker("RECORD {\"kind\":\"material\",\"tag\":\""+tag+"\",\"entities\":"+Arrays.toString(entities)+
      ",\"n\":"+Arrays.toString(n)+",\"ki\":"+Arrays.toString(ki)+"}");
  }
  static void edgeSamples(Model m) {
    GeomSequence g=m.component("c").geom("g");
    for(int edge:m.component("c").selection("coreBoundary").entities(1)) {
      double[] range=g.edgeParamRange(edge);
      if(range.length!=2||!Double.isFinite(range[0])||!Double.isFinite(range[1]))
        throw new IllegalStateException("Invalid native edge parameter range");
      double[] parameters=new double[65];
      for(int i=0;i<65;i++) parameters[i]=range[0]+(range[1]-range[0])*i/64.0;
      parameters[0]=range[0]; parameters[64]=range[1];
      double[][] coordinates=g.edgeX(edge,parameters);
      if(coordinates.length!=65) throw new IllegalStateException("Invalid native edge coordinate row count");
      for(double[] point:coordinates) {
        if(point.length!=2||!Double.isFinite(point[0])||!Double.isFinite(point[1]))
          throw new IllegalStateException("Invalid native edge coordinate");
      }
      marker("RECORD {\"kind\":\"edge_samples\",\"tag\":\"coreBoundary\",\"edge\":"+edge+
        ",\"parameter_range\":"+Arrays.toString(range)+",\"parameters\":"+Arrays.toString(parameters)+
        ",\"coordinates\":"+Arrays.deepToString(coordinates)+"}");
    }
  }
  public static Model run() throws Exception {
    marker("IDENTITY __IDENTITY__"); marker("FRAGMENT_SHA256 __FRAGMENT_SHA256__");
    Model m=ModelUtil.create("BendGeometryProbe"); m.modelPath("."); m.label("Bend geometry diagnostic");
    m.component().create("c",true); m.component("c").geom().create("g",2);
    GeomSequence g=m.component("c").geom("g"); g.lengthUnit("um");
    rectangle(g,"lower",-2.5,1.3); rectangle(g,"center",-1.2,2.4); rectangle(g,"upper",1.2,1.3);
__FRAGMENT__
    g.feature("bend_core").set("selresult","on");
__ACTUAL_FEATURES__
    g.run(); String actualUnit=g.lengthUnit();
    marker("GEOMETRY_UNIT_CODEPOINTS "+Arrays.toString(actualUnit.codePoints().toArray()));
    boolean unitIsMicrometer="um".equals(actualUnit)||"\u00b5m".equals(actualUnit)||"\u03bcm".equals(actualUnit);
    marker("GEOMETRY_UNIT "+(unitIsMicrometer?"um":"unsupported"));
    marker("COUNTS "+Arrays.toString(g.getNEntities()));
    m.component("c").selection().create("allDomains","Explicit");
    m.component("c").selection("allDomains").geom("g",2); m.component("c").selection("allDomains").all();
    m.component("c").selection().create("bg","Difference");
    m.component("c").selection("bg").set("entitydim",2);
    m.component("c").selection("bg").set("add",new String[]{"allDomains"});
    m.component("c").selection("bg").set("subtract",new String[]{"g_bend_core_dom"});
    material(m,"coremat","g_bend_core_dom","2.6"); material(m,"clad","bg","1.45");
    measure(m,"domain","core","g_bend_core_dom",2); measure(m,"domain","bg","bg",2);
    measure(m,"domain","allDomains","allDomains",2); materialReadback(m,"coremat"); materialReadback(m,"clad");
    box(m,"p1",-0.001,0.001); box(m,"p2",13.999,14.001);
    m.component("c").selection().create("exterior","Explicit");
    m.component("c").selection("exterior").geom("g",2,1,new String[]{"exterior"});
    m.component("c").selection("exterior").all();
    m.component("c").selection().create("open","Difference");
    m.component("c").selection("open").set("entitydim",1);
    m.component("c").selection("open").set("add",new String[]{"exterior"});
    m.component("c").selection("open").set("subtract",new String[]{"p1","p2"});
    m.component("c").selection().create("coreBoundary","Explicit");
    m.component("c").selection("coreBoundary").geom("g",2,1,new String[]{"exterior"});
    m.component("c").selection("coreBoundary").set(m.component("c").selection("g_bend_core_dom").entities(2));
    for(int port=1;port<=2;port++) {
      String tag="core_end"+port;
      int[] edges=intersection(m.component("c").selection("coreBoundary").entities(1),
        m.component("c").selection("p"+port).entities(1));
      m.component("c").selection().create(tag,"Explicit");
      m.component("c").selection(tag).geom("g",1); m.component("c").selection(tag).set(edges);
    }
    for(String tag:new String[]{"p1","p2","coreBoundary","core_end1","core_end2","exterior","open"})
      measure(m,"boundary",tag,tag,1);
    edgeSamples(m);
    marker("NO_SOLVE_COUNTS physics="+m.component("c").physics().tags().length+
      " mesh="+m.component("c").mesh().tags().length+" study="+m.study().tags().length+" sol="+m.sol().tags().length);
    m.save("BendGeometryProbe.mph"); marker("CHECKPOINT_SAVED"); marker("NATIVE_COMPLETED"); return m;
  }
  public static void main(String[] args) throws Exception {
    try { run(); } catch(Exception error) {
      marker("FAILED "+error.getClass().getName()+": "+error.getMessage()); throw error;
    }
  }
}
"""


def _render_parts(turn_angle_deg=15.0, minimum_radius_um=3.0, width_um=0.3, samples=64):
    profile, fragment = profile_module().render_profile(turn_angle_deg, minimum_radius_um, width_um, samples)
    identity = digest(canonical(profile))
    readbacks = []
    for segment in profile["segments"]:
        tag = segment["tag"]
        if segment["kind"] == "euler":
            readbacks.append(
                '    marker("RECORD {\\"kind\\":\\"table\\",\\"tag\\":\\"'
                + tag
                + '\\",\\"values\\":"+Arrays.deepToString(g.feature("'
                + tag
                + '").getDoubleMatrix("table"))+"}");'
            )
        else:
            readbacks.append(
                '    marker("RECORD {\\"kind\\":\\"rectangle\\",\\"tag\\":\\"'
                + tag
                + '\\",\\"pos\\":"+Arrays.toString(g.feature("'
                + tag
                + '").getDoubleArray("pos"))+",\\"size\\":"+Arrays.toString(g.feature("'
                + tag
                + '").getDoubleArray("size"))+"}");'
            )
    # Literal substitution is restricted to generated numeric geometry/fixed tags.
    text = JAVA.replace("__IDENTITY__", identity).replace("__FRAGMENT_SHA256__", digest(fragment))
    text = text.replace("__FRAGMENT__", fragment.decode("utf-8")).replace("__ACTUAL_FEATURES__", "\n".join(readbacks))
    return profile, fragment, text.encode("utf-8")


def render_geometry_probe(turn_angle_deg=15.0, minimum_radius_um=3.0, width_um=0.3, samples=64):
    profile, _, source = _render_parts(turn_angle_deg, minimum_radius_um, width_um, samples)
    return profile, source


def bundle_parts(turn_angle_deg=15.0, minimum_radius_um=3.0, width_um=0.3, samples=64):
    profile, fragment, source = _render_parts(turn_angle_deg, minimum_radius_um, width_um, samples)
    members = {
        "geometry.json": serialized(profile),
        "geometry_fragment.java": fragment,
        "BendGeometryProbe.java": source,
    }
    manifest = {
        "schema_version": "1.0",
        "stage": "geometry_only_native_probe",
        "parameters": profile["parameters"],
        "geometry_identity": digest(canonical(profile)),
        "source_sha256": digest(source),
        "fragment_sha256": digest(fragment),
        "files": {name: digest(data) for name, data in members.items()},
        "dependencies": dependencies(),
        "will_execute": False,
        "physics_accepted": False,
        "native_execution": "not_performed",
    }
    return members, manifest


def prepare_bundle(output, turn_angle_deg=15.0, minimum_radius_um=3.0, width_um=0.3, samples=64):
    output = safe(output)
    if os.path.lexists(output):
        raise ValueError("Output path must not already exist")
    members, manifest = bundle_parts(turn_angle_deg, minimum_radius_um, width_um, samples)
    output.mkdir()  # Exclusive creation; parent directory must already exist.
    for name, data in {**members, "manifest.json": serialized(manifest)}.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    return manifest


def verify_bundle(bundle):
    bundle = safe(bundle, directory=True)
    if {member.name for member in bundle.iterdir()} != BUNDLE_FILES:
        raise ValueError("Bundle file census mismatch")
    for name in BUNDLE_FILES:
        if not safe(bundle / name).is_file():
            raise ValueError("Bundle member is not a regular file")
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    parameters = manifest.get("parameters") if isinstance(manifest, dict) else None
    if not isinstance(parameters, dict) or set(parameters) != PARAMETERS:
        raise ValueError("Invalid geometry parameters")
    members, expected = bundle_parts(**parameters)
    if manifest != expected or (bundle / "manifest.json").read_bytes() != serialized(expected):
        raise ValueError("Bundle manifest or producer identity mismatch")
    for name, expected_bytes in members.items():
        if (bundle / name).read_bytes() != expected_bytes:
            raise ValueError("Bundle member differs from trusted rendering: " + name)
    return expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    prepare = operations.add_parser("prepare", help="Write a new offline geometry probe bundle")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--turn-angle-deg", type=float, default=15.0)
    prepare.add_argument("--minimum-radius-um", type=float, default=3.0)
    prepare.add_argument("--width-um", type=float, default=0.3)
    prepare.add_argument("--samples", type=int, default=64)
    verify = operations.add_parser("verify", help="Read-only verification against this trusted tool")
    verify.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "prepare":
            result = prepare_bundle(
                args.output, args.turn_angle_deg, args.minimum_radius_um, args.width_um, args.samples
            )
        else:
            result = verify_bundle(args.bundle)
        print(serialized(result).decode("utf-8"), end="")
    except (ValueError, TypeError, OSError, UnicodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
