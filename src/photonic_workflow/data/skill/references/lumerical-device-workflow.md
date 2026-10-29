# Lumerical complete-device workflow

Use this route to migrate a parameterized optical component through geometry,
modal ports, every requested source column, complete complex S export, and the
existing circuit or optimization tools. Read [lumerical-workflows.md](lumerical-workflows.md)
for local execution and licensing. A device workflow preserves its declared
model level; it does not convert a COMSOL binary model into equivalent FDTD.

## Freeze the same physical question

Record family/geometry, dimensionality, indices or material dispersion, band,
polarization, channel order, port windows and physical reference planes. The
existing COMSOL native family uses `2d-scalar-index-surrogate`. A finite-height
3D extrusion is a different model, even when its footprint and indices match.
Check the actual out-of-plane field component when comparing 2D polarizations;
vendor TE/TM names alone do not establish equality of Maxwell problems.

Use the shared geometry constructors rather than redrawing access curves.
Retain their semantic port order and micrometre-to-metre conversion. Continue
the same guide/material behind each interior source/monitor plane through its
PML backing. Audit actual primitives, overlaps, annulus radii, material index,
port normal/direction and sampled coordinates after native construction.
Geometry readback is separate from modal and driven evidence.

## Execute and export

Use `operation: "fdtd-device"` in a strict Lumerical request. Inspect the request
and its normalized plan before native execution. The public execution command
and local-license handling remain the same as for the smaller diagnostics:

```json
{
  "schema_version": "1.0",
  "operation": "fdtd-device",
  "parameters": {
    "family": "straight",
    "geometry_parameters": {"width_um": 0.3, "length_um": 6.0},
    "model_dimension": "2d",
    "mode_selection": "fundamental TM mode",
    "core_index": 2.6,
    "clad_index": 1.45,
    "wavelength_start_m": 1.5e-6,
    "wavelength_stop_m": 1.6e-6,
    "frequency_points": 5,
    "mesh_accuracy": 3
  }
}
```

Geometry parameters retain the shared builder's micrometre units. Optical
request lengths with `_m` use metres. In the 2D scalar route, finite-height
geometry does not introduce vertical confinement; the invariant out-of-plane
dimension is part of the declared reduction. The 3D route needs an explicitly
chosen height/vertical cladding span and a separately validated port baseline.

```powershell
photonic lumerical plan DEVICE_REQUEST.json --install-root D:/Apps/Lumerical --json
photonic lumerical run DEVICE_REQUEST.json --output D:/Research/lumerical-runs/device-001 --install-root D:/Apps/Lumerical --local-license --threads 2 --json
photonic lumerical device-export D:/Research/lumerical-runs/device-001/receipt.json --output D:/Research/lumerical-runs/device-s.csv --project-root D:/Research/lumerical-runs --json
photonic lumerical compare-devices COARSE_RECEIPT.json FINE_RECEIPT.json --json
```

Paths are placeholders; use the reviewed request and actual receipt from the
chosen run. Outputs must be new files/directories. From the source checkout,
`scripts/invoke-lumerical.ps1` replaces `photonic lumerical` and uses the current
source rather than a possibly older installed CLI.

The native runner retains `source_dataset.json` and exports it through the
same complete-complex-S bridge used by supplied datasets. `device-export`
verifies the recorded artifact sizes/hashes, actual source identities and the
raw matrix against the exported dataset before re-exporting to the chosen
circuit directory. This detects inconsistent artifacts; local hashes do not
independently certify the physical model or the authenticity of a solver run.
Keep its CSV, metadata and original JSON archive together. `compare-devices`
requires matched geometry/materials/channels/spectral grid and compares powers;
it does not silently fit phase gauges across independently built models.

The seven optical geometry families are `straight`, `crossing`,
`directional-coupler`, `mmi2x2`, `ybranch`, `ring` and `ring-modulator`.
The ordinary ring accepts the shared `bus_count` geometry setting. The
`ring-modulator` route currently builds its optical footprint with the selected
optical material; it does not run a PN, Poisson or CHARGE calculation.
For dispersion, optional request parameters are `core_material_model` and
`clad_material_model`, for example `{"model": "li-silicon-1980",
"temperature_k": 293.15}` and `{"model": "malitson-fused-silica-1965"}`.
The recipes supply real bulk index with explicit zero extinction; do not infer
a measured absorption law or a calibrated foundry stack. Inspect the retained
sampled table, fitted complex index, fit error and actual assignments. The
`material_fit_tolerance` is an absolute complex-index error, default `0.01`.

## Solve every declared source

Create all FDTD port objects in one built model and select the requested mode
basis before the source loop. Keep geometry, mesh, material, reference planes
and mode settings unchanged while changing only the active source port/mode.
Retain one native model/result per source and an explicit source-index map.
Do not rebuild geometry separately for each source or infer missing columns
from symmetry, reciprocity or an ideal device model.

Lumerical port objects combine source, modal analysis and S readout. Their
individual S results belong to the currently excited source. The ports group
is not an aggregate S-result provider. A full matrix requires all source
channels; the vendor's matrix-sweep utility likewise runs one simulation for
each active port/mode row. See [port objects](https://optics.ansys.com/hc/en-us/articles/360034382554-Ports-FDTD-Simulation-Object)
and the [matrix-sweep utility](https://optics.ansys.com/hc/en-us/articles/360034403214-S-parameter-matrix-sweep-utility).

Every spectral sample must contain every receiver/source pair, with rows as
outgoing channels and columns as incoming channels. Save native result axes
before reshaping; reject ambiguous or missing dimensions. Keep the original
complex arrays, normalization observations and exact frequency grid. Do not
invert a contaminated incoming matrix or fit phases to improve a diagnostic.

## Preserve modal and power meaning

One chosen mode per physical port gives a complete matrix only for that
declared channel set. It does not prove that other guided modes are absent.
Resolve extra propagating channels when the claim requires them; otherwise
state the missing coverage. Native source/receiver mode profiles or phase
anchors should be compared across columns to detect a changed basis. A
successful same-model source loop alone does not prove broadband gauge
continuity or compatibility with independently built components.

The implemented runner compares unscaled E/H profiles, coordinates and sampled
frequencies across source columns, including overlap, norm and phase changes.
It retains the native profile dataset labels and the selected channel index.
It also audits the direction-corrected native incoming modal powers: the
excited input must be within 5% of unity, other inputs below `1e-3`, and modal
power norms positive and finite. These observations are retained without
renormalizing the exported matrix. Profile checks apply to the sampled profile
frequencies; they are not a proof of unsampled spectral behavior.

Raw expansion coefficients require modal-power and direction conventions;
they are not automatically power-normalized S amplitudes. The built-in
expansion analysis includes finite-grid corrections. Absorbing port modes
need an explicitly justified normalization; the nonabsorbing power-orthogonal
formula must not be applied silently. See the vendor's [mode-expansion theory](https://optics.ansys.com/hc/en-us/articles/360034902433-Using-and-understanding-Mode-Expansion-Monitors).

For each source, record reflection, transmission into every retained guided
channel, and their sum. A deficit is an unclassified residual unless separate
radiation/absorption measurements resolve it. A positive excess can expose
normalization or convergence errors. Evaluate reciprocity and the largest
singular value only under their applicable assumptions. Never clamp or
symmetrize the exported matrix to make these checks pass.

## Consume the actual matrix

Keep power-wave normalization, time convention, channel labels, modes,
directions and reference planes with the exported CSV. The existing data bridge
preserves the original dataset and jointly sorts its spectral grid/matrices.
An explicit time-convention conversion conjugates amplitudes and records that
operation; it does not align independently calculated modal phases.

Run existing circuit validation before composition. For an optimization trial,
derive the objective from the retained native matrix at the declared band and
ports. Count a complete device evaluation by its actual source solves; four
ports require at least four driven runs for one selected mode per port. Save
failed candidates and actual costs. Do not relabel geometry-only or synthetic
data as a native evaluation, or treat a best observed point as a global optimum.

Circuit input validation keeps its strict default largest-singular-value
allowance of `1e-6`. When a numerical allowance is justified, declare it with
`device-export --passivity-tolerance VALUE` in `[0, 0.05]` and carry the returned
component metadata into the circuit request. The metadata records this choice
and the unchanged data. The argument changes circuit input acceptance only;
it neither corrects the raw matrix nor passes physical device qualification.
The runner's separate coarse diagnostic permits a largest singular value up
to `1.05`; a pass there does not override the circuit's stricter default.

`optimize-step` joins the existing bounded candidate suggestion and trial
contracts to one native evaluation. Its exact configuration contains
`schema_version`, `spec_file`, `base_request`, `trials_dir`, `objective` and
`parameter_map`. Map only explicit geometry parameters:

```json
{
  "schema_version": "1.0",
  "spec_file": "optimization-spec.json",
  "base_request": "straight-request.json",
  "trials_dir": "trials",
  "objective": {
    "name": "through_power",
    "out_port": "right",
    "in_port": "left",
    "statistic": "mean_power"
  },
  "parameter_map": {"width_um": "geometry_parameters.width_um"}
}
```

```powershell
photonic lumerical optimize-step CONFIG.json --output D:/Research/lumerical-runs/step-001 --json
photonic lumerical optimize-step CONFIG.json --output D:/Research/lumerical-runs/step-002 --execute --local-license --json
```

Without `--execute`, the operation plans/suggests rather than solving. A failed
or invalid diagnostic cannot become a completed training observation. The
trial records the specification and base-request identities. Supported scalar
statistics include mean/min/max power and mean insertion loss in dB; state
the optimization direction explicitly. This numerical evaluator is distinct
from native full-wave adjoint optimization or automatic device qualification.
The specification must select backend `lumerical-fdtd-device` and a fidelity
matching its request: `full-wave-2d-scalar` for the planar scalar model, or
`full-wave-3d` for a finite-height vector model. The 2D route is not relabelled
as calibrated effective-index modelling. Changes to mesh, materials, ports or
objective identity require a separate bound trial history rather than pooling
incompatible observations. Zero transmission does not have a finite insertion
loss and must not be silently clipped into a successful dB objective.
Geometry variables mapped to `_um` fields must declare unit `um`; no automatic
nanometre conversion is performed. Supported native constraint observations are
`max_reflection_power`, `max_singular_value` and `max_reciprocity_error`.
Use the packaged `examples/lumerical/device-optimization*.json` pair with
`device-coupler.json` for a complete gap-screening configuration.

## Minimal discriminating tests

1. Straight guide: all two source columns over multiple spectral points,
   source/receiver axes, low reflection, transmission power, actual-plane phase
   and a finer mesh with the same port basis.
2. Four-port coupler: all sixteen complex entries at each spectral point,
   per-source guided-power accounting, conditional passivity/reciprocity and a
   geometry perturbation that changes the observed response.
3. Circuit: two exported components at compatible conventions/reference planes;
   compare a cascade with an independently calculated complex product or
   direct network solve.
4. Optimization: at least two actual native candidate evaluations, with metrics
   reproduced from their stored S data and no synthetic substitution.

Mesh, port-window, PML distance, temporal decay and spectral resolution remain
independent numerical controls. In particular, sparse ring samples do not
establish linewidth/Q or reliable interpolation. Choose tolerances from the
claim before inspecting results, and retain any failed checks.

Primary vendor documentation refreshed 2026-10-29. Execution results belong in
the [run-specific report](../docs/research/lumerical-device-workflow-2026-10-29.md).
The [capability migration audit](../docs/research/lumerical-capability-matrix-2026-10.md)
distinguishes shared tools and new FDTD support from capabilities retained in
COMSOL, including native PN/Poisson, multiphysics and adjoint paths.
