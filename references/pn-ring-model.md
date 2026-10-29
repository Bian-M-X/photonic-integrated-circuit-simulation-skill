# Ordinary rings and PN-depletion ring modulators

Use `photonic_workflow.ring_modulator` for all-pass bus/annulus geometry,
quasistatic abrupt-junction response, or an original native 1D Poisson probe.
The ordinary and active ring share geometry; activation changes the annulus's
declared index/extinction through the PN result. No copied vendor model is included.

## Geometry and optical reference

`build_ring_geometry(parameters)` returns native primitives, semantic core/active
groups, port windows, exact intended area and connected-component count. Radius
is measured at the ring centerline; gap is the minimum bus/annulus edge distance.
These inputs use micrometres. The default two-dimensional scalar index is a
surrogate, not a calibrated 220 nm SOI stack or vector TE mode.

The optical engine uses a caller-declared **zero-bias real index** plus
`delta_n_eff`. It uses `absolute_k_eff` for carrier extinction at the selected
bias; adding the zero-bias carrier loss a second time would double count it.
Under `exp(+iwt)` and forward `exp(-i beta L)`, passive index is `n - i*k`.
Intrinsic/noncarrier baseline absorption, if present, is separate.

## Electrical approximation and parameter units

`depletion_response(pn)` accepts concentrations in cm^-3, electrical/optical
widths in um, positive reverse bias in volts and temperature in kelvin.
The model assumes an abrupt, fully ionized, nondegenerate silicon junction
and negligible minority carriers in the neutral regions. The intrinsic
carrier density and silicon relative permittivity are explicit inputs.
It does not derive a temperature-dependent intrinsic density automatically.

With p at negative x and n at positive x:

```text
Vbi = kB*T/q * ln(Na*Nd/ni^2)
W = sqrt(2*eps*(Vbi+Vr)/q * (1/Na+1/Nd))
xp = W*Nd/(Na+Nd); xn = W*Na/(Na+Nd)
Na*xp = Nd*xn
Q/A = q*Na*xp = q*Nd*xn
C/A = d(Q/A)/dVr = eps/W = (Q/A)/(2*(Vbi+Vr))
```

Convert every concentration to m^-3 before these SI electrostatic expressions.
The finite p/n electrical domains extend beyond the optical core. The core can
be fully depleted while W still grows; that is optical saturation, not electrical
contact punch-through. A depletion edge reaching a contact is rejected because
the assumed neutral-contact boundary is then invalid. Leakage and avalanche
are outside this approximation even when the geometric check passes.

The [Ansys PN-junction verification](https://optics.ansys.com/hc/en-us/articles/360042273134-pn-junction-diode)
uses built-in potential and depletion width as independent numerical checks.
COMSOL's [semiconductor equations](https://doc.comsol.com/6.4/doc/com.comsol.help.semicond/semicond_ug_semiconductor.6.56.html)
describe the reverse-bias band/quasi-Fermi behavior that a full transport model
must resolve. The present prescribed-charge model does not solve that transport.

## Carrier law and projection

The 1550 nm empirical silicon relations are

```text
F_n(N,P) = -8.8e-22*N - 8.5e-18*P^0.8
F_alpha(N,P) = 8.5e-18*N + 6.0e-18*P       [cm^-1]
k = alpha * wavelength_cm / (4*pi)
```

These coefficients originate in [Soref and Bennett, JQE 23, 123–129 (1987)](https://doi.org/10.1109/JQE.1987.1073206)
and are listed in the official [charge-to-index theory](https://optics.ansys.com/hc/en-us/articles/360034382494-Charge-distribution-to-change-in-refractive-index-theory).
The implemented law is restricted to the 1550 nm coefficient set. Holding it
fixed over a narrow optical sweep is a declared dispersion approximation.

Evaluate the nonlinear hole term **locally**, then average over neutral/depleted
regions using the assumed uniform intensity in the core and declared confinement.
Subtract the zero-bias local-law average from the biased local-law average.
Neither `F(mean carrier density)` nor a fractional power of a negative carrier
difference is equivalent. The returned `mean_electron_cm3` and `mean_hole_cm3`
are audit quantities, not inputs to a second nonlinear conversion.

`optical_overlap` is declared confinement, not computed from a vector mode.
When coupling this response into the native planar solver, interpret this factor
as only the unrepresented confinement or model correction (for example, vertical
confinement). The native field solve already supplies lateral overlap; supplying
a total 3D modal confinement factor here would count that contribution twice.
`delta_n_eff` and `absolute_k_eff` then modify the uniform effective **core**
index, rather than directly specifying the solved propagation index. Replacing
the transverse carrier map by a uniform within-core average is an approximation.
`active_fraction<1` is a roundtrip-average compact approximation; it does not
create an actual biased sector or preserve its local coupler loading. For a
spatially faithful partial-ring model, supply separately grouped arc geometry.
Keep `optical_width_um` and `junction_length_um` consistent with the ring width
and actual active circumference. Capacitance includes that declared junction
height/length and active fraction, while parasitic/contact capacitances are absent.

## Native electrical and optical checks

`photonic_workflow.native_pn` supplies `prepare_pn_bundle`, `verify_pn_bundle`,
`run_pn_bundle` and `calibrate_pn_run`. Preparation/verification are solver-free;
execution is a separate authorized operation with one native process campaign,
a shared 180 s wall limit and private isolated runtime directories. Calibration
binds the raw console, generated source, fresh compiled class and checkpoint.
Completed numerical failures remain failed checks; they are not silently
converted into execution failures or accepted physical models.

`render_pn_java(pn)` produces `NativePn`, an original 1D coefficient-form PDE
Poisson benchmark that needs base COMSOL functionality. Native expressions
compute Vbi, W, xp and xn from the input concentrations and voltage. Four
connected intervals place mesh boundaries at the charge discontinuities;
neutral contacts carry fixed potentials 0 and Vbi+Vr. The solved variable is
dimensionless potential divided by 1 V, which keeps coefficient/source units
explicit. The source prints actual solution coordinates, potential, field,
native charge quadrature, a stationary dataset identity and a checkpoint.
Its capacitance marker is Q/(2*Vj) under the abrupt-depletion law; use several
native voltages and finite charge differences for an independent C-V check.

Compare this native potential/field against `poisson_reference`, verify both
signed charge integrals and charge neutrality, then check the optical engine
actually used the resulting index/extinction. A successful prescribed-Poisson
benchmark does not establish drift-diffusion carrier accuracy in an SOI rib.

For actual device calibration, import converged carrier maps and their modal
overlap or measured complex index versus bias. The official
[PN phase-shifter workflow](https://optics.ansys.com/hc/en-us/articles/360042328674-PN-depletion-phase-shifter)
separates carrier, optical-mode and compact-model steps. Its electrical bandwidth
also needs resistance. The [ring workflow](https://optics.ansys.com/hc/en-us/articles/360042322794-Ring-Modulator)
likewise characterizes coupling, passive propagation and active response before
circuit assembly. COMSOL's [SOI modulator example](https://www.comsol.com/model/silicon-on-insulator-modulator-148411)
couples Semiconductor and Wave Optics for a higher-fidelity route; no file or
proprietary example content from that model is redistributed here.
