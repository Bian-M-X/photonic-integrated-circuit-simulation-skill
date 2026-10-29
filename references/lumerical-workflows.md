# Lumerical execution and COMSOL migration

Use this route for native Lumerical automation, migration of reviewed PIC
geometry and optical data, or a product-specific local diagnostic. Shared
engineering guidance and G/M evidence definitions still apply. Installation,
execution, numerical agreement and qualified-device acceptance are separate
results.

For the implemented device path, see [complete device workflow](lumerical-device-workflow.md):
shared geometry/material recipes → every selected-mode source solve → raw
complex S and modal-basis checks → existing circuit composition and bounded
optimization. The geometry-only exporter below has a smaller family subset.

## Choose the migration level

| Existing asset | Reuse | Rebuild or verify in Lumerical |
|---|---|---|
| Design intent, parameters and tolerances | Keep dimensions, band, stack, temperature, mode labels and loss assumptions | Explicit coordinate mapping, units and actual material assignments |
| Native primitive geometry | `export-geometry` uses the existing geometry builder and emits fixed LSF plus JSON | Extrusion height, overlaps, Boolean topology and native object readback; export alone has no fields |
| Circular/Euler recipe output | Reuse canonical numeric points, widths, curvature and length | Map micrometres to metres; retain polygon sampling error and compare endpoints/area; Java fragments do not execute in Lumerical |
| Li silicon/Malitson silica recipes | Reuse the same formula/version, wavelength grid and temperature limits | FDTD material fit and MODE dispersion; bulk silicon is not an effective modal index, and fused silica is an oxide surrogate |
| Complex S matrices and circuits | Import all source/receiver channels and keep the current CSV/circuit contracts | Normalization, time convention, modal basis, port direction and reference planes |
| Optimization/corner/report code | Reuse objective definitions, budgets, sensitivities and artifact tracking | Each solver's request, result extraction, failure status and fidelity calibration |
| `.mph`, COMSOL Java, selections and studies | Retain as provenance and a comparison baseline | Reconstruct Lumerical objects, mesh, boundary conditions, ports, sources and monitors; no direct project-file conversion is provided |
| COMSOL adjoint/MMA or electro-optic physics | Keep the physical objective and independent benchmark | Product-specific gradient, material derivative, charge/thermal coupling and sign checks; a native optical smoke does not validate them |

For the native library, the existing COMSOL optical model is a
`2d-scalar-index-surrogate`. Extruding its footprint to a finite-height
Lumerical geometry changes the model level; it does not establish 2D-to-3D
equivalence. This geometry exporter supports `straight`, `crossing`,
`directional-coupler`, `mmi2x2` and `ybranch`; ring/PN-region geometry is outside
its supported subset. Use a common simplified model when making a numerical
solver comparison.

## Discover and plan before executing

The local installation may be a parent directory, version directory or product
directory. Discovery locates the matching `api/python/lumapi.py` and product
executables without claiming a license checkout. The user-specified Windows
installation is under `D:/Apps/Lumerical`; do not substitute a default Program
Files path or change proxy settings.

```powershell
photonic lumerical discover --install-root D:/Apps/Lumerical --json
photonic lumerical plan examples/lumerical/mode-waveguide.json --install-root D:/Apps/Lumerical --json
photonic lumerical run examples/lumerical/mode-waveguide.json --output D:/Research/lumerical-runs/mode-001 --install-root D:/Apps/Lumerical --timeout 180 --threads 2 --json
```

Use a fresh output directory. A source checkout can use
`python -m photonic_workflow.cli` with `src` on `PYTHONPATH` when the installed
console script has an older version. The native API is supplied by the local
Lumerical installation; no vendor library is redistributed in this package.
On this Windows checkout, `scripts/invoke-lumerical.ps1` forwards arguments to
the current source using `python`, without replacing the installed CLI. For
example, `./scripts/invoke-lumerical.ps1 discover --install-root D:/Apps/Lumerical --json`.
Official [session management](https://optics.ansys.com/hc/en-us/articles/360041873053-Session-Management-Python-API)
documents product constructors and session arguments. The executor uses hidden
sessions, closes them, and runs a bounded worker process with a timeout.
Keep licensed runs serial and inspect failures before retrying.

For an existing local license, a server address can refer to the same computer;
it does not require external Internet. If this installation's local manager is
stopped, explicitly use `--local-license` on `run`. This starts the existing
`Shared Files/licensing/winx64/lmgrd.exe` in its supported local-only application
mode with the existing license file, or reuses a listening local manager. It
passes the endpoint to the worker and stops only manager processes it created.
Service settings, license contents, parent environment and proxy remain unchanged.
For an already running service, `--license-server 1055@localhost` sets only the
child's `ANSYSLMD_LICENSE_FILE`. These two options are mutually exclusive.
See the official [environment and INI configuration](https://optics.ansys.com/hc/en-us/articles/360025358714-Lumerical-license-configuration-using-environment-variable-and-ini-files).

```powershell
./scripts/invoke-lumerical.ps1 run examples/lumerical/mode-waveguide.json --output runs/mode-local-001 --install-root D:/Apps/Lumerical --local-license --threads 2 --json
./scripts/invoke-lumerical.ps1 run examples/lumerical/fdtd-uniform.json --output runs/fdtd-local-001 --install-root D:/Apps/Lumerical --local-license --threads 2 --json
```

Public JSON selects fixed operations and typed numeric parameters. It accepts
no arbitrary LSF, Python callback, model-load instruction or evaluated
expression. Task-specific reviewed source can still be developed under the
normal authorized workflow; it needs its own provenance and validation.

## Native diagnostic requests

Requests have `schema_version: "1.0"`, `operation` and `parameters`. Parameters
use SI metres and seconds where indicated; unknown parameters fail validation.

| Operation | Question answered | Scope |
|---|---|---|
| `mode-waveguide` | Can MODE build a declared rectangular core and solve guided modes with plausible effective indices? | Constant-index, finite-height cross section; mode identities and convergence still need inspection |
| `fdtd-uniform` | Can FDTD propagate a plane wave through a uniform dielectric with plausible power and phase? | Uniform-medium solver/monitor diagnostic; no waveguide ports or complete device matrix |
| `geometry-readback` | Does a licensed FDTD CAD session reproduce migrated object dimensions, vertices and scalar material assignments? | Actual CAD construction and saved project; no field solve or device matrix |
| `fdtd-device` | Can the shared device geometry be solved with every physical input port separately excited? | Complete selected-mode matrix, native field/basis and material readback; seven optical footprints, explicit 2D scalar or 3D level |

Minimal MODE request:

```json
{
  "schema_version": "1.0",
  "operation": "mode-waveguide",
  "parameters": {
    "wavelength_m": 1.55e-6,
    "width_m": 5e-7,
    "height_m": 2.2e-7,
    "core_index": 3.476,
    "clad_index": 1.444,
    "mesh_cells": 100
  }
}
```

These indices are declared constant test inputs. They do not represent a
validated foundry material stack. Preserve the saved native project, raw
complex arrays, request, compact result, worker log, product version and hashes.
A passing diagnostic checks the implemented path and its specified numerical
conditions; it does not pass G1 or establish broadband phase continuity.

Finer meshes, larger transverse windows and changed PML are independent tests.
For FDTD, also check simulation duration, residual energy, spectral sampling
and phase at known monitor locations. For a component, replace the uniform
control with a qualified straight-waveguide/port baseline and actual source
columns. MODE FDE success does not establish EME success, and neither implies
FDTD, DEVICE/Multiphysics or INTERCONNECT execution. Those products and
operations require their own license, minimal model and parity evidence.

`fdtd-device` provides that all-source optical execution path and has separate
[local test evidence](../docs/research/lumerical-device-workflow-2026-10-29.md).
It does not transfer COMSOL electrical/thermal or adjoint solver implementation.

The FDTD diagnostic explicitly uses nearest-mesh-cell monitor interpolation.
Its phase reference planes are the exported E-dataset `x` coordinates, which
can differ from requested CAD coordinates. Raw artifacts preserve both planes
and both phase comparisons. Do not use requested positions to interpret fields
sampled on another plane or relax a phase threshold to hide that mismatch.
See [frequency-domain monitor sampling](https://optics.ansys.com/hc/en-us/articles/360034902393-Frequency-domain-monitor-Simulation-object).

## Transfer geometry and materials

```powershell
photonic lumerical export-geometry examples/lumerical/crossing-geometry.json --output D:/Research/lumerical-runs/crossing-geometry --height-um 0.22 --core-index 3.48 --json
```

Read the export receipt for supported native families and artifact paths.
The request contains only `schema_version`, `family` and `parameters`; extract
those fields from a native solve request explicitly. Physics/mesh/PN fields are
rejected so they cannot disappear silently in a geometry transfer.
`export-geometry` constructs geometry; it does not run Lumerical, assign a
complete stack or create qualified ports. Keep port identifiers and centerlines
with the footprint. Inspect z placement, source/monitor cross sections, core
ends, overlap priorities and background before adding a solver region. Existing
COMSOL segmented boundary windows are not Lumerical port objects.

The separate `geometry-readback` request at
`examples/lumerical/geometry-readback.json` embeds a geometry-only
`native_request`, `height_um` and `core_index` in `parameters`. Use the same
`plan`/`run` commands to build it through FDTD's native API, compare rectangle
bounds or polygon vertices and material/index readback, and save `model.fsp`.
It requires an actual product session and license even though no field solver
runs. A successful offline LSF export is not this native readback check.

For a shared material model, export sampled wavelength and complex index or
permittivity with units and the source formula/hash. Lumerical supports
[sampled optical materials](https://optics.ansys.com/hc/en-us/articles/360034915093-Creating-new-sampled-data-materials-in-FDTD),
but FDTD must fit a time-domain material model. Inspect the fitted complex
index over the simulation band and reserve an error budget for its discrepancy.
MODE's interpolation/fitting choices can differ; see the
[MODE material settings](https://optics.ansys.com/hc/en-us/articles/360034917013-EME-solver-Simulation-object).
Matching material names or one index value does not establish matching
dispersion, absorption or group delay.

## Exchange complete complex S data

Use the reviewed JSON fixture at `examples/lumerical/sparameters.json` as the
exchange schema. It is a synthetic data-format fixture, not a solved device.
The bridge requires:

- producer product/version, declared model level and explicit `passive` flag;
- a frequency or wavelength axis with explicit units;
- ordered channels with original port, mode, incoming/outgoing directions and
  reference plane;
- time dependence, power-wave normalization and spectral/outgoing/incoming
  matrix-axis declaration;
- every complex matrix element encoded as `[real, imaginary]`.

```powershell
photonic lumerical import-sparameters examples/lumerical/sparameters.json --output D:/Research/lumerical-runs/device-s.csv --project-root D:/Research/lumerical-runs --json
```

For reviewed extraction code, `photonic_workflow.lumerical_exchange` exposes
`dataset_from_arrays`, `normalize_lumerical_sparameters` and
`export_lumerical_sparameters`. Pass the native complex NumPy matrix to
`dataset_from_arrays` only after arranging its axes as
`(spectral, outgoing, incoming)` and supplying the same explicit metadata.
The helper preserves real and imaginary values without squeezing or inferring
native dataset dimensions.

The exporter sorts the spectral grid and matrix samples together, writes
`wavelength_nm,out_port,in_port,s_real,s_imag` CSV, and retains channel and
convention metadata with source hashes in `<output>.csv.metadata.json`.
It also archives the original input bytes in `<output>.csv.source.json`,
including original sample order, BOM, line endings and any unchanged values.
Use its assembly component
metadata with existing `photonic circuit validate`/`compose`. The CSV alone
cannot carry modal reference planes; keep the sidecar with it. An explicitly
requested time-convention change conjugates the complex data and records the
conversion. It does not align independently calculated mode phases or de-embed
reference planes. Do not silently conjugate, take square roots of power, fill
missing columns from reciprocity or reinterpret array axes.

For native extraction prefer [FDTD ports](https://optics.ansys.com/hc/en-us/articles/360034382554-Ports-FDTD-Simulation-Object)
with an S-parameter sweep. Raw mode-expansion coefficients require normalization
and direction handling before they become power-wave S parameters; see
[mode-expansion results](https://optics.ansys.com/hc/en-us/articles/360034902433-Using-and-understanding-Mode-Expansion-Monitors).
For multiple modes, declare one channel per port/mode and retain the complete
matrix. Preserve actual source-column identity and any symmetry assumptions.

Run conditional passivity/reciprocity/power diagnostics using their physical
assumptions. Missing guided power, absorption, radiation, truncation error and
mode-conversion channels remain distinct. Cross-solver agreement additionally
needs a common basis, reference planes and convergence budget. A lossless data
conversion is a data-integrity result, not proof of equal solver physics.

Primary-source documentation refreshed **2026-10-29**. Local execution evidence
belongs in a run-specific report; these vendor documents do not verify the
installed license or claim qualification of any generated device.
