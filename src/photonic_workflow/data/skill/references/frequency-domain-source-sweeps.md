# Frequency-Domain Source Sweeps

Use this reference when COMSOL numeric ports must produce a complete complex
S matrix, especially when phase, reciprocity, passivity, or group delay will be
claimed. Treat each item below as a fail-closed evidence requirement.

## Contents

- [Freeze The Port Basis Before Solving](#freeze-the-port-basis-before-solving)
- [Audit The Study Without Solving](#audit-the-study-without-solving)
- [Parse Source-Conditioned Columns Correctly](#parse-source-conditioned-columns-correctly)
- [Close Power For Every Input](#close-power-for-every-input)
- [Preserve The Expensive Solved State](#preserve-the-expensive-solved-state)
- [Build Fail-Closed Machine Evidence](#build-fail-closed-machine-evidence)
- [Keep The Claim Boundary Closed](#keep-the-claim-boundary-closed)

## Freeze The Port Basis Before Solving

1. Keep all port excitations in one model instance. Do not rebuild geometry,
   materials, mesh, or boundary modes independently for each source column.
2. Give ports stable numeric names and bind each Numeric Port to its intended
   Boundary Mode Analysis step.
3. Perform a multi-eigenpair census before selecting a branch. Then use a
   separate one-eigenpair selected-mode step per port and record its port name,
   mode index, effective index, selection, orientation, and reference plane.
4. Fix one power normalization for every source, normally 1 W power waves.
5. Fix the arbitrary complex phase of every port mode. In COMSOL 6.4, a Numeric
   Port exposes the mode-phase property `Thetap`; verify the property through
   local version-matched documentation or API readback before relying on it.
6. Align opposite-facing ports only after applying the correct polar/axial
   field reflection. Record electric- and magnetic-field overlaps and the
   applied phase. Do not reuse a phase value from a different geometry,
   wavelength, mesh, or mode branch.

Distinguish a common real sign from an arbitrary complex phase. When both
incoming and outgoing bases of each channel receive the same real sign,
`D = D^-1 = D^T` and `S' = D S D`; symmetry, singular values and unitarity are
preserved. Reflected E/H overlaps may therefore share either +1 or -1 under
this explicitly declared convention. They may not have different signs or an
unexplained complex phase. This allowance is **between port bases**, not between
source columns: one port's basis must remain frozen throughout the source sweep.
Normalized shape overlap alone proves neither mode power nor direction. Check
whether the backend exports outgoing or incoming modes before integrating signed
Poynting flux; the COMSOL 6.4 Numeric Port documentation defines outgoing modes.

Without this basis contract, retain raw numbers only as diagnostics and state
the missing assumptions. Even column powers need correct modal normalization.
Fixed input/output unitary coordinate changes preserve singular values;
source-dependent output bases need not. Do not attach passivity, reciprocity,
phase-continuity, group-delay or compact-model qualification to unproved raw
columns. See `executable-diagnostics.md` for the distinction and executable checks.

## Audit The Study Without Solving

Create a dedicated non-solving configuration stage and read back:

- study and step tags;
- exact study-step type;
- source port names and order;
- selected Boundary Mode Analysis bindings;
- source powers, reference planes, orientations, and mode phases;
- absence of mesh, boundary-mode, and driven-solve execution.

For COMSOL 6.4 Java API models, the Frequency Domain Source Sweep study-step
type is `FrequencyDomainSourceSweep`. Do not assume the plausible but invalid
name `FrequencySourceSweep`. Treat this as version-specific knowledge: verify
the local API before porting it to another release.

Run the expensive solve only after this configuration gate passes. Retain
failed API attempts as diagnostic history instead of silently replacing them.

For a mode-first execution, inspect the generated solver sequence before
choosing a stop point. In the 6.4 straight canary, running through the second
`StoreSolution` node preserves both selected port modes without executing the
driven step. Export and check those modes, save the model, then resume at the
actual driven `StudyStep` with `runFrom`; rerunning the complete sequence would
invalidate the claimed frozen basis. The node tags are model-specific, not a
portable ordering rule.

Bind a resumed solve to the checkpoint hash, accepted mode report, original
producer source and mode-definition identity. Require actual shape/stage and
unique port/dataset/solution identity from native readback. A driven-only log
can inherit a census from this verified precursor; absence of new census rows
does not justify rerunning modes. Compare unscaled complex E/H before/after
resume and across source columns, including amplitude and phase. Missing
precursor exports must fail the dependent check. Reanalysis should be read-only
on frozen evidence and write a new result, preserving the original failure.

## Parse Source-Conditioned Columns Correctly

A source-sweep dataset may define each `Sij` only at the solution index for
source `j`. For a two-port model, read S11/S21 from source 1 and S12/S22 from
source 2. Generalize the same rule to larger matrices.

- Require every physical `(row, column)` entry exactly once.
- Freeze an explicit channel-to-source-solution mapping and verify it on readback.
  `source_solution_index == column` is specific to the one-based, ordered
  two-port recipe, not a general COMSOL dataset indexing rule.
- Reject nonfinite values at the physical positions.
- Do not require an entry to be finite under unrelated source indices.
- Do not replace undefined unrelated positions with zero.
- Recompute `abs(Sij)^2` from the printed real and imaginary parts.

This mapping is part of the evidence contract, not a postprocessing detail.

For two physical faces with two modes each, freeze four channels, for example
`[L0,R0,L1,R1]`. Multiple modal ports may share a face. Preflight one wavelength
with all four excitations before scanning the band. Export actual source labels,
dataset/solution dimensions, wavelength, E/H modal projection, incoming power,
independent material absorption and source-free nonport outward flux. Never
guess an array axis or repeatedly use `[0][0]` without verified source selection.
The new N-channel diagnostic validates exported column identity and conditions;
it does not implement this COMSOL projection/exporter. A verified same-face
multimode native example remains a separate validation task.

## Close Power For Every Input

For source column `j`, define a documented sign convention and recompute:

```text
modal_fraction_j = sum_i abs(Sij)^2
accounted_fraction_j = modal_fraction_j
  + (signed_nonport_exterior_flux_j + material_absorption_j) / Pin_j
closure_residual_j = 1 - accounted_fraction_j
```

Integrate signed Poynting flux only over finalized non-port exterior faces and
absorption over the intended material domains. Audit operator dimensions,
entity sets, and zero port overlap before the solve. Inside a COMSOL coupling
operator, local `nx`, `ny`, and `nz` may be valid where component-qualified
normal variables are not; verify the expression in its actual operator scope.

Keep a scattering feature's outgoing-power value as an independent crosscheck;
do not substitute it for the signed exterior integral unless equality has been
demonstrated. Treat tiny negative absorption within a declared numerical
tolerance as numerical zero, not physical gain.

Also compare direct port-flux integrals against modal power and compute a
signed closed-surface balance. Opposite errors in incoming and outgoing flux
can nearly cancel even when each differs materially from its modal value.
Report both discrepancies; neither a small S-based closure nor a small total
surface residual establishes the accuracy of individual loss or reflection.

To isolate postprocessing from solution error, first reuse the same solved
checkpoint and vary integration order with actual operator selections, source
identities and order settings read back. If all values are identical, include
a nonpolynomial spatial integral with a known analytic answer as a positive
control: stored settings alone do not prove that the evaluation used them.
Use the actual selected interval for that reference and distinguish stale
evaluation/cache behavior from genuine order stability. Agreement between a
backend Poynting expression and its explicit E/H formula is a same-solution
consistency check, not independent validation of the field solution.

Then change the mesh with geometry and ports fixed, recording actual mesh
statistics alongside requested sizes. Recompute accepted modes for each mesh
and freeze them within that mesh's source sweep. Cross-mesh complex-S changes
need a demonstrated mode convention; any common real-sign basis transformation
must be recorded separately from preserved raw matrices. Three shrinking
differences support a refinement trend, not a general convergence certificate.

## Preserve The Expensive Solved State

- Save a solver-owned model checkpoint immediately after the driven solve and
  before derived-value evaluation. A postprocessor failure must not erase a
  valid high-cost solution.
- If iterative convergence has already failed with Inf/NaN for the same frozen
  system, a preselected direct solver can be a controlled diagnostic route.
  Record factorization count, out-of-core use, peak memory, and source order.
- Confirm whether one factorization is reused for multiple right-hand sides;
  never infer reuse merely from the study name.
- Treat a native class-status sidecar as acceptance evidence only if its
  semantics are proven. Prefer zero process exit, explicit terminal markers,
  fresh exact artifacts, and independent parsing.

## Build Fail-Closed Machine Evidence

Require and hash the exact source, rendered run configuration, model, solver
console, batch log, selected-mode prerequisite, and parser. Record run ID,
source commit, solver version, study type, mesh/DOF census, source order, and
artifact containment.

Independently recompute:

- complex power identities;
- per-input power closure;
- expected reciprocity error;
- largest singular value for passive systems;
- an optional unitarity residual when loss is expected to be negligible.

Test rejection paths for missing completion markers, wrong source-column
mapping, nonfinite values, power mismatch, closure drift, reciprocity drift,
singular-value drift, and incomplete solver-sequence evidence. Prefer explicit
machine markers for critical facts; localized solver logs require tested,
version-tolerant parsing.

## Keep The Claim Boundary Closed

A same-model, common-basis result at one wavelength and one mesh is only a
nominal diagnostic. It does not establish converged insertion loss, reflection
floor, broadband phase, group delay, or reusable component performance.

Before promotion, require tracked mode identity across the declared band,
qualified material dispersion, wavelength checkpoints, PML/boundary evidence,
mesh/domain/substrate/port/length convergence, phase continuity, and a complete
error budget. Keep the governing gate `blocked` until those families pass.
