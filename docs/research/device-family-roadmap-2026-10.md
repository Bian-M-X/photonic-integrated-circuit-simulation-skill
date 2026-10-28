# Device capability development and decision record

Updated 2026-10-28. This records the next development stage, not a claim that the whole
roadmap is implemented. The lead agent owns scope, assumptions and acceptance;
delegated coding, source research and independent numerical checks use separate
assignments. Model identity and run evidence belong in each campaign's record.

## Current release and next priorities

Version 0.7.0 delivers the seven reduced S models, readback diagnostics and
bounded native canary helpers under the skill name
`photonic-integrated-circuit-simulation`. The records below retain the chronology
and limits of the native tests. Next, develop bend geometry and a four-port
crossing route in parallel with the separate power/convergence investigation;
then extend geometry-based coupling, MMI and Y tests. Each native claim needs
its appropriate evidence, while exploratory work can proceed independently.
Use focused checks during development and one full regression/package check
per release batch, rather than repeating a complete delivery process per probe.

## Delivered software scope

The seven parameterized models cover straight propagation, directional coupling,
single-bus and add-drop rings, uniform Bragg CMT, ideal 2x2 MMI and ideal Y screening.
The two ring variants share a family; the ideal MMI is a circuit baseline with
caller-declared split, excess loss and phase, not a geometry/self-imaging solver.
The Y baseline includes branch reflections and an explicit reflected orthogonal
branch combination. It is not an all-ports-matched junction or a geometry model.
Strict versioned requests produce complete complex matrices, explicit units,
conventions and limitations. They can export into the existing circuit engine.
The composition loader also accepts its writer's checked derived-power column,
making hierarchical reuse possible without deleting a column manually.

The canary also has a separate offline symmetric taper profile generator.
It creates configure-stage source and expected geometry, including equal-width
and zero-length controls, while leaving the historical native template and
runner unchanged. Separate profile-bound mode and driven helpers now validate
checkpoint lineage and native readbacks. One equal-width control and one default
nonzero double ramp completed single-wavelength driven diagnostics. The target-mode
S observations do not establish device qualification: the approximately 0.67%
port/modal power mismatch persists. Custom profiles need their own mode evidence,
readbacks and appropriate convergence before a performance claim.

The seven parameterized S models are analytic/reduced capabilities. A geometry request cannot be answered
by pretending the input effective index or coupling coefficient was calculated.
No material database, convergence gate or native fidelity label is upgraded by
these changes. In particular, `2D_material_index_surrogate` must not silently
become `full-wave-2d-eim` to fit a circuit schema.

## Validation structure

1. Numerical contracts: reject malformed requests, nonfinite values and wrong
   units/bounds; preserve complete port order and complex amplitudes.
2. Independent equations: Hamiltonian eigenvectors for coupling; feedback
   linear systems for rings; boundary-value ODE integration for Bragg. Include
   limiting cases, phase, critical coupling and unequal arcs. For the ideal MMI,
   check orthogonal eigenchannels, coherent-input passivity and actual two-stage
   circuit interference; a correct split ratio alone must not pass.
3. Integration: generate CSV, load actual component contracts, eliminate an
   actual network and round-trip the composed output. Test destructive examples
   such as corrupted derived power rather than only happy paths.
4. Native diagnostic: a new original straight/taper canary starts with semantic
   geometry/material/boundary readback, followed by sampled modal census and a
   same-model source sweep. Compilation, configuration, modes, driven fields,
   exports and physical checks each retain their own outcome. An API failure
   blocks dependent stages even if the launcher returned zero.
5. Qualification: only after native diagnostics close, refine mesh, modal
   windows, background/absorber and frequency sampling, then compare an
   independently calibrated reduced model at common reference planes.

The reusable native runner is single-wavelength and single-mesh per invocation.
A separate frozen campaign compared three independently remeshed straight controls.
Its scope is a 2D scalar index surrogate, not 3D SOI or a device acceptance certificate. Experimental
source existence is distinct from successful execution. Consult the associated
campaign receipt for actual attempted/completed stages and failures.

## Prioritized next iterations

The 2026-10-19 straight-control diagnostic now has fresh compilation,
configuration readback, selected modes checked against an independent slab
oracle, and both driven source columns from the same mode checkpoint. The
observed effective index is about 2.1836923 versus 2.1837000 analytically. This
is a 2D scalar bulk-index surrogate at 1550 nm, not calibrated SOI EIM. The
direct port-flux integrals differ from modal power by about 0.67%; small
S-based closure alone therefore cannot establish loss accuracy. The selected
mode exports include complex E/H; the full-domain exports contain Ez and
Poynting components, not the full magnetic field. Taper was unexecuted at that
stage; its later profile-bound runs are recorded below.

The follow-up three-mesh campaign used 21,222 / 38,592 / 73,126 elements.
The maximum receiver flux/modal discrepancy decreased from about 0.676% to
0.429% to 0.276%, but the final mesh still fails the frozen 0.1% target.
The last-two-mesh power change is about 0.001592 of input power, also above
the frozen 0.00025 target. Stable modal transmission is insufficient to
override either failure. Same-checkpoint result integration at orders 6 and 8
agrees to about 2.1e-14, while a nonpolynomial control improves with order:
the observed gap is not explained by that integration-order interval.
This is evidence of a mesh-sensitive discrepancy, not a complete cause diagnosis
or a demonstrated asymptotic convergence rate.

For native performance qualification, isolate the remaining straight-control
field/port discretization and boundary-window sensitivities in a separately
budgeted campaign. Independent exploratory device-family work can continue with
its own scope and limitations. Retain direct flux, modal power and native energy closure
as distinct observables; never fit a common amplitude correction to pass.
Keep the existing thresholds fixed when diagnosing this discrepancy.
Follow with zero-change and short-taper controls using the same
mode-first contract. A new bounded campaign needs its own declared budget;
an interrupted campaign must not reset its elapsed time to obtain more runs.

| Priority | Work | Entry evidence | Required counterexample / decision |
|---|---|---|---|
| 1 | Refine the straight power baseline, then zero-change taper control | Existing straight diagnostic plus mesh/integration and boundary sensitivity | Wrong core material; clipped mode window; incorrect source/dataset mapping; small S closure hiding a flux discrepancy |
| 2 | Taper profiles, bend and crossing validation | Straight control and an explicit target mode | High total flux with low desired-mode overlap; radiation versus absorption |
| 3 | Native directional coupler and reduced-model calibration | Two local modes, supermode splitting and complete four-port S | Deliberate mismatch; compare amplitude and phase across wavelength |
| 4 | MMI and Y branch | Complete input/output modal census, reflection and excess-loss accounting | Correct 50:50 ratio with large excess loss must fail |
| 5 | Rings and Bragg geometry/native validation | Validated couplers/propagation and wavelength resolution budget | Ring backscattering and undersampled narrow poles; CMT breakdown at strong grating |
| 6 | Polarization converter, free-space grating coupler and modulator | Vector/3D, overlap or multiphysics route appropriate to the claim | Vertical leakage, polarization impurity, invalid material/drive response |

Within each iteration, rank unresolved tasks by the claims they block and the
cost of a discriminating test. Freeze a small acceptance target before running;
do not spend the run budget merely increasing the number of families named in
documentation. Keep a reserved validation budget instead of using every run for
candidate search. Failures should produce a concrete API/physics hypothesis,
not identical retries or looser tolerances.

## Known interface boundaries

The 2026-10-24 existing-checkpoint spatial diagnostic completed two-source
postprocessing at seven internal sections. Coordinate/length controls,
integration-order comparisons and material-split integrals passed, but exported
complex components did not reproduce the sampled flux expression within the
frozen tolerance. The overall diagnostic therefore remains failed. Actual
electric-field order was read back as 2; the cause of the sampling mismatch and
the underlying H evaluation remain unresolved. Keep both the original port-gap
and mesh-change failures active.

The next bounded sampling campaign retained three failed native attempts. Its
completed CutLine portions at one section showed nonmultiplicativity even for
the analytic coordinate expression `y^2`; increasing result refinement reduced
both that residual and the component-product flux residual. Direct complex-field
arrays matched separately exported real/imaginary components. These observations
support a sampling-path contribution but do not isolate the entire flux error.
The explicit Solution comparison remains incomplete: after explicit domain
binding, converting the numeric coordinates from um to m returned physical
`x/1[um]` near 5e-8 rather than the intended 0.05, and the frozen coordinate guard
rejected it. Thus the SI-input hypothesis failed for that path. That campaign
remains closed; its partial first point is not a completed comparison.

A subsequent separately frozen campaign retained explicit domain binding and
used the original um numeric coordinates. It completed one existing-solution
postprocess: 214 rows per source on the Solution path, with all 13 algebraic
checks passing, while CutLine refine=1/2 failures remained. Returned physical
coordinates agreed with their inputs to about 2.3e-16 um. The 214 rows contain
repeated coordinates and are not 214 independent spatial locations. Cut traces
can differ at the same coordinate; the all-domain point result does not certify
side-specific interface traces. This establishes a usable local sampling control,
not mesh convergence, magnetic-field accuracy or a resolved receiver power gap.
Independent analytic family development and multiport counterexample tests can
continue while native qualification waits; do not promote their evidence tier.

The next bounded campaign checked explicit single-domain traces at the same
section, with fixed 0.001/0.0001 um interface offsets and requested interface
points. After one retained unit-readback failure, all 56 two-source rows passed
the identity and algebra checks. Actual `dom` distinguished selected interface
sides; local all-domain/single-domain flux differences were at roundoff scale.
This does not establish a continuous interface limit, global field accuracy or
the cause of earlier cut and receiver discrepancies.

Two equal-width taper controls also passed native configuration readbacks.
Their core/background areas, material assignments and port spans matched, while
full-model vertex/edge counts were 18/22 for the collinear polygon and 12/16 for
the rectangle (five domains each). Their boundary IDs differed. Next, bind
profile/source/checkpoint identity and actual geometry to the mode workflow;
do not reuse fixed-profile selections or plots. No mesh or field solve was
performed for these controls. Native bend/crossing/coupler expansion remains
dependent on the evidence required by its particular performance claim.

Profile-bound mode preparation and offline evidence validation are now available
in the separate canary helper. Two equal-width representations completed native
mode checks with profile/source/receipt/checkpoint linkage. The independent slab
reference gave neff 2.1837000141; both native controls gave about 2.1836922644,
with normalized outward power 1 and E/H residual about 2.22e-7. This validates
the bounded port-mode observation, not device scattering or the unresolved
receiver power gap. Preserve the original producer snapshot when helper bytes
change, and bind any later driven-resume source to the same identified profile
and actual checkpoint. Short nonzero tapers and bend/crossing expansion are the
next exploratory targets after that resume route is implemented and tested.

The profile-bound resume route has now completed a bounded three-job campaign:
historical equal-width modes to driven continuation, a fresh nonzero taper mode
checkpoint, then its own driven continuation. Both driven models produced complete
two-source target-mode complex S at 1550 nm. The taper's raw target-mode T was
about 0.9999979 with R about 6.34e-7, but receiving-flux/modal gaps reached about
0.00680 Pin and still failed 1e-3. These are recorded diagnostics, not a validated
loss estimate or converged comparison. No cross-model phase gauge alignment was
established. Next, expand smooth-bend/crossing geometry controls while planning a
separate port-normalization and convergence test for any performance acceptance.

The first bend extension is an offline return-to-center Euler geometry helper:
four signed Euler turns, normal offsets and straight leads, with a zero-angle
rectangle and mirror control. It reuses the existing Euler numerical recipe
and reports intended versus sampled lengths/areas separately. Its Java fragment
configures interpolation solids, without a material/port/solver backend.
Independent geometry tests and sample refinement therefore remain software
evidence. Actual native topology/area/selections, its own mode checkpoint and
any bend-loss/convergence claim require subsequent evidence; the existing
two-port taper mode protocol cannot simply consume this geometry fragment.

A subsequent bounded COMSOL geometry-only probe accepted the zero-angle
rectangle's semantic domains/material/end windows after an explicit unit
codepoint repair. The default closed-interpolation bend formed one core and
passed its area/end-width checks, but a finalized lower-edge sample deviated
about 0.52 nm from the intended boundary, failing the frozen 0.1 nm contour
criterion. The upper measured-box versus sampled-edge extent discrepancy is
also retained. No bend mode/field solve ran. The 0.1 nm target was chosen for this
geometry probe, not supplied as a user device specification. A 0.52 nm departure
does not itself establish a device performance failure or block unrelated
exploratory families. Next, prepare an open-offset/flat-cap construction and test
its native geometry with precision requirements declared for that next use.
Preserve the original failed criterion and checkpoint; any prospective tolerance
change is a new test decision, not a retroactive pass.

- The exterior partition helper accepts disjoint physical faces. Several modal
  Port features may refer to one face. A future channel-to-face validator must
  express that explicitly; removing the overlap check would hide real errors.
- Source-column maps differ between caller-declared diagnostics, a legacy
  ordered two-source recipe and actual native `PortName` readback. Never promote
  one evidence level into another by renaming fields.
- Parameterized device evaluation currently has CLI/Python interfaces. MCP
  exposes its reference route; adding executable MCP tools is separate work.
- Existing scalar-power parsers do not recover complex S or phase. Existing
  fixed Hadamard native evidence is not a generic multimode device backend.
- Source checkout, built wheel and globally installed skill copies are separate
  versions. A tested source update is not an automatic global deployment.
