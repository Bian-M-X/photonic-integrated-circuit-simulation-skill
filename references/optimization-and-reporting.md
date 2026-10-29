# Optimization and Reporting

Use this reference for parameter sweeps, inverse-design workflows, energy diagnostics, model comparison, 2D-to-3D progression, and reproducible reporting.

For an expensive search, choose a representation and budget using
`low-cost-optimization.md`. High-dimensional design uses `adjoint-and-fabrication.md`;
cross-fidelity ranking uses `multifidelity-and-error-budgets.md`. Solver/hardware
choices are in `comsol-performance.md`, and paper-to-method decisions are in
`inverse-design-evidence.md`. Load only the route needed for the task.

## Contents

- [Sweep Strategy](#sweep-strategy)
- [Objective Functions](#objective-functions)
- [Energy Diagnostics](#energy-diagnostics)
- [External Optimization Loop](#external-optimization-loop)
- [Design-Region Discipline](#design-region-discipline)
- [Resolution Refinement](#resolution-refinement)
- [Multi-Input Metric Interpretation](#multi-input-metric-interpretation)
- [2D To 3D Progression](#2d-to-3d-progression)
- [Visible Artifacts](#visible-artifacts-before-manufacturing-claims)
- [Reporting Package](#reporting-package)
- [Claim Labels](#claim-labels)

## Sweep Strategy

Start small and increase cost when the previous result justifies it. The
following is a useful progression, not a mandatory ordering for every device.
Authorized exploratory searches do not need G7 or a completed G1 unless the
project explicitly imposes that prerequisite. Keep candidate rankings
diagnostic until the relevant baseline, convergence and uncertainty checks pass.

1. single wavelength
2. short coarse wavelength sweep
3. local peak/valley refinement
4. one-parameter geometry sweep
5. two-parameter joint sweep
6. mesh or boundary sensitivity check
7. final reporting sweep

For MZI/LT-aMZI, useful sweep dimensions include:

- `gap_dc`
- `Lc`
- bend radius
- port straight length
- background margin
- boundary type
- mesh level
- `n_wg_eff` or `n_g` assumption

Record each sweep with a manifest:

```text
run_id
date/time
model source
parameter ranges
mesh strategy
boundary strategy
physics tag
dataset used
output files
key metrics
known issues
```

## Objective Functions

Do not optimize only peak transmission. Include physical penalties.

For an LT-aMZI:

```text
score = max(T21)
        - penalty(peak_nonuniformity)
        - penalty(R11_at_peak)
        - penalty(integrated_radiation_and_absorption)
        - penalty(FSR_error)
```

Possible metrics:

- `max(T21)`
- `min(T21)`
- extinction ratio
- insertion loss
- FSR mean and standard deviation
- `R11 = abs(S11)^2` at peaks
- `T21 + R11` (collected modal power for this two-channel example)
- peak-to-peak nonuniformity

Correct FSR with low peak transmission is consistent with the expected delay,
but does not by itself validate topology, absolute phase, loss or boundary settings.
Check coupling, return matching and numerical convergence before attributing loss.

## Energy Diagnostics

For a low-loss two-port reflected-output model:

```text
T21 = abs(S21)^2
R11 = abs(S11)^2
Ssum = T21 + R11
unaccounted_power_fraction = 1 - Ssum
```

Interpretation:

- high `R11`: reflection, port mismatch, or poor round-trip coupler matching
- low `Ssum`: investigate missing guided channels, radiation, absorption and
  numerical imbalance separately; the residual alone identifies none of them
- correct FSR but low T21: optimize couplers and losses, do not rebuild topology first
- no fringes: check `DeltaL`, couplers, ports, and sweep range

## External Optimization Loop

Use a backend-independent outer loop with a solver-specific evaluator:

1. Freeze candidate variables/units, objectives, constraints, total evaluation
   budget and verification reserve.
2. Ask the shared proposer for one bounded candidate using identified history.
3. Construct the solver-specific model from the frozen shared parameters.
4. Execute the actual required input sources; one four-port selected-mode
   evaluation contains four source solves, not one interchangeable solver job.
5. Verify raw artifacts, source identity, complete matrices and diagnostics.
6. Compute objective/constraint values from those retained native results.
7. Record success/failure and cost, and resume from that history. Promote a
   candidate only after its separate fidelity/convergence/robustness checks.

For **COMSOL**, the established evaluator generates reviewed Java, compiles
with installation-matched `comsolcompile`, runs batch and exports actual
results. The dedicated native adjoint/MMA route has its own gradient and
evidence discipline in `comsol-adjoint-inverse-design.md`.

For **Lumerical FDTD**, `photonic lumerical optimize-step` joins the shared
`OptimizationSpec`/`OptimizationTrial` and proposer to receipt-bound native
device matrices. Without `--execute` it creates a candidate plan only; with
`--execute` it evaluates one geometry candidate, records a pending trial before
the solve and retains failures. Current mappings are explicit micrometre
geometry parameters, with declared port-power/insertion-loss objectives and
the supported reflection/singular-value/reciprocity constraints. Read
`lumerical-device-workflow.md` for the exact supported schema.

The shared read-only `optimize suggest` supplies bounded low-dimensional
GP-EI candidates from frozen trials; see `low-cost-optimization.md`. The bounded
Lumerical evaluator does not implement native adjoint gradients or the entire
robust-optimization stack. Generic `optimize run`/`resume` remains distinct
from this explicit one-step route. Do not pool different solver, mesh, model
level, reference plane, material or objective identities in one training history.

Use `dual-solver-workflows.md` for the frozen matched-model benchmark before
claiming that a different backend gives equal or better objective accuracy.

### Evidence Cadence

Do not create a full release package for every optimizer iteration. Freeze an
evidence cadence before the search:

- record every trial's ID, parameters, objective/constraint values, execution
  state, and failure class in a compact append-only index;
- retain restart checkpoints at the declared `checkpoint_interval`;
- retain full solver artifacts only at declared milestones, anomalies, promoted
  candidates, and final winners;
- hash the optimizer specification, baseline, checkpoint state, and promotion
  decision;
- replay promoted candidates from the frozen specification before G7 passes.

Evidence sampling reduces storage, not accountability. Missing intermediate
artifacts must not be reconstructed or described as if they were retained.

### Concurrency And Manufacturability

Commercial solvers remain one worker by default. Increase `worker_count` only
when license entitlement, per-worker prefs/config/tmp isolation, timeout and
orphan cleanup, cost limits, and artifact attribution are explicitly
authorized and tested. A cloud GPU service is not automatically exempt from
cost, credential, tenant-isolation, or provenance controls.

Before promoting an inverse-designed result, check the declared fabrication
model: minimum feature and gap, curvature, connectivity, binarization/filter
or projection settings, etch/layer constraints, and relevant process corners.
These checks are hard only when manufacturability or tapeout readiness is
claimed; exploratory optical screening remains labeled accordingly.

For expensive or noisy objectives:

- measure a small pilot and reserve final verification budget
- choose GP/local search for a few expensive variables, or a checked adjoint for
  high-dimensional smooth design; do not default to a population method
- use SPSA or a small population only when gradient access/noise/discreteness
  warrants it and a matched-budget pilot supports the choice
- limit parallelism unless runtime directories and license behavior are well understood
- treat foreground timeouts as inconclusive until logs and output folders are checked

## Design-Region Discipline

When using a design region or pixelized material distribution:

- design region has its own selection
- fixed waveguide arms have their own selection
- background has its own selection
- fixed-core material does not cover the design region
- design-region material does not overwrite fixed waveguides
- ports and boundary regions are not optimization variables

This selection discipline also applies to non-pixelized circuits. Directional couplers, arms, loop reflector, bends, background, and ports should be auditable as separate geometry or selection groups.

## Resolution Refinement

When moving from lower to higher resolution:

- back up the previous best vector
- record source and target resolution
- try nearest-neighbor lifting
- try bilinear or smooth lifting
- evaluate both before continuing optimization
- do not assume smoother interpolation is better

Always compare post-lift performance before claiming improvement.

## Multi-Input Metric Interpretation

For devices evaluated with multiple independent input excitations, aggregated transmission can exceed 1 without violating single-input energy conservation.

Example:

```text
trans_total = sumA + sumB
```

Interpret each input separately:

- `T_aa:T_ab`
- `T_ba:T_bb`
- per-input reflection
- per-input uncollected power

For MZI/LT-aMZI single-input sweeps, focus on:

- `abs(S21)^2`
- `abs(S11)^2`
- `S11 + T21`
- peak and valley wavelengths
- FSR
- peak uniformity

## 2D To 3D Progression

Use 2D EIM for:

- topology checks
- FSR and phase trends
- fast coupler sweeps
- bend-radius screening
- candidate ranking

Use 3D for:

- true SOI cross-section mode
- vertical field confinement
- sidewall and etch-depth effects
- bend and coupler loss with realistic thickness
- final engineering validation

Recommended 3D progression:

1. straight 3D waveguide with ports
2. cross-section mode analysis for `n_eff(lambda)` and `n_g(lambda)`
3. short bend or coupler submodel
4. compact 3D substructure
5. full 3D device only if computationally feasible

Do not present an unconverged coarse 3D run as final validation.

## Visible Artifacts Before Manufacturing Claims

Before claiming manufacturability, export visible intermediate artifacts:

- field plots
- spectrum plots
- layout preview
- binary/density preview for design regions
- CSV mask
- SVG or PNG layout sketch
- parameter manifest

These are not substitutes for PDK-checked GDS, DRC/LVS, or experimental validation.

## Reporting Package

A complete report should include:

- paper or design target summary
- implemented assumptions
- geometry and material audit
- port and boundary setup
- mesh strategy
- validation ladder results
- field maps
- wavelength spectra
- extracted metrics
- energy budget
- comparison with theory or paper data
- limitations
- next engineering steps

Artifacts to deliver when allowed:

- model files
- build/run scripts
- sweep scripts
- batch logs
- CSV/TXT tables
- figures
- model-quality audit
- slides or report document

## Claim Labels

Use precise labels:

- `full-wave verified`
- `2D effective-index verified`
- `reduced-model verified`
- `preliminary optimization candidate`
- `requires 3D validation`
- `requires experimental validation`

Avoid overclaiming:

- do not call 2D EIM a final 3D design
- do not call a local sweep winner a global optimum
- do not use a pretty field plot as sole proof
- do not ignore `S11`, uncollected power, or boundary losses
