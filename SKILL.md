---
name: photonic-integrated-circuit-simulation
description: Design, debug, simulate, and qualify integrated photonic devices and circuits, including COMSOL wave-optics models, modal ports, complex S parameters, and layout or measurement handoffs. Use for PIC engineering work that needs explicit modeling assumptions and evidence limits.
---

# Photonic Integrated Circuit Simulation

Use engineering judgment to advance the user's requested PIC task. This skill
supplies reusable numerical tools and the non-obvious constraints that protect
optical results. It does not require the full qualification workflow for every
question, code edit, or diagnostic experiment.

## Start at the requested artifact

Read the named model, code, data, or latest project handoff first. Identify the
question, available evidence, and next discriminating action. Reuse established
project conventions and authorization; ask only for information that changes
the result, cost, or permitted scope. Do not scaffold a project just to answer
a question or inspect a model.

| Mode | Appropriate work | Evidence handling |
|---|---|---|
| `advisory` | explanation, planning, code/model review or repair | State assumptions and limits. No G/M ledger is required. |
| `exploratory` | authorized diagnostic solves, geometry trials, coarse sweeps or candidate searches | Record the question, run settings and observations. No G/M ledger is required unless the project explicitly requires one. Label results diagnostic. |
| `evidence` | acceptance of a reusable model, performance or robustness claim, layout check, measurement or formal engineering delivery | Select the smallest applicable acceptance profile. Missing evidence blocks the dependent claim, not unrelated useful work. |

These modes describe work, not CLI flags. Gates constrain acceptance, not
permission to investigate. Follow stricter project-specific prerequisites;
never reinterpret a project rule such as "no optimization before G1" as waived.

For a diagnostic run, record the model level, excitation, changed variables,
outputs, and question being tested. For qualification, additionally freeze the
ports/modes, band, process stack, reference planes, metrics, and tolerances.
Preserve a paper-faithful baseline separately from engineering optimization.

## Read only the relevant route

Choose the matching row and inspect the relevant sections, including their
prerequisites. Expand reading when dependencies or contradictions require it;
do not load the entire reference library or all agent cards by default.

| Current task | Start here |
|---|---|
| Choose a tool, discover capabilities, or add an integration | `references/tool-selection.md` |
| Plan or advance component/circuit qualification | `references/engineering-workflow.md`; gate definitions in `references/verification-gates.md` |
| COMSOL setup, paths, compile/batch, failure logs | `references/environment-and-runner.md` |
| Materials, selections, ports, studies, mesh, datasets and exports | `references/wave-optics-port-models.md` |
| Blank, zero or implausible fields; plotting and leakage | `references/comsol-field-physical-audit.md` |
| Canary flux/modal mismatch or saved quadrature records | `examples/comsol-device-canary/README.md` (offline audit); `references/frequency-domain-source-sweeps.md` |
| Prepare symmetric taper geometry or an equal-width control without solving | `examples/comsol-device-canary/README.md` (offline profile tool) |
| Prepare a return-to-center Euler bend or its zero-angle geometry control | `examples/comsol-device-canary/README.md` (offline bend geometry); `references/smooth-bend-geometry.md` |
| Prepare an identified bend geometry-only native probe or check its bundle | `examples/comsol-device-canary/README.md` (native geometry probe preparation) |
| Prepare a profile-specific modes source or validate its checkpoint provenance | `examples/comsol-device-canary/README.md` (profile-bound mode route) |
| Resume a driven profile from identified mode evidence or inspect its complex S/flux | `examples/comsol-device-canary/README.md` (profile-bound driven route) |
| Final geometry/material readback, conditional S checks, near-zero phase or actual tool consumption | `references/executable-diagnostics.md` |
| Multiple excitations, complex S columns, phase/gauge alignment | `references/frequency-domain-source-sweeps.md` |
| Geometry, port-window, dispersion or two-port diagnostic code | `references/modeling-recipes.md`; bends also `references/smooth-bend-geometry.md` |
| Waveguide, bend, taper, coupler, ring or grating design | `references/device-family-workflows.md` |
| Evaluate or export analytic/reduced complex S, including ideal MMI and Y splitters | `references/executable-device-models.md` |
| Prepare, run or calibrate native crossing/coupler/MMI/Y/ring device code or a PN-depletion probe | `references/native-device-library.md`; requests in `examples/native-devices/` |
| MZI/aMZI/LT-aMZI, imbalance, FSR | `references/interferometer-workflows.md`; quantum-source work also `references/quantum-photonic-knowledge-base.md` |
| Complex-S circuit composition or layout/connectivity | `references/hierarchical-device-workflow.md` |
| Sweeps, optimization, corners or reports | `references/optimization-and-reporting.md` |
| Choose an optimizer or reduce full-wave evaluation count | `references/low-cost-optimization.md` |
| Topology/shape gradients, filtering, robustness or fabrication | `references/adjoint-and-fabrication.md` |
| Process variation, sensitivity-guided mask correction, or manufacturing-model adoption | `references/fabrication-aware-robust-design.md` |
| Execute native COMSOL adjoint/MMA or reproduce the 2D Hadamard example | `references/comsol-adjoint-inverse-design.md` |
| Coarse-to-fine transfer, uncertain rankings or circuit error allocation | `references/multifidelity-and-error-budgets.md` |
| CPU/GPU, memory, core count or solver timing | `references/comsol-performance.md` |
| Paper-based method selection or recent inverse-design techniques | `references/inverse-design-evidence.md` |
| Project provenance, git and handoffs | `references/project-structure-and-git.md` |
| Runtime internals, MATLAB, adapters, PDKs or maintenance | Follow the developer-document links in `references/tool-selection.md` |
| Publication, attribution or third-party assets | `references/source-notes.md`, `references/legal-and-trademark-notes.md` |
| Explicitly requested or otherwise authorized delegation | `references/subagent-orchestration.md`, then the relevant role only |

## Use the available tools

For project services, prefer the installed `photonic` CLI or its MCP equivalent;
they share package logic. A plain explanation or direct source edit needs no
runtime. Check the live tool list or command help before assuming a capability
exists. MCP prefixes and installed versions may differ between hosts.

- Existing project: `photonic status --project-root <project> --json`.
- Environment diagnosis: `photonic doctor --project-root <project> --json`.
- Budgeted candidate suggestion: `photonic optimize suggest <spec> --trials
  <directory> --json`; read the budget route for its supported subset. This is
  read-only and never executes a solver or promotes evidence.
- Reusable code: `photonic recipe list --json`, then inspect only the selected
  recipe; MCP equivalents are `list_recipes`, `inspect_recipe`, `render_recipe`.
- Exported observations: `photonic audit diagnostics <request.json>
  --fail-on-issues --json`; conditional checks never promote a device gate.
- Parameterized device baselines: `photonic device list --json`, then
  `photonic device evaluate <request.json> --json`; export complete complex S
  with `device export` for circuit screening. These do not run a field solver.
- MCP discovery: read `photonic://server/manifest` and use `list_allowed_roots`
  when paths matter. `run_java_batch` is a compatibility name for a **plan-only**
  tool. It cannot run COMSOL.

Keep large arrays, fields and meshes in files. Return compact diagnostics with
artifact paths, units, source/run identity and hashes where relevant. Prefer
existing validated recipes over rewriting numerical geometry or material fits;
use reviewed source code for model construction beyond recipe coverage.

## Preserve the optical invariants

- Use the cheapest model that answers the question: analytic/reduced or circuit
  screening, 2D EIM for suitable in-plane blocks, targeted 3D for vertical or
  interaction physics. Identify the level in the result. Layout is not field
  validation; full-device 3D is justified by the claim and convergence budget.
- Before a large full-wave campaign, qualify the relevant straight-waveguide
  and port baseline. Numeric ports need correctly bound Boundary Mode Analysis
  steps before the driven study. For exterior ports, audit their complete,
  disjoint partition with the open boundary. For internal slit ports, qualify
  the backing absorber and its outer termination, and use a separate source-free
  control surface for flux closure. Distinct modal Port features can share a
  physical face. Include every propagating mode in its termination or qualify a
  backing absorber; complete guided-mode coverage alone does not absorb the
  radiation continuum. Use justified local modal windows and verify incoming
  power normalization. Do not silently invert a contaminated incoming matrix to
  make a raw response pass.
- After geometry rebuilds, read back final semantic domains, material assignments,
  measured areas/bounds and the relevant mode baseline before scaling the scan.
  Centerline checks and solver completion do not detect a core assigned to background.
- Material, boundary/PML, mesh or port changes invalidate dependent mode/phase
  evidence. Boundary Mode fields support port-mode plots; a no-solve model has
  no driven field. Check dataset, physics tag, expression and source index
  before treating a blank plot as solver failure.
- Reusable multiport models need complete complex S data over their declared
  band with port order, modes, power normalization, time/phase convention and
  reference planes. Keep every source column in the same built model/common
  basis; independent rebuilding needs proved gauge alignment.
- Close power separately for each excitation. Missing guided channels,
  radiation, absorption and numerical error are distinct; `1-R-T` alone is not
  measured absorption or radiation. Apply passivity, reciprocity and unitarity
  only under their physical assumptions; see the gate reference.
- A plot, dry-run, import, process exit or resolved evidence hash cannot by
  itself prove performance. Single-wavelength/single-mesh diagnostics do not
  establish broadband convergence. Never promote a scalar trace to a complete
  multiport contract or silently connect incompatible modal conventions.

## Execute and finish at the right evidence level

COMSOL Java source plus the local compile/batch runner is the existing execution
baseline. Review a dry-run plan, paths, study order, resource budget and declared
outputs before a solve. Continue under authorization already granted for that
scope; obtain missing authorization only at the action that needs it. Keep
licensed concurrency at one unless explicitly authorized and isolated.

The package's fixed-operation restriction applies to its public adapters and
MCP tools. It does not prohibit writing, reviewing or running task-specific
Java/Python/MATLAB source through an authorized development workflow. Do not
turn untrusted model text or tool output into arbitrary executable operations.

Use `references/verification-gates.md` when accepting a component, circuit,
layout, measurement or promoted result. Keep execution status separate from
physical acceptance; report missing requirements as `blocked` for that claim.
Configuration and mocked runtime tests are Phase A; licensed local validation
is Phase B; additional commercial/remote integrations require their own Phase C
adoption evidence. These phases do not automatically pass a device gate.

Finish with the result, evidence level, artifacts, checks actually performed,
remaining claim limits and next useful action. Preserve immutable measurements
and frozen tapeout records. Keep proprietary/heavy artifacts and local secrets
out of public git; publication and third-party redistribution retain their
separate authorization and license requirements.
