# Verification Gates

Use these gates to accept a declared engineering claim. Explanation, code
repair, authorized diagnostic solves, and exploratory searches do not require
a ledger. Record diagnostic evidence without declaring qualification. A
project may impose stricter prerequisites; this reference does not waive them.

## Contents

- [Choose The Active Profile](#choose-the-active-profile)
- [Record Resolved Evidence](#record-resolved-evidence)
- [Apply Physical Checks Conditionally](#apply-physical-checks-conditionally)
- [G0-G8 Design Gates](#g0-device-contract)
- [Minimum Gate Ledger](#minimum-gate-ledger)

For runnable conditional scattering, exported final-geometry and near-zero
phase checks, use `executable-diagnostics.md`. Its statuses refer to those
checks only: raw numerics, applicability and evidence qualification are separate.
A passing diagnostic does not close a gate, and a not-applicable passive check
must not be reintroduced as an unconditional column-power rejection downstream.

## Choose The Active Profile

Freeze the intended claim, then evaluate only the smallest profile that covers
it. Gates outside the active profile remain inactive; do not set them to
`not_applicable` merely to make a dashboard green.

The runtime reports every profile as an available assessment; it does not
persist a selected profile or infer one from a command. Record the chosen
profile names and claim in the project contract/handoff. Unselected `blocked`
records are not a global stop signal. G0-G8 are not a universal execution order.

| Base profile | Required gates |
|---|---|
| component qualification | G0 and G2; G1 is conditional on solver ports or driven-wave evidence |
| circuit qualification | component plus G3-G4 |
| layout/connectivity only (`layout-connectivity`) | G0 and G5; no optical-performance or tapeout acceptance |
| combined optical/layout tapeout assessment (`layout-tapeout`) | circuit plus G5; real foundry signoff remains separate |
| raw acquisition (`measurement-capture`) | M0-M1; no calibrated-value claim |
| calibrated measurement | M0-M2 |
| simulation/measurement correlation | M0-M3 |
| recalibrated model release | M0-M4 |

Compose the base with only the required overlay:

| Overlay | Required gate |
|---|---|
| promoted higher-fidelity/full-wave comparison | G6 |
| optimization or robustness promotion | G7 |
| formal handoff or publication | G8 |

Every defining gate in a selected base or overlay must have
`effective_status=pass`. A conditionally applicable gate such as G1 may use a
hashed `not_applicable` rationale when the frozen claim genuinely does not rely
on that physics. This prevents both over-gating unrelated work and completing a
component profile with G2 marked `not_applicable`.

Small solver diagnostics still obey authorization, dry-run, path, license,
resource, and concurrency rules, but they do not earn a gate `pass` by default.

`component` qualifies reusable optical scattering models. An eigenmode study,
thermal calculation, geometry fragment, or single-input trace is not forced
through G2 just because it is called a component. Report that narrower result
with its own checks and limits. Overlay closure alone never proves a base claim.
G8 applies to a formal engineering evidence package, not every answer, code
patch, README update, or software release; software uses its maintenance checks.

## Record Resolved Evidence

For a new `pass`, provide one mapping for every requirement shown by
`photonic gate list --json`:

```powershell
photonic gate set G0 pass `
  --evidence topology=requirements/device-contract.md `
  --evidence ports=requirements/device-contract.md `
  --evidence band=requirements/device-contract.md `
  --evidence stack=requirements/device-contract.md `
  --evidence modes=requirements/device-contract.md `
  --evidence metrics=requirements/device-contract.md `
  --evidence tolerances=requirements/device-contract.md `
  --evidence claim=requirements/device-contract.md
```

The runtime requires each mapped path to be nonempty, readable,
project-relative, and inside the project root. It stores a SHA-256 with every
mapping and derives an `effective_status`; a deleted or changed artifact blocks
that effective status while preserving the recorded historical status.
The live `verification/gates.json` file cannot be its own hashed evidence,
because recording a gate changes that file. Export an immutable project-relative
ledger snapshot or handoff manifest and map the `ledger` requirement to that
snapshot instead.

Legacy ledgers with unkeyed paths remain readable and keep their recorded
status, but report `evidence_policy=legacy-unverified`. Use
`all_gates_evidence_verified` or the selected `closure_profiles` result for new
automation. The compatibility field `all_gates_passed` reports recorded status
only and is not scientific acceptance.

Use gate-level `not_applicable` only when the gate definition permits it. Record
exactly one `applicability=<project-relative-file>` mapping and a reason. A
resolved path and hash prove evidence-reference integrity, not that the file is
scientifically correct; physical review remains separate.

Keep every required mapping. One concise report may cover several requirements;
there is no requirement to create a separate file for each key. Where a physical
check is conditional, the report must explain its applicability and alternative
evidence. For example, an analytic S model has no finite-element mesh or driven
field: its convergence/field-sanity sections identify the analytic scope and
numerical checks. This is reviewed evidence, not a runtime per-check waiver.
Never write "not applicable" for a check that the actual claim depends on.

## Apply Physical Checks Conditionally

Do not create one universal "physics passed" switch. Classify each check by the
frozen device physics and intended claim.

| Check | Hard when | Diagnostic, inconclusive, or not applicable when |
|---|---|---|
| structure, units, source-column mapping, complex-power arithmetic, nonfinite values | always for the artifact that uses that contract | never waive silently |
| per-input power/energy accounting | a solver-derived passive, active, or lossy claim reports power flow | exploratory single-point work may report it as diagnostic; account for radiation, absorption, PML, and gain rather than forcing modal sums to one |
| passivity | the component or network is declared passive and normalization/channels are complete | active/gain devices require a gain/stability budget instead |
| reciprocity | materials, bias, modulation, and time variation imply reciprocity | nonreciprocal or time-varying devices require their declared asymmetry test instead |
| unitarity | the model is lossless and every propagating channel is represented | lossy, radiative, absorbing, gain, truncated-mode, or incomplete-channel models |
| mesh/boundary/port/domain convergence | a 2D EIM or 3D solver result is promoted quantitatively, compared at G6, or used to claim an optimization improvement | advisory screening or a declared single-mesh diagnostic |
| analytic/reduced-model comparison | G0 freezes a valid benchmark, applicability envelope, metric, and tolerance | otherwise use it as a trend or anomaly diagnostic, not a universal equality gate |
| causality/Kramers-Kronig | a broadband compact model or time-domain release has sufficient sampling, reference-plane convention, extrapolation/fitting method, and an error contract | a single wavelength, sparse/narrow band, or data with uncontrolled truncation/discretization; return `inconclusive`, not false failure |
| field-image sanity | a final driven-field dataset exists | visual plausibility never earns a pass alone, but an unexplained red flag vetoes promotion |
| manufacturability | layout, tapeout, or an inverse-designed winner claims fabrication readiness | topology or optical screening without a fabrication claim |

Automation is an interceptor, not the final physical referee. For an
inapplicable conditional check, preserve an explicit rationale artifact. For a
missing required check use `blocked`; for a completed check outside tolerance
use `fail`; for bandwidth/discretization-limited causality or ambiguous visual
evidence use `inconclusive` in the artifact and keep the gate `blocked`.

Set numerical tolerances from the decision being made, normalization, model
fidelity and uncertainty budget before acceptance. Do not impose a universal
1% power residual, fixed mesh size, number of refinements, or mandatory 3D run.
Demonstrate stability of the claimed metric; a claimed improvement must exceed
the relevant numerical/measurement uncertainty. Stronger reasoning can choose
better tests, but cannot substitute for missing observations.

## G0 Device Contract

Require:

- device family and topology;
- external ports and input conditions;
- wavelength/frequency band;
- process stack, materials, polarization, and modes;
- target metrics and tolerances;
- claim level: exploratory, reduced-model, 2D EIM, 3D, or experiment-correlated.

Resolve ambiguities that affect the next costly run or acceptance decision.
Exploration may proceed with explicit provisional assumptions. Freeze only the
contract supporting the claim being accepted. For layout-only work, record the
optical context where known and explicitly exclude optical performance from the
claim; do not invent a wavelength or mode just to fill a key.

## G1 Port and Straight-Waveguide Baseline

Require:

- solved input/output modes;
- stable port orientation and numbering;
- exact disjoint and complete exterior-boundary partition audit;
- `S21`, `S11`, phase, and mode profile;
- one declared power normalization, reference-plane convention, and complex
  port-mode phase basis;
- all claimed complex S-matrix columns from one model/source sweep or an
  independently verified gauge-alignment transform;
- per-input modal, signed exterior-flux, and material-absorption accounting;
- acceptable boundary and mesh sensitivity;
- driven-field physical audit from the final dataset, with geometry, ports,
  scale, and full exterior visible;
- reference-plane locations recorded.

This gate establishes the normalization inherited by all component models.
The runtime requirement list also includes mode identity, exterior partition,
source/common-basis evidence, per-input power, and the final driven-field audit;
one attractive S value cannot cover those checks implicitly.

## G2 Component Qualification

For a reusable optical scattering block require:

- complete complex multiport S matrix over the declared band;
- correct mode label for every port;
- passivity check for passive components;
- reciprocity class and check when physically expected, or evidence for the
  declared nonreciprocal behavior;
- per-input energy budget;
- geometry/process parameters and model level;
- mesh, boundary, wavelength-step, and port-reference checks;
- limits outside which the model must not be used.

Convergence concerns the declared model: analytic/circuit checks, 2D EIM
sensitivity, or 3D sensitivity as applicable. A qualified 2D EIM model remains
2D EIM. G2 does not automatically require 3D or process corners; promotion to
physical-stack accuracy or fabrication robustness adds those obligations.

Do not qualify a component from a field plot or one transmission curve alone.
Also do not qualify a component from attractive S values when the field plot
has an unexplained physical red flag. Visual plausibility is necessary
diagnostic evidence for field-based work but is never sufficient by itself.

## G3 Assembly Contract

Require:

- all instances reference known components;
- each instance port is connected exactly once or exposed externally;
- no mode mismatch at a direct connection;
- one wavelength grid and one S-parameter convention;
- routing phase/loss represented by explicit components;
- manifest validation passes.

Use `python scripts/photonic_assembly.py validate <manifest>`.

## G4 Circuit-Level Behavior

Require:

- external S matrix generated over the target band;
- passive-network singular value within tolerance;
- expected reciprocity/nonreciprocity behavior or an active-network gain budget;
- correct qualitative transfer function;
- energy accounting per independent input;
- wavelength resolution sufficient for narrow features;
- sensitivity or corner screen for high-impact parameters.

When a COMSOL source sweep supplies the matrix, require the source-conditioned
column mapping, phase basis, and evidence checks in
`frequency-domain-source-sweeps.md`.

Label this evidence `circuit-level verified`, not `full-wave verified`.

## G5 Layout and Connectivity

Require:

- port-aware placement and routing;
- no unintended disconnected or multiply connected ports;
- extracted connectivity agrees with the intended manifest;
- minimum bend radius, spacing, cross-section, and layer transitions checked;
- DRC passes against the selected PDK or declared surrogate rules;
- layout artifacts and PDK/version are recorded.

Label a design without a real PDK as `layout concept`, not `tapeout ready`.

## G6 Promoted Subassembly

Require at least one higher-fidelity check for each critical interaction:

- same external reference planes and input modes as the circuit model;
- same wavelength range and comparable sampling;
- complex S-matrix or metric comparison;
- declared error tolerance;
- root-cause analysis for disagreement;
- compact-model update when necessary.

## G7 Robustness and Optimization

Require:

- objective and constraints recorded before optimization;
- baseline preserved;
- checkpoint/evidence-sampling policy recorded;
- nominal and corner results separated;
- mesh/solver noise smaller than claimed improvement;
- minimum-feature, filtering/projection, and process checks when
  manufacturability is claimed;
- winner re-evaluated at the highest validated fidelity;
- local-search results not called globally optimal.

## G8 Final Evidence Package

Require:

- source or model-generation scripts;
- manifests and component contracts;
- solver logs and exported tables where shareable;
- plots generated from stored data;
- gate ledger;
- comparison with theory, literature, or measurement;
- limitations and exact next step;
- public-release audit if publishing.

## Minimum Gate Ledger

```json
{
  "gate": "G1",
  "status": "pass",
  "effective_status": "pass",
  "evidence_policy": "mapped-sha256",
  "evidence_references_resolved": true,
  "next_action": "qualify the component"
}
```

Keep the detailed requirement-to-artifact mappings in `verification/gates.json`.
Never convert missing evidence, a legacy unkeyed path, or a diagnostic-only
physical check into a pass by inference.

## Method References

- scikit-rf exposes passivity evaluation for a fitted scattering model rather
  than treating every raw finite-band trace as a universal passivity proof:
  <https://scikit-rf.readthedocs.io/en/v1.12.0/api/generated/skrf.vectorFitting.VectorFitting.is_passive.html>.
- Ansys documents that finite bandwidth, sampling, discretization, fitting
  error, and unavailable out-of-band data affect causality conclusions; use this
  to justify `inconclusive` rather than a blanket Kramers-Kronig hard failure:
  <https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v252/en/Subsystems/Circuit/Content/Circuit/CausalityPassivityandFittingErrorsFAQs.htm>.
