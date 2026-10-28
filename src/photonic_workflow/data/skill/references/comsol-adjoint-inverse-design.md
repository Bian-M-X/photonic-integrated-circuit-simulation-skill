# Native COMSOL adjoint inverse design

Use this route to execute a density-based photonic inverse design with a local
licensed COMSOL installation. Start with the runnable example in
[examples/comsol-hadamard-inverse](../examples/comsol-hadamard-inverse/README.md); it contains original Java model construction
and a bounded Windows runner. The package's plan-only MCP adapter is a separate
interface and does not execute this development example.

## Obtain the complete executable fixture

A full repository checkout or release source archive contains the original
`examples/comsol-hadamard-inverse` directory. Install that checkout with
`python -m pip install -e ".[inverse-design]"` in a local environment before
running its README commands. A thin skill copy still requires the matching
runtime and its optional scientific dependencies.

The runtime wheel also carries a synchronized finite mirror of the original
example under `data/skill/examples/comsol-hadamard-inverse`. With the matching
released runtime installed (`python -m pip install "photonic-workflow[inverse-design]==0.7.0"`
once that version is published), extract it to a **new writable directory**:

```python
from importlib.resources import as_file, files
from pathlib import Path
import shutil

target = Path("hadamard-example-new")
resource = files("photonic_workflow").joinpath("data/skill/examples/comsol-hadamard-inverse")
with as_file(resource) as source:
    shutil.copytree(source, target)  # fails if the target already exists
```

For the unpublished local build, install the local wheel with its
`[inverse-design]` extra instead of requesting an unavailable released version.
Run `python hadamard-example-new/campaign.py --output NEW_RUN_DIRECTORY` to
inspect its solver-free plan; add the local solver path and `--execute` only
for the authorized native run. Run files stay outside the package's read-only
resource tree. COMSOL Wave Optics and Optimization licenses are still required
for execution. The mirror contains only original source/README files, no cached
fields, checkpoints, optimized masks or vendor models; edit the canonical
repository example and run the synchronization script rather than editing the
mirror independently.

## Freeze the optical problem

Distinguish material-index 2D, calibrated effective-index 2D, and full 3D models.
The Hadamard example uses in-plane electric fields and out-of-plane magnetic
fields, relative permittivities 12.1 and 2.1, and a 1.3 by 1.3 micrometre design
square. The 400 nm straight access guides attach to the four sides. Ports are
ordered left, bottom, top, right; inputs are 1 and 2, outputs 3 and 4. The density
is reflected across `y=x`. The access guides and outer domain are outside the
1.69 square micrometre design footprint.

These plan-view choices follow He et al.,
[Science Advances 9, eadg6685](https://doi.org/10.1126/sciadv.adg6685), and the
[author manuscript including supplementary materials](https://arxiv.org/pdf/2309.04895).
The two-dimensional bulk
permittivity reduction is an explicitly different modeling assumption from a
220 nm SOI device. It does not establish fabricated efficiency or tomography.

## Resolve modes and gauge before optimizing

For a planar slab with in-plane electric field, the magnetic profile obeys the
TM slab dispersion relation. With half width `a`, `u=h*a`, `v=q*a`, and
`V=k0*a*sqrt(eps_core-eps_clad)`, the even mode satisfies
`u*tan(u)=(eps_core/eps_clad)*v`, `u^2+v^2=V^2`.
The odd relation is `-u*cot(u)=(eps_core/eps_clad)*v`.
At 1550 nm the example supports **two** guided modes, with effective indices
about 2.98196 and 1.61485. A four-channel fundamental-mode S matrix does not
account for every guided mode.

An analytically uniform access guide permits exact user-defined magnetic port
profiles. The native API is `PortType=UserDefined`, `InputType=H`, and vector
`H0={0,0,profile}`. The [COMSOL 6.4 Port documentation](https://doc.comsol.com/6.4/doc/com.comsol.help.woptics/woptics_ug_optics.6.20.html)
defines the profile as the outgoing wave, including on an excited port, with
internal amplitude normalization. Fix the fundamental profile real and positive
at the guide centre, the odd profile positive on the positive transverse side,
and `Thetap=0` on every port. Recalculate dispersion when wavelength or materials
change. Benchmark against numeric Boundary Mode Analysis before adopting this
shortcut for another guide family. General cross-sections still require a mode
solver and an explicit common gauge.

Resolve every propagating mode, including channels outside the target logical
block. The campaign uses TM0/TM1 on each face, with eight source channels. Modal
order is TM0 left/bottom/top/right, then TM1 in the same physical order. The
analytic 400 nm slab coverage check rejects four channels for the default stack;
it is not a general waveguide coverage test. An earlier exterior-modal,
four-port binary mask gave an apparent high-throughput pass that failed when
odd-mode termination was added. Incomplete termination changed that boundary
problem. This lesson does not imply that adding listener modes to transparent,
domain-backed slits should change the driven field: the PML must absorb the
complete outgoing field, while the extra channels resolve its modal content.

Keep all source columns in one built model, and run a source sweep with the
optimized density frozen. Use known physical reference-plane lengths for
deembedding; never fit independent output and input phases to make a gate pass.

## Use uniform PML stretching and independent bidirectional readout

The campaign route is `boundary_model=slit_pml`: eight explicitly domain-backed
interior slit features (`PortSlit=true`, `SlitType=DomainBacked`), a straight
uniform continuation behind each slit, and Cartesian polynomial PML domains.
The same stack continues across both sides of each slit. COMSOL's Port
documentation requires a reflection-free backing region; assigning a PML is
configuration evidence, and its reflection sensitivity still needs a driven
check. The legacy `exterior_modal` route is retained for comparison, not as the
current campaign's boundary contract.

Set and read back these PML source fields in fresh builds and loaded checkpoints:

```text
ScalingType = Cartesian
stretchingType = polynomial
wavelengthSourceType = userDefined
typicalWavelength = c_const/freq/sqrt(eps_clad)
PMLfactor = pml_scale
PMLgamma = pml_curvature
```

The chosen wavelength is spatially uniform and bounds the longest bulk
propagating wavelength in this lossless isotropic core/cladding fixture. It is
frequency dependent in the frequency-domain study; the eigenfrequency
restriction on frequency-dependent PML wavelengths does not apply here. The
[PML implementation documentation](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_definitions.21.137.html)
states that the typical wavelength scales the coordinate displacement. Its
[wavelength guidance](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_definitions.21.138.html)
recommends accounting for shorter components through mesh resolution and
curvature. The explicit single-wavelength requirement on that page is stated
for multiphysics; applying a common longitudinal stretch to this layered slab
also follows from separation of its guided modes.

Controlled native diagnostics found that the former `fromPhysics` setting
produced a substantial incoming-basis defect and apparent excess singular value;
changing to the uniform expression removed the dominant defect. The explanation
that local material wavelengths produced incompatible core/cladding coordinate
maps is an **inference**, not a demonstrated vendor defect. A transverse-independent
longitudinal map preserves the slab modal interface conditions; different maps
across that interface generally do not preserve the same separated modal
continuation. Establish the exact old mechanism with native stretch-field
readback before making a stronger causal claim. Thickness, strength or mesh
tests made with the former setting do not qualify the repaired PML.

Native slit-port diagonal S outputs were nonfinite in the retained diagnostics.
Do not fill or infer those entries. Instead project the solved fields on a
separate closed, source-free contour inside the slits; the nominal inward offset
is `projection_offset_um=0.2`. Partition that contour into four modal windows
and the remaining open segments, and prove disjoint set equality with its
geometry-derived boundary. Integrate signed Poynting flux with explicit outward
normals on this contour, away from the slit field jump.

For a **lossless isotropic uniform access guide with real propagating TM modes**,
let `n` be its outward normal, `t=z_hat cross n`, `E_t=E dot t`, and `h_m` the real
magnetic profile, normalized by `integral(Z_m*h_m^2 dl)=2*P0`, where
`P0=1 W/m` and `Z_m=beta_m/(omega*epsilon0*eps_r)` is piecewise in the core and
cladding. Then `Hz=(a_m-b_m)*h_m` and `E_t=(a_m+b_m)*Z_m*h_m` give

```text
a_m(contour) = integral(h_m*(E_t + Z_m*Hz) dl)/(4*P0)
b_m(contour) = integral(h_m*(E_t - Z_m*Hz) dl)/(4*P0)
a_m(slit) = a_m(contour)*exp(-i*beta_m*projection_offset)
b_m(slit) = b_m(contour)*exp(+i*beta_m*projection_offset)
```

These phase signs use `exp(+i*omega*t)`. The four tangential electric components
are `-Ey`, `Ex`, `-Ex`, `Ey` for left/bottom/top/right. The formulas require a
common real modal gauge and adequate transverse windows; quantify finite-window,
mesh and contour sensitivity, especially for the weakly confined odd mode.
They are not a general lossy-mode or anisotropic-mode overlap prescription.

Export both matrices: nominal-source outgoing amplitudes `A` and incoming
amplitudes `B`, with rows as modes and columns as the same eight source solutions.
Retain `A` as the reported observed matrix. An approximate unit incoming basis
requires the operator-norm bound `||B-I||_2 <= 0.005`, not merely a maximum-entry
test. Report both residuals, together with passivity `sigma_max(A) <= 1.005`,
reciprocity and signed-flux closure. These are engineering tolerances, not exact
identities. Never replace `A` by `A B^-1`, renormalize columns, or fit phases to
rescue acceptance. Such transformations may diagnose source contamination but
cannot remove unmeasured incoming radiation or certify the prescribed source
contract. Missing or failed incoming evidence blocks slit-PML acceptance.

## Optimize the whole differentiable chain

The example uses a real control field on one triangle, a domain Helmholtz
filter, a geometric mirror operator, tanh projection, and linear interpolation
of permittivity. The intended native adjoint must differentiate this complete
chain and the projected readout; its correctness requires the checks below.
Fix the arms, port cross-sections, and outer boundary during the search.

For the declared balanced splitter target
`U=[[1,i],[i,1]]/sqrt(2)`, coherent target power for input 1 is
`J=|a-i*b|^2/2`, where `a=A31` and `b=A41` on the slit-PML route.
This is target-mode throughput times conditional state
fidelity, so it penalizes attenuation and a wrong relative phase. A power-only
product such as `4*|S31|^2*|S41|^2` is a diagnostic objective; it does not fix the
gate phase. Mirror symmetry can reduce training excitations, but independent
validation must still evaluate both input columns and coherent superpositions.
Write `eta=|a|^2+|b|^2` and `pwrong=|a+i*b|^2/2`. The coherent objective is
`eta-gate_weight*pwrong`. Under the imposed mirror and common gauge,
`T=[[a,b],[b,a]]` has minimum all-input throughput
`lambda_min(T^H*T)=eta-2*abs(Re(conj(a)*b))`. The optional `state_floor`
objective is the conservative smooth expression

```text
eta - sqrt(4*Re(conj(a)*b)^2 + 1e-8) - 10*pwrong
```

Use `realdot(a,b)` for `Re(conj(a)*b)` in COMSOL. The smoothing term lowers the
throughput floor and supplies a differentiable surrogate; it does not prove an
all-state conditional fidelity bound. Independent validation must check the
actual two-column target block, its mirror residual and `lambda_min(T^H*T)`.
The `state_floor` route requires a mirror amplitude residual at most 0.005;
otherwise the symmetry-based training reduction fails its contract.

The revised candidate campaign uses `objective_profile=coherent` for gradient
checks and optimization, following the independently exercised higher-throughput
continuation. It keeps `objective_profile=state_floor` for binary validation
so the measured mirror gate remains compulsory. This changes the search
objective, not the actual two-input acceptance metric. It sets `fidelity_weight=10`,
`training_band=five` and maximizes the minimum over
1520/1536.61/1550/1565/1580 nm. Port dispersion is recomputed analytically at each
trained frequency; other-wavelength binary checks rebuild fresh profiles.
1536.61 nm already revealed a weakness and is now a training point, so it is
not an untouched holdout. The revised holdouts are 1543.3 and 1572.3 nm.

Use COMSOL's `realdot(z,z)` for squared complex amplitudes. Split complex state
variables into real and imaginary parts when native sensitivity diagnostics
identify nonanalytic contributions. The filter field remains real. These are
solver choices to verify on the installed version, not assumptions that any
complex expression is automatically differentiable.

Micrometre-scale domain integrals in the filter can be badly scaled relative to
the Maxwell block. Multiplying **all** filter coefficients and its source by
the same dimensionless constant preserves its equation and can improve the
transposed linear solve. The fixture uses a factor of `1e12` with SI spatial
coordinates. Check forward invariance and derivatives; do not transplant this
number blindly into another unit system or relax a failed residual check.

Before a long search, perturb the **filter source**, not the projected material:
`theta_fixed + alpha*v(x,y)`. Make `alpha` the only active sensitivity parameter,
freeze the mesh, and compare native `fsens(alpha)` with central differences at
two step sizes in more than one spatial direction. This checks the mirror,
filter, projection, Maxwell solve and objective together. Numerical utility
tests or successful forward runs alone do not establish this gradient.
Earlier single-frequency gradient diagnostics do not qualify the changed PML,
readout and state-floor objective. Gradient mode accepts only
`training_band=single`: the revised campaign reserves six native checks,
direction 0 at all five training wavelengths and direction 1 additionally at
1550 nm, with two central-difference steps per job. Check all five native
objective values and the `min` aggregation separately. These single-frequency
checks do not establish a differentiated multi-frequency active-set gradient
or multiple-direction derivatives at every trained wavelength.

**Retained failure and controlled repair.** The earlier `pml-probe-17-gradient`
check at 1550 nm, direction 0, returned adjoint `+3.94694` versus stable central
differences about `-2.23832`. In `pml-adjoint-24-solution-termination`, changing
only Fully Coupled `termonres=off` repaired this discrepancy while the forward
objective changed by less than `6e-12`. The projected state-floor
adjoint was `-2.238323555`; relative errors against steps 0.001 and 0.0005 were
`3.49e-6` and `8.73e-7`. The canonical direction-1 check in
`pml-adjoint-25-direction1` also passed both steps, with maximum relative error
`4.25e-6`. These are two centre-wavelength directional checks, not completed
five-frequency qualification, optimizer acceptance or full campaign success.
The recipe remains provisional pending the remaining checks and independent
native reproduction. Forward PML/readout diagnostics alone do not establish
sensitivity correctness.

The mixed cross term itself is mathematically consistent with COMSOL's
[documented `realdot` derivatives](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_definitions.21.039.html)
and [complex sensitivity guidance](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_sensitivity.33.09.html).
For `c=Re(conj(a)*b)`, the algebraically equivalent expression
`c=(realdot(a+b,a+b)-realdot(a-b,a-b))/4` has the same value and first variation.
The smoothed floor contributes
`-4*c/sqrt(4*c^2+1e-8)*dc`. Comparing the two expressions is an assembly
diagnostic, not a proven repair; neither rewriting the objective nor setting
complex-splitting flags replaces the native finite-difference check.

## Continue, freeze, and validate

Preserve the preceding control field when increasing projection sharpness;
restarting each stage from the uniform initial density is not continuation.
Save stage models and keep the last successful stage when a later one fails.
Record the initial density, physical filter length, mesh, objective, beta
schedule, move limit, iteration count, solver, threads, and measured wall time.
An MMA objective trace need not improve monotonically. A better printed value
does not identify a recoverable design unless its matching control field was
saved. The current example saves stage endpoints; do not label an earlier log
maximum as the delivered design. COMSOL's optional
[gradient-based solution retention](https://doc.comsol.com/6.4/doc/com.comsol.help.opt/opt_ug_solver.8.06.html)
can retain additional iterations, but changes storage cost and introduces the
`optSolInd` solution index. Before adopting it, verify the iteration/frequency
mapping and restart selection; the existing five-frequency exporter assumes
the final optimizer solution and must not silently read a different iteration.
Checkpoint checks read the study's `topo.optobj` as a StringMatrix `[[expression]]`.
The generated Optimization solver's `optobj` is a String scalar
`all_obj_contrib`, not an expression array. Check its `objcontrib=all`,
`control=topo` and `objectivesolution=min` (or `auto` for single frequency)
against the study configuration. Maximization direction is the study's
`objectivetype=maximization`; do not query that property on the generated solver.
These types were read back from the local native API. Preserve the seed and
physical profile.

For this fixture, `evaluation_limit` sets the per-stage native `nsolvemax`
stop threshold; it is not a strict evaluation cap. In the independently
reproduced 2026-10-04 GCMMA comparison, the requested and read-back threshold
was 20, but accepted `(Iter, Inner, nEval, rounded J)` rows ended at
`(5,7,26,0.6111)` after histories `nEval=1,3,7,14,19,26` and
`Inner=-,2,4,7,5,7`. COMSOL finished the inner loop before stopping. The
same-seed reduced-move MMA comparison ended at 10 outer iterations and
11 evaluations. Include initial and rejected inner-loop evaluations in cost;
do not equate accepted outer iterations with objective evaluations.

`run.py` records actual per-stage optimization rows and counters from the
six-column optimizer table in `batch.log`, not the Newton table. For incomplete
stages, the last accepted count is only a lower bound. The summed band count
times the number of training frequencies is a nominal training frequency-state
evaluation count (one source per training frequency), excluding subsequent
eight-source validation and all adjoint/Newton/linear-solve accounting.
Verified partial counts from failed jobs are included before success checks;
an empty interrupted next stage does not discard completed prefix work.
Unknown or unverified cost is reported explicitly, not treated as zero.
Aggregates containing incomplete or unknown attempts are marked as lower bounds.
New training logs include both raw complex target-mode amplitudes at every
stage/frequency, collected before the later source-sweep configuration. The
campaign checks their objective reconstruction and exposes common coherent /
state-floor scores, input-one throughput and a labeled mirror surrogate. Use
these for objective comparisons; do not compare unlike raw objective values or
replace the independent two-column/all-input metric with the mirror surrogate.
For recovery drivers, `optimization_prechecks(...)` exposes these values under
`objective_components`, with an `available` flag and stage-indexed
`training_stages[stage]["minima"]` / `["points"]`. Inspect this returned schema
before consuming it. A postprocessing schema error after a completed, hash-bound
solve calls for fresh offline verification and a new recovery record, not an
automatic repeat of the native optimization.
Older logs without amplitudes mark these components unavailable. When reading
old MPH data, select the matching training checkpoint and verify its study,
stored frequencies and excitation. COMSOL can return an isotropic material as
a scalar array or 1x1 matrix; validate the expression/tensor meaning instead of
requiring an expanded nine-entry serialization.
`campaign.py` checks the batch hash and trace consistency, all requested stage
completions, and rounded final objectives against training minima. Actual
per-stage counts above the requested threshold are recorded as `cost_overrun`:
retain the completed solver receipt and independent physical analysis, then
stop all further native jobs. The check cannot prevent an overshoot within the
completed job. Wall timeout and maximum outer iterations are separate bounds.

The native example explicitly sets and reads back Fully Coupled
`dtech=const`, `damp=1`, `jtech=onevery`, `ntermconst=tol`, and
`termonres=off`, and reads back
the MMA minimax handling setting `mmaminmax=on`. Maximization itself is set on
the study, as above. The
[COMSOL 6.4 FullyCoupled API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.28.html)
defines these damping, Jacobian-update and termination properties. This is a
model-specific choice: at fixed optimization controls, the Helmholtz filter is
linear and independent of the electric field; at fixed filtered density, the
wave problem is linear. Their coupling has block-triangular structure, so exact
full Newton updates can ideally resolve the forward state in two updates.
That does not guarantee a correct final sensitivity Jacobian. COMSOL's
[sensitivity algorithm](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.154.html)
uses the transpose of the last forward linearization for the adjoint. In this
triangular filter/Maxwell system, a small final residual can coexist with
cross-block derivatives assembled at a preceding state. The failing diagnostic
terminated with two Jacobian assemblies; solution-based termination added a
near-zero correction and a third assembly, consistent with refreshing the
linearization needed for sensitivities. This explanation is supported by the
controlled test and documented reuse, not direct inspection of the assembled
matrix. `termonres=off` selects solution-based error estimation instead of the
residual-based early stop; it retains `ntermconst=tol` and the tolerance value.
It is a stricter convergence path for this fixture, not a universal prescription
for nonlinear optics. Keep complex splitting active and verified for both the
sensitivity study and its finite-difference comparison study.

Retained diagnostics motivated these explicit solver settings after automatic
Newton reached its iteration limit during projection continuation. A successful
short restart is evidence for that step only; it does not qualify the revised
PML, objective, complete continuation or independent binary validation.

Do not read the MMA log's `Error` column as an unscaled density increment.
In a five-frequency, one-iteration diagnostic from uniform density 0.5,
the log reported 0.417 while direct evaluation of the control field gave a
maximum change of 0.0417365, within the configured 0.05 move limit. The ratio
is consistent with normalization by the local move interval; that observation
is not a general formula for every COMSOL optimizer. Inspect actual controls,
their scales and effective study/solver settings before changing an optimizer
because of a log value. Stored solver customizations and the controlling study
must be considered together.

Treat gray-density performance as provisional. Export the density, extract an
actual binary geometry, and solve that geometry independently. Reevaluate after
mesh refinement and a boundary/port-window change, then test wavelengths held
out from the objective. If phase, loss, split ratio or robustness changes beyond
the declared tolerance, repair the design or narrow the claim.
Refine both the core and cladding. The selected binary candidate is first solved
at 25/100 nm core/cladding maxima. The locked comparison reference uses
20/80 nm core/cladding maxima, outer half-width 3.15 μm, port half-window
1.5 μm and projection offset 0.2 μm. Compare with 15/60 nm refinement and with
an expanded boundary/window configuration on the reference mesh. Retain the
absolute stability limits: 0.005 throughput, 0.002 fidelity and 0.02 splitting
ratio. Throughput checks include coherent superpositions, not just the two
basis-input powers; compute the all-input minimum from the actual target block.
Every configuration must independently pass incoming normalization, complete
eight-channel passivity/reciprocity and signed-flux closure. These checks are
additional to the stability comparison and cannot be traded against each other.

The executable campaign uses a cheap additional design variable when the first
binary contour shifts the split ratio: the threshold of the filtered field.
It estimates the local slope of the signed log power ratio from **actual binary
solves**, proposes a bounded secant step, and retains all attempts. This is an
engineering correction of a gray-to-binary model discrepancy, not a claim of a
new optimization theorem. It can fail if topology changes make the response
nonsmooth; then return to a better-resolved or robust topology objective. Freeze
the chosen mask before the reserved mesh, boundary and wavelength validations.
Never relabel those held-out evaluations as an untouched validation after tuning
against them.

Run `python examples/comsol-hadamard-inverse/campaign.py --help` for the bounded
workflow. Its default is a plan; `--execute` starts native jobs. For checkpoint
recovery, `run.py` offers a frozen-validation mode that rebuilds diagnostics and
exports density without repeating optimization. The solver receipt distinguishes
successful execution from scientific acceptance. The standalone example verifier
binds matrix, signed-flux, incoming amplitudes, plan and boundary-set evidence to
their receipt hashes. Frozen source-sweep export is a centre-wavelength check;
fresh binary models supply the other wavelength and geometry checks.

The revised candidate campaign reserves at most **36 native jobs**:

| Stage | Maximum jobs | Evidence purpose |
|---|---:|---|
| Single-frequency full-chain gradient checks | 6 | Direction 0 at all five training points; direction 1 at 1550 nm |
| Optimization and continuation/restart | 5 | Five-point minimum coherent objective; explicit restart lineage |
| Binary threshold candidates | 6 | Actual binary solves; all attempts retained |
| Locked validation | 19 | Independent checks of the fixed selected mask |

The five optimization jobs are beta 2 for eight iterations, a restarted beta 2
for thirty-two, beta 4/8 for forty each, beta 16 for forty, and beta 32 for forty
after core-mesh refinement from 45 to 25 nm. Restart boundaries are part of the
recipe, since they reset MMA history.
The coarse restart uses `reconfigure_restart: true` to regenerate the solver
from the saved warmup control field; subsequent restarts retain the checked
solver setup, matching the exercised lineage.
Binary search begins at .5/.495/.505,
then uses observed secants or sign-bracket interpolation, bounds [.44,.53], and
a .02 step limit relative to the best observed finite imbalance. No optical
matrix entries or port phases are fitted. The center-only threshold search
does not spend or replace any reserved qualification check.

The nineteen locked jobs use the same hashed binary mask:

Run training-wavelength and numerical-variation checks before the two holdouts.
The campaign stops at the first acceptance or convergence failure, records the
completed and unspent checks, and never labels a partial suite as passed. This
preserves unused holdouts when the mask already fails a known training or
numerical condition. The same nineteen configurations and thresholds still
have to pass for qualification. Once a holdout has been observed, its result
must be disclosed if it influences subsequent design decisions.

| Checks | Jobs | Wavelengths and changed settings |
|---|---:|---|
| Centre mesh references | 2 | 1550 nm, 20/80 and 15/60 nm core/cladding |
| Other training references | 4 | 1520/1536.61/1565/1580 nm, 20/80 nm |
| Holdouts | 2 | 1543.3/1572.3 nm, 20/80 nm |
| Expanded boundary/window | 4 | 1520/1536.61/1550/1580 nm, outer half-width 3.65 μm and port half-window 1.7 μm |
| Stronger PML | 2 | 1536.61/1550 nm, thickness 1.2 μm and scale 2 |
| Shifted projection contour | 2 | 1536.61/1550 nm, inward offset 0.4 μm |
| Additional mesh refinement | 3 | 1520/1536.61/1580 nm, 15/60 nm |

Compare each perturbation with the same-wavelength 20/80 nm reference; at
1550 nm also compare the selected 25/100 nm binary candidate with both mesh
references. Boundary, PML and projection variants use the 20/80 nm mesh. The
1565 nm and holdout results have no reserved mesh-sensitivity comparison, and
the holdouts have no reserved boundary/PML/contour-sensitivity comparison.

The selected binary design completed all **nineteen locked checks and thirteen
convergence comparisons** on 2026-10-10. An independent completion audit
recomputed raw 8×8 outgoing/incoming matrix metrics and signed-flux checks,
verified the frozen source/driver and prior inputs, and confirmed worker release.
See the [qualified 2D showcase](../docs/showcases/hadamard-2d/README.md).
GPT-6.1-sol independently authored the reproduction drivers and generated the
uniform-start design lineage and bounded threshold calibration. The root agent
executed the final unchanged frozen driver because the initial subagent
authorization review lacked direct user quotations; independent audit followed.
The qualification applies to this selected lineage and locked binary mask. It
does not establish that the revised default recipe was rerun uninterrupted from
scratch, or that all earlier research attempts are included in its cost figures.
Plan generation, unit tests, a passing diagnostic or execution receipt alone
remain insufficient for physical acceptance.
The former three-point-training, nineteen-total-job contract is superseded.
Its 1536.61 nm test is disclosed and absorbed into training, and must not be
relabeled as untouched validation. The five trained and two holdout wavelengths
are **seven discrete points**, not continuous-band convergence. If holdout
results influence design selection or retuning, disclose their use and reserve
new independent tests for any revised claim.

Boundary-set verification uses COMSOL's documented
[named selections and adjacency](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.56.html).
On the slit-PML route it proves the independent inner control-volume boundary
equals the disjoint union of its four modal windows and open segments. The
legacy exterior-modal route separately proves equality with the full physical
exterior. Neither proof follows merely from nonempty port selections.

For this example, the standalone matrix checker is
`python -m photonic_workflow.optimization.hadamard INPUT.json --output REPORT.json`.
It checks six single-photon basis/superposition inputs, conditional Choi overlap,
minimum all-input target throughput, splitting ratios, passivity and reciprocal
mode consistency. Six-state conditional fidelity is not a proven all-input
conditional fidelity minimum. It accepts a larger observed matrix when extra
modes are provided. The standalone matrix checker does not by itself establish
the slit-PML incoming-basis, field, flux or convergence contract; the campaign
also requires the receipt-bound artifact analysis. The default
fidelity floor 0.987 and throughput floor 0.9 are **engineering criteria**; the
paper's reported experimental 0.987(3) has a different definition, and the paper
does not supply a numerical Hadamard throughput floor. Report successful
two-dimensional surrogate calculations in those terms.

For export, convergence, geometry constraints and fabrication corners, also read
[adjoint and fabrication](adjoint-and-fabrication.md) and
[source-sweep contracts](frequency-domain-source-sweeps.md).

## Fixed-checkpoint native discrete-gradient checker

The delivered `examples/comsol-hadamard-inverse/check_discrete_gradient.py`
uses the sibling runner's process supervisor and digest helper, and compiles
`CvfDiscreteGradientProbe.java` through the official COMSOL entrypoint. Start
with a plan:

```powershell
python examples/comsol-hadamard-inverse/check_discrete_gradient.py `
  --solver-root $env:PHOTONIC_SOLVER_ROOT --restart C:\Private\beta8-checkpoint.mph `
  --output C:\Private\fresh-gradient-run --processors 8 --timeout 900
```

Add `--execute` only within the user's authorized solver scope. The default
creates no artifacts and launches no process. The restart must be the existing
weight10, `state_floor`, slit-PML, five-frequency beta8 checkpoint. This checker
has a fixed beta16 evaluation, one feasible control direction and two central
steps (0.001, 0.0005), without changing optimization, mesh or CVF type.

Solution-data copying requires both the original `std1` study association and
an explicit minimal `StudyStep` for `std1/freq`, `splitcomplex=true`, before
`createSolution()`. Every evaluation rebuilds the sensitivity sequence, checks
the full-index/coordinate map, reads back perturbed controls, and validates the
mapped `Fsens` imaginary components. The gradient contraction is the actual
discrete-vector dot product without an area multiplier or clipping.

The parser independently recomputes AD/FD relative errors and the minimum
across all five wavelengths from original observations; all fixed samples and
markers are mandatory, finite and unique. It checks printed values against
recomputed values and uses a fixed relative tolerance of 0.002. Receipt fields
`completed` and `gradient_pass` distinguish native completion from scientific
agreement. Exit codes are 0 pass, 1 execution/invalid-data failure, and 2 valid
data with gradient disagreement. This diagnostic establishes neither all
control directions nor performance acceptance or mesh/PML convergence. See the
example README for the complete CLI and receipt contract.
