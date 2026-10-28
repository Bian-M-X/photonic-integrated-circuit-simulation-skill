# Hierarchical Device Composition

Read this reference when a target device contains multiple reusable photonic blocks, when a full-device FEM model is too expensive, or when layout, circuit, and full-wave evidence must stay consistent.

## Feasibility Verdict

It is practical to compose simple devices into a complex photonic device, but no single representation is sufficient:

1. Use parameterized geometry parts for reusable full-wave geometry.
2. Use calibrated multiport S-parameter or compact models for scalable circuit composition.
3. Use a port-aware layout/netlist representation for placement, routing, and connectivity.
4. Promote critical subassemblies to full-wave simulation before making an engineering claim.

Do not interpret circuit-level composition as full-device 3D validation. Do not interpret geometry reuse as automatic reuse of materials, physics, mesh, or calibrated port models.

## Three Composition Layers

### Geometry layer

Use geometry parts or generator functions for waveguides, tapers, bends, directional couplers, MMIs, rings, gratings, phase sections, and transitions.

Each geometry block must expose:

- geometric input parameters;
- named optical ports with positions and orientations;
- named selections for core, cladding, ports, design region, and mesh controls;
- centerline length and reference-plane locations;
- footprint or keep-out region.

COMSOL geometry parts can be instantiated repeatedly and can preserve selections, but part models do not carry materials, mesh, or physics. Rebind those explicitly after assembly and audit the resulting selections.

### Circuit layer

Represent each calibrated block as a wavelength-dependent multiport S matrix. Use the complete complex matrix, not only insertion loss or one transmission coefficient.

The component contract must record:

- ordered port names;
- mode at each port, such as `TE0` or `TM0`;
- wavelength grid and units;
- complex-amplitude normalization;
- time/phase convention;
- reference plane for every port;
- model level: analytic, reduced, 2D EIM full-wave, 3D full-wave, or measured;
- passive/active assumption;
- geometry and process corner represented by the model;
- validation range and known extrapolation limits.

Use `scripts/photonic_assembly.py` for a dependency-light manifest check and dense S-matrix composition. Use SAX, INTERCONNECT, or another circuit engine when gradients, recursive netlists, statistical models, time-domain behavior, or a PDK compact-model library is required.

### Layout layer

Use port-aware placement and routing to produce a hierarchical layout. A layout connection is valid only when these properties match or an explicit transition is inserted:

- layer/cross-section;
- port width;
- orientation;
- polarization and mode;
- process stack;
- minimum bend radius and routing clearance.

Run connectivity extraction and DRC before describing a design as layout-ready. LVS-like agreement means the extracted layout netlist matches the intended circuit netlist; it does not prove optical performance.

## Multi-Fidelity Workflow

### Stage 0: Freeze the device contract

Record the external ports, target band, polarization/modes, process stack, performance metrics, operating corners, and final claim level. Separate paper reproduction from engineering optimization.

### Stage 1: Build a component library

For each component:

1. validate a straight-waveguide and port baseline;
2. build the smallest full-wave model that captures the component physics;
3. sweep the target wavelength range and relevant geometry/process parameters;
4. export the complete complex S matrix with stable port numbering;
5. check passivity, reciprocity where expected, energy balance, mesh sensitivity, and boundary sensitivity;
6. save the component contract next to its S data.

Do not mix S matrices with different mode normalization, phase convention, port reference planes, or wavelength grids without an explicit conversion.

For analytic/reduced screening, `photonic device export` supplies a complete
five-column complex-S CSV and component metadata; see
`executable-device-models.md`. The loader also accepts the composition writer's
sixth, trailing `power` column only when it matches `s_real**2+s_imag**2`
(relative tolerance 1e-9, absolute tolerance 1e-12). This derived column never
replaces amplitudes or supplies missing phase. Unknown columns are rejected.

### Stage 2: Define and validate the assembly

Create `circuits/assembly.json` with:

```json
{
  "schema_version": "1.0",
  "conventions": {
    "wavelength_unit": "nm",
    "sparameter_normalization": "power-wave",
    "time_dependence": "exp(+iwt)"
  },
  "components": {
    "dc": {
      "ports": ["o1", "o2", "o3", "o4"],
      "port_modes": {"o1": "TE0", "o2": "TE0", "o3": "TE0", "o4": "TE0"},
      "model_level": "full-wave-3d",
      "reference_plane": "straight access-waveguide boundary",
      "sparameters": "../components/sparameters/dc.csv",
      "passive": true
    }
  },
  "instances": {"dc1": {"component": "dc"}},
  "connections": [],
  "external_ports": {"in1": "dc1:o1", "in2": "dc1:o2", "out1": "dc1:o3", "out2": "dc1:o4"}
}
```

The CSV format is long-form and complete:

```text
wavelength_nm,out_port,in_port,s_real,s_imag
1550,o1,o1,0.01,0.00
1550,o1,o2,0.00,0.00
...
```

Every wavelength must contain every `(out_port, in_port)` pair. All components in one manifest must currently use the same wavelength grid.

Validate before composition:

```powershell
python scripts/photonic_assembly.py validate circuits/assembly.json
```

### Stage 3: Compose and screen the circuit

Compose the external S matrix:

```powershell
python scripts/photonic_assembly.py compose circuits/assembly.json `
  --output data/processed/circuit_sparameters.csv `
  --summary verification/circuit_summary.json
```

The script connects internal ports as ideal zero-length matched junctions and eliminates them from the block-diagonal component network. Represent routing loss and phase with explicit waveguide/bend/transition components; do not hide them in an ideal connection.

Check:

- expected transfer functions and resonance/fringe positions;
- power sum per independent input;
- maximum singular value for passive networks;
- reciprocity error where expected;
- sensitivity to component and phase variations;
- whether narrow resonances are resolved by the shared wavelength grid.

### Stage 4: Generate layout and extract connectivity

Place the same component instances, route by named ports, and extract a netlist from the layout. Compare instance types, settings, connections, and external ports with the simulation manifest.

Keep layout generation and circuit simulation connected by stable component names and port names. Avoid maintaining two unrelated hand-written netlists.

### Stage 5: Promote critical subassemblies

Select full-wave promotion targets using risk, not visual complexity alone. Promote:

- interfaces with mode or cross-section changes;
- tightly spaced components with electromagnetic cross-talk;
- compound couplers or resonant cells whose behavior depends on routing;
- reflections created by short spacing between nominally independent blocks;
- regions where compact-model and layout assumptions disagree;
- high-sensitivity or high-Q sections.

Compare the promoted subassembly with the circuit prediction over the same band. If error exceeds the declared tolerance, recalibrate the compact model, shift reference planes, or enlarge the full-wave block boundary.

### Stage 6: Optimize and verify corners

Optimize at the cheapest validated fidelity. Re-evaluate winners at higher fidelity and across fabrication, temperature, wavelength, polarization, and drive corners. Preserve nominal, corner, and Monte Carlo results separately.

## Full-Device FEM Decision Rule

Run a complete 2D or 3D full-device model only when at least one is true:

- the device is small enough for a converged solve;
- long-range coupling invalidates block separation;
- radiation channels couple multiple blocks;
- the claim explicitly requires whole-device field evidence;
- circuit/subassembly comparisons show unexplained disagreement.

Otherwise, report a hierarchical verification claim: calibrated components plus circuit composition plus selected full-wave subassembly checks.

## Failure Modes

| Failure | Likely cause | Required response |
|---|---|---|
| Valid layout, wrong spectrum | phase/reference-plane or compact-model error | align conventions and re-export complex S matrices |
| Passive network gains power | incomplete/incorrect S data or normalization mismatch | reject model; audit singular values and normalization |
| Composition is singular | unresolved feedback pole, internal dark state, or invalid ideal connection | inspect topology and internal numerical rank; revise propagation/loss only when physically justified |
| Port mode mismatch | direct connection between incompatible modes | insert a validated transition/mode converter |
| Full-wave subassembly disagrees | block interaction omitted | enlarge calibration block or add a compound model |
| DRC passes but performance fails | geometrical legality is not optical validation | rerun circuit and promoted full-wave gates |

An ideal lossless feedback loop can contain an undetermined internal dark state
even when its external transmission looks finite. A linear solver returning
numbers does not prove uniqueness: roundoff can hide exact singularity. The
circuit composer checks the internal feedback matrix before solving and rejects
numerical rank deficiency at `eps * max(matrix.shape) * largest_singular_value`.
This is a floating-point resolution check, not an accuracy certificate for every
near-resonant network. Keep well-resolved feedback controls and do not insert
arbitrary damping to make a singular test pass. Physically justified loss or
propagation changes define a different model and must be recorded as such.

## Official Technical Basis

- COMSOL 6.4 Port and S-parameter documentation: numeric ports require boundary-mode studies, port sweeps compute complete S matrices, and port names control S-variable and Touchstone naming.
- COMSOL Geometry Parts and PartInstance documentation: parameterized parts can be instantiated and retain output selections, while geometry part files do not contain materials, mesh, or physics.
- GDSFactory documentation: components expose ports and connectivity can be extracted into a netlist.
- SAX documentation: component S-parameter models can be connected through flat or recursive netlists and evaluated as a circuit.
- Ansys INTERCONNECT documentation: compound elements can flatten hierarchical circuits or replace them with equivalent scattering data; CML workflows package compact models.

Read `references/source-notes.md` for refreshable links. Verify current vendor documentation before depending on a version-specific API.
