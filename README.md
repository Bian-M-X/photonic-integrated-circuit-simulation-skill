# Photonic Integrated Circuit Simulation

**Build photonic models, run local solvers, and carry the actual complex S matrix into circuits and optimization.**

[简体中文](README.zh.md) · [Quick start](#quick-start) · [Lumerical](#native-lumerical) · [Examples](#real-simulation-examples) · [Documentation](#documentation)

[![Python compatibility](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/python-compat.yml/badge.svg)](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/python-compat.yml)
[![Agent compatibility](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/agent-compat.yml/badge.svg)](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/agent-compat.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`photonic-workflow` is a Python runtime, CLI, MCP server and agent skill for integrated photonics.
It connects reusable geometry and material recipes, native **COMSOL / Ansys Lumerical** runs,
complete complex S parameters, circuit composition, bounded optimization and reproducible evidence.

- **Reuse the engineering work:** shared numeric geometry, material formulas, contracts and circuit tools.
- **Keep solver details explicit:** native objects, modes, boundaries and mesh are built for each backend.
- **Inspect the evidence:** retain every declared source column, raw arrays, model files and artifact hashes.

Package version: **0.8.0 · alpha**. The dual-solver additions below are **Unreleased**; see the [changelog](CHANGELOG.md).
The core works without a commercial solver. Native runs require a separately installed, licensed product.

## Quick start

Requires **Python 3.11+**. Start from a checkout:

```powershell
git clone https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill.git
Set-Location photonic-integrated-circuit-simulation-skill
python -m pip install -e .
photonic --version
```

Create and compose the bundled MZI example without opening a solver:

```powershell
photonic init demo-mzi --device-family mzi --json
photonic check --project-root demo-mzi --json
photonic circuit validate demo-mzi/circuits/assembly.json --json
photonic circuit compose demo-mzi/circuits/assembly.json `
  --output demo-mzi/data/processed/circuit_sparameters.csv `
  --summary demo-mzi/verification/circuit_summary.json --json
photonic status --project-root demo-mzi --json
```

The output is a complex circuit S matrix and a composition summary. These deterministic
analytic fixtures exercise the runtime; they are not full-wave or fabricated-device evidence.
Use a new project/output directory when repeating commands.

To use the agent skill, install the checkout in your agent's discovered skills directory.
Its `SKILL.md` entrypoint is [the operational router](SKILL.md). The skill name is `photonic-integrated-circuit-simulation`;
the package and console command remain `photonic-workflow` and `photonic`.

## Native Lumerical

Install the small runtime extra; it does not install Ansys products or licenses:

```powershell
python -m pip install -e ".[lumerical]"
photonic lumerical discover --install-root D:/Path/To/Lumerical --json
photonic lumerical plan examples/lumerical/device-coupler.json `
  --install-root D:/Path/To/Lumerical --json
```

Run the declared four-port optical device, inspect the retained source sweep and export it:

```powershell
photonic lumerical run examples/lumerical/device-coupler.json `
  --output runs/coupler-001 --install-root D:/Path/To/Lumerical `
  --local-license --threads 2 --timeout 300 --json
photonic lumerical inspect-result runs/coupler-001/receipt.json --json
photonic lumerical device-export runs/coupler-001/receipt.json `
  --output coupler.csv --project-root runs/circuit-data-001 --json
```

Replace the installation placeholder. `--local-license` uses this computer's existing
license manager temporarily when needed; a configured running service can be used without
that flag. It does not need external Internet. License files, service settings and proxy
configuration are left unchanged. Licensed runs are serial by default.

Each declared input port is actually excited. The output keeps native `.fsp` models,
raw per-source arrays, a complete selected-mode S matrix, modal checks and hash receipts.
CSV export preserves the complex values and original JSON bytes, with channel conventions
and reference planes alongside the data. See [the complete-device workflow](references/lumerical-device-workflow.md).

The example is a **2D scalar-index surrogate**, not a calibrated 3D SOI stack.
An explicit 3D route is available and a 3D straight control has been exercised.
Geometry parameters use μm; optical request fields ending in `_m` use metres.

From a checkout with an older installed console script, use
`./scripts/invoke-lumerical.ps1` in place of `photonic lumerical`.
Run `photonic lumerical --help` for all 11 commands, including data import and matched-mesh comparisons.

## Real simulation examples

These images come from native Lumerical DFT field monitors, not drawn field patterns.

| Directional coupler · 1548.39 nm | Add-drop ring · 1573.77 nm |
|---|---|
| [![Native directional-coupler electric field](docs/images/lumerical/coupler_field.png)](docs/images/lumerical/coupler_field.png) | [![Native add-drop-ring electric field](docs/images/lumerical/ring_field.png)](docs/images/lumerical/ring_field.png) |

Both are **2D scalar** diagnostics. Each color scale is normalized to its own maximum
`|E|²`; colors across images do not represent equal absolute power. The ring reached its
**3 ps finite time window**, so the image does not establish resonance, Q or steady-state convergence.
The monitors were added to model copies; the corresponding native source-column S values
remained unchanged. [Device test report](docs/research/lumerical-device-workflow-2026-10-29.md).

Earlier COMSOL results remain available:

- [2D Hadamard inverse-design case and numerical verifier](docs/showcases/hadamard-2d/README.md).
- [SOI Euler-coupler field gallery and 50:50 case](docs/legacy-readme-en.md#euler-splitter).
- [Native passive-device and PN benchmark records](docs/research/native-library-v08.md).

## What is shared, and what is native?

| Layer | Available today | Evidence or boundary |
|---|---|---|
| Solver-free core | Project contracts, analytic device models, complex-S circuits, audits and provenance | No commercial runtime required |
| Geometry and materials | Seven optical device families; six numeric recipes; Li silicon / Malitson silica formulas | Native construction and sampled-material fitting are checked separately |
| COMSOL | Native device runs/calibration, PN-Poisson controls and existing adjoint examples | Product- and model-specific evidence retained |
| Lumerical | MODE/FDTD diagnostics, all-source device matrices, export, power comparison and bounded candidate evaluation | Seven optical footprints; one selected mode per physical port |
| Recipe backends | Canonical JSON for all six recipes; COMSOL Java; Lumerical LSF for circular/Euler geometry | Geometry rendering does not solve fields |
| MCP | **18 tools / 43 resources** for discovery, planning, recipes, inspection, export, circuits and evidence | No solver or arbitrary-shell execution through MCP |
| Cross-solver controls | Matched scalar straight/coupler benchmark plans and receipt-bound power comparison | No implicit phase alignment or universal accuracy/speed claim |

The existing COMSOL PN and adjoint paths and its multiphysics guidance are retained. They have not been
converted into native CHARGE/HEAT/EME/INTERCONNECT or a Lumerical adjoint execution path.
The `ring-modulator` FDTD family currently builds its **optical footprint**, not a voltage-driven PN model.
See the [capability mapping](docs/research/lumerical-capability-matrix-2026-10.md) and [dual-solver workflow](references/dual-solver-workflows.md).

## Reuse a recipe

Discover the versioned catalog and render the same numeric geometry for Lumerical:

```powershell
photonic recipe list --json
photonic recipe inspect geometry.symmetric-euler-bend --json
photonic recipe render geometry.symmetric-euler-bend `
  --input examples/recipes/symmetric-euler-bend.json `
  --renderer lumerical-lsf-fragment --instance-id euler-main `
  --height-um 0.22 --core-index 3.476 `
  --output generated/euler-main.lsf --project-root . --json
```

Height and index are explicit target settings. Circular routes use analytic native ring
sectors; Euler geometry preserves the canonical sampled boundary polygon. A fragment supplies
geometry, not cladding, PML, modes or a qualified device. Material and port-window recipes
retain their numeric output where a native script would change their meaning.
[Recipe contracts, Python API and renderer limits](references/modeling-recipes.md).

## Use MCP with the same data

Start the stdio server with explicit readable and writable roots:

```powershell
photonic-mcp --read-root D:/Path/To/Project `
  --read-root D:/Path/To/Lumerical --write-root D:/Path/To/Project/runs
```

Connect that command through your MCP client's stdio configuration. The server shares
the package services and includes read-only reference documents in the installed wheel.
Restart a running server after upgrading to refresh its tool and resource catalog.

| Task | MCP tools |
|---|---|
| Reuse a recipe | `list_recipes`, `inspect_recipe`, `render_recipe` |
| Prepare Lumerical work | `discover_lumerical_install`, `plan_lumerical_run` |
| Inspect/export actual results | `inspect_lumerical_result`, `compare_lumerical_results`, `export_lumerical_result` |
| Consume the matrix | `validate_circuit`, `compose_circuit`, `validate_contract` |
| Inspect project evidence | `inspect_project`, `gate_status`, `audit_project_artifacts` |

Actual licensed execution remains an explicit local CLI action. MCP's compatibility-named
`run_java_batch` renders a plan only. A result inspection verifies artifacts; it does not
promote a physics gate. [MCP configuration and adoption boundary](references/comsol-mcp-evaluation.md).

## Compare, optimize and verify

Freeze a common benchmark before examining paired results:

```powershell
photonic lumerical plan-benchmark straight --power-tolerance 0.03 --json
photonic lumerical compare-solvers COMSOL_RECEIPT.json LUMERICAL_RECEIPT.json `
  --power-tolerance 0.03 --json
photonic lumerical optimize-step examples/lumerical/device-optimization.json `
  --output runs/coupler-opt-plan-001 --json
```

Receipt arguments above are placeholders. Comparisons require matched geometry, material,
channels, model level and wavelength grid. The tolerance is declared before solving;
failed comparisons are retained. Power agreement does not prove cross-solver phase agreement.
Optimization writes a plan by default; `--execute` evaluates one actual budgeted candidate.

Local evidence includes **16 device evaluations / 51 source columns**, two actual candidate
evaluations with history resume, and **3 native LSF CAD cases / 114 property checks**.
These are bounded diagnostics, not acceptance of every device or backend.
The latest unified-tool tests, paired results and unresolved discrepancies are recorded in
[the implementation report](docs/research/lumerical-unified-tools-2026-10-30.md).

For development checks:

```powershell
python -m pip install -e ".[dev,lumerical]"
python -m pytest -q
python -m ruff check src tests scripts
python scripts/test_skill_metadata.py
./scripts/sync-packaged-skill-resources.ps1
```

CI checks code, contracts, resource mirrors, packaging and installed-wheel behavior.
Licensed evidence is recorded separately; see [maintenance and compatibility](docs/maintenance.md).

## Documentation

| Need | Start here |
|---|---|
| Agent routing and tool selection | [Skill entrypoint](SKILL.md) · [Tool selection](references/tool-selection.md) |
| Shared engineering process | [Engineering workflow](references/engineering-workflow.md) · [Dual-solver mapping](references/dual-solver-workflows.md) |
| Lumerical execution and devices | [Installation / diagnostics](references/lumerical-workflows.md) · [Complete devices](references/lumerical-device-workflow.md) |
| COMSOL execution and physics | [Environment / runner](references/environment-and-runner.md) · [Ports and wave optics](references/wave-optics-port-models.md) |
| Reusable numeric building blocks | [Modeling recipes](references/modeling-recipes.md) · [Executable device models](references/executable-device-models.md) |
| Circuits and quantum photonics | [Hierarchy](references/hierarchical-device-workflow.md) · [Quantum knowledge base](references/quantum-photonic-knowledge-base.md) |
| PN and inverse design | [PN ring model](references/pn-ring-model.md) · [COMSOL adjoint](references/comsol-adjoint-inverse-design.md) |
| Advanced integrations | [MATLAB](docs/architecture/matlab-integration.md) · [PDK models](docs/architecture/pdk-model.md) · [Adapter contracts](docs/architecture/adapter-contract.md) |
| Reproducibility and changes | [Maintenance](docs/maintenance.md) · [Changelog](CHANGELOG.md) · [Historical README](docs/legacy-readme-en.md) |

For an issue or contribution, include the request, model level, expected behavior,
actual result and a small reproducible case. Keep license files, credentials, private PDKs
and proprietary solver projects outside public contributions.

**MIT licensed.** This independent project includes no commercial solver or license.
COMSOL, MathWorks and Ansys product names identify optional integrations, not affiliation or endorsement.
See [source notes](references/source-notes.md) and [legal notes](references/legal-and-trademark-notes.md).
