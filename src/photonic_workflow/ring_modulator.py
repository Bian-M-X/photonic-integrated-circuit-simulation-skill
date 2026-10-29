"""Ring geometry and a declared abrupt-junction carrier-depletion approximation.

The electrical model is one-dimensional, quasistatic and piecewise depleted;
it is not a drift-diffusion, avalanche, RF, or calibrated SOI mode solver.
Carrier coefficients are the room-temperature 1550 nm Soref--Bennett fit.
"""

from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from typing import Any

from .exceptions import InvalidInputError

ELEMENTARY_CHARGE_C = 1.602176634e-19
BOLTZMANN_J_PER_K = 1.380649e-23
VACUUM_PERMITTIVITY_F_PER_M = 8.8541878128e-12

_GEOMETRY = {
    "bus_count": 1.0,
    "radius_um": 3.0,
    "width_um": 0.3,
    "gap_um": 0.2,
    "lead_um": 2.5,
    "clearance_um": 1.2,
    "port_window_um": 2.4,
}
_PN = {
    "acceptor_cm3": 1e17,
    "donor_cm3": 1e17,
    "intrinsic_cm3": 1e10,
    "temperature_k": 300.0,
    "relative_permittivity": 11.7,
    "reverse_bias_v": 0.0,
    "p_region_width_um": 1.0,
    "n_region_width_um": 1.0,
    "optical_width_um": 0.3,
    "junction_offset_um": 0.0,
    "optical_overlap": 0.8,
    "active_fraction": 1.0,
    "junction_height_um": 0.22,
    "junction_length_um": 6 * math.pi,
    "wavelength_nm": 1550.0,
}


def _normalise(parameters: dict[str, Any] | None, defaults: dict[str, float]) -> dict[str, float]:
    if parameters is None:
        return dict(defaults)
    if not isinstance(parameters, dict) or not all(isinstance(key, str) for key in parameters):
        raise InvalidInputError("parameters must be a string-keyed object")
    unknown = set(parameters) - set(defaults)
    if unknown:
        raise InvalidInputError(f"Unknown parameters: {sorted(unknown)}")
    result = dict(defaults)
    for key, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, Real):
            raise InvalidInputError(f"{key} must be a finite real number")
        try:
            numeric = float(value)
        except (OverflowError, ValueError) as exc:
            raise InvalidInputError(f"{key} must be a finite real number") from exc
        if not math.isfinite(numeric):
            raise InvalidInputError(f"{key} must be a finite real number")
        result[key] = numeric
    return result


def _range(value: float, name: str, lower: float, upper: float) -> None:
    if not lower <= value <= upper:
        raise InvalidInputError(f"{name} must lie in [{lower}, {upper}]")


def build_ring_geometry(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepare an all-pass bus plus an exact annulus; do not invoke a solver.

    ``radius_um`` is the ring centerline radius. The bus centerline is y=0,
    and its distance to the annulus is exactly ``gap_um`` at x=0.
    """
    p = _normalise(parameters, _GEOMETRY)
    if p["bus_count"] not in (1.0, 2.0):
        raise InvalidInputError("bus_count must be 1 (all-pass) or 2 (add-drop)")
    for name in ("width_um", "gap_um"):
        _range(p[name], name, 0.05, 2.0)
    _range(p["radius_um"], "radius_um", 0.5, 100.0)
    _range(p["lead_um"], "lead_um", 0.2, 30.0)
    _range(p["clearance_um"], "clearance_um", 0.5, 10.0)
    _range(p["port_window_um"], "port_window_um", 0.2, 10.0)
    radius, width = p["radius_um"], p["width_um"]
    if radius <= width / 2:
        raise InvalidInputError("radius_um must exceed half the ring width")
    if not width < p["port_window_um"] <= width + 2 * p["clearance_um"]:
        raise InvalidInputError("port_window_um must contain the core and fit within background clearance")
    inner, outer = radius - width / 2, radius + width / 2
    center_y = radius + width + p["gap_um"]
    half_length = outer + p["lead_um"]
    box = [-half_length, half_length, -width / 2 - p["clearance_um"], center_y + outer + p["clearance_um"]]
    geometry = {
        "family": "ring",
        "parameters": p,
        "bbox_um": box,
        "primitives": [
            {
                "tag": "bus",
                "type": "rectangle",
                "x": -half_length,
                "y": -width / 2,
                "width": 2 * half_length,
                "height": width,
                "group": "core",
            },
            {
                "tag": "resonator",
                "type": "ring",
                "cx": 0.0,
                "cy": center_y,
                "outer_radius": outer,
                "inner_radius": inner,
                "group": "active",
            },
        ],
        "ports": [
            {
                "name": "input",
                "side": "left",
                "center_um": [-half_length, 0.0],
                "width_um": width,
                "window_um": p["port_window_um"],
            },
            {
                "name": "through",
                "side": "right",
                "center_um": [half_length, 0.0],
                "width_um": width,
                "window_um": p["port_window_um"],
            },
        ],
        "expected_core_area_um2": 2 * half_length * width + 2 * math.pi * radius * width,
        "expected_core_components": 2,
        "model_level": "2d-scalar-index-surrogate",
        "limitations": [
            "The annulus and bus are native geometry proposals, not field or convergence evidence.",
            "Scalar planar material indices do not establish a calibrated SOI effective-index or vector model.",
            "A finite spectral grid does not qualify a narrow resonance, linewidth, Q or broadband interpolation.",
        ],
    }
    if p["bus_count"] == 2:
        upper_y = 2 * center_y
        geometry["bbox_um"][3] = upper_y + width / 2 + p["clearance_um"]
        geometry["primitives"].append(
            {
                "tag": "drop_bus",
                "type": "rectangle",
                "x": -half_length,
                "y": upper_y - width / 2,
                "width": 2 * half_length,
                "height": width,
                "group": "core",
            }
        )
        geometry["ports"].extend(
            [
                {
                    "name": "add",
                    "side": "right",
                    "center_um": [half_length, upper_y],
                    "width_um": width,
                    "window_um": p["port_window_um"],
                },
                {
                    "name": "drop",
                    "side": "left",
                    "center_um": [-half_length, upper_y],
                    "width_um": width,
                    "window_um": p["port_window_um"],
                },
            ]
        )
        geometry["expected_core_area_um2"] += 2 * half_length * width
        geometry["expected_core_components"] = 3
    return geometry


def _pn_parameters(parameters: dict[str, Any] | None) -> dict[str, float]:
    p = _normalise(parameters, _PN)
    for name in ("acceptor_cm3", "donor_cm3"):
        _range(p[name], name, 1e15, 1e18)
    _range(p["intrinsic_cm3"], "intrinsic_cm3", 1e8, 1e12)
    _range(p["temperature_k"], "temperature_k", 200.0, 400.0)
    _range(p["relative_permittivity"], "relative_permittivity", 8.0, 16.0)
    _range(p["reverse_bias_v"], "reverse_bias_v", 0.0, 20.0)
    for name in ("p_region_width_um", "n_region_width_um", "optical_width_um"):
        _range(p[name], name, 0.05, 10.0)
    _range(p["junction_height_um"], "junction_height_um", 0.02, 5.0)
    _range(p["junction_length_um"], "junction_length_um", 0.1, 2000.0)
    _range(p["optical_overlap"], "optical_overlap", 0.0, 1.0)
    _range(p["active_fraction"], "active_fraction", 0.0, 1.0)
    if p["wavelength_nm"] != 1550.0:
        raise InvalidInputError("The implemented silicon carrier coefficients are for 1550 nm only")
    low = -p["optical_width_um"] / 2 - p["junction_offset_um"]
    high = p["optical_width_um"] / 2 - p["junction_offset_um"]
    if low < -p["p_region_width_um"] or high > p["n_region_width_um"]:
        raise InvalidInputError("The optical core must lie within the electrical p/n domains")
    return p


def _depletion(p: dict[str, float], reverse_bias_v: float) -> dict[str, float]:
    na, nd = p["acceptor_cm3"] * 1e6, p["donor_cm3"] * 1e6
    ni = p["intrinsic_cm3"] * 1e6
    thermal = BOLTZMANN_J_PER_K * p["temperature_k"] / ELEMENTARY_CHARGE_C
    built_in = thermal * math.log(na * nd / ni**2)
    permittivity = VACUUM_PERMITTIVITY_F_PER_M * p["relative_permittivity"]
    drop = built_in + reverse_bias_v
    width = math.sqrt(2 * permittivity / ELEMENTARY_CHARGE_C * drop * (1 / na + 1 / nd))
    xp, xn = width * nd / (na + nd), width * na / (na + nd)
    if xp >= p["p_region_width_um"] * 1e-6 or xn >= p["n_region_width_um"] * 1e-6:
        raise InvalidInputError("Depletion reaches an electrical contact: finite-domain punch-through is not modeled")
    return {
        "built_in_voltage_v": built_in,
        "potential_drop_v": drop,
        "depletion_width_um": width * 1e6,
        "xp_um": xp * 1e6,
        "xn_um": xn * 1e6,
        "peak_field_v_per_m": ELEMENTARY_CHARGE_C * na * xp / permittivity,
        "charge_per_area_c_per_m2": ELEMENTARY_CHARGE_C * na * xp,
        "capacitance_per_area_f_per_m2": permittivity / width,
    }


def _overlap(low: float, high: float, left: float, right: float) -> float:
    return max(0.0, min(high, right) - max(low, left))


def _carriers(p: dict[str, float], d: dict[str, float]) -> dict[str, float]:
    width = p["optical_width_um"]
    low, high = -width / 2 - p["junction_offset_um"], width / 2 - p["junction_offset_um"]
    fp = _overlap(low, high, -p["p_region_width_um"], -d["xp_um"]) / width
    fn = _overlap(low, high, d["xn_um"], p["n_region_width_um"]) / width
    na, nd = p["acceptor_cm3"], p["donor_cm3"]
    # Evaluate the nonlinear hole law in each local neutral region, then average.
    # Applying (mean hole density)^0.8 or (removed hole density)^0.8 is different.
    factor = p["optical_overlap"] * p["active_fraction"]
    return {
        "neutral_p_core_fraction": fp,
        "neutral_n_core_fraction": fn,
        "mean_electron_cm3": fn * nd,
        "mean_hole_cm3": fp * na,
        "carrier_index_change_eff": -factor * (8.8e-22 * nd * fn + 8.5e-18 * na**0.8 * fp),
        "alpha_eff_per_cm": factor * (8.5e-18 * nd * fn + 6.0e-18 * na * fp),
    }


def depletion_response(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return quasistatic PN quantities and optical perturbations relative to 0 V.

    Positive ``reverse_bias_v`` increases the junction potential. Minority
    carriers, fringing, diffusion tails, leakage and breakdown are absent.
    The real baseline index belongs to the caller's zero-bias reference.
    ``absolute_k_eff`` is positive carrier extinction at the requested bias.
    """
    p = _pn_parameters(parameters)
    zero = _depletion(p, 0.0)
    state = _depletion(p, p["reverse_bias_v"])
    carriers_zero, carriers = _carriers(p, zero), _carriers(p, state)
    wavelength_cm = p["wavelength_nm"] * 1e-7
    absolute_k = carriers["alpha_eff_per_cm"] * wavelength_cm / (4 * math.pi)
    zero_k = carriers_zero["alpha_eff_per_cm"] * wavelength_cm / (4 * math.pi)
    area = p["junction_height_um"] * p["junction_length_um"] * p["active_fraction"] * 1e-12
    return {
        "parameters": p,
        **state,
        "zero_bias": {**zero, **carriers_zero},
        "carriers": carriers,
        "junction_area_m2": area,
        "junction_charge_c": state["charge_per_area_c_per_m2"] * area,
        "junction_capacitance_f": state["capacitance_per_area_f_per_m2"] * area,
        "delta_n_eff": carriers["carrier_index_change_eff"] - carriers_zero["carrier_index_change_eff"],
        "absolute_k_eff": absolute_k,
        "delta_k_eff": absolute_k - zero_k,
        "absolute_alpha_eff_per_cm": carriers["alpha_eff_per_cm"],
        "zero_bias_alpha_eff_per_cm": carriers_zero["alpha_eff_per_cm"],
        "optical_reference": "real index is caller-declared 0 V reference; carrier absorption is absolute at bias",
        "time_convention": "exp(+iwt); passive complex index n-i*k; forward propagation exp(-i*beta*L)",
        "model_level": "1d-abrupt-depletion-with-declared-optical-overlap",
        "physics_accepted": False,
        "limitations": [
            "Abrupt fully ionized nondegenerate silicon junction; no carrier transport, fringing or breakdown solve.",
            "Intrinsic density and permittivity are caller parameters; "
            "no temperature-dependent material fit is supplied.",
            "Soref--Bennett coefficients are fixed at room-temperature 1550 nm; "
            "no broadband or thermal fit is implied.",
            "Uniform optical intensity inside the core and declared confinement; no SOI vector mode overlap is solved.",
            "Partial active_fraction is a uniform roundtrip average, not an explicit active-arc geometry.",
            "Capacitance excludes contacts and parasitics; "
            "resistance, RF bandwidth, eye quality and yield are not predicted.",
        ],
    }


def poisson_reference(parameters: dict[str, Any] | None, positions_um: list[float]) -> dict[str, Any]:
    """Evaluate the independent piecewise solution used to check a native Poisson solve.

    x=0 is the junction, p is x<0, and potential is zero at the p contact.
    The field points from n to p. The neutral-contact regions have zero field.
    """
    response = depletion_response(parameters)
    p = response["parameters"]
    if not isinstance(positions_um, (list, tuple)) or not positions_um:
        raise InvalidInputError("positions_um must be a nonempty sequence")
    epsilon = VACUUM_PERMITTIVITY_F_PER_M * p["relative_permittivity"]
    na, nd = p["acceptor_cm3"] * 1e6, p["donor_cm3"] * 1e6
    xp, xn = response["xp_um"] * 1e-6, response["xn_um"] * 1e-6
    rows = []
    for position in positions_um:
        if isinstance(position, bool) or not isinstance(position, Real):
            raise InvalidInputError("positions_um contains a nonfinite or nonnumeric position")
        try:
            x_um = float(position)
        except (OverflowError, ValueError) as exc:
            raise InvalidInputError("positions_um contains a nonfinite or nonnumeric position") from exc
        if not math.isfinite(x_um):
            raise InvalidInputError("positions_um contains a nonfinite or nonnumeric position")
        if not -p["p_region_width_um"] <= x_um <= p["n_region_width_um"]:
            raise InvalidInputError("position lies outside the electrical domain")
        x = x_um * 1e-6
        if x < -xp:
            potential, field, charge = 0.0, 0.0, 0.0
        elif x < 0:
            potential = ELEMENTARY_CHARGE_C * na * (x + xp) ** 2 / (2 * epsilon)
            field = -ELEMENTARY_CHARGE_C * na * (x + xp) / epsilon
            charge = -ELEMENTARY_CHARGE_C * na
        elif x < xn:
            potential = response["potential_drop_v"] - ELEMENTARY_CHARGE_C * nd * (xn - x) ** 2 / (2 * epsilon)
            field = -ELEMENTARY_CHARGE_C * nd * (xn - x) / epsilon
            charge = ELEMENTARY_CHARGE_C * nd
        else:
            potential, field, charge = response["potential_drop_v"], 0.0, 0.0
        rows.append({"x_um": x_um, "potential_v": potential, "field_v_per_m": field, "charge_c_per_m3": charge})
    return {"parameters": p, "rows": rows, "physics_accepted": False}


def render_pn_java(parameters: dict[str, Any] | None = None) -> str:
    """Render an original base-COMSOL 1D coefficient-PDE Poisson benchmark.

    Depletion interfaces are computed from native parameter expressions.
    The prescribed charge is an approximation, not a Semiconductor interface
    or drift-diffusion solution. Rendering never compiles or runs the source.
    """
    p = depletion_response(parameters)["parameters"]
    identity = hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    values = {
        "Na": f"{p['acceptor_cm3']:.17g}[1/cm^3]",
        "Nd": f"{p['donor_cm3']:.17g}[1/cm^3]",
        "ni": f"{p['intrinsic_cm3']:.17g}[1/cm^3]",
        "Tpn": f"{p['temperature_k']:.17g}[K]",
        "epsr": f"{p['relative_permittivity']:.17g}",
        "Vr": f"{p['reverse_bias_v']:.17g}[V]",
        "Lp": f"{p['p_region_width_um']:.17g}[um]",
        "Ln": f"{p['n_region_width_um']:.17g}[um]",
    }
    parameters_java = "\n".join(f'    m.param().set("{key}","{value}");' for key, value in values.items())
    # Only validated finite numeric literals are embedded, never caller source.
    template = r"""import com.comsol.model.*;
import com.comsol.model.util.*;
import java.util.*;
public class NativePn {
  static void marker(String s){System.out.println("PN "+s);}
  static void require(boolean b,String s){if(!b)throw new IllegalStateException(s);}
  static double[] globals(Model m,String data,String[] expressions){
    m.result().numerical().create("pnGlobal","EvalGlobal");
    m.result().numerical("pnGlobal").set("data",data);
    m.result().numerical("pnGlobal").set("expr",expressions);
    double[][] a=m.result().numerical("pnGlobal").getReal();
    require(a.length==expressions.length,"Global expression count");
    double[] result=new double[a.length];
    for(int i=0;i<a.length;i++){require(a[i].length==1,"Global solution count");result[i]=a[i][0];}
    m.result().numerical().remove("pnGlobal");return result;
  }
  public static Model run()throws Exception{
    marker("IDENTITY __IDENTITY__");
    Model m=ModelUtil.create("NativePn");m.modelPath(".");
    m.label("Original prescribed-depletion Poisson benchmark; not drift diffusion");
__PARAMETERS__
    m.param().set("eps_si","epsilon0_const*epsr");
    m.param().set("Vbi","k_B_const*Tpn/e_const*log(Na*Nd/ni^2)");
    m.param().set("Vj","Vbi+Vr");
    m.param().set("Wpn","sqrt(2*eps_si*Vj/e_const*(1/Na+1/Nd))");
    m.param().set("xp","Wpn*Nd/(Na+Nd)");m.param().set("xn","Wpn*Na/(Na+Nd)");
    m.component().create("c",true);m.component("c").geom().create("g",1);
    m.component("c").geom("g").lengthUnit("um");
    m.component("c").geom("g").create("intervals","Interval");
    m.component("c").geom("g").feature("intervals").set("p","-Lp -xp 0 xn Ln");
    m.component("c").geom("g").run();
    String unit=m.component("c").geom("g").lengthUnit();
    marker("UNIT_CODEPOINTS "+Arrays.toString(unit.codePoints().toArray()));
    require("um".equals(unit)||"\u00b5m".equals(unit)||"\u03bcm".equals(unit),"Unknown geometry unit");
    marker("UNIT um");
    require(m.component("c").geom("g").getNDomains()==4,"Expected four Poisson domains");
    for(String tag:new String[]{"left","right"}){
      m.component("c").selection().create(tag,"Box");
      m.component("c").selection(tag).set("entitydim",0);
      m.component("c").selection(tag).set("xmin",tag.equals("left")?"-Lp-1e-6[um]":"Ln-1e-6[um]");
      m.component("c").selection(tag).set("xmax",tag.equals("left")?"-Lp+1e-6[um]":"Ln+1e-6[um]");
      require(m.component("c").selection(tag).entities(0).length==1,"Contact selection");
      marker("CONTACT "+tag+" "+Arrays.toString(m.component("c").selection(tag).entities(0)));
    }
    m.component("c").variable().create("pnvar");
    m.component("c").variable("pnvar").set("rho_pn",
      "if(x < -xp,0[C/m^3],if(x < 0[um],-e_const*Na,if(x < xn,e_const*Nd,0[C/m^3])))");
    m.component("c").physics().create("poisson","CoefficientFormPDE","g");
    m.component("c").physics("poisson").field("dimensionless").field("phi_pn");
    m.component("c").physics("poisson").field("dimensionless").component(new String[]{"phi_pn"});
    m.component("c").physics("poisson").prop("ShapeProperty").set("order",2);
    m.component("c").physics("poisson").prop("ShapeProperty").set("valueType","real");
    m.component("c").physics("poisson").prop("Units").set("SourceTermQuantity","dimensionless");
    m.component("c").physics("poisson").feature("cfeq1").set("c","1[um^2]");
    m.component("c").physics("poisson").feature("cfeq1").set("a","0");
    m.component("c").physics("poisson").feature("cfeq1").set("da","0");
    m.component("c").physics("poisson").feature("cfeq1").set("f","rho_pn*1[um^2]/(eps_si*1[V])");
    for(String tag:new String[]{"left","right"}){
      m.component("c").physics("poisson").create(tag,"DirichletBoundary",0);
      m.component("c").physics("poisson").feature(tag).selection().named(tag);
      m.component("c").physics("poisson").feature(tag).set("r",tag.equals("left")?"0":"Vj/1[V]");
    }
    m.component("c").cpl().create("intall","Integration");
    m.component("c").cpl("intall").selection().geom("g",1);
    m.component("c").cpl("intall").selection().all();
    m.component("c").cpl("intall").set("intorder",8);
    m.component("c").mesh().create("mesh");
    m.component("c").mesh("mesh").feature("size").set("custom",true);
    m.component("c").mesh("mesh").feature("size").set("hmax","min(Wpn/12,0.01[um])");
    m.component("c").mesh("mesh").create("edge","Edge");
    m.component("c").mesh("mesh").run();
    m.study().create("std");m.study("std").create("stat","Stationary");m.study("std").run();
    String solution=null,data=null;
    for(String s:m.sol().tags())if("std".equals(m.sol(s).study())){
      require(solution==null,"Multiple solutions");solution=s;}
    require(solution!=null,"Missing stationary solution");
    for(String d:m.result().dataset().tags())if("Solution".equals(m.result().dataset(d).getType())&&
      solution.equals(m.result().dataset(d).getString("solution"))){require(data==null,"Multiple datasets");data=d;}
    require(data!=null,"Missing stationary dataset");marker("DATASET "+data+" SOLUTION "+solution);
    String[] expressions={"Na/1[1/cm^3]","Nd/1[1/cm^3]","ni/1[1/cm^3]","Tpn/1[K]","epsr",
      "Vr/1[V]","Lp/1[um]","Ln/1[um]","xp/1[um]","xn/1[um]","Vbi/1[V]","Vj/1[V]",
      "intall(if(x>0[um],rho_pn,0[C/m^3]))/1[C/m^2]",
      "intall(if(x<0[um],rho_pn,0[C/m^3]))/1[C/m^2]",
      "intall(rho_pn)/1[C/m^2]",
      "intall(if(x>0[um],rho_pn,0[C/m^3]))/(2*Vj)/1[F/m^2]"};
    double[] v=globals(m,data,expressions);marker("READBACK "+Arrays.toString(v));
    marker("XP "+v[8]);marker("XN "+v[9]);marker("POTENTIAL "+v[11]);
    marker("CHARGE "+v[12]+","+v[13]+","+v[14]);marker("CAPACITANCE "+v[15]);
    int count=101;double[] positions=new double[count];
    for(int i=0;i<count;i++)positions[i]=-v[6]+(v[6]+v[7])*i/(count-1.0);
    m.result().numerical().create("pnSamples","Interp");
    m.result().numerical("pnSamples").set("data",data);
    m.result().numerical("pnSamples").set("coord",new double[][]{positions});
    m.result().numerical("pnSamples").set("edim",1);
    m.result().numerical("pnSamples").selection().geom("g",1);
    m.result().numerical("pnSamples").selection().all();
    m.result().numerical("pnSamples").set("ext",0);
    m.result().numerical("pnSamples").set("coorderr","on");
    m.result().numerical("pnSamples").set("matherr","on");
    m.result().numerical("pnSamples").set("recover","off");
    m.result().numerical("pnSamples").set("expr",new String[]{"x/1[um]","phi_pn*1[V]",
      "-d(phi_pn,x)*1[V]","rho_pn"});
    double[][][] sampled=m.result().numerical("pnSamples").getData();
    require(sampled.length==4&&sampled[0].length==1&&sampled[0][0].length==count,"Sample shape");
    for(int i=0;i<count;i++)marker("SAMPLE "+i+","+sampled[0][0][i]+","+sampled[1][0][i]+","+
      sampled[2][0][i]+","+sampled[3][0][i]);
    marker("FIELD sampled_actual_solution_gradient");
    m.save("pn_checkpoint.mph");marker("COMPLETED prescribed_depletion_poisson_not_drift_diffusion");return m;
  }
  public static void main(String[] args)throws Exception{run();}
}
"""
    return template.replace("__IDENTITY__", identity).replace("__PARAMETERS__", parameters_java)


__all__ = ["build_ring_geometry", "depletion_response", "poisson_reference", "render_pn_java"]
