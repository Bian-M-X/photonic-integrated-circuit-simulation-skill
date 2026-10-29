# Native device geometry and calibration

This route supplies parameterized COMSOL source for a straight control, crossing,
directional coupler, 2x2 MMI, Y branch, ordinary all-pass/add-drop ring and PN-depletion
ring modulator. JSON preparation and verification do not launch a solver.
`photonic native run` explicitly compiles and executes the fixed generated
COMSOL source with a local license. The 13 MCP tools retain their existing
plan-only execution boundary; this CLI does not turn `run_java_batch` into an
execution tool.

The optical model level is `2d-scalar-index-surrogate`. Default core/cladding
indices 2.6/1.45 are declared scalar inputs, not calibrated 3D SOI material or
modal indices. Default examples are single-wavelength diagnostics and do not
establish device performance, convergence or a passed qualification gate.

## Requests and geometry

Use the JSON files in `examples/native-devices/`. Optical requests contain
`schema_version: "1.0"`, `family`, `parameters`, `wavelengths_nm` and `stage`.
The ring modulator additionally accepts `pn`. Unknown fields, boolean numbers,
nonfinite values and out-of-bounds parameters are rejected. Wavelengths must
increase strictly within 1200–1700 nm. All geometry lengths are in micrometres.

| Family | Geometry parameters beyond shared width/clearance/port window | Port order |
|---|---|---|
| `straight` | `length_um` | left, right |
| `crossing` | `arm_length_um`, `center_width_um` | west, east, south, north |
| `directional-coupler` | `coupling_length_um`, `gap_um`, `port_offset_um`, `lead_um`, `transition_um`, `samples` | upper_left, lower_left, upper_right, lower_right |
| `mmi2x2` | `body_width_um`, `body_length_um`, `access_offset_um`, `port_offset_um`, `lead_um`, `transition_um`, `samples` | upper_left, lower_left, upper_right, lower_right |
| `ybranch` | `branch_length_um`, `port_offset_um`, `lead_um`, `samples` | trunk, upper, lower |
| `ring`, `ring-modulator` | `radius_um`, `gap_um`, `lead_um`, `bus_count` | input, through; add, drop for two buses |

Shared keys are `width_um`, `clearance_um` and `port_window_um`. Curved access
guides use normal-offset sampled cubic paths; they are polygonal approximations,
not exact Euler bends. A ring uses an exact annulus and a separate straight bus;
`radius_um` is the centerline radius and `gap_um` is edge-to-edge separation.
The default `bus_count: 1` is a two-port all-pass layout. `bus_count: 2` adds a
second bus with the same width/gap, yielding four ports ordered input, through,
add (upper right), drop (upper left). These are geometry options, not additional
validated device families.
Geometry output includes primitives, semantic groups, bounds, intended union
area, connected-component count and ports. It is a proposal until native readback.

Optional `materials` contains `core_index` and `cladding_index`. Optional `mesh`
contains `core_mesh_um`, `cladding_mesh_um` and `port_mesh_um`; the latter adds
local port-boundary refinement. Default core/cladding mesh maxima are 0.08/0.28
um. The request rejects a port width at or above the second symmetric scalar
slab-mode cutoff because this backend selects one mode per face. This restriction
does not establish single-mode behavior of a physical SOI cross section.

Top-level `measure_mesh_area` defaults to true for rings/modulators and false
for the other families. In `solve`, it additionally records each semantic area
with order-8 integration of 1 on the curved finite-element mesh (`AREA_MESH`).
Rendering-mesh areas (`AREA`) remain available separately. Driven curved-device
calibration requires this independent mesh-area record and keeps the original
area tolerances; `configure` does not produce the solved mesh-area readback.

## Prepare, execute and inspect

Run from the skill checkout; choose fresh bundle and output paths. From an
uninstalled source checkout, use `python -m photonic_workflow.cli` in place of
`photonic` with `PYTHONPATH` pointing to `src`.

Offline preparation uses the core package. Before native execution, install the
`comsol` extra (`python -m pip install 'photonic-workflow[comsol]'`, or
`python -m pip install -e '.[comsol]'` from the checkout) for process supervision,
and supply a licensed COMSOL installation with its matching Java compiler.

```powershell
photonic native list --json
photonic native prepare examples/native-devices/crossing.json --output D:/Research/native-runs/crossing-bundle --json
photonic native verify D:/Research/native-runs/crossing-bundle --json
photonic native run D:/Research/native-runs/crossing-bundle --solver-root "C:/Program Files/COMSOL/COMSOL64/Multiphysics" --timeout 600 --cores 4 --json
```

Set `--solver-root` to the actual installation, or use `PHOTONIC_SOLVER_ROOT`.
`run` verifies the bundle against trusted source generation before compilation,
uses an isolated run directory and returns its `receipt` path. Reuse the task's
existing execution authorization and keep licensed campaigns serial. Run success
remains separate from calibration and physical acceptance.

`stage: "configure"` builds and audits geometry/material/port assignments.
`"modes"` also solves the selected boundary modes and records their effective
indices, phase anchors and normalization powers. `"solve"` additionally drives
every source port at each wavelength in the same built model. Start with the
straight control and the smallest stage that resolves the current question.

Use the actual receipt returned by `run`:

```powershell
photonic native calibrate D:/Research/native-runs/actual-run/receipt.json --output D:/Research/native-runs/crossing-result.json --csv-output D:/Research/native-runs/crossing-s.csv --json
photonic native compare D:/Research/native-runs/crossing-coarse.json D:/Research/native-runs/crossing-fine.json --json
```

Calibration binds unchanged bundle/source/class/console bytes through
the local receipt, checks geometry areas and core ends, selected modes, source
identities and complete wavelength/source/receiver axes. It retains the complete
complex S matrix and signed port/open/absorbed flux per excitation. Inspect
`max_port_flux_modal_gap`, `signed_power_balance`, guided power, open flux and
absorbed power separately; `1-R-T` is not a measured loss decomposition. A local
receipt is provenance, not independently authenticated experimental evidence.

The CSV columns are `wavelength_nm,out_port,in_port,s_real,s_imag`, with every
port pair at every wavelength. S rows are receivers and columns are sources.
Keep returned port order, mode normalization, physical reference planes and
time convention with any circuit import. Raw native numeric-port phases do not
establish alignment across separately built runs. A shared model does not by
itself prove broadband phase continuity, group delay or compatibility with
another component's phase basis.

For mesh comparison, prepare and execute separate requests with the same
geometry, materials, wavelengths and port order but refined mesh settings.
`compare` reports changes in `abs(S)**2`; it does not assert complex-phase
convergence or apply an acceptance tolerance. Also vary port windows, exterior
domain/open-boundary treatment and spectral resolution as the claim requires.
A sparse ring sweep cannot establish resonance linewidth, Q or interpolation.
Calibrated results and mesh comparisons retain `physics_accepted: false`.

## PN-depletion coupling and numerical check

`ring-modulator` uses the same annulus/bus geometry as `ring`. Its `pn` object
accepts positive `reverse_bias_v`, `acceptor_cm3`, `donor_cm3`, electrical domain
widths, temperature, permittivity and declared optical-overlap parameters. The
optical width and junction length default to the ring width and circumference;
explicit values must match them. The active annulus uses the declared zero-bias
real core index plus `delta_n_eff`, and the biased `absolute_k_eff`. Under
`exp(+iwt)` and forward `exp(-i beta L)`, passive index is `n-i*k`.

The standalone PN request is a plain parameter object, as in
`examples/native-devices/pn-depletion.json`; it has no optical request wrapper.

```powershell
photonic native pn-response examples/native-devices/pn-depletion.json --json
photonic native pn-prepare examples/native-devices/pn-depletion.json --output D:/Research/native-runs/pn-bundle --json
photonic native pn-run D:/Research/native-runs/pn-bundle --solver-root "C:/Program Files/COMSOL/COMSOL64/Multiphysics" --timeout 180 --cores 4 --json
photonic native pn-calibrate D:/Research/native-runs/actual-pn-run/receipt.json --json
```

The electrical probe solves prescribed 1D abrupt-depletion charge Poisson and
compares native potential, field and charge quadrature with the analytical
reference. Carrier-to-index conversion uses the 1550 nm Soref–Bennett law,
evaluated locally before averaging with declared uniform optical intensity and
confinement. Optical core saturation is distinct from electrical contact
punch-through; the latter is rejected. Neither this check nor the coupled
scalar optical solve validates drift-diffusion, an SOI rib mode, leakage,
breakdown, contact resistance, RF bandwidth or electro-optic S parameters.
See [pn-ring-model.md](pn-ring-model.md) for assumptions, units, carrier-law
projection, capacitance limits and routes to measured or higher-fidelity input.

## Reuse the Python API

```python
from photonic_workflow.native_devices import load_native_json, native_request
from photonic_workflow.native_backend import prepare_native_bundle, verify_native_bundle

request = load_native_json("examples/native-devices/directional-coupler.json")
geometry, config = native_request(request)
prepare_native_bundle("D:/Research/native-runs/coupler-bundle", geometry, config)
verify_native_bundle("D:/Research/native-runs/coupler-bundle")
```

Use `native_geometry.build_geometry` or `ring_modulator.build_ring_geometry`
for geometry alone, `ring_modulator.depletion_response`/`poisson_reference` for
the declared PN approximation, and `native_pn.prepare_pn_bundle` /
`verify_pn_bundle` for offline electrical preparation. Explicit execution APIs
are `native_backend.run_native_bundle` and `native_pn.run_pn_bundle`; calibration
APIs are `native_devices.calibrate_native_run` and `native_pn.calibrate_pn_run`.
`native_scattering_csv` and `compare_native_meshes` reuse calibrated optical
results. Keep heavy generated models, fields and run directories outside git.
