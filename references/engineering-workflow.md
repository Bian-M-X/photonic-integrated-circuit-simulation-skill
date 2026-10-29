# Engineering Qualification Workflow

Read this reference when the task requires component/circuit qualification or
an end-to-end campaign. These are dependent engineering stages, not a mandatory
checklist for a local edit or diagnostic. Resume at the stage justified by the
project's evidence. The gate reference is authoritative for acceptance criteria.

Authorized diagnostic runs and candidate searches can precede qualification
with provisional assumptions and explicit limits, unless the project forbids
that ordering. Choose the next step by the uncertainty it can resolve. Do not
turn the section numbering into an all-project execution gate.

## Modeling Ladder

| Question | Default evidence level |
|---|---|
| topology, phase trend, FSR, coarse screening | analytic/reduced or circuit |
| many qualified connected blocks | complete complex multiport S network |
| individual passive in-plane block | declared 2D scalar screening or calibrated EIM; targeted 3D when vertical physics matters |
| vertical confinement, etch depth, free-space/grating coupling | 3D full wave |
| placement, routing, connectivity, rules | layout and extracted netlist |
| final corner behavior | circuit corners plus promoted full-wave checks |
| fabricated behavior | calibrated measurement and correlation |

Use a complete-device 3D solve only when the claim requires it, the device is
small enough to converge, or interaction physics invalidates block separation.
For COMSOL/Lumerical choices, shared tool consumption and matched-model
comparisons, read [dual-solver-workflows.md](dual-solver-workflows.md). A scalar
constant-index model is not promoted to calibrated EIM by changing its solver.

## Qualification Stages

### 1. Freeze the design intent

Record topology, external ports and excitations, wavelength/frequency band,
materials and cross-sections, polarization/modes, PDK/process stack, metrics,
tolerances, variation variables, packaging/test constraints, and claim level.
Keep a paper-faithful baseline separate from engineering optimization.

### 2. Establish the port baseline

Use the same cross-section and conventions as the intended device. Verify mode
shape, `S21`, `S11`, phase, mesh, boundaries/PML, and actual reference planes.
Use the selected backend's port construction; vendor feature names are not
interchangeable:

- **COMSOL:** bind Numeric Port features to one Boundary Mode Analysis per
  port before the driven study. For exterior ports, port selections are mutually
  disjoint, do not overlap scattering/radiation selections, and together cover
  the exterior. Internal slit ports have a different backing/termination audit.
  A core-only terminal may be valid for a particular reduced model; modes that
  need cladding support require a justified segmented modal window rather than
  an arbitrary whole device side.
- **Lumerical FDTD:** use native port objects, explicit inward source direction
  and selected mode, and extend the same waveguide behind interior port planes
  through PML backing. Audit E/H profile sampling coordinates, incoming modal
  power, mode-power normalization and the actual active source. These internal
  monitors do not form a COMSOL exterior-boundary partition. See
  [lumerical-device-workflow.md](lumerical-device-workflow.md).

After materials, boundaries, ports, PML, or mesh change, invalidate stale mode
selection and phase evidence.

### 3. Qualify building blocks

Evaluate each bend, taper, splitter, coupler, ring, grating, transition, phase
section, sensor, modulator, or inverse-designed region independently.

For reusable models, export the complete complex S matrix across the declared
band. Record port order, modes, normalization, time/phase convention,
reference planes, model level, geometry/process parameters, validity range,
source run, and hashes.

For either backend, obtain every input column from the same built model and
common modal basis. COMSOL uses its source-sweep study; Lumerical selects each
actual source port in the same constructed model. Do not rebuild a second
input independently without proved gauge alignment, or fill it by reciprocity.

### 4. Compose before promoting

```text
qualified components
  -> complete complex S data
  -> validated manifest/netlist
  -> circuit response and sensitivity
  -> layout and extracted connectivity
  -> selected full-wave promotion
```

Represent propagation phase/loss, bends, tapers, and transitions explicitly.
An assembly connection is ideal and zero-length. Reject unknown endpoints,
port reuse, dangling required ports, mode mismatches, incomplete matrices,
wavelength-grid mismatches, non-finite values, and passivity violations.

Geometry-part reuse does not transfer material, physics, mesh, selection, or
component-qualification evidence.

### 5. Run external tools reproducibly

Probe first and render a dry-run plan. Use argument arrays, allowed roots,
isolated runtime directories, timeouts, redaction, fixed entrypoints, and
commercial concurrency one unless explicitly authorized otherwise.

For COMSOL, Java API source plus the licensed local batch runner remains the
trusted legacy execution path:

```powershell
& .\scripts\invoke-waveguide-java-batch.ps1 `
  -JavaFile <model.java> `
  -OutputFile <model.mph> `
  -BatchLog <run.log> `
  -DryRun
```

Remove `-DryRun` after reviewing paths, selections, study order, cost,
outputs, and authorization. Reuse authorization already granted for this scope. Exit code zero without the declared output model
and batch log is failure.

For Lumerical, use the installation-matched Python API through the bounded
`photonic lumerical plan` / `run` route. The local MODE/FDE, FDTD controls and
selected-mode device sweeps have their own recorded native evidence; preserve
request, project, raw arrays, source identity, logs and receipt. `device-export`
checks raw-data identity before existing circuit tools consume it. An available
installation does not imply all Ansys products or operations have been tested.

For MATLAB, `matlab -batch` is the default controlled route. Phase A supports
check/plan and fixed-wrapper contracts. An Engine import, shared-session name,
product list, or compiled MEX file is not trusted execution. Run real batch,
Engine, layout, FDFD, or RF fixtures only as authorized Phase B validation.
LiveLink, instruments, Simulink, real PDK/tapeout and remote/HPC integrations
require their own adoption evidence. Local Lumerical MODE/FDE and FDTD tests
are bounded Phase-B observations; EME, CHARGE/HEAT, INTERCONNECT, native adjoint
and multiphysics adoption remain separate. Do not label every Lumerical route
untested merely because another product has no native fixture.

Adoption records qualify a declared integration suite. A controlled experiment
may collect the evidence needed to qualify it under existing authorization;
its success must not be reported as adoption of untested features. For example,
a basic MATLAB batch smoke does not qualify LiveLink, GDS, RF or instrument use.

### 6. Debug by evidence

Check, in order:

1. topology and path-length definition;
2. material and geometry selections;
3. port orientation, modes, study binding, normalization, reference planes;
4. boundaries, background/PML, and missing channels;
5. mesh and wavelength sampling;
6. physics tag, expression, dataset, and source column;
7. field-image physical sanity, including confinement and full-domain leakage;
8. energy/passivity budget;
9. only then geometry or optimizer settings.

For each independent input, account for every intended output. Do not combine
different excitations and label the sum one energy balance.

### 7. Search, then qualify the accepted result

Define objectives, constraints, budgets, failure handling, and robustness
variables before searching. Preserve the baseline and checkpoints. Re-evaluate
winners at the validated fidelity needed for the claim; use higher fidelity and
process/temperature corners when accuracy or robustness claims require them. A local,
heuristic, surrogate, or noisy search winner is not a proved global optimum.
The shared runtime provides bounded low-dimensional candidate suggestions.
Lumerical `optimize-step --execute` connects one candidate to a real all-source
device evaluation and recorded history. Generic `optimize run`/`resume` and a
Lumerical adjoint interface are separate capabilities. The existing dedicated
COMSOL adjoint/MMA route is described in `comsol-adjoint-inverse-design.md`;
its evidence does not transfer to another solver's gradients.

### 8. Inspect, gate, and hand off

Execution status and acceptance status are independent. Inspect artifacts,
hashes, units, conventions, convergence, tolerances, and limitations before
changing a gate.

Select the smallest base profile that covers the intended claim:

- component: G0 and G2, plus G1 when the claim relies on solver ports or driven waves;
- circuit: component plus G3-G4;
- layout/connectivity alone: G0 and G5; combined optical/layout tapeout assessment: circuit plus G5;
- raw acquisition: M0-M1; calibrated measurement: M0-M2, plus M3 for correlation and M4 for recalibrated release.

Add only the overlays the claim needs: G6 for a promoted higher-fidelity
comparison, G7 for an optimization/robustness promotion, and G8 for formal
engineering evidence delivery or publication. Routine answers and software
releases do not need G8. A defining gate in a selected base or overlay must
`pass`; `not_applicable` is not a shortcut to profile completion.

Leave gates outside the active profile inactive. Use `not_applicable` only where
the gate definition permits it and record hashed applicability evidence. For a
new `pass`, map every declared requirement to a nonempty project-relative file;
the runtime records its SHA-256. A resolved evidence reference proves neither
the file's scientific meaning nor physical acceptance.

Handoff scripts/contracts, manifests, logs, tables, plots, run/gate state,
limitations, and the exact next safe action. Keep proprietary or heavy
artifacts out of public git unless explicitly authorized.

## Phase and Claim Boundaries

- Phase A proves the local core, contracts, mocks, safe plans, and compatibility
  paths only after its acceptance suite passes.
- Phase B is licensed local validation with controlled non-confidential
  fixtures.
- Phase C is bounded commercial, foundry, instrument, measurement, and remote
  integration after backend-specific adoption gates.

Use only the evidence label actually earned: analytic/reduced, circuit,
layout-concept, PDK/DRC-checked, 2D EIM, 3D subassembly, full-device 3D,
measured, calibrated, correlated, or recalibrated. These labels are not
interchangeable.
