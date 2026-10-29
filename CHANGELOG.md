# Changelog

All notable changes are recorded here. Versions follow Semantic Versioning;
recipe schema and recipe semantic versions are maintained independently from
the host package version.

## [Unreleased]

## [0.8.0] - 2026-10-29

### Added

- Parameterized native straight, four-port crossing, directional coupler, 2x2
  MMI, three-port Y, all-pass/add-drop ring and PN-depletion ring sources. The
  geometry, actual material domains, port windows, bound-mode observations and
  complete source/wavelength complex S axes have explicit readbacks.
- `photonic native` preparation, verification, bounded local execution,
  receipt-bound calibration/CSV export and power-only mesh comparison. The
  explicit local `run` command executes fixed regenerated Java; the 13 MCP
  tools keep their existing non-execution boundary. There are 40 MCP resources.
- Native scalar port-window and boundary-mesh controls, retained failed native
  attempts, and raw source-bound field exports. A three-wavelength straight
  control reduced the flux/modal gap from about 2.14% to 0.0128% with refinement;
  this is a bounded diagnostic result, not a universal device accuracy claim.
- Ordinary rings support one-bus/two-port and two-bus/four-port geometry. Curved
  finite-element area integration is separate from rendering-based CAD areas;
  rendering precision must not silently loosen a geometry check.
- Abrupt lateral PN depletion, 1550 nm Soref--Bennett index/extinction response,
  and a native prescribed-charge 1D Poisson benchmark with solved-potential and
  field comparisons, charge quadrature, voltage and asymmetric-doping controls.
- Receipt-bound native baseline tables, ordinary-ring radius/spectrum screens,
  matched 0 V/2 V four-port optical scans, local 20 pm spectral controls and
  repeatable request generation.
  Sanitized numeric summaries and a power-spectrum figure preserve the scope
  of these diagnostics separately from full SOI device qualification.

### Compatibility and limits

- Native optics uses the explicit `2d-scalar-index-surrogate` level, now also
  accepted by the circuit schema without relabeling it as a calibrated SOI EIM.
  Supplied indices, optical overlap and material laws retain their scope.
- PN validation checks the prescribed-depletion approximation; it does not
  establish semiconductor drift-diffusion, 3D SOI overlap, electrical parasitics,
  RF bandwidth or fabrication qualification. Cross-model phase alignment and
  continuous-band guarantees require their own evidence.
- Failed receipts and coarse-grid discrepancies remain visible. Native execution,
  numerical calibration and physical device qualification are separate results.

## [0.7.0] - 2026-10-28

### Changed

- Renamed the installable skill to `photonic-integrated-circuit-simulation` and
  moved active repository links to `photonic-integrated-circuit-simulation-skill`.
  The `photonic-workflow` distribution, Python imports, `photonic` CLI and MCP
  server identity remain compatible. Reinstall the skill under its new name;
  old installed copies are not automatically migrated.
- The full CI suite uses pytest and installs its canary process dependencies,
  so the new function-based regressions run in clean environments.

### Added

- Identified bend geometry-only probe preparation and verification, with final
  semantic-domain/material readbacks, true core-to-end-window intersections and
  finalized native edge samples. Bundles preserve producer dependencies; offline
  verification never starts COMSOL or establishes mode/performance acceptance.
- Bounded native geometry evidence for the zero-angle control and a retained
  nonzero closed-interpolation counterexample. A native edge deviated about
  0.52 nm from the intended lower boundary, failing its 0.1 nm contour target
  despite passing area/end-width checks. API unit codepoints prevent console
  replacement characters from silently establishing geometry units.
- Offline return-to-center Euler-bend geometry, reusing the existing symmetric
  Euler recipe with normal offsets, a zero-angle rectangle and explicit path,
  area and sampling diagnostics. Fixed Java interpolation-curve fragments are
  configuration proposals; native geometry, modes and bend loss remain untested.
- Offline profile-bound driven continuation, with a data-only historical mode
  evidence route, pre-resume native state assertions and complete two-source
  complex S/signed-flux diagnostics. Original receipts are preserved and
  current mode criteria are recomputed; device qualification remains separate.
- Explicit fatal-record rejection shared by mode/driven evidence checks and
  semantic verification of the fixed canary's actual frequency/source axis.
- Native two-source driven diagnostics for the equal-width control and one
  nonzero double ramp using its own mode checkpoint. Raw S/flux linkage and
  profile-aware field plots were checked; the port/modal mismatch still fails.
- Offline profile-specific modes preparation and evidence validation, binding
  generated Java, runtime profile identity, geometry/port readbacks, completed
  native receipts and selected-mode checkpoints. Conflicting duplicate E/H
  traces and driven-result markers are rejected before mode acceptance.
- The `comsol` optional dependency set includes psutil for the canary's native
  process supervision and offline selected-mode evidence analysis.
- Two profile-bound equal-width controls completed native selected-port mode
  diagnostics, with an independent slab/complex-field check and preserved
  producer snapshots. Device scattering and convergence remain unqualified.
- Single-domain interface sampling guidance backed by a two-source saved-solution
  diagnostic, including actual domain membership, zero extrapolation and atomic
  row acceptance. Local algebraic consistency does not resolve the receiver gap.
- Native configure-only evidence for two equal-width taper controls: equal
  domain geometry/materials but different finalized vertex/edge counts and
  boundary IDs. Profile-bound mode/solve reuse remains future work.
- Offline symmetric taper profile preparation with equal-width and zero-length
  controls, strict polygon/parameter checks and configure-only Java generation.
  The default preserves legacy rendered bytes; custom profiles are not solved
  or accepted by the legacy fixed-profile modes/solve/plot pipeline.
- Same-point sampling guidance backed by a two-source existing-solution
  diagnostic: explicit Solution interpolation passes component-product checks
  while CutLine nonmultiplicativity remains visible. Coordinate and trace
  validation remain separate from field, port and mesh acceptance.

- Ideal reciprocal three-port `ybranch-ideal` with matched trunk, explicit
  branch reflections and coherent combining; complete complex S and independent
  channel/circuit counterexamples. Geometry and odd-mode radiation are not solved.
- Circuit composition rejects numerically rank-deficient internal feedback
  before solving, including a balanced lossless Y-loop dark state that roundoff
  previously hid. Resolvable near-resonant controls remain supported; no damping
  is added and the output schema is unchanged.
- Ideal four-port `mmi2x2-ideal` circuit model with explicit splitting power,
  excess loss and common phase, complete reciprocal complex S export and
  coherent-interference counterexamples. It is not a geometry-dependent MMI
  solver; the original five models and request schema remain compatible.
- Existing-solution spatial-flux diagnostic guidance: signed internal cuts,
  explicit coordinate units and physical-location controls, material splits,
  path-specific quadrature controls, and strict observation metadata. Native
  batch triage distinguishes entry/completion from exit status and uses typed
  property readbacks. These additions do not qualify new device families.
- Offline canary audit with checkpoint SHA-256 verification, strict source,
  dataset and integration-order records, and a nonpolynomial quadrature control.
  Postprocessing consistency and receiver flux/modal agreement retain separate
  outcomes. This tool does not launch COMSOL or certify checkpoint/log provenance.
- Three-mesh straight-control evidence: the maximum receiver power discrepancy
  decreases from about 0.676% to 0.276%, but still fails the frozen 0.1% target;
  the last-two-mesh power change also fails its independent target. Result-level
  quadrature controls and actual mesh readbacks are documented. Taper and broader
  native family qualification remain gated on the unresolved baseline.
- Five parameterized analytic/reduced device models (waveguide, directional
  coupler, all-pass ring, add-drop ring and uniform Bragg CMT), complete complex
  scattering export and `photonic device list/evaluate/export`. Independent
  algebra/ODE and circuit-integration tests distinguish numerical correctness
  from native device qualification. Request schema is separate version 1.0.
- Circuit component loading accepts the existing composition writer's optional
  derived `power` column, verifies it against the complex amplitude, and rejects
  unknown columns or malformed rows. Existing five-column inputs are unchanged.
- Explicit distinction between physical-face partitioning and modal channels;
  the existing partition helper's rejection of overlapping physical faces is
  preserved.
- Experimental straight/taper native canary source, strict native-row parsing
  and bounded compiler diagnostics. The 2026-10-19 straight-control campaign
  reached configuration readback, selected port modes and a two-source driven
  solve resumed from the same saved mode checkpoint. Independent slab and
  exported-field checks support this single-mesh, single-wavelength 2D scalar
  diagnostic only; taper execution and physical convergence remain unverified.
  Failed original receipts are retained separately from parser reanalysis.
- Read-only `photonic audit diagnostics` for conditional N-channel scattering,
  final 2D geometry/material readbacks and strict plus conditioned phase checks.
  Requests use a separate version 1.0 format; no existing recipe or G/M contract
  semantics change. All outputs remain diagnostic and caller-evidence dependent.
- Instrumented Python transformation I/O receipts with explicit path roots,
  content fingerprints and separate stale planned-consumer warnings.
- Benchmark-driven positive/negative regressions and documented native-test
  boundaries. Frozen campaign reports retain the version and producer bytes
  used at execution; updating the source does not migrate installed copies.

- On-demand fabrication-aware robust design guidance and a full-text assessment
  of BOSON, PRISM and scalable photonic inverse design, with explicit adoption
  conditions and separate paper-faithful and engineering objective expressions.
- NumPy-only axial scenarios and sensitivity-weighted fourth-power pattern loss,
  with area quadrature, checked wafer derivatives and interaction/cancellation
  counterexamples, including diluted bad-scenario loss for binary targets.
  These diagnostics do not implement full paper backends or
  certify process models, fabrication yield or new native device performance.
- Readable packaged fabrication, diagnostics and device-model references: 38 MCP
  resources, still 13 tools. Persisted G/M schemas remain unchanged.

## [0.6.0] - 2026-10-10

### Added

- Read-only `photonic optimize suggest` for bounded continuous, single-fidelity
  GP-EI candidate suggestions, with frozen-spec provenance, pending/failure
  accounting, observed constraints and a reserved final-validation budget.
- Solver-independent filter/projection derivatives, complex matrix metrics,
  sampled gradient checks, smooth worst-case loss and conditional error-budget
  comparison/allocation; no new core dependencies or automatic solver execution.
- Weighted physical-density grayness and threshold-discrepancy diagnostics;
  material-field bounds are kept separate from optical-error and fabrication claims.
- Six on-demand inverse-design references linking four supplied papers and
  recent primary sources to representation, fabrication, fidelity and cost decisions.
- Reproducible analytic ask/tell comparison and a serial Windows COMSOL direct-
  solver benchmark with isolated runtime directories and owned-process timeout.
- Original native COMSOL adjoint/MMA example with a Helmholtz-filtered density
  field, mirror mapping, projection/mesh continuation, binary contour extraction,
  source-conditioned eight-mode scattering and a bounded qualification campaign.
- Domain-backed slit/PML termination, independent bidirectional modal projection,
  signed flux closure and all-input logical throughput from the smallest singular
  value; a failed incoming-mode check cannot be repaired by matrix inversion.
- Qualified [2D Hadamard showcase](docs/showcases/hadamard-2d/README.md), completed
  2026-10-10: all nineteen locked checks and thirteen convergence comparisons pass,
  independently recomputed from the raw eight-mode matrices and flux records.
  Qualification covers the selected binary bulk-index surrogate at seven discrete
  wavelengths; it makes no continuous-band, 3D or fabrication claim.

### Changed

- Load plotting dependencies only when drawing, so numerical preview helpers
  work in the core-only installation. Recomputed showcase residuals use a
  roundoff-only comparison; physical gates and literal configurations stay exact.

- Added optional `-Processors` to the Java batch wrapper. Retained default
  behavior, one-worker execution and existing project-specific physics gates.
- Corrected two-channel power accounting to distinguish `R11=abs(S11)^2` from
  amplitude and unaccounted power from physically identified loss.
- Exposed six new MCP references (35 resources, still 13 tools), with explicit
  resource-read and installed-package verification. Contract schemas remain 1.0.
- Added optional inverse-design dependencies and solver-free coverage for mask
  extraction, complex Hadamard metrics and the native COMSOL runner contract.
  Software coverage alone does not establish physical acceptance; the separately
  audited native showcase supplies the declared 2D qualification evidence.
- Required solution-error termination for the coupled filter/Maxwell Newton solve:
  a small residual could leave sensitivity using the preceding field's Jacobian.
  Two-step finite differences verify the repaired chain before optimization.
- Exposed bounded MMA/GCMMA, move-limit and per-stage evaluation-limit controls
  with native readback. Five-frequency checkpoints can use frozen export recovery;
  this rechecks the original training settings and does not rerun optimization.
- Preserve completed and partial native evaluation costs, and reconstruct both
  objective profiles from receipt-bound training amplitudes. Observed evaluation
  overruns stop later jobs without discarding the physical result.
- Explicitly restore the example's mirror constraint during contour extraction;
  bind previews to the actual mask, field and freshly analyzed native evidence.
- Run the unchanged nineteen locked checks with training/numerical checks first
  and holdouts last; stop on the first failed gate and never report partial PASS.
- Align campaign schema 3 with the independently exercised coherent restart
  lineage, six observed binary-threshold trials and a 36-job maximum. Preserve
  the nineteen validation configurations, thirteen comparison pairs and gates.
  The selected lineage and its later frozen-mask qualification are disclosed;
  this is not a claim of a new uninterrupted default-campaign execution.

## [0.5.0] - 2026-09-09

### Added

- Separate `layout-connectivity` (G0/G5) and `measurement-capture` (M0/M1)
  acceptance profiles, with tests preventing broader claim promotion and
  invalidation checks when evidence changes.
- MCP recipe discovery, single-recipe inspection and bounded artifact rendering
  through existing deterministic services, with no-overwrite output protection
  and CLI parity tests. The MCP surface grows from 10 to 13 tools.
- Task-oriented tool selection, a focused primary-source integration survey,
  and an on-demand engineering qualification reference.

### Changed

- Added an explicit exploratory route for authorized diagnostic solves and
  searches without mandatory gate ledgers. Gates govern acceptance, while
  stricter project prerequisites continue to apply. Documented claim-specific
  tolerances, conditional fidelity/corners, and the scope of G2/G8.
- Updated English and Chinese README guidance and versioned provider examples;
  retained gate schemas, existing profile meanings and backend-adoption checks.
- Updated CI's MCP tool-count assertion and require the recipe artifact smoke.
- Reduced the skill entrypoint from 302 to about 130 lines; route by the requested
  artifact and load only relevant references. Clarified that public adapter
  restrictions do not prohibit authorized task-specific model programming.
- Added explicit MCP side-effect annotations and shared the recipe output-path
  policy between CLI and MCP without changing numerical algorithms or gates.
- Split skill-internal gate use into lightweight advisory mode and claim-scoped
  evidence mode, with composable base profiles and promotion/delivery overlays.
- Replaced label-only gate evidence with project-relative, SHA-256-bound
  `CHECK=PATH` evidence mappings for new PASS/N/A transitions; legacy records
  remain readable but are reported as unverified rather than silently promoted.
- Made passivity, reciprocity, unitarity, power closure, causality, convergence,
  field review, and manufacturability checks conditional on the device physics
  and the claim being promoted instead of universal entry requirements.
- Documented COMSOL study-sequence, convergence, and export contracts without
  claiming unverified renderer coverage, and clarified the current native-adjoint
  boundary, evidence cadence, checkpointing, and concurrency expectations.
- Repositioned the skill as a solver-agnostic, auditable photonic design and
  closure workflow while retaining COMSOL as a bounded adapter and historical
  repository name.
- Tightened numeric-port and open-boundary selection guidance with an exact,
  fail-closed exterior partition audit derived from corrected SOI splitter
  modeling experience and reconciled with COMSOL's local cross-section model.
- Added mandatory physical field-image review rules so implausible confinement,
  launch area, leakage, PML concentration, or plot context blocks acceptance.
- Switched the trusted Windows Java compile route to COMSOL's official
  `comsolcompile` entrypoint before `comsolbatch`, retaining the legacy wrapper
  parameter alias for compatibility and safely normalizing COMSOL's unique
  named-model output suffix.

Implementation and validation: OpenAI Codex.

### Fixed

- Read lazy CLI defaults through Click's public API so the compatibility
  snapshot is stable across Click 8.4/8.5 without invoking default callables.
- Recognize Windows short-path aliases for recipe output roots after rejecting
  symlinks/junctions; preserve canonical containment and no-overwrite checks.

## [0.4.0] - 2026-08-01

### Added

- Installable `photonic-workflow` package, `photonic` CLI, bounded MCP server,
  adapter SPI, project/run stores, versioned contracts, adoption gates, and
  solver-independent workflow profiles.
- Six deterministic modeling recipes distilled by reviewed behavioral and
  public-formula reimplementation from two read-only LT-aMZI projects: circular and
  symmetric-Euler geometry, segmented port windows, Li silicon and Malitson
  fused-silica bulk dispersion, and common-basis two-port diagnostics.
- Strict recipe request schemas, exact recipe versions, parameter contracts,
  packaged provenance hashes, canonical JSON output, and allowlisted fixed
  numeric COMSOL Java fragments for geometry/port setup only.
- MATLAB Phase A contracts and probes, external-backend adoption ledgers,
  package resource mirrors, artifact audits, and multi-context GitHub Actions
  validation.
- Python 3.11-3.14 compatibility lanes, checked-in skill/UI metadata schema
  validation, SHA-pinned Actions, split release permissions, SHA-256 release
  inventories, and GitHub build-provenance attestations.

### Changed

- Legacy Python and PowerShell entry points now delegate to package services
  while retaining regression-tested compatibility contracts.
- The legacy analytic-bend helper no longer writes arbitrary `--output` paths;
  bounded fragment creation is provided by `photonic recipe render`.
- MCP resource counts are derived from one registry and verified against source,
  packaged, and installed-wheel resources instead of duplicated magic numbers.
- The minimal third-party adapter example now declares host compatibility
  `photonic-workflow>=0.4,<0.5`.

### Evidence boundaries

- Recipe evaluation and rendering do not execute COMSOL or establish full-wave
  validation, convergence, fabrication readiness, or device acceptance.
- MATLAB Phase B remains blocked by the recorded native startup crash in the
  required normal interactive Windows context. LiveLink, Lumerical, instruments,
  and real PDK/DRC/LVS integrations remain separate Phase C adoption gates.

[0.8.0]: https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/compare/75a1840...main
[0.7.0]: https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/compare/10508ed...75a1840
[0.6.0]: https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/compare/v0.5.0...10508ed
[0.5.0]: https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/releases/tag/v0.4.0
