# Shared COMSOL and Lumerical workflows

Use this reference when reusing a recipe, consuming data from another backend,
selecting a solver or comparing their results. Keep the physical question and
data contract shared; implement native CAD, modes, boundaries and solves in the
selected backend. Common geometry is useful provenance, not numerical parity.

## One engineering loop, explicit backend steps

| Stage | Shared asset | COMSOL implementation | Lumerical implementation |
|---|---|---|---|
| Define | geometry parameters, band, material formulas, mode/polarization intent | native-family request | fixed MODE/FDTD request |
| Build | canonical numeric geometry and semantic ports | generated Java / semantic selections | native rectangles, polygons, annuli, leads and readback |
| Modes | cross-section, mode identity, normalization observations | Boundary Mode Analysis bound to Numeric Ports | native mode selection and E/H profile/power readback |
| Sources | every declared input, one frozen model/basis | FrequencyDomainSourceSweep | select each native source port in the same constructed model |
| Boundaries | open-domain target and convergence budget | exterior modal/open-boundary partition or qualified internal backing | interior port planes, continuing waveguides and PML backing |
| Exchange | complete complex S, units, channel order, phasor and reference planes | `native calibrate` and CSV export | `lumerical device-export` and archived native JSON |
| Consume | circuit assembler, objective definitions, trial budget and reporting | existing common tools | the same common tools after compatibility checks |
| Accept | project-specific numerical/physical evidence | backend-specific controls | backend-specific controls |

Recipes expose mathematical output independently of their rendering target.
The material recipes are called directly by the Lumerical sampled-material
bridge; its fitted index and assignments need separate readback. A Java fragment
does not execute as LSF. A new native renderer must preserve the recipe's units,
curve sampling and topology rather than redraw a similar-looking structure.
Inspection/planning MCP tools share the package logic and do not start a vendor
process. Actual licensed execution remains an explicit local runner action.

## Matched scalar benchmark

The executable protocol in `photonic_workflow.lumerical.parity` provides two
controls: `straight` and `directional-coupler`. `make_benchmark_plan` freezes:

- the same canonical geometry, port order, 0.30 um end widths and constant
  indices 2.6/1.45;
- a two-dimensional scalar out-of-plane electric-field problem, labeled
  `2d-scalar-index-surrogate`; Lumerical's native name for this channel is
  `fundamental TM mode`, not a claim about a 3D SOI TE/TM branch;
- all five identical wavelength samples derived from the native uniform
  frequency grid between 1500 and 1600 nm;
- COMSOL mesh 0.04 um core / 0.14 um cladding / 0.02 um ports and FDTD mesh 5;
- a declared screening power allowance of 0.03 (three absolute percentage
  points), before inspecting the paired output;
- separate finer settings: COMSOL 0.025/0.10/0.01 um and FDTD mesh 6.

The default screening allowance is not a production or paper-performance
specification. Freeze a different tolerance before a campaign when its physical
question requires one. Retain failed runs; do not widen the budget after seeing
a discrepancy. If geometry, material or model level changes, create a new plan.

Generate a plan without starting a solver:

```powershell
photonic lumerical plan-benchmark straight --power-tolerance 0.03 --json
python scripts/compare_photonic_solvers.py plan --family straight --output runs/paired-straight-001 --power-tolerance 0.03
```

The CLI returns the normalized plan in its JSON envelope. The standalone script
materializes `benchmark-plan.json`, `comsol-request.json` and
`lumerical-request.json`. Full example plans are
`examples/lumerical/benchmark-straight.json` and
`examples/lumerical/benchmark-coupler.json`. They contain both native requests;
they are not themselves inputs to `photonic lumerical run`.

Run the two requests using the existing explicit native commands:

```powershell
photonic native prepare runs/paired-straight-001/comsol-request.json --output runs/paired-straight-001/comsol-bundle --json
photonic native run runs/paired-straight-001/comsol-bundle --solver-root COMSOL_ROOT --cores 2 --json
photonic lumerical run runs/paired-straight-001/lumerical-request.json --output runs/paired-straight-001/fdtd --install-root LUMERICAL_ROOT --local-license --threads 2 --json
```

Use the actual COMSOL receipt path returned by its run; it is in a unique
subdirectory under the prepared bundle. Existing FDTD evidence can be reused
only when its frozen request/geometry exactly match the declared protocol.
The Python comparator reads identified native receipts, not hand-entered plots:

```powershell
photonic lumerical compare-solvers COMSOL_RECEIPT.json FDTD_RECEIPT.json --power-tolerance 0.03 --json
python scripts/compare_photonic_solvers.py compare --comsol-receipt COMSOL_RECEIPT.json --lumerical-receipt FDTD_RECEIPT.json --power-tolerance 0.03 --output runs/paired-straight-001/comparison.json
```

It verifies COMSOL's generated-source/bundle/compiled/raw-console bindings and
Lumerical's complete raw matrix/source bindings. It requires identical declared
geometry, material assumptions, channel order and sampled wavelengths. Actual
COMSOL port planes come from `PIC PORT_GEOMETRY`; FDTD planes come from the
native port E dataset. Only coordinate roundoff up to `1e-15 m` is accepted.
The COMSOL native readback must also match each semantic port's transverse
window center and width; a same-length window on the wrong guide is rejected.
Its transverse rendering-bounds center has an explicit `1e-12 m` allowance for
the COMSOL bounds record's float quantization. The initial coupler record's
center roundoff was about `3e-14 m`. This allowance does not translate a
longitudinal reference plane or change any matrix element or power tolerance.
No interpolation, symmetry fill, conjugation, de-embedding, phase fit or matrix
normalization is applied. Every output/input pair at every sample contributes
to maximum and RMS differences in `|S|²`.

The report distinguishes `within_declared_power_tolerance` from
`outside_declared_power_tolerance`, retains per-wavelength differences and
guided power sums, and always leaves `physics_accepted=false`. Agreement on
five points does not establish an unsampled broadband response or an entire
solver's superiority. A disagreement can expose different open-boundary,
spatial discretization, source or finite-time errors; inspect each before
changing the design.

## Initial native comparison observations

Both controls completed actual COMSOL source sweeps and were compared with
retained FDTD mesh-5 data at all five frozen wavelengths and every channel pair.
The initial COMSOL mesh was 0.04/0.14/0.02 um. The 0.03 absolute power allowance
was declared before these results:

| Control | Matrix elements compared | Maximum absolute change in `|S|²` | Within declared 0.03? |
|---|---:|---:|---|
| Straight, two ports | 20 | `0.0000128528294765` | yes |
| Directional coupler, four ports | 80 | `0.0520321246393` | **no** |

The coupler discrepancy is about 5.20 power percentage points, above the
predeclared three-point allowance; its worst sampled wavelength was about
1523.81 nm. This negative observation remains part of the record even if a
later refinement improves agreement. Neither result compares complex phase,
establishes broadband convergence or ranks one solver as more accurate.
The next discriminating test is the already planned separate mesh refinement,
followed by boundary and time-window studies if the discrepancy remains.
The baseline local record is `runs/lumerical-reuse-20261029/native-parity-summary.json`;
publish only its reviewed compact evidence summary, not proprietary native
models or local installation/receipt paths.

Subsequent fine-mesh comparison at the same 1.2 um lateral clearance still
failed the original 0.03 budget (maximum absolute power difference 0.0474452).
An explicitly recorded boundary-sensitivity test kept the fine meshes and
core device unchanged while expanding both lateral clearances to 4 um. Its
maximum difference was 0.0225582, within the same budget. Retain both failures;
the enlarged-window pass is not evidence of complete boundary convergence or
general solver equivalence. See the [full unified-tool report](../docs/research/lumerical-unified-tools-2026-10-30.md)
for requests, geometry/receipt bindings and the complete sequence.

## Phase and refinement boundaries

The implemented comparator is deliberately power-only. Native COMSOL and FDTD
complex modal gauges are independent, even when each individual source sweep
has a common internal basis. Before a complex-phase, group-delay or mixed-solver
coherent-circuit claim, independently establish mode-field projection, power
normalization, time convention, mode direction and physical reference-plane
compatibility. A least-squares phase fit to improve agreement is not that
evidence. Power agreement alone cannot authorize mixing coherent S matrices.

Refine each backend separately before attributing a cross-solver difference:

1. Keep the same physical geometry/materials/channels and change mesh only.
2. Test COMSOL exterior window/open-boundary distance or the qualified backing
   scheme; independently test FDTD PML/buffer parameters.
3. Lengthen FDTD time windows and inspect residual energy/stopping conditions,
   especially for rings; refine both backends' spectral grid near resonances.
4. Compare the measured change with the frozen error budget. Report unresolved
   effects and failed checks rather than calling every complete run converged.

## Capabilities that remain separate

The shared optical path does not convert `.mph`, arbitrary COMSOL Java,
study/mesh trees, PN/Poisson, thermal/electrical/stress coupling or a dedicated
COMSOL adjoint/MMA evaluator into Lumerical native execution. Existing COMSOL
features remain available. CHARGE/HEAT, EME, INTERCONNECT and a native Lumerical
gradient path need their own implementation and native evidence. A successful
MODE/FDE or FDTD fixture cannot qualify these products by association.
