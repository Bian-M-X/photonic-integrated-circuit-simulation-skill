"""Data-only generation and supervised execution of small native PIC models.

The generated COMSOL model is a 2D out-of-plane scalar index surrogate. A
completed solve is diagnostic evidence, never automatic device qualification.
All Java is generated from validated numeric primitives; bundles cannot supply
arbitrary Java, Python, commands, or result expressions.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import suppress
from itertools import pairwise
from pathlib import Path
from typing import Any

_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")
_FAMILIES = {"straight", "crossing", "directional-coupler", "mmi2x2", "ybranch", "ring", "ring-modulator"}
_CONFIG_DEFAULTS = {
    "wavelengths_nm": [1550.0],
    "core_index": 2.6,
    "cladding_index": 1.45,
    "active_index": None,
    "active_extinction": 0.0,
    "core_mesh_um": 0.08,
    "cladding_mesh_um": 0.28,
    "port_mesh_um": None,
    "export_fields": True,
    "measure_mesh_area": False,
    "stage": "solve",
}


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must lie in [{low}, {high}]")
    return value


def _numeric_list(value: Any, count: int, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(f"{name} requires {count} numeric entries")
    return [_number(x, name, -10000, 10000) for x in value]


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _validate_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(geometry, dict) or geometry.get("family") not in _FAMILIES:
        raise ValueError("Unsupported native device family")
    # Copy through strict JSON, rejecting executable/custom objects and nonfinite
    # metadata as well as all executable fields below.
    value = json.loads(_canonical(geometry))
    bounds = _numeric_list(value.get("bbox_um"), 4, "bbox_um")
    if not bounds[0] < bounds[1] or not bounds[2] < bounds[3]:
        raise ValueError("Nonpositive background extent")
    if max(bounds[1] - bounds[0], bounds[3] - bounds[2]) > 200:
        raise ValueError("Native diagnostic box exceeds 200 um")
    primitives = value.get("primitives")
    if not isinstance(primitives, list) or not 1 <= len(primitives) <= 64:
        raise ValueError("Expected 1..64 geometry primitives")
    tags: set[str] = set()
    for primitive in primitives:
        if not isinstance(primitive, dict) or not _TAG.fullmatch(str(primitive.get("tag", ""))):
            raise ValueError("Invalid primitive tag")
        tag = primitive["tag"]
        if tag in tags or tag.startswith("pic"):
            raise ValueError("Duplicate or reserved primitive tag")
        tags.add(tag)
        if primitive.get("group") not in {"core", "active"}:
            raise ValueError("Primitive group must be core or active")
        kind = primitive.get("type")
        allowed = {"tag", "type", "group"}
        if kind == "rectangle":
            allowed |= {"x", "y", "width", "height"}
            x = _number(primitive.get("x"), "rectangle x", -10000, 10000)
            y = _number(primitive.get("y"), "rectangle y", -10000, 10000)
            w = _number(primitive.get("width"), "rectangle width", 1e-5, 200)
            h = _number(primitive.get("height"), "rectangle height", 1e-5, 200)
            points = [(x, y), (x + w, y + h)]
        elif kind == "polygon":
            allowed |= {"points"}
            if not isinstance(primitive.get("points"), list) or not 3 <= len(primitive["points"]) <= 2048:
                raise ValueError("Polygon requires 3..2048 vertices")
            points = [_numeric_list(point, 2, "polygon point") for point in primitive["points"]]
            area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True))
            if abs(area) < 1e-9:
                raise ValueError("Degenerate polygon")
        elif kind == "ring":
            allowed |= {"cx", "cy", "outer_radius", "inner_radius"}
            cx = _number(primitive.get("cx"), "ring cx", -10000, 10000)
            cy = _number(primitive.get("cy"), "ring cy", -10000, 10000)
            outer = _number(primitive.get("outer_radius"), "outer radius", 0.05, 100)
            inner = _number(primitive.get("inner_radius"), "inner radius", 0, outer)
            if inner >= outer:
                raise ValueError("Ring radii must define positive width")
            points = [(cx - outer, cy - outer), (cx + outer, cy + outer)]
        else:
            raise ValueError("Unsupported primitive type")
        if set(primitive) != allowed:
            raise ValueError(f"Unknown or missing {kind} primitive fields")
        for x, y in points:
            if not bounds[0] - 1e-9 <= x <= bounds[1] + 1e-9 or not bounds[2] - 1e-9 <= y <= bounds[3] + 1e-9:
                raise ValueError("Primitive lies outside background box")
    ports = value.get("ports")
    if not isinstance(ports, list) or not 2 <= len(ports) <= 4:
        raise ValueError("Native models require 2..4 ports")
    names: set[str] = set()
    spans: dict[str, list[tuple[float, float]]] = {side: [] for side in ("left", "right", "bottom", "top")}
    for port in ports:
        if not isinstance(port, dict) or set(port) != {"name", "side", "center_um", "width_um", "window_um"}:
            raise ValueError("Unknown or missing port fields")
        if not _TAG.fullmatch(str(port["name"])) or port["name"] in names or port["side"] not in spans:
            raise ValueError("Invalid or duplicate port name/side")
        names.add(port["name"])
        x, y = _numeric_list(port["center_um"], 2, "port center")
        width = _number(port["width_um"], "port width", 0.02, 10)
        window = _number(port["window_um"], "port window", width, 20)
        side = port["side"]
        axis = 0 if side in {"left", "right"} else 1
        expected = bounds[{"left": 0, "right": 1, "bottom": 2, "top": 3}[side]]
        if abs((x, y)[axis] - expected) > 1e-9:
            raise ValueError("Port center must be on its declared exterior face")
        center = (x, y)[1 - axis]
        lower, upper = center - window / 2, center + window / 2
        face_low, face_high = (bounds[2], bounds[3]) if axis == 0 else (bounds[0], bounds[1])
        if lower < face_low - 1e-9 or upper > face_high + 1e-9:
            raise ValueError("Port window exceeds exterior face")
        if any(min(upper, b) - max(lower, a) > -1e-8 for a, b in spans[side]):
            raise ValueError("Port windows on the same face must be separated")
        spans[side].append((lower, upper))
    area = value.get("expected_core_area_um2")
    if area is not None:
        _number(area, "expected core area", 1e-9, 40000)
    components = value.get("expected_core_components")
    if isinstance(components, bool) or not isinstance(components, int) or not 1 <= components <= 8:
        raise ValueError("Expected core component count must be 1..8")
    return value


def normalize_native_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the bounded solver configuration; this does not execute anything."""
    if config is not None and (not isinstance(config, dict) or set(config) - set(_CONFIG_DEFAULTS)):
        raise ValueError("Unknown native configuration fields")
    value = _CONFIG_DEFAULTS | (config or {})
    waves = value["wavelengths_nm"]
    if not isinstance(waves, list) or not 1 <= len(waves) <= 161:
        raise ValueError("Expected 1..161 wavelengths")
    value["wavelengths_nm"] = [_number(w, "wavelength_nm", 1200, 1700) for w in waves]
    if len(set(value["wavelengths_nm"])) != len(waves):
        raise ValueError("Duplicate wavelengths are ambiguous")
    for key in ("core_index", "cladding_index"):
        value[key] = _number(value[key], key, 1, 5)
    if value["cladding_index"] >= value["core_index"]:
        raise ValueError("Core index must exceed cladding index")
    if value["active_index"] is None:
        value["active_index"] = value["core_index"]
    value["active_index"] = _number(value["active_index"], "active_index", value["cladding_index"] + 0.01, 5)
    value["active_extinction"] = _number(value["active_extinction"], "active_extinction", 0, 0.2)
    value["core_mesh_um"] = _number(value["core_mesh_um"], "core_mesh_um", 0.005, 0.2)
    value["cladding_mesh_um"] = _number(value["cladding_mesh_um"], "cladding_mesh_um", 0.01, 0.6)
    if value["port_mesh_um"] is not None:
        value["port_mesh_um"] = _number(value["port_mesh_um"], "port_mesh_um", 0.005, 0.2)
    if value["stage"] not in {"configure", "modes", "solve"}:
        raise ValueError("Native stage must be configure, modes, or solve")
    if type(value["export_fields"]) is not bool:
        raise ValueError("export_fields must be a boolean")
    if type(value["measure_mesh_area"]) is not bool:
        raise ValueError("measure_mesh_area must be a boolean")
    return value


def _jnumber(value: float) -> str:
    return repr(float(value))


def _jarray(values: list[float]) -> str:
    return "new double[]{" + ",".join(_jnumber(v) for v in values) + "}"


def _jstrings(values: list[str]) -> str:
    return "new String[]{" + ",".join(json.dumps(v) for v in values) + "}"


def _geometry_java(geometry: dict[str, Any]) -> str:
    x0, x1, y0, y1 = geometry["bbox_um"]
    xcuts, ycuts = {x0, x1}, {y0, y1}
    for port in geometry["ports"]:
        x, y = port["center_um"]
        half = port["window_um"] / 2
        if port["side"] in {"left", "right"}:
            ycuts.update((y - half, y + half))
        else:
            xcuts.update((x - half, x + half))
    xs, ys = sorted(xcuts), sorted(ycuts)
    lines = []
    for i, (a, b) in enumerate(pairwise(xs)):
        for j, (c, d) in enumerate(pairwise(ys)):
            lines.append(f'rect(g,"picbg{i}_{j}",{a},{c},{b - a},{d - c});')
    groups: dict[str, list[str]] = {"core": [], "active": []}
    for primitive in geometry["primitives"]:
        tag = primitive["tag"]
        groups[primitive["group"]].append(f"g_{tag}_dom")
        if primitive["type"] == "rectangle":
            p = primitive
            lines.append(f'rect(g,"{tag}",{p["x"]},{p["y"]},{p["width"]},{p["height"]});')
        elif primitive["type"] == "polygon":
            points = ",".join("{" + ",".join(_jnumber(v) for v in xy) + "}" for xy in primitive["points"])
            lines.extend(
                [
                    f'g.create("{tag}","Polygon");g.feature("{tag}").set("source","table");',
                    f'g.feature("{tag}").set("table",new double[][]{{{points}}});',
                    f'g.feature("{tag}").set("type","solid");',
                ]
            )
        else:
            p = primitive
            for suffix, radius in (("o", p["outer_radius"]), ("i", p["inner_radius"])):
                lines.extend(
                    [
                        f'g.create("{tag}{suffix}","Circle");',
                        f'g.feature("{tag}{suffix}").set("pos",{_jarray([p["cx"], p["cy"]])});',
                        f'g.feature("{tag}{suffix}").set("r",{radius});',
                    ]
                )
            lines.extend(
                [
                    f'g.create("{tag}","Difference");',
                    f'g.feature("{tag}").selection("input").set(new String[]{{"{tag}o"}});',
                    f'g.feature("{tag}").selection("input2").set(new String[]{{"{tag}i"}});',
                ]
            )
        lines.append(f'g.feature("{tag}").set("selresult","on");')
    lines.extend(
        [
            "g.run();",
            f'union(m,"semPassive",{_jstrings(groups["core"])});',
            f'union(m,"semActive",{_jstrings(groups["active"])});',
            'union(m,"semCore",new String[]{"semPassive","semActive"});',
        ]
    )
    for index, port in enumerate(geometry["ports"], 1):
        x, y = port["center_um"]
        half = port["window_um"] / 2
        eps = 1e-6
        bounds = (
            [x - eps, x + eps, y - half - eps, y + half + eps]
            if port["side"] in {"left", "right"}
            else [
                x - half - eps,
                x + half + eps,
                y - eps,
                y + eps,
            ]
        )
        lines.append(f'box(m,"p{index}",{",".join(_jnumber(v) for v in bounds)});')
    return "\n    ".join(lines)


def render_java(
    geometry: dict[str, Any],
    *,
    wavelengths_nm: list[float],
    core_index: float = 2.6,
    cladding_index: float = 1.45,
    active_index: float | None = None,
    active_extinction: float = 0.0,
    core_mesh_um: float = 0.08,
    cladding_mesh_um: float = 0.28,
    port_mesh_um: float | None = None,
    export_fields: bool = True,
    measure_mesh_area: bool = False,
    stage: str = "solve",
) -> str:
    """Render a standalone ``NativePic`` Java model from numeric data only."""
    geometry = _validate_geometry(geometry)
    config = normalize_native_config(
        {
            "wavelengths_nm": wavelengths_nm,
            "core_index": core_index,
            "cladding_index": cladding_index,
            "active_index": active_index,
            "active_extinction": active_extinction,
            "core_mesh_um": core_mesh_um,
            "cladding_mesh_um": cladding_mesh_um,
            "port_mesh_um": port_mesh_um,
            "export_fields": export_fields,
            "measure_mesh_area": measure_mesh_area,
            "stage": stage,
        }
    )
    replacements = {
        "__GEOMETRY__": _geometry_java(geometry),
        "__STAGE__": config["stage"],
        "__WAVES__": _jarray(config["wavelengths_nm"]),
        "__PORTS__": str(len(geometry["ports"])),
        "__NCORE__": _jnumber(config["core_index"]),
        "__NCLAD__": _jnumber(config["cladding_index"]),
        "__NACTIVE__": _jnumber(config["active_index"]),
        "__KACTIVE__": _jnumber(config["active_extinction"]),
        "__COREMESH__": _jnumber(config["core_mesh_um"]),
        "__BGMESH__": _jnumber(config["cladding_mesh_um"]),
        "__WIDTHS__": _jarray([p["width_um"] for p in geometry["ports"]]),
        "__WINDOWS__": _jarray([p["window_um"] for p in geometry["ports"]]),
        "__COMPONENTS__": str(geometry["expected_core_components"]),
        "__AREA__": _jnumber(geometry.get("expected_core_area_um2") or -1),
    }
    source = _JAVA
    for key, value in replacements.items():
        source = source.replace(key, value)
    if not config["export_fields"]:
        source = source.replace('      if(lambda==WAVES[0])exportField(m,ds,main,lambda);', "")
    if config["port_mesh_um"] is not None:
        before_tri = '    m.component("c").mesh("mesh").create("tri","FreeTri");'
        if source.count(before_tri) != 1:
            raise RuntimeError("Unknown native mesh insertion point")
        mesh_value = _jnumber(config["port_mesh_um"])
        port_mesh = '''    Set<Integer> portEdges=new TreeSet<>();
    for(int k=1;k<=N;k++)portEdges.addAll(ids(m.component("c").selection("p"+k).entities(1)));
    m.component("c").mesh("mesh").create("portSize","Size");
    m.component("c").mesh("mesh").feature("portSize").selection().geom("g",1);
    m.component("c").mesh("mesh").feature("portSize").selection().set(array(portEdges));
    m.component("c").mesh("mesh").feature("portSize").set("custom",true);
    m.component("c").mesh("mesh").feature("portSize").set("hmax","__PORTMESH__[um]");
    require(ids(m.component("c").mesh("mesh").feature("portSize").selection().entities(1)).equals(portEdges),
      "Port mesh selection mismatch");
    marker("PORT_MESH "+m.component("c").mesh("mesh").feature("portSize").getString("hmax")+
      " "+Arrays.toString(array(portEdges)));'''.replace("__PORTMESH__", mesh_value)
        source = source.replace(before_tri, port_mesh + "\n" + before_tri)
    if config["measure_mesh_area"]:
        before_mesh = '    m.component("c").mesh().create("mesh");'
        after_solve = '      String ds=dataset(m,main);'
        if source.count(before_mesh) != 1 or source.count(after_solve) != 1:
            raise RuntimeError("Unknown native area integration insertion point")
        area_operators = '''    String[] areaLabels={"core","active","bg","all"};
    String[] areaSelections={"semCore","semActive","semBg","allDomains"};
    for(int a=0;a<areaLabels.length;a++){
      if(m.component("c").selection(areaSelections[a]).entities(2).length==0)continue;
      String op="intArea"+a;
      m.component("c").cpl().create(op,"Integration");
      m.component("c").cpl(op).selection().geom("g",2);
      m.component("c").cpl(op).selection().named(areaSelections[a]);
      m.component("c").cpl(op).set("intorder",8);
      require(m.component("c").cpl(op).getInt("intorder")==8,"Area quadrature settings mismatch");
      require(ids(m.component("c").cpl(op).selection().entities(2)).equals(
        ids(m.component("c").selection(areaSelections[a]).entities(2))),"Area integration selection mismatch");
      marker("AREA_MESH_OPERATOR "+areaLabels[a]+" "+m.component("c").cpl(op).getInt("intorder")+" "+
        Arrays.toString(m.component("c").cpl(op).selection().entities(2)));
    }'''
        area_values = '''      if(lambda==WAVES[0]){
        String[] areaLabels={"core","active","bg","all"};
        String[] areaSelections={"semCore","semActive","semBg","allDomains"};
        for(int a=0;a<areaLabels.length;a++){
          if(m.component("c").selection(areaSelections[a]).entities(2).length==0){
            marker("AREA_MESH "+areaLabels[a]+" 0.0");continue;
          }
          double[][] area=series(m,ds,"intArea"+a+"(1)/(1[um^2])");
          require(area[0].length==N&&area[1].length==N,"Area source axis mismatch");
          require(area[0][0]>0,"Nonpositive curved-mesh domain area");
          for(int j=0;j<N;j++)require(Math.abs(area[0][j]-area[0][0])<1e-10*
            Math.max(1,area[0][0])&&Math.abs(area[1][j])<1e-10,"Source-dependent curved-mesh area");
          marker("AREA_MESH "+areaLabels[a]+" "+area[0][0]);
        }
      }'''
        source = source.replace(before_mesh, area_operators + "\n" + before_mesh)
        source = source.replace(after_solve, after_solve + "\n" + area_values)
    if re.search(r"__[A-Z]+__", source):
        raise RuntimeError("Unrendered native model placeholder")
    return source


# Preserve generated Java blank-line bytes used by existing native receipts.
_JAVA = r"""import com.comsol.model.*;
__INDENTED_BLANK__
import com.comsol.model.util.*;
__INDENTED_BLANK__
import java.util.*;
__INDENTED_BLANK__

/** Original data-generated 2D scalar PIC diagnostic. No proprietary model. */
public final class NativePic {
__INDENTED_BLANK__
  static final int N=__PORTS__, EXPECTED_COMPONENTS=__COMPONENTS__;
__INDENTED_BLANK__
  static final String STAGE="__STAGE__";
__INDENTED_BLANK__
  static final double[] WAVES=__WAVES__, WIDTHS=__WIDTHS__, WINDOWS=__WINDOWS__;
__INDENTED_BLANK__
  static final double NC=__NCORE__, NB=__NCLAD__, NA=__NACTIVE__, KA=__KACTIVE__, EXPECTED_AREA=__AREA__;
__INDENTED_BLANK__
  static void marker(String text){
    System.out.println("PIC "+text);
    }
__INDENTED_BLANK__
  static void require(boolean ok,String text){
    if(!ok)throw new IllegalStateException(text);
    }
__INDENTED_BLANK__
  static Set<Integer> ids(int[] a){
    Set<Integer>s=new TreeSet<>();
    for(int n:a)s.add(n);
    return s;
    }
__INDENTED_BLANK__
  static int[] array(Set<Integer>s){
    return s.stream().mapToInt(Integer::intValue).toArray();
    }
__INDENTED_BLANK__
  static void rect(GeomSequence g,String t,double x,double y,double w,double h){
__INDENTED_BLANK__
    g.create(t,"Rectangle");
    g.feature(t).set("pos",new double[]{
    x,y}
    );
__INDENTED_BLANK__
    g.feature(t).set("size",new double[]{
    w,h}
    );
    g.feature(t).set("selresult","on");
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static void union(Model m,String tag,String[] add){
__INDENTED_BLANK__
    if(add.length==0){
    m.component("c").selection().create(tag,"Explicit");
    m.component("c").selection(tag).geom("g",2);
    }
__INDENTED_BLANK__
    else {
    m.component("c").selection().create(tag,"Union");
    m.component("c").selection(tag).set("entitydim",2);
    m.component("c").selection(tag).set("input",add);
    }
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static void box(Model m,String t,double x0,double x1,double y0,double y1){
__INDENTED_BLANK__
    m.component("c").selection().create(t,"Box");
    m.component("c").selection(t).set("entitydim",1);
__INDENTED_BLANK__
    m.component("c").selection(t).set("condition","inside");
__INDENTED_BLANK__
    m.component("c").selection(t).set("xmin",x0);
    m.component("c").selection(t).set("xmax",x1);
__INDENTED_BLANK__
    m.component("c").selection(t).set("ymin",y0);
    m.component("c").selection(t).set("ymax",y1);
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static void material(Model m,String tag,String selection,double n,double k){
__INDENTED_BLANK__
    m.component("c").material().create(tag,"Common");
    m.component("c").material(tag).selection().named(selection);
__INDENTED_BLANK__
    m.component("c").material(tag).propertyGroup().create("RefractiveIndex","Refractive index");
__INDENTED_BLANK__
    m.component("c").material(tag).propertyGroup("RefractiveIndex").set("n",new String[]{
    ""+n}
    );
__INDENTED_BLANK__
    m.component("c").material(tag).propertyGroup("RefractiveIndex").set("ki",new String[]{
    ""+k}
    );
__INDENTED_BLANK__
    m.component("c").material(tag).propertyGroup("def").set("relpermeability",new String[]{
    "1","0","0","0","1","0","0","0","1"}
    );
__INDENTED_BLANK__
    m.component("c").material(tag).propertyGroup("def").set("electricconductivity",new String[]{
    "0","0","0","0","0","0","0","0","0"}
    );
__INDENTED_BLANK__
    require(ids(m.component("c").material(tag).selection().entities(2)).equals(ids(m.component("c")
    .selection(selection).entities(2))),"Material entity mismatch");
__INDENTED_BLANK__
    for(String x:m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("n"))require(Math
    .abs(Double.parseDouble(x)-n)<1e-12,"Material n mismatch");
__INDENTED_BLANK__
    for(String x:m.component("c").material(tag).propertyGroup("RefractiveIndex").getStringArray("ki"))require(Math
    .abs(Double.parseDouble(x)-k)<1e-12,"Material extinction mismatch");
__INDENTED_BLANK__
    marker("MATERIAL "+tag+" "+n+" "+k+" "+Arrays.toString(m.component("c").material(tag)
    .selection().entities(2)));
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static double measure(Model m,String selection,int dim){
__INDENTED_BLANK__
    m.component("c").geom("g").measureFinal().selection().geom("g",dim);
__INDENTED_BLANK__
    m.component("c").geom("g").measureFinal().selection().set(m.component("c").selection(selection)
    .entities(dim));
__INDENTED_BLANK__
    return m.component("c").geom("g").measureFinal().getVolume();
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static double[] bounds(Model m,String selection,int dim){
__INDENTED_BLANK__
    m.component("c").geom("g").measureFinal().selection().geom("g",dim);
__INDENTED_BLANK__
    m.component("c").geom("g").measureFinal().selection().set(m.component("c").selection(selection)
    .entities(dim));
__INDENTED_BLANK__
    return m.component("c").geom("g").measureFinal().getBoundingBox();
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static int components(Model m,int[] domains){
__INDENTED_BLANK__
    m.component("c").selection().create("adjTmp","Explicit");
    m.component("c").selection("adjTmp").geom("g",2,1,new String[]{
    "exterior"}
    );
__INDENTED_BLANK__
    List<Set<Integer>> edges=new ArrayList<>();
__INDENTED_BLANK__
    for(int dom:domains){
    m.component("c").selection("adjTmp").set(new int[]{
    dom}
    );
    edges.add(ids(m.component("c").selection("adjTmp").entities(1)));
    }
__INDENTED_BLANK__
    int[] group=new int[domains.length];
    for(int i=0;
    i<group.length;
    i++)group[i]=i;
__INDENTED_BLANK__
    for(int i=0;
    i<group.length;
    i++)for(int j=0;
    j<i;
    j++){
__INDENTED_BLANK__
      Set<Integer> shared=new TreeSet<>(edges.get(i));
    shared.retainAll(edges.get(j));
__INDENTED_BLANK__
      if(!shared.isEmpty()){
    int a=group[i],b=group[j];
    for(int k=0;
    k<group.length;
    k++)if(group[k]==a)group[k]=b;
    }
__INDENTED_BLANK__
    }
__INDENTED_BLANK__
    Set<Integer> unique=new TreeSet<>();
    for(int i:group)unique.add(i);
    m.component("c").selection().remove("adjTmp");
    return unique.size();
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static void auditGeometry(Model m){
__INDENTED_BLANK__
    Set<Integer> core=ids(m.component("c").selection("semCore").entities(2));
__INDENTED_BLANK__
    Set<Integer> passive=ids(m.component("c").selection("semPassive").entities(2));
__INDENTED_BLANK__
    Set<Integer> active=ids(m.component("c").selection("semActive").entities(2));
__INDENTED_BLANK__
    Set<Integer> overlap=new TreeSet<>(passive);
    overlap.retainAll(active);
    require(overlap.isEmpty(),"Passive/active domains overlap");
__INDENTED_BLANK__
    Set<Integer> bg=ids(m.component("c").selection("semBg").entities(2));
__INDENTED_BLANK__
    Set<Integer> all=ids(m.component("c").selection("allDomains").entities(2));
__INDENTED_BLANK__
    require(!core.isEmpty()&&!bg.isEmpty(),"Empty semantic domains");
__INDENTED_BLANK__
    overlap=new TreeSet<>(core);
    overlap.retainAll(bg);
    require(overlap.isEmpty(),"Core/background overlap");
__INDENTED_BLANK__
    Set<Integer> cover=new TreeSet<>(core);
    cover.addAll(bg);
    require(cover.equals(all),"Material partition incomplete");
__INDENTED_BLANK__
    double coreArea=measure(m,"semCore",2);
    marker("AREA core "+coreArea);
__INDENTED_BLANK__
    marker("AREA active "+(active.isEmpty()?0:measure(m,"semActive",2)));
__INDENTED_BLANK__
    marker("AREA bg "+measure(m,"semBg",2));
    marker("AREA all "+measure(m,"allDomains",2));
__INDENTED_BLANK__
    marker("CORE_BBOX "+Arrays.toString(bounds(m,"semCore",2)));
__INDENTED_BLANK__
    if(EXPECTED_AREA>0)require(Math.abs(coreArea-EXPECTED_AREA)<Math.max(1e-5,EXPECTED_AREA*0.002),
    "Core area differs from proposal");
__INDENTED_BLANK__
    int count=components(m,array(core));
    marker("CORE_COMPONENTS "+count);
    require(count==EXPECTED_COMPONENTS,"Core topology mismatch");
__INDENTED_BLANK__
    marker("GEOMETRY_PASS");
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static void auditPorts(Model m){
__INDENTED_BLANK__
    Set<Integer> seen=new TreeSet<>();
__INDENTED_BLANK__
    for(int k=1;
    k<=N;
    k++){
__INDENTED_BLANK__
      Set<Integer> port=ids(m.component("c").selection("p"+k).entities(1));
    require(!port.isEmpty(),"Empty port window");
__INDENTED_BLANK__
      for(int edge:port)require(seen.add(edge),"Overlapping port windows");
__INDENTED_BLANK__
      double len=measure(m,"p"+k,1);
    double[] b=bounds(m,"p"+k,1);
__INDENTED_BLANK__
      marker("PORT_GEOMETRY "+k+" "+len+" "+b[0]+" "+b[1]+" "+b[2]+" "+b[3]);
__INDENTED_BLANK__
      require(Math.abs(len-WINDOWS[k-1])<1e-5,"Actual port-window extent mismatch");
__INDENTED_BLANK__
      Set<Integer> ends=new TreeSet<>(port);
    ends.retainAll(ids(m.component("c").selection("coreBoundary").entities(1)));
__INDENTED_BLANK__
      String end="coreEnd"+k;
    m.component("c").selection().create(end,"Explicit");
    m.component("c").selection(end).geom("g",1);
    m.component("c").selection(end).set(array(ends));
__INDENTED_BLANK__
      double width=measure(m,end,1);
    marker("CORE_END "+k+" "+width);
    require(Math.abs(width-WIDTHS[k-1])<1e-5,"Actual port core width mismatch");
__INDENTED_BLANK__
    }
__INDENTED_BLANK__
    Set<Integer> open=ids(m.component("c").selection("open").entities(1));
__INDENTED_BLANK__
    for(int edge:open)require(seen.add(edge),"Open boundary overlaps ports");
__INDENTED_BLANK__
    require(seen.equals(ids(m.component("c").selection("exterior").entities(1))),"Exterior partition incomplete");
__INDENTED_BLANK__
    marker("PORTS_PASS");
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static Model build(){
__INDENTED_BLANK__
    Model m=ModelUtil.create("NativePic");
    m.modelPath(".");
    m.label("Original scalar PIC diagnostic");
__INDENTED_BLANK__
    m.param().set("lambda0",WAVES[0]+"[nm]");
    m.param().set("f0","c_const/lambda0");
__INDENTED_BLANK__
    m.component().create("c",true);
    m.component("c").geom().create("g",2);
    GeomSequence g=m.component("c").geom("g");
    g.lengthUnit("um");
__INDENTED_BLANK__
    __GEOMETRY__
    String unit=g.lengthUnit();
    marker("UNIT_CODEPOINTS "+Arrays.toString(unit.codePoints().toArray()));
__INDENTED_BLANK__
    require("um".equals(unit)||"\u00b5m".equals(unit)||"\u03bcm".equals(unit),"Unknown geometry unit");
    marker("UNIT um");
    marker("ENTITY_COUNTS "+Arrays.toString(g.getNEntities()));
__INDENTED_BLANK__
    m.component("c").selection().create("allDomains","Explicit");
    m.component("c").selection("allDomains").geom("g",2);
    m.component("c").selection("allDomains").all();
__INDENTED_BLANK__
    m.component("c").selection().create("semBg","Difference");
    m.component("c").selection("semBg").set("entitydim",2);
    m.component("c").selection("semBg").set("add",new String[]{
    "allDomains"}
    );
    m.component("c").selection("semBg").set("subtract",new String[]{
    "semCore"}
    );
__INDENTED_BLANK__
    if(m.component("c").selection("semPassive").entities(2).length>0)material(m,"passiveMat",
    "semPassive",NC,0);
__INDENTED_BLANK__
    if(m.component("c").selection("semActive").entities(2).length>0)material(m,"activeMat",
    "semActive",NA,KA);
__INDENTED_BLANK__
    material(m,"cladMat","semBg",NB,0);
    auditGeometry(m);
__INDENTED_BLANK__
    m.component("c").selection().create("exterior","Explicit");
    m.component("c").selection("exterior").geom("g",2,1,new String[]{
    "exterior"}
    );
    m.component("c").selection("exterior").all();
__INDENTED_BLANK__
    String[] portTags=new String[N];
    for(int k=1;
    k<=N;
    k++)portTags[k-1]="p"+k;
__INDENTED_BLANK__
    m.component("c").selection().create("open","Difference");
    m.component("c").selection("open").set("entitydim",1);
    m.component("c").selection("open").set("add",new String[]{
    "exterior"}
    );
    m.component("c").selection("open").set("subtract",portTags);
__INDENTED_BLANK__
    m.component("c").selection().create("coreBoundary","Explicit");
    m.component("c").selection("coreBoundary").geom("g",2,1,new String[]{
    "exterior"}
    );
    m.component("c").selection("coreBoundary").set(m.component("c").selection("semCore")
    .entities(2));
    auditPorts(m);
__INDENTED_BLANK__
    if(STAGE.equals("configure"))return m;
__INDENTED_BLANK__
    m.component("c").physics().create("ewfd","ElectromagneticWavesFrequencyDomain","g");
    m.component("c").physics("ewfd").prop("components").set("components","outofplane");
    m.component("c").physics("ewfd").feature("wee1").set("DisplacementFieldModel","RefractiveIndex");
__INDENTED_BLANK__
    for(int k=1;
    k<=N;
    k++){
__INDENTED_BLANK__
      String t="port"+k;
    m.component("c").physics("ewfd").create(t,"Port",1);
    m.component("c").physics("ewfd").feature(t).selection().named("p"+k);
__INDENTED_BLANK__
      m.component("c").physics("ewfd").feature(t).set("PortType","Numeric");
    m.component("c").physics("ewfd").feature(t).set("PortName",""+k);
    m.component("c").physics("ewfd").feature(t).set("Pin","1[W/m]");
    m.component("c").physics("ewfd").feature(t).set("Thetap","0");
    m.component("c").physics("ewfd").feature(t).set("PortExcitation","on");
__INDENTED_BLANK__
      m.component("c").cpl().create("intp"+k,"Integration");
    m.component("c").cpl("intp"+k).selection().geom("g",1);
    m.component("c").cpl("intp"+k).selection().named("p"+k);
__INDENTED_BLANK__
      require("Numeric".equals(m.component("c").physics("ewfd").feature(t).getString("PortType"))&&(""+k)
    .equals(m.component("c").physics("ewfd").feature(t).getString("PortName")),"Native port binding");
__INDENTED_BLANK__
    }
__INDENTED_BLANK__
    m.component("c").physics("ewfd").create("sctr","Scattering",1);
    m.component("c").physics("ewfd").feature("sctr").selection().named("open");
__INDENTED_BLANK__
    m.component("c").cpl().create("intopen","Integration");
    m.component("c").cpl("intopen").selection().geom("g",1);
    m.component("c").cpl("intopen").selection().named("open");
__INDENTED_BLANK__
    m.component("c").cpl().create("intabs","Integration");
    m.component("c").cpl("intabs").selection().geom("g",2);
    m.component("c").cpl("intabs").selection().named("allDomains");
__INDENTED_BLANK__
    m.component("c").mesh().create("mesh");
    m.component("c").mesh("mesh").feature("size").set("custom",true);
    m.component("c").mesh("mesh").feature("size").set("hmax","__BGMESH__[um]");
    m.component("c").mesh("mesh").feature("size").set("hmin","0.005[um]");
__INDENTED_BLANK__
    m.component("c").mesh("mesh").create("coreSize","Size");
    m.component("c").mesh("mesh").feature("coreSize").selection().geom("g",2);
    m.component("c").mesh("mesh").feature("coreSize").selection().named("semCore");
    m.component("c").mesh("mesh").feature("coreSize").set("custom",true);
    m.component("c").mesh("mesh").feature("coreSize").set("hmax","__COREMESH__[um]");
    m.component("c").mesh("mesh").create("tri","FreeTri");
__INDENTED_BLANK__
    m.study().create("std");
__INDENTED_BLANK__
    for(int k=1;
    k<=N;
    k++){
    String t="bma"+k;
    m.study("std").create(t,"BoundaryModeAnalysis");
    m.study("std").feature(t).set("PortName",""+k);
    m.study("std").feature(t).set("modeFreq","f0");
    m.study("std").feature(t).set("shift",""+((NC+NB)/2));
    m.study("std").feature(t).set("neigs",1);
    m.study("std").feature(t).set("neigsactive",true);
    }
__INDENTED_BLANK__
    m.study("std").create("drive","FrequencyDomainSourceSweep");
    m.study("std").feature("drive").set("plist","f0");
__INDENTED_BLANK__
    return m;
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static double[] flat(double[][]a){
    int n=0;
    for(double[]r:a)n+=r.length;
    double[]v=new double[n];
    int k=0;
    for(double[]r:a)for(double x:r)v[k++]=x;
    return v;
    }
__INDENTED_BLANK__
  static double[][] series(Model m,String dataset,String expression){
    return series(m,dataset,expression,true);
  }
  static double[][] series(Model m,String dataset,String expression,boolean finiteAll){
__INDENTED_BLANK__
    m.result().numerical().create("probe","Global");
    try{
__INDENTED_BLANK__
      m.result().numerical("probe").set("data",dataset);
    m.result().numerical("probe").set("expr",new String[]{
    expression}
    );
__INDENTED_BLANK__
      double[][][]r=m.result().numerical("probe").getData(),i=m.result().numerical("probe")
    .getImagData();
__INDENTED_BLANK__
      double[]re=flat(r[0]),im=i==null?new double[re.length]:flat(i[0]);
    require(re.length==im.length,"Complex axes differ");
__INDENTED_BLANK__
      if(finiteAll){
        for(double x:re)require(Double.isFinite(x),"Nonfinite real observation");
        for(double x:im)require(Double.isFinite(x),"Nonfinite imaginary observation");
      }
    return new double[][]{
    re,im}
    ;
__INDENTED_BLANK__
    }
    finally{
    m.result().numerical().remove("probe");
    }
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static double[] selectedSource(double[][] values,int sourceIndex,int expectedCount){
    require(values.length==2&&values[0].length==expectedCount&&values[1].length==expectedCount,
      "Scattering source axis mismatch");
    require(sourceIndex>=0&&sourceIndex<expectedCount,"Scattering source index outside axis");
    double real=values[0][sourceIndex],imag=values[1][sourceIndex];
    require(Double.isFinite(real)&&Double.isFinite(imag),"Nonfinite physical scattering observation");
    return new double[]{real,imag};
  }
  static String dataset(Model m,String sol){
    for(String tag:m.result().dataset().tags())if("Solution".equals(m.result().dataset(tag)
    .getType())&&sol.equals(m.result().dataset(tag).getString("solution")))return tag;
    throw new IllegalStateException("No native dataset "+sol);
    }
__INDENTED_BLANK__
  static void direct(SolverFeature f){
__INDENTED_BLANK__
    if("Stationary".equals(f.getType())){
    f.create("picDirect","Direct");
    f.feature("picDirect").set("linsolver","pardiso");
    for(String child:f.feature().tags())if("FullyCoupled".equals(f.feature(child).getType()))f
    .feature(child).set("linsolver","picDirect");
    }
__INDENTED_BLANK__
    for(String child:f.feature().tags())if(!child.equals("picDirect"))direct(f.feature(child));
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  static void selectedModes(Model m,String main,double lambda){
__INDENTED_BLANK__
    int port=0;
__INDENTED_BLANK__
    for(String t:m.sol(main).feature().tags())if("StoreSolution".equals(m.sol(main).feature(t)
    .getType())){
__INDENTED_BLANK__
      port++;
    require(port<=N,"Unexpected selected mode store");
__INDENTED_BLANK__
      String ds=dataset(m,m.sol(main).feature(t).getString("sol"));
__INDENTED_BLANK__
      double[][]neff=series(m,ds,"ewfd.neff_"+port);
__INDENTED_BLANK__
      double[][]actualWave=series(m,ds,"c_const/freq/1[nm]");
__INDENTED_BLANK__
      double[][]anchor=series(m,ds,"intp"+port+"(ewfd.tEmodez_"+port+")");
__INDENTED_BLANK__
      String e="ewfd.tEmodez_"+port,hx="ewfd.tHmodex_"+port,hy="ewfd.tHmodey_"+port;
__INDENTED_BLANK__
      double[][]power=series(m,ds,"intp"+port+"(0.5*real(-"+e+"*conj("+hy+")*nx+"+e+"*conj("+hx+")*ny))/(1[W/m])");
__INDENTED_BLANK__
      require(neff[0].length==1&&actualWave[0].length==1&&anchor[0].length==1&&power[0]
    .length==1,"Selected mode scalar axes");
__INDENTED_BLANK__
      marker("MODE "+lambda+" "+port+" "+neff[0][0]+" "+neff[1][0]);
__INDENTED_BLANK__
      marker("MODE_ANCHOR "+lambda+" "+port+" "+anchor[0][0]+" "+anchor[1][0]);
__INDENTED_BLANK__
      marker("MODE_POWER "+lambda+" "+port+" "+power[0][0]);
      marker("MODE_DATASET "+lambda+" "+port+" "+ds+" "+
        m.sol(main).feature(t).getString("sol")+" 1 "+actualWave[0][0]);
      require(Math.abs(actualWave[0][0]-lambda)<1e-6,"Selected mode wavelength mismatch");
      require(neff[0][0]>NB&&neff[0][0]<NC&&Math.abs(neff[1][0])<1e-5,
        "Selected mode outside bound branch");
      require(Math.abs(power[0][0]-1)<1e-3,"Selected mode normalization mismatch");
__INDENTED_BLANK__
    }
__INDENTED_BLANK__
    require(port==N,"Missing selected mode stores");
__INDENTED_BLANK__
  }
  static void exportField(Model m,String ds,String solution,double lambda)throws Exception{
    String[] expressions={"PortName","c_const/freq/1[nm]","x/1[um]","y/1[um]",
      "real(ewfd.Ez)","imag(ewfd.Ez)","ewfd.normE^2"};
    m.result().numerical().create("fieldExport","Eval");
    try{
      m.result().numerical("fieldExport").set("data",ds);
      m.result().numerical("fieldExport").set("expr",expressions);
      m.result().numerical("fieldExport").set("refine",1);
      m.result().numerical("fieldExport").set("smooth","none");
      double[][][] values=m.result().numerical("fieldExport").getData();
      require(values.length==expressions.length,"Field expression axis mismatch");
      int rows=values[0][0].length;
      require(rows>0,"No native field rows");
      for(int e=0;e<values.length;e++){
        require(values[e].length==N,"Field source axis mismatch");
        require(values[e][0].length==rows,"Field coordinate axis mismatch");
      }
      for(int i=0;i<rows;i++){
          for(int e=0;e<values.length;e++)require(Double.isFinite(values[e][0][i]),"Nonfinite field row");
          require(Math.abs(values[0][0][i]-1)<1e-9&&Math.abs(values[1][0][i]-lambda)<1e-6,
            "Field actual source/wavelength mismatch");
          StringBuilder record=new StringBuilder("FIELD_ROW ");
          for(int e=0;e<values.length;e++){
            if(e>0)record.append(',');
            record.append(values[e][0][i]);
          }
          marker(record.toString());
      }
      marker("FIELD_META {\"schema_version\":\"1.0\",\"artifact\":\"field.csv\",\"dataset\":\""+ds+
          "\",\"solution\":\""+solution+"\",\"source_axis_index\":0,\"source_port\":1,"+
          "\"wavelength_nm\":"+lambda+",\"coordinate_units\":\"um\",\"field_units\":\"V/m\","+
          "\"expressions\":[\"PortName\",\"c_const/freq/1[nm]\",\"x/1[um]\",\"y/1[um]\","+
          "\"real(ewfd.Ez)\",\"imag(ewfd.Ez)\",\"ewfd.normE^2\"],\"refine\":1,\"smooth\":\"none\","+
          "\"rows\":"+rows+",\"coordinate_multiplicity\":\"retained\","+
          "\"sampling\":\"COMSOL Eval mesh rows; not independent spatial locations\"}");
      marker("FIELD "+lambda+" 1 "+ds+" "+rows);
    }finally{m.result().numerical().remove("fieldExport");}
  }
__INDENTED_BLANK__
  static void solve(Model m)throws Exception{
__INDENTED_BLANK__
    m.component("c").mesh("mesh").run();
    marker("MESH_COMPLETE "+m.component("c").mesh("mesh").getNumElem());
    m.study("std").createAutoSequences("sol");
__INDENTED_BLANK__
    String main=null;
    for(String s:m.sol().tags())if("std".equals(m.sol(s).study())&&m.sol(s).feature()
    .tags().length>0){
    require(main==null,"Ambiguous main solver");
    main=s;
    }
__INDENTED_BLANK__
    require(main!=null,"Missing main solver");
    for(String t:m.sol(main).feature().tags())direct(m.sol(main).feature(t));
__INDENTED_BLANK__
    String lastStore=null,driveStart=null;
__INDENTED_BLANK__
    for(String t:m.sol(main).feature().tags()){
__INDENTED_BLANK__
      if("StoreSolution".equals(m.sol(main).feature(t).getType()))lastStore=t;
__INDENTED_BLANK__
      if("StudyStep".equals(m.sol(main).feature(t).getType())&&"drive".equals(m.sol(main)
    .feature(t).getString("studystep")))driveStart=t;
__INDENTED_BLANK__
    }
__INDENTED_BLANK__
    require(lastStore!=null&&driveStart!=null,"Cannot split BMA and driven sequence");
__INDENTED_BLANK__
    for(double lambda:WAVES){
__INDENTED_BLANK__
      m.param().set("lambda0",lambda+"[nm]");
    m.sol(main).run(lastStore);
    selectedModes(m,main,lambda);
__INDENTED_BLANK__
      if(STAGE.equals("modes"))continue;
__INDENTED_BLANK__
      m.sol(main).runFrom(driveStart);
    marker("DOF "+lambda+" "+Arrays.toString(m.sol(main).getSize()));
__INDENTED_BLANK__
      String ds=dataset(m,main);
    double[][]src=series(m,ds,"PortName"),waves=series(m,ds,"c_const/freq/1[nm]");
__INDENTED_BLANK__
      require(src[0].length==N&&waves[0].length==N,"Source/wavelength axis mismatch");
__INDENTED_BLANK__
      for(int j=0;
    j<N;
    j++){
__INDENTED_BLANK__
        require(Math.abs(src[0][j]-(j+1))<1e-9&&Math.abs(waves[0][j]-lambda)<1e-6,"Actual source/wavelength mismatch");
    marker("SOURCE "+lambda+" "+(j+1)+" "+src[0][j]);
__INDENTED_BLANK__
        for(int i=1;
    i<=N;
    i++){
__INDENTED_BLANK__
          double[][]s=series(m,ds,"ewfd.S"+i+(j+1),false);
          double[] physical=selectedSource(s,j,N);
    marker("S "+lambda+" "+(j+1)+" "+i+" "+physical[0]+" "+physical[1]);
__INDENTED_BLANK__
          double[][]flux=series(m,ds,"intp"+i+"(ewfd.Poavx*nx+ewfd.Poavy*ny)/(1[W/m])");
    require(flux[0].length==N,"Flux source axis mismatch");
    marker("FLUX "+lambda+" "+(j+1)+" p"+i+" "+flux[0][j]);
__INDENTED_BLANK__
        }
__INDENTED_BLANK__
        for(String region:new String[]{
    "open","abs"}
    ){
    String expr=region.equals("open")?"intopen(ewfd.Poavx*nx+ewfd.Poavy*ny)/(1[W/m])":"intabs(ewfd.Qh)/(1[W/m])";
    double[][]v=series(m,ds,expr);
    require(v[0].length==N,"Power source axis mismatch");
    marker("FLUX "+lambda+" "+(j+1)+" "+region+" "+v[0][j]);
    }
__INDENTED_BLANK__
      }
      if(lambda==WAVES[0])exportField(m,ds,main,lambda);
__INDENTED_BLANK__
    }
__INDENTED_BLANK__
    m.save(STAGE.equals("modes")?"selected_modes.mph":"driven.mph");
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  public static Model run()throws Exception{
__INDENTED_BLANK__
    marker("STAGE "+STAGE);
    Model m=build();
    m.save("configured.mph");
__INDENTED_BLANK__
    if(!STAGE.equals("configure"))solve(m);
    marker("COMPLETE "+STAGE);
    return m;
__INDENTED_BLANK__
  }
__INDENTED_BLANK__
  public static void main(String[]args)throws Exception{
    try{
    run();
    }
    catch(Exception error){
    marker("FAILED "+error.getClass().getName()+": "+error.getMessage());
    throw error;
    }
    }
__INDENTED_BLANK__
}
__INDENTED_BLANK__
""".replace("__INDENTED_BLANK__", "    ")


def extract_native_field(console: str) -> tuple[bytes, dict[str, Any]]:
    """Parse fixed native mesh observations without deduplication or fitting.

    This parses data only. The caller must authenticate the console and native
    receipt before interpreting the result as an observed field.
    """
    records = [line for line in console.splitlines() if line.startswith("PIC FIELD_META")]
    if len(records) != 1 or not records[0].startswith("PIC FIELD_META "):
        raise ValueError("Expected one native field metadata record")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate native field metadata key")
            result[key] = value
        return result

    metadata = json.loads(records[0][len("PIC FIELD_META ") :], object_pairs_hook=unique)
    required = {
        "schema_version": "1.0",
        "artifact": "field.csv",
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
        "coordinate_multiplicity": "retained",
    }
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in required.items()):
        raise ValueError("Native field metadata conventions mismatch")
    if (
        type(metadata.get("source_axis_index")) is not int
        or metadata["source_axis_index"] != 0
        or type(metadata.get("source_port")) is not int
        or metadata["source_port"] != 1
        or type(metadata.get("rows")) is not int
        or not 0 < metadata["rows"] <= 5_000_000
        or not _TAG.fullmatch(str(metadata.get("dataset", "")))
        or not _TAG.fullmatch(str(metadata.get("solution", "")))
    ):
        raise ValueError("Invalid native field identity/count")
    wavelength = _number(metadata.get("wavelength_nm"), "native field wavelength", 1200, 1700)
    rows = []
    for line in console.splitlines():
        if not line.startswith("PIC FIELD_ROW"):
            continue
        if not line.startswith("PIC FIELD_ROW "):
            raise ValueError("Malformed native field row")
        fields = line[len("PIC FIELD_ROW ") :].split(",")
        if len(fields) != 7:
            raise ValueError("Native field row requires seven columns")
        try:
            values = [float(value) for value in fields]
        except ValueError as error:
            raise ValueError("Malformed native field value") from error
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite native field observation")
        if abs(values[0] - 1) >= 1e-9 or abs(values[1] - wavelength) >= 1e-6 or values[6] < 0:
            raise ValueError("Native field source/wavelength/value mismatch")
        rows.append(fields)
    if len(rows) != metadata["rows"]:
        raise ValueError("Incomplete native field row count")
    summaries = [line.split() for line in console.splitlines() if line.startswith("PIC FIELD ")]
    if (
        len(summaries) != 1
        or len(summaries[0]) != 6
        or float(summaries[0][2]) != wavelength
        or summaries[0][3] != "1"
        or summaries[0][4] != metadata["dataset"]
        or int(summaries[0][5]) != metadata["rows"]
    ):
        raise ValueError("Native field summary mismatch")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["source_port", "wavelength_nm", "x_um", "y_um", "ez_real", "ez_imag", "e2_v2_m2"])
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8"), metadata


def prepare_native_bundle(
    output: str | Path, geometry: dict[str, Any], config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Create a new immutable-input bundle, refusing existing destinations."""
    geometry = _validate_geometry(geometry)
    config = normalize_native_config(config)
    source = render_java(geometry, **config).encode("utf-8")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "geometry.json").write_bytes(_canonical(geometry))
    (output / "config.json").write_bytes(_canonical(config))
    (output / "NativePic.java").write_bytes(source)
    manifest = {
        "schema_version": "1.0",
        "family": geometry["family"],
        "stage": config["stage"],
        "model_level": "2d-scalar-index-surrogate",
        "native_execution": False,
        "files": {name: _sha(output / name) for name in ("geometry.json", "config.json", "NativePic.java")},
    }
    (output / "manifest.json").write_bytes(_canonical(manifest))
    return manifest


def verify_native_bundle(bundle: str | Path) -> dict[str, Any]:
    """Verify hashes and regeneration with the currently trusted generator."""
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    if manifest.get("schema_version") != "1.0" or set(manifest.get("files", {})) != {
        "geometry.json",
        "config.json",
        "NativePic.java",
    }:
        raise ValueError("Invalid native bundle manifest")
    for name, expected in manifest["files"].items():
        path = bundle / name
        if path.is_symlink() or _sha(path) != expected:
            raise ValueError(f"Native bundle member mismatch: {name}")
    geometry = _validate_geometry(json.loads((bundle / "geometry.json").read_bytes()))
    config = normalize_native_config(json.loads((bundle / "config.json").read_bytes()))
    if manifest.get("family") != geometry["family"] or manifest.get("stage") != config["stage"]:
        raise ValueError("Native bundle identity mismatch")
    if (bundle / "NativePic.java").read_bytes() != render_java(geometry, **config).encode("utf-8"):
        raise ValueError("Native source does not match trusted generation")
    return {
        "manifest": manifest,
        "geometry": geometry,
        "config": config,
        "manifest_sha256": _sha(bundle / "manifest.json"),
    }


def _launch(command: list[str], folder: Path, log: Path, timeout: float) -> dict[str, Any]:
    # Imported only for execution; offline preparation stays usable with the core.
    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("Native supervision requires photonic-workflow[comsol]") from error
    started = time.monotonic()
    owned: dict[tuple[int, float], Any] = {}
    with log.open("wb") as stream:
        process = subprocess.Popen(
            command,
            cwd=folder,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        root = psutil.Process(process.pid)
        owned[(root.pid, root.create_time())] = root
        timed_out = False
        try:
            while process.poll() is None:
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    for child in root.children(recursive=True):
                        owned[(child.pid, child.create_time())] = child
                if time.monotonic() - started >= timeout:
                    timed_out = True
                    break
                time.sleep(0.1)
        finally:
            if timed_out or process.poll() is None:
                for child in reversed(list(owned.values())):
                    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        child.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
            _, alive = psutil.wait_procs(list(owned.values()), timeout=3)
            if alive:
                for child in alive:
                    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        child.kill()
                _, alive = psutil.wait_procs(alive, timeout=5)
    return {
        "exit_code": process.poll(),
        "stdout": log.name,
        "seconds": time.monotonic() - started,
        "timed_out": timed_out,
        "owned_processes_exited": not alive,
        "argv": command,
    }


def run_native_bundle(
    bundle: str | Path,
    solver_root: str | Path | None = None,
    *,
    timeout_s: float = 600,
    compile_timeout_s: float = 90,
    cores: int = 4,
) -> dict[str, Any]:
    """Run one verified bundle in a unique directory with a shared wall budget.

    The caller must have authorized native licensed execution. This function
    refuses concurrent native solver processes and preserves failed attempts.
    Paths and launcher hashes stay in the private receipt, not public source.
    """
    timeout_s = _number(timeout_s, "native timeout", 15, 7200)
    compile_timeout_s = _number(compile_timeout_s, "compile timeout", 5, 300)
    if isinstance(cores, bool) or not isinstance(cores, int) or not 1 <= cores <= 16:
        raise ValueError("Native cores must be 1..16")
    verified = verify_native_bundle(bundle)
    bundle = Path(bundle).resolve()
    root_value = solver_root or os.environ.get("PHOTONIC_SOLVER_ROOT")
    if not root_value:
        raise ValueError("Provide solver_root or PHOTONIC_SOLVER_ROOT")
    root = Path(root_value).resolve()
    executables = {key: root / "bin" / "win64" / f"comsol{key}.exe" for key in ("compile", "batch")}
    if any(not path.is_file() for path in executables.values()):
        raise ValueError("Native compile/batch launcher not found")
    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("Native supervision requires photonic-workflow[comsol]") from error
    for process in psutil.process_iter(["name"]):
        with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            if (process.info["name"] or "").lower() in {
                "comsol.exe",
                "comsolbatch.exe",
                "comsolcompile.exe",
                "comsolmphserver.exe",
            }:
                raise RuntimeError("Another native COMSOL process is active; concurrency is one")
    folder = bundle / ("run-" + uuid.uuid4().hex[:12])
    folder.mkdir()
    shutil.copyfile(bundle / "NativePic.java", folder / "NativePic.java")
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "failed",
        "stage": verified["config"]["stage"],
        "family": verified["geometry"]["family"],
        "bundle": str(bundle),
        "run_directory": str(folder),
        "manifest_sha256": verified["manifest_sha256"],
        "java_sha256": _sha(folder / "NativePic.java"),
        "launchers": {key: {"path": str(path), "sha256": _sha(path)} for key, path in executables.items()},
        "timeout_s": timeout_s,
        "cores": cores,
        "physical_qualification": "not_established",
        "artifacts": [],
    }
    start = time.monotonic()
    try:
        for directory in (
            "compiler_config",
            "compiler_workspace",
            "compiler_prefs",
            "compiler_tmp",
            "config",
            "workspace",
            "prefs",
            "tmp",
        ):
            (folder / directory).mkdir()
        compile_command = [str(executables["compile"])]
        for flag, subdir in (
            ("-configuration", "compiler_config"),
            ("-data", "compiler_workspace"),
            ("-prefsdir", "compiler_prefs"),
            ("-tmpdir", "compiler_tmp"),
        ):
            compile_command.extend((flag, str(folder / subdir)))
        compile_command.append(str(folder / "NativePic.java"))
        receipt["compile"] = _launch(compile_command, folder, folder / "compile.log", min(compile_timeout_s, timeout_s))
        compiled = folder / "NativePic.class"
        if (
            receipt["compile"]["exit_code"] != 0
            or not receipt["compile"]["owned_processes_exited"]
            or not compiled.is_file()
        ):
            raise RuntimeError("Native compilation failed or processes survived")
        receipt["class_sha256"] = _sha(compiled)
        if compiled.stat().st_size < 32:
            raise RuntimeError("Native compiler did not produce a class")
        # Revalidate all frozen inputs immediately before entering the solver.
        if verify_native_bundle(bundle)["manifest_sha256"] != verified["manifest_sha256"]:
            raise ValueError("Bundle changed during compilation")
        if _sha(folder / "NativePic.java") != receipt["java_sha256"]:
            raise ValueError("Run source changed during compilation")
        remaining = timeout_s - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError("Shared native wall budget exhausted after compile")
        batch_command = [str(executables["batch"]), "-np", str(cores)]
        for flag, subdir in (
            ("-configuration", "config"),
            ("-data", "workspace"),
            ("-prefsdir", "prefs"),
            ("-tmpdir", "tmp"),
        ):
            batch_command.extend((flag, str(folder / subdir)))
        batch_command.extend(
            (
                "-inputfile",
                str(compiled),
                "-outputfile",
                str(folder / "model.mph"),
                "-batchlog",
                str(folder / "native.log"),
            )
        )
        receipt["batch"] = _launch(batch_command, folder, folder / "console.log", remaining)
        console = (folder / "console.log").read_text(encoding="utf-8", errors="replace")
        lines = console.splitlines()
        if (
            receipt["batch"]["exit_code"] != 0
            or receipt["batch"]["timed_out"]
            or not receipt["batch"]["owned_processes_exited"]
            or lines.count("PIC STAGE " + receipt["stage"]) != 1
            or lines.count("PIC COMPLETE " + receipt["stage"]) != 1
            or lines.count("PIC GEOMETRY_PASS") != 1
            or lines.count("PIC PORTS_PASS") != 1
            or any(line.startswith("PIC FAILED ") for line in lines)
        ):
            raise RuntimeError("Native process or exact completion checks failed")
        checkpoint = {"configure": "configured.mph", "modes": "selected_modes.mph", "solve": "driven.mph"}[
            receipt["stage"]
        ]
        if not (folder / checkpoint).is_file() or (folder / checkpoint).stat().st_size < 256:
            raise RuntimeError("Missing nonempty native checkpoint")
        if receipt["stage"] == "solve" and verified["config"]["export_fields"]:
            field_csv, field_metadata = extract_native_field(console)
            field_metadata["source_console_sha256"] = _sha(folder / "console.log")
            field_metadata["source_records"] = "PIC FIELD_ROW"
            field_metadata["derivation"] = "Parsed rows; no coordinate deduplication, fitting or averaging"
            (folder / "field.csv").write_bytes(field_csv)
            (folder / "field-metadata.json").write_bytes(_canonical(field_metadata))
            receipt["field_derivation"] = {
                "source": "console.log",
                "source_sha256": field_metadata["source_console_sha256"],
                "metadata_record": "PIC FIELD_META",
                "row_records": "PIC FIELD_ROW",
                "rows": field_metadata["rows"],
            }
        receipt["status"] = "completed"
    except Exception as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - start
        for name in (
            "NativePic.java",
            "NativePic.class",
            "compile.log",
            "console.log",
            "native.log",
            "field.csv",
            "field-metadata.json",
            "configured.mph",
            "selected_modes.mph",
            "driven.mph",
            "model.mph",
        ):
            path = folder / name
            if path.is_file():
                receipt["artifacts"].append({"path": name, "sha256": _sha(path), "bytes": path.stat().st_size})
        (folder / "receipt.json").write_bytes(_canonical(receipt))
    return receipt
