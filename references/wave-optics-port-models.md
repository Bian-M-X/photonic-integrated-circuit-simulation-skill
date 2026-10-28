# Wave-Optics Port Models

Use this reference for 2D effective-index models, materials, geometry selections, numeric ports, boundary mode analysis, scattering/PML boundaries, mesh strategy, datasets, S-parameter expressions, and energy diagnostics.

## Contents

- [Model Scope Decision](#model-scope-decision)
- [Materials And Geometry](#material-selection-audit)
- [Numeric Port Setup](#numeric-port-setup)
- [Study Sequence Contract](#study-sequence-contract)
- [Boundary Conditions](#boundary-conditions)
- [Mesh Strategy](#mesh-strategy)
- [Convergence Contract](#convergence-contract)
- [Postprocessing And Datasets](#postprocessing-expressions)
- [Export Contract](#export-contract)
- [Energy Diagnostics](#energy-diagnostics)
- [Straight Waveguide Smoke Test](#straight-waveguide-smoke-test)

## Model Scope Decision

Before building geometry, state the model class:

- `2D EIM`: top-view effective-index approximation for topology, coupling trends, phase, FSR, and fast sweeps.
- `3D submodel`: straight waveguide, bend, directional coupler, or short cell validation.
- `full 3D`: expensive final validation, not the default first step.

2D EIM is not a final fabrication sign-off. It is useful for fast physical reasoning and parameter ranking.

## Common Global Parameters

```text
lambda0 = 1.55[um]
freq0 = c_const/lambda0
w = 0.5[um]
n_bg = 1.444
n_wg_eff = <mode-solver-or-paper-value>
epsr_bg = n_bg^2
epsr_wg = n_wg_eff^2
mu_r = 1
sigma = 0
```

For a paper using a `500 nm x 220 nm` SOI strip waveguide, prefer a separate cross-section mode analysis to extract:

- `n_eff(lambda)`
- `n_g(lambda)`
- single-mode or multimode behavior
- wavelength dispersion
- approximate mode-field extent for port sizing

If mode analysis is not available, use paper values or an engineering estimate, and label the result as an approximation.

## Material Selection Audit

Keep explicit selections:

- `sel_bg`: all background/cladding domains.
- `sel_wg`: all waveguide effective-core domains.
- optional `sel_dc_gap`: coupler-gap refinement region.
- optional `sel_bends`: bend refinement regions.
- optional `sel_ports`: port boundaries.

Assign materials:

- `mat_bg`: `epsilonr = epsr_bg`, `mur = 1`, `sigma = 0`.
- `mat_wg`: `epsilonr = epsr_wg`, `mur = 1`, `sigma = 0`.

Audit after every geometry rebuild:

- no waveguide domain is left in background material
- no background island is assigned waveguide material
- booleans did not destroy selections
- design-region material does not overwrite fixed waveguides

Read these assignments from the finalized native model, together with domain
areas, bounding boxes and semantic selection provenance. Do not use fixed domain
numbers or smallest-area selection as a universal shortcut. Check the actual
finished outline after interpolation and booleans; sharp end caps can invalidate
an otherwise correct centerline. Use `executable-diagnostics.md` for a runnable
2D exported-readback guard. Its pass does not establish native connectivity,
material tensors or an independently verified mode profile.

In the COMSOL 6.4 native canary, finalized domain measurements use
`geom("g").measureFinal().selection().geom("g", 2)` followed by
`selection().set(domainIds)`. The geometry-object selection returned by
`measure()` is a different API; neither an object selection nor an assumed
`MeshSelection.init(int)` call can substitute for finalized entity selection.
Verify the version-matched API and native readback before reusing this pattern.
Compare measured area and bounds together: a tiny area difference explained
by coordinate representation warrants an explicit geometry tolerance, not a
change to optical acceptance limits. Preserve the initial discrepancy and its
explanation; this does not establish mesh convergence.

## Geometry Rules

Build from centerlines when possible:

- centerline length defines phase and `DeltaL`
- waveguide width is applied from `w`
- bend radius is measured at centerline
- do not use x-coordinate distance as a path-length proxy

For bends and transitions:

- avoid sharp 90-degree corners
- use arcs, S-bends, fillets, or rounded polylines
- keep `R_bend >= 5[um]` as a cautious 2D EIM starting point for 500 nm-class SOI strips
- sweep `R_bend = 5, 7.5, 10[um]` when bend loss matters
- keep non-port waveguides at least several microns away from outer boundaries

For port approach sections:

- local guide must be straight
- port boundary must be perpendicular to propagation direction
- keep `5-10 um` straight section before the port

## Numeric Port Setup

For port-based frequency-domain simulations:

1. Put ports on exterior computational boundaries.
2. Make each port boundary perpendicular to a local straight waveguide.
3. Select the intended local modal cross-section, not an arbitrary whole outer
   edge shared by unrelated guides or background.
4. Create one boundary mode analysis step per numeric port when numeric ports are used.
5. Bind each port to the correct boundary mode analysis result.
6. Run final frequency-domain or wavelength-domain study after port modes are available.

Port mistakes are common. Check:

- selected boundary id is correct
- port orientation is correct
- excitation is enabled only on the intended input port
- non-excited output ports are terminated, not excited
- scattering/radiation boundary does not include port boundaries
- distinct ports do not share any boundary entity
- ports plus open-boundary treatment cover the complete exterior, with no
  missing exterior and no selected internal boundary
- final study uses the port mode solution, not a stale or missing mode

The exact local cross-section is model-class dependent:

- In a reduced 2D EIM topology where geometry segmentation makes the silicon or
  effective-core terminal segment the validated port face, select only that
  segment. This prevents a numeric port from launching across the entire outer
  side of the computational domain.
- When the boundary-mode problem needs the evanescent cladding field, create a
  bounded local window containing exactly that guide/core and a justified
  cladding margin. Confirm field decay at the window edge.
- A COMSOL example may use core plus cladding segments across one local slab
  cross-section. This supports a local modal window; it does not justify
  selecting an outer boundary that also contains unrelated terminals or open
  background.

After geometry finalization, call the pure
`audit_exterior_boundary_partition` helper or implement the same set equality
in Java: every exterior boundary must appear exactly once in either one port or
the open-boundary selection.

For a complete complex S matrix, keep all source columns in one model and one
declared port-mode phase basis. Read
`frequency-domain-source-sweeps.md` before configuring or parsing a COMSOL
Frequency Domain Source Sweep. Independently rebuilt source cases may support
per-column powers, but not complex reciprocity, singular-value, phase, or
group-delay claims unless their gauges are explicitly aligned and audited.

## Study Sequence Contract

Treat the study graph as a reviewed contract, not an incidental Model Builder
ordering. Record the COMSOL release, physics tag, study/step tags, port-to-mode
bindings, source order, dataset tags, and intended exports before solving.

For numeric ports:

1. finalize geometry, selections, materials, boundaries/PML, ports, and mesh;
2. add one Boundary Mode Analysis step per numeric port and bind it to exactly
   that port;
3. run or compile a no-driven-solve readback that verifies the ordered steps,
   port bindings, search shift, requested mode count, normalization, and mesh;
4. inspect and track the intended mode at every port using effective index,
   field shape/overlap, polarization, confinement, and propagation direction;
5. run the final Frequency Domain, Wavelength Domain, or
   `FrequencyDomainSourceSweep` step only after the modal basis is accepted;
6. bind tables and field plots to the final driven dataset, while keeping mode
   plots on the corresponding boundary-mode datasets;
7. invalidate the modal basis and repeat the checks after materials, boundaries,
   ports, PML, geometry, or mesh change.

A configuration readback proves only that the intended graph was built. A
runtime smoke proves only that COMSOL started and produced fresh artifacts. A
single driven solve is a physics canary. None of those alone proves convergence
or component qualification.

Do not publish a versioned Java study/mesh/export renderer until its exact
COMSOL release passes `comsolcompile`, a no-solve API readback fixture, and a
bounded driven smoke. Until then, keep handwritten Java project-local and
reviewed against this contract rather than advertising an unverified template.

## Boundary Conditions

Start with scattering/radiation boundaries for quick models. For engineering claims, compare:

- larger background margin
- PML
- scattering boundary
- mesh refinement near boundaries

Critical rule: without PML, scattering/radiation selections contain every
exterior boundary except the port boundaries. With PML, document which exterior
faces are handled by the PML construction and its outer termination. In either
case, port and open-boundary treatments are mutually exclusive and jointly
complete over the exterior.

If S parameters are undefined, zero, or flat:

1. Confirm physics tag, for example `emw` or `ewfd`.
2. Confirm final solution dataset.
3. Confirm port boundaries are excluded from scattering/PML selections.
4. Confirm boundary mode analysis completed.
5. Confirm port feature references the correct mode step.

## Mesh Strategy

Start with a robust predefined mesh if custom mesh prevents meshing or solving. After the first successful solve, add local mesh controls.

Rules of thumb:

- waveguide core: at least `8-10` elements across width
- DC gap: at least `5` elements across the gap
- bend region: same or finer than waveguide core
- far background: coarse mesh to save memory
- port boundaries: enough resolution to represent the port mode

2D EIM starting values:

```text
waveguide max element: 0.05-0.08 um
coupler gap max element: 0.02-0.04 um
bend max element: 0.05-0.08 um
far background max element: 0.2-0.4 um
```

Mesh refinement order:

1. predefined mesh to get a working solve
2. local waveguide refinement
3. local coupler-gap refinement
4. local bend refinement
5. convergence check on key metrics

In the COMSOL 6.4 Size API, the default `size` node always uses its size
properties and has no `hmaxactive` or `hminactive` property. Additional local
Size nodes expose those switches. Read back the appropriate properties for
each node instead of applying one property list to both. Record actual element
counts after meshing; requested size values alone are not a refinement check.
See the [6.4 Size API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_mesh.49.100.html).

For PML models, use the mesh topology required by the selected PML formulation
and verify the PML coordinates and domain selections after geometry changes.
COMSOL's Wave Optics physics-controlled mesh uses structured PML meshes by
default: swept in 3D and mapped in 2D. A PML feature without the intended PML
mesh, domain, and field-decay behavior is configuration evidence only.

## Convergence Contract

Declare the convergence family, metrics, and tolerances before reading the
answer. Vary one numerical cause at a time so a stable scalar cannot hide
compensating errors.

Use independent families as applicable:

- core/gap/bend mesh refinement;
- port-window size and port-boundary resolution;
- background-domain margin;
- PML thickness, coordinate stretching, and PML mesh;
- input/output straight length and reference-plane location;
- wavelength/frequency sampling;
- solver formulation or tolerance after the spatial model is stable.

For each member record:

```text
family_id, member_id, changed_parameter, value
geometry/material/physics/study/mesh hashes
element counts, field DOF, mesh quality
solver type, ordering, memory mode, convergence/exit markers
wall time and peak memory when available
mode identity and effective index at every port
complex S entries, per-input power closure, and declared target metrics
field-audit artifact and output hashes
```

Do not call two coincident values a convergence proof without a declared family
and tolerance. A one-mesh solve remains `diagnostic`. For an improvement claim,
show that numerical uncertainty is smaller than the claimed improvement. If a
refinement changes the tracked mode, source basis, reference plane, or physical
model, treat it as a new comparison problem rather than one convergence step.

Run a resource-bounded canary before a large direct solve. A compile-only DOF
count supports memory planning; it does not establish driven-source feasibility,
field accuracy, PML effectiveness, or convergence.

## Postprocessing Expressions

Use component prefixes when required:

```text
comp1.emw.normE^2
abs(comp1.emw.S21)^2
10*log10(abs(comp1.emw.S21)^2)
abs(comp1.emw.S11)^2
```

If the physics tag is `ewfd`, use:

```text
comp1.ewfd.normE^2
abs(comp1.ewfd.S21)^2
10*log10(abs(comp1.ewfd.S21)^2)
abs(comp1.ewfd.S11)^2
```

Do not mix `emw` and `ewfd`; inspect the model's actual physics tag first.

For quadrature experiments on an already solved model, result-level `IntLine`
and `IntSurface` evaluations can set `intorderactive=true` and `intorder`
without recomputing the solution. Read back the selection, dimension, units,
dataset and actual source axis. The 6.4 `getReal()` default has expressions in
rows and solution numbers in columns; verify cardinality before interpreting
an index. Test a known nonpolynomial spatial integral to establish that order
changes affect evaluation. Newly added physics coupling operators may not be
available in the existing solution's evaluation context; an unknown-operator
error is not a reason to rerun an expensive field solution blindly. See the
[6.4 numerical integration API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.084.html).

## Dataset Rules

Choose the correct dataset:

- field plot: final driven frequency-domain solution
- sweep plot: final parametric or wavelength sweep solution
- S-parameter table: final driven solution
- mode profile: boundary mode analysis dataset

Do not evaluate final S parameters on a boundary-mode dataset.

Debug order for plotting:

1. Add `comp1.` prefix.
2. Verify physics tag.
3. Select final solution dataset.
4. Evaluate one expression at a time.
5. Only then build derived plots or reports.

Before accepting any plot, apply `comsol-field-physical-audit.md`. For a guided
SOI mode, most energy should be associated with the intended high-index core
and connected guide, with physically plausible evanescent tails and leakage.
Broad high-amplitude background excitation or a field concentrated in an
unrelated boundary/PML is a model error even if an S value looks attractive.

## Export Contract

Freeze exports before the final run. Every exported table or plot must identify:

- model/run ID, COMSOL version, physics tag, study step, and dataset tag;
- wavelength/frequency and source-solution index;
- port order, mode labels, normalization, phase/time convention, and reference
  planes;
- raw real/imaginary S entries rather than power-only traces when a complex
  multiport claim is intended;
- per-input modal powers, signed non-port exterior flux, material absorption,
  and closure residual with sign conventions;
- mesh family/member, element count, field DOF, solver/termination markers, and
  convergence status;
- linear and log field views from the final driven dataset with geometry,
  ports, scale, and the full exterior visible;
- fresh artifact timestamps or pre/post signatures plus SHA-256 provenance.

Exit code zero without every declared fresh export is an execution failure. A
fresh export with internally consistent arithmetic can still be physically
rejected. Keep configuration, execution, evidence-reference integrity,
convergence, and physical acceptance as separate fields.

## Energy Diagnostics

For a two-port reflected-output model:

```text
T21 = abs(S21)^2
R11 = abs(S11)^2
Ssum = T21 + R11
radiation_or_uncollected = 1 - Ssum
```

Interpretation:

- correct FSR and low peak T21: interference exists, but coupling/ports/boundaries/bends/mesh may be poor
- high S11: reflection, port mismatch, or round-trip coupler mismatch
- low Ssum: radiation, boundary absorption, bend loss, or uncollected output
- single-wavelength T21 is insufficient for interferometer validation

Do not assign `1 - sum(abs(Sij)^2)` to radiation or absorption by inference.
For every independent input, reconcile modal output power with explicitly
integrated signed non-port exterior flux and material absorption. Keep a solver
feature's outgoing-power variable as a crosscheck unless its equality to the
chosen flux integral has been demonstrated. See
`frequency-domain-source-sweeps.md` for the fail-closed accounting contract.

## Straight Waveguide Smoke Test

Before building a complex device:

1. Build one straight waveguide with two numeric ports.
2. Assign `mat_wg` and `mat_bg`.
3. Run boundary mode analysis and frequency-domain solve at `lambda0`.
4. Confirm high `abs(S21)^2`.
5. Confirm low `abs(S11)^2`.
6. Plot `comp1.<tag>.normE^2`.

Only proceed to couplers and MZI devices after this passes.

## Official Method References

- COMSOL 6.4 documents that numeric ports obtain mode fields and propagation
  constants from Boundary Mode Analysis:
  <https://doc.comsol.com/6.4/doc/com.comsol.help.woptics/woptics_ug_modeling.5.34.html>.
- COMSOL 6.4 documents the Wave Optics study types and the default structured
  PML mesh behavior:
  <https://doc.comsol.com/6.4/doc/com.comsol.help.woptics/woptics_ug_optics.6.02.html>.
- COMSOL 6.4 changed the definition of total mode fields and excludes PML
  domains from default field plots, so version and full-domain plot selections
  must be recorded explicitly:
  <https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_release_text.06.107.html>.
