<a id="top"></a>

<p align="center">
  <img src="docs/images/readme/hero.svg" alt="Photonic Integrated Circuit Simulation — conceptual waveguide illustration" width="100%" />
</p>

<h1 align="center">Photonic Integrated Circuit Simulation</h1>

<p align="center">Explore photonic ideas with your agent, one model and one piece of evidence at a time.</p>

<p align="center">
  <strong>English · <a href="README.zh.md">简体中文</a></strong>
</p>

<p align="center">
  <a href="https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/python-compat.yml"><img src="https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/python-compat.yml/badge.svg" alt="Python compatibility" /></a>
  <a href="https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/platform-compat.yml"><img src="https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/platform-compat.yml/badge.svg" alt="Platform compatibility" /></a>
  <a href="https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/agent-compat.yml"><img src="https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/agent-compat.yml/badge.svg" alt="Agent compatibility" /></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.11%2B-9a765a?logo=python&amp;logoColor=white" alt="Python 3.11 or newer" /></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/0.7.0-alpha-71866b" alt="Version 0.7.0 alpha" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-bd795d" alt="MIT License" /></a>
</p>

<p align="center">
  <a href="#overview">Overview</a> · <a href="#install">Install</a> · <a href="#quick-start">Quick start</a> · <a href="#showcases">Showcases</a> · <a href="#workflow">Workflow</a> · <a href="#cli">CLI</a> · <a href="#integrations">Integrations</a> · <a href="#updates">Updates</a> · <a href="#docs">Docs</a>
</p>

---

<a id="overview"></a>

## What This Project Is

`photonic-workflow` is an installable local runtime and agent skill for
auditable photonic-integrated-circuit design closure. It connects design
intent, component and compact-model contracts, complex S-parameter circuits,
layout/netlist comparisons, bounded solver plans, optimization, packaging,
tapeout, measurement, provenance, and evidence gates.

The repository and skill use the name **Photonic Integrated Circuit Simulation**;
the runtime remains solver-agnostic. COMSOL, MATLAB, Lumerical, layout/PDK tools, instruments, and
remote services are bounded adapters; this project does not replace an
electromagnetic solver, foundry signoff, calibrated measurement, or engineering
judgment.

| Agent skill | Python package | CLI |
|---|---|---|
| `$photonic-integrated-circuit-simulation` | `photonic-workflow` | `photonic` |

| What would you like to do? | Start here |
|---|---|
| Try the local workflow without a commercial solver | [Install the core](#install) → [MZI quick start](#quick-start) |
| Give Codex access to the skill | [Install the agent skill](#agent-skill) → [Skill entrypoint](SKILL.md) |
| Inspect inverse design and simulation evidence | [2D Hadamard](#hadamard) · [SOI Euler splitter](#euler-splitter) |
| Connect existing tools or projects | [MCP, MATLAB, and solvers](#integrations) · [Documentation map](#docs) |

## What Version 0.7.0 Provides

| Design & modeling | Automation & integration | Verification & provenance |
|---|---|---|
| PIC / PDK contracts, complex S-parameter circuits, reusable geometry recipes | Local CLI, 13 MCP tools, bounded external-tool plans | G / M evidence gates, provenance, SHA-256 artifact audits |

The current update adds seven executable complex-S models: straight waveguide,
directional coupler, all-pass ring, add-drop ring, uniform Bragg reflector,
ideal 2×2 MMI and ideal Y branch. These are analytic/reduced models with declared
indices, coupling and losses; they do not calculate those inputs from geometry.
Both ring variants belong to one device family. Use them for screening and
circuit composition, with [model assumptions and examples](references/executable-device-models.md).

[Readback diagnostics](references/executable-diagnostics.md) check geometry,
complete source columns and phase conventions. The separate
[COMSOL canary](examples/comsol-device-canary/README.md) includes bounded native
straight/taper tests in a 2D scalar bulk-index surrogate and a geometry-only
Euler-bend probe. The straight/taper receiver-flux/modal-power discrepancy remains
unresolved, so near-unity target-mode transmission is not a qualified loss result.
The default closed-interpolation bend shows about 0.52 nm contour deviation,
exceeding its probe's 0.1 nm target; no bend mode or field solve ran. That precision target is
specific to the probe; the deviation alone does not establish a performance failure.
Native crossing, geometry-calibrated MMI/Y and broader device qualification remain future work;
see the [capability record and next priorities](docs/research/device-family-roadmap-2026-10.md).

<details>
<summary><strong>Full capability map and status definitions</strong></summary>

| Surface | Current role |
|---|---|
| Installable core | Click CLI, Pydantic contracts, NumPy circuit composition, project configuration, run store, provenance, artifact audit, and G0-G8/M0-M4 ledgers |
| PIC and PDK contracts | Design intent, devices, ports, components, netlists, layouts, PDK/technology/corner models, model cards, packaging, test, tapeout, and measurement records |
| Circuit compatibility | Legacy `assembly.json` 1.0 and long-form complex S-parameter CSV validation/composition |
| Executable device screening | Seven parameterized analytic/reduced models, complete complex S matrices and CSV reuse in circuits; geometry, scattering and phase diagnostics |
| Reusable modeling recipes | Versioned, fail-closed circular/Euler geometry, segmented port windows, bulk material dispersion, and common-basis two-port diagnostics distilled from reviewed LT-aMZI workflows |
| External backends | Capability probes and bounded plans; commercial execution remains separately authorized and test-gated |
| MATLAB | Phase A check, inventory, plan, controlled-wrapper, result, and Engine-probe surfaces; real local smoke belongs to Phase B |
| MCP | Dependency-light stdio JSON-RPC transport whose manifest enumerates all registered skill resources and 13 narrow tools; no solver, MATLAB, instrument, or arbitrary-shell execution |
| Legacy entry points | Existing Python and PowerShell commands remain compatibility entry points while package-service parity is regression-tested |
| Research record | Official/project-maintained source surveys for PIC and MATLAB tools with explicit local and physics verification boundaries |

Implementation and local availability are reported separately:

- implementation: `implemented`, `experimental`, `planned`, or `unverified`;
- availability: `available`, `unavailable`, `incompatible`, or `unverified`.

Neither field is a device gate. Only inspected evidence can change a G or M
gate.

</details>

<a id="install"></a>

## Install

Python 3.11 or newer is required. Install the solver-independent core from a
reviewed checkout:

```powershell
git clone https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill.git
Set-Location .\photonic-integrated-circuit-simulation-skill

python -m pip install -e .
photonic --version
```

<details>
<summary><strong>Optional dependencies and installation scope</strong></summary>

The core installs only Click, Pydantic, and NumPy. Optional extras describe
integration families; they do not download commercial products, licenses,
PDKs, MATLAB toolboxes, or instruments:

```powershell
python -m pip install -e ".[layout,circuit,sparams]"
python -m pip install -e ".[dev]"
```

Install optional dependencies only for an approved local workflow and review
their licenses independently. The `all` extra intentionally includes only
redistributable Python packages listed in `pyproject.toml`; it is not a
complete PIC environment.

</details>

<a id="agent-skill"></a>

### Install the agent skill

To install the Codex skill itself, place this repository under a discovered
skills directory such as:

```powershell
$SkillRoot = Join-Path $env:USERPROFILE '.codex\skills\photonic-integrated-circuit-simulation'
git clone https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill.git $SkillRoot
```

Restart Codex or open a new task after changing skill discovery locations.

<a id="quick-start"></a>

## Five-Minute Solver-Free Start

Create an MZI project, validate it, and inspect its fail-closed status:

```powershell
$ProjectRoot = Join-Path $env:TEMP 'photonic-mzi-demo'

photonic init $ProjectRoot --device-family mzi --json
photonic check --project-root $ProjectRoot --json
photonic circuit validate "$ProjectRoot\circuits\assembly.json" --json
photonic circuit compose "$ProjectRoot\circuits\assembly.json" `
  --output "$ProjectRoot\data\processed\circuit_sparameters.csv" `
  --summary "$ProjectRoot\verification\circuit_summary.json" `
  --json
photonic status --project-root $ProjectRoot --json
```

The bundled fixtures are deterministic analytic examples. They exercise
contracts and network composition; they are not a qualified PDK, fabricated
device, or full-wave validation.

<details>
<summary><strong>Initialization profiles and project contracts</strong></summary>

Available initialization profiles are:

- `pdk-first`;
- `layout-first`;
- `custom-device-first`;
- `matlab-legacy-layout`;
- `matlab-assisted-design`.

`photonic.toml` records runtime policy and aliases. Physical geometry,
materials, modes, topology, boundary conditions, objectives, and acceptance
thresholds belong in versioned design and run contracts.

</details>

<a id="showcases"></a>

## Showcases

These cases use the repository's existing design images, field plots, and numerical records. Each declares its own model level and acceptance scope.

<a id="hadamard"></a>

### Illustrated example: 2D Hadamard inverse design

A 1.3 × 1.3 µm binary design passed **19 locked-mask COMSOL checks and 13
convergence comparisons** on 2026-10-10, followed by an independent raw-matrix
audit. The model is a **2D bulk-index surrogate** with 400 nm access guides.
Its scope is seven sampled wavelengths and the declared engineering gates;
3D SOI performance, fabrication and experimental process tomography require
additional evidence.

| Frozen binary design | Field preview at 1550 nm |
|---|---|
| ![Frozen binary Hadamard-equivalent geometry](docs/showcases/hadamard-2d/figures/design.png) | ![Normalized center-wavelength field preview](docs/showcases/hadamard-2d/figures/field-linear.png) |

| Metric | Nominal center | Worst of 19 checks | Fixed gate |
|---|---:|---:|---:|
| Minimum target-port throughput over all logical inputs, `eta_all` | 0.9475064821 | **0.9246576286** | ≥ 0.9 |
| Minimum six-state conditional fidelity, `F6` | 0.9999822474 | **0.9995299555** | ≥ 0.987 |

The fixed target is `U = [[1,i],[i,1]] / sqrt(2)`. With the declared phase matrix
`D = diag(1,-i)`, `D U D = H`; no port phases were fitted to the simulation.
Conditional fidelity and Choi overlap are distinct from the paper's
experimental process fidelity, and throughput is reported separately.

<details>
<summary><strong>Spectrum and sampling at seven discrete wavelengths</strong></summary>

![Performance at seven computed wavelengths](docs/showcases/hadamard-2d/figures/spectrum-discrete.png)

The spectrum shows computed points without interpolation: five training
wavelengths and two held-out wavelengths, 1543.3 and 1572.3 nm. All plotted
points use a 20/80 nm core/cladding mesh; the nominal center below uses 25/100 nm.
The field image is a normalized propagation preview; numerical records supply
the power and phase metrics.

</details>

<details>
<summary><strong>Optimization budget, workflow, and numerical replay</strong></summary>

![Budgeted native inverse-design workflow](docs/images/showcase/hadamard-workflow/workflow.png)

The default budget is six gradient jobs, five continuation jobs, at most six
binary threshold trials and nineteen reserved checks: at most **36 native
jobs**. Each job can contain many frequency and linear solves. The new default
was checked against the observed successful lineage; a fresh one-command
end-to-end native run of that default was not performed.

From an installed checkout, verify the public numerical bundle without
starting COMSOL:

```console
python docs/showcases/hadamard-2d/verify.py
python docs/showcases/hadamard-2d/plot_spectrum.py
```

This recomputes numerical self-consistency; it does not reauthenticate omitted
native files or rerun COMSOL. See the [full case and replay instructions](docs/showcases/hadamard-2d/README.md),
the [native optimization example](examples/comsol-hadamard-inverse/README.md),
and the [illustrated technical report (Chinese)](docs/research/inverse-design-project-report.zh.md).

</details>

<a id="euler-splitter"></a>

### Showcase: Prompt-to-COMSOL SOI Euler 50:50 Splitter

This public-safe test case shows how the skill turns a natural-language request
into an auditable COMSOL model, a coupling-length screen, a fine-mesh result,
and field-image checks. The design is an SOI-based four-port evanescent
directional coupler at 1550 nm. Eight solid Euler interpolation curves route
the 500 nm waveguides into and out of a 200 nm gap; every bend has a 30 degree
turn and a 5.0 um minimum radius.

#### Field result

| Linear field, `ewfd.normE^2` | Log field, normalized `10 log10` scale |
|---|---|
| ![Linear electric-field intensity for the SOI Euler directional coupler](docs/images/showcase/soi-euler-50-50/field-linear.png) | ![Log-scale electric-field intensity for the SOI Euler directional coupler](docs/images/showcase/soi-euler-50-50/field-log.png) |

The linear view shows the upper-port excitation coupling into two guided
outputs. The log view exposes weak background radiation and was checked against
the explicitly integrated open-boundary flux; it is not used by itself as proof
of device qualification.

**Collected-output split: 48.5839% / 51.4161%.** The selected 2.50 µm coupling length meets this case's 50:50 ±2 percentage-point target.

> **Claim boundary:** this is a single-input, single-wavelength, preliminary
> 2D EIM engineering result. Full component qualification remains blocked until
> a same-model four-input complex S-matrix sweep, wavelength bandwidth,
> and boundary/PML sensitivity are supplied. Fabrication-robustness and physical
> 3D-stack claims additionally need the relevant corners and 3D validation.
> The committed images and summary are a sanitized reported showcase, not a
> reproducible G8 evidence package. Local Java sources, solver logs, and raw
> tables are not implied to be public artifacts.

<details>
<summary><strong>Test configuration and original prompt</strong></summary>

| Test item | Value |
|---|---|
| Model | `GPT-5.6sol high` |
| Skill (at test time) | `$photonic-waveguide-optics` |
| Solver | COMSOL Multiphysics 6.4.0.293, Electromagnetic Waves, Frequency Domain |
| Platform | 220 nm SOI context; 2D effective-index model (EIM) |
| Wavelength | 1550 nm |
| Selected coupling geometry | 0.20 um edge-to-edge gap; 2.50 um parallel coupling length |
| Evidence level | Preliminary fine-mesh 2D EIM result at one wavelength |

The original test prompt is reproduced verbatim. The local skill path is part
of that prompt; readers should replace it with their own installation path.

```text
[$photonic-waveguide-optics](C:\\Users\\lenovo\\.codex\\skills\\photonic-waveguide-optics\\SKILL.md) 请使用此skill套件利用comsol给我一份SOI基础的回转半径5um的欧拉弯在1550nm波长下形成的50:50分束器的仿真，建议使用倏逝场耦合方案，最终给出场图
```

</details>

<details>
<summary><strong>Fine-mesh metrics, length screen, and audit process</strong></summary>

#### Final fine-mesh result

| Metric | Result |
|---|---:|
| P3 transmission, `T31` | 0.485296 |
| P4 transmission, `T41` | 0.513588 |
| Collected-output split | 48.5839% / 51.4161% |
| Collected power, `T31 + T41` | 0.998884 |
| Collected excess loss | 0.00485 dB |
| Input reflection, `R11` | 5.15e-6 (about -52.88 dB) |
| Open-boundary outward flux | 0.001112 W/m (about 0.111% of input power per metre) |
| Port-mode effective index | 2.22879723 |
| Mesh / frequency-domain DOF | 558,912 triangles / 3,913,885 DOF |

The 2.50 um result meets this test's 50:50 +/- 2 percentage-point acceptance
target. A coarse-to-fine mesh comparison changed the collected upper fraction
by only 0.00327 percentage points.

#### Coupling-length screen at 1550 nm

| Coupling length (um) | `T31` | `T41` | Collected upper fraction | `T31 + T41` |
|---:|---:|---:|---:|---:|
| 1.0 | 0.673455 | 0.325021 | 0.674483 | 0.998476 |
| 2.5, coarse | 0.485277 | 0.513634 | 0.485806 | 0.998911 |
| 4.0 | 0.299400 | 0.699629 | 0.299691 | 0.999029 |
| 10.0 | 0.035454 | 0.963388 | 0.035495 | 0.998842 |

The monotonic transfer from P3 to P4 is consistent with evanescent directional
coupling. The workflow first froze the device contract and acceptance rule,
qualified a straight-waveguide/numerical-port baseline, checked disjoint and
complete port/open-boundary selections, screened coupling length, reran the
selected design on a finer mesh, and audited both field views and power
bookkeeping.

</details>

<a id="workflow"></a>

## Modeling and Evidence Workflow

Use the lowest-cost model that can answer the declared question:

```text
design intent and claim
  -> straight-waveguide and port baseline
  -> independently qualified component models
  -> complete complex multiport S data
  -> validated circuit and sensitivity
  -> port-aware layout and extracted connectivity
  -> selected promoted full-wave checks
  -> robustness and evidence package
  -> test readiness, measurement, correlation, recalibration
```

G0-G8 track design through evidence packaging. M0-M4 are a separate
post-fabrication track:

| Gate | Required evidence |
|---|---|
| `G0` | Device contract and intended claim |
| `G1` | Port and straight-waveguide baseline |
| `G2` | Component qualification |
| `G3` | Assembly contract |
| `G4` | Circuit behavior |
| `G5` | Layout and connectivity |
| `G6` | Promoted full-wave subassembly |
| `G7` | Robustness and optimization |
| `G8` | Reproducible evidence package |
| `M0` | Test readiness |
| `M1` | Raw-data integrity |
| `M2` | Calibrated measurement |
| `M3` | Simulation/measurement correlation |
| `M4` | Compact-model recalibration |

Missing evidence is `blocked`, not pass. A gate pass requires explicit evidence.

<a id="cli"></a>

## CLI Map

Run `photonic <group> --help` for the authoritative command schema.

| Area | Command groups |
|---|---|
| Project and recovery | `init`, `check`, `doctor`, `status`, `inspect`, `report` |
| PDK and device data | `pdk`, `component`, `model`, `sparams`, `variation` |
| Reusable modeling | `recipe list`, `recipe inspect`, `recipe render` |
| Device screening | `device list`, `device evaluate`, `device export` |
| Circuit and layout | `circuit`, `netlist`, `layout` |
| External planning | `solver`, `matlab` |
| Campaigns and release | `optimize`, `package`, `testplan`, `tapeout`, `measurement` |
| Evidence and security | `gate`, `audit` (including `audit diagnostics`) |

<details>
<summary><strong>Backend adoption, JSON responses, and exit codes</strong></summary>

Backend readiness is deliberately separate from device evidence. Initialize,
inspect, and evaluate one backend record at a time:

```powershell
photonic gate adoption list --project-root . --json
photonic gate adoption init matlab-runtime --project-root . --dry-run --json
photonic gate adoption init matlab-runtime --project-root . --json
photonic gate adoption inspect matlab-runtime --project-root . --json
photonic gate adoption record matlab-runtime capability-probe blocked `
  --reason "normal interactive-user probe is pending" `
  --project-root . --json
photonic gate adoption evaluate matlab-runtime --project-root . --json
```

Records live under `verification/adoption/`. Initialization never overwrites an
existing record, and `--dry-run` performs no writes. Pass/fail evidence supplied
to the CLI must be a readable project-relative file; a nonblank reference alone
is not accepted as proof.

JSON responses use a stable envelope with command, status, exit code, data,
warnings, and errors. Important exit codes are:

| Code | Meaning |
|---:|---|
| 0 | success |
| 1 | internal or unclassified failure |
| 2 | invalid input |
| 3 | unavailable capability |
| 4 | incompatible version |
| 5 | execution failure |
| 6 | acceptance rejected |
| 7 | security violation |
| 8 | timeout |

A read-only status command may return code 0 while every evidence gate remains
`blocked`. Execution success and physical acceptance are independent states.

</details>

<details>
<summary><strong>Reusable modeling recipes</strong></summary>

### Reusable Modeling Recipes

The built-in recipe registry turns reviewed LT-aMZI modeling primitives into
stable, inspectable calls without copying project-specific models or claiming
solver acceptance:

```powershell
photonic recipe list --json
photonic recipe inspect geometry.symmetric-euler-bend --json
photonic recipe render geometry.symmetric-euler-bend `
  --input .\examples\recipes\symmetric-euler-bend.json `
  --renderer canonical-json `
  --json
```

Each recipe uses an exact semantic version, explicit units, strict input
validation, deterministic output, and packaged provenance. Only the allowlisted
geometry/port recipes can emit bounded COMSOL Java fragments; rendering is not
solver execution or physics evidence. Each Java fragment also requires an
explicit safe `--instance-id` so multiple MZI arms/routes can coexist without
feature-tag collisions. See `references/modeling-recipes.md`.

</details>

<a id="integrations"></a>

## Tool Integrations

The core works independently. External probes, plans, and execution follow their own integration boundaries.

### Phase Boundaries

The phase labels describe integration maturity, not device acceptance:

- **Phase A — reliable local core:** installable package, contracts, safe
  plans, mock fixtures, run recovery, gates, legacy parity, MATLAB
  check/plan surfaces, thin MCP, and public-CI-safe tests.
- **Phase B — authorized local validation:** licensed `matlab -batch` and
  `matlab.unittest` smoke, optional Engine checks, data round trips, legacy
  layout/FDFD/RF fixtures, and local numerical parity.
- **Phase C — bounded external integrations:** COMSOL LiveLink, Lumerical,
  instruments, Simulink, commercial PDK/tapeout, packaging/test execution,
  measurement correlation, and large or remote optimization after
  backend-specific adoption gates.

Files, descriptors, schemas, product listings, imports, and dry-run plans do
not prove Phase B/C execution. A MATLAB FDFD result is not 3D full-wave
evidence; generated GDS is not foundry DRC signoff; solver convergence is not
measurement correlation.

<details>
<summary><strong>MATLAB</strong></summary>

### MATLAB

MATLAB is optional. The default controlled route is `matlab -batch`; MATLAB
Engine is an optional probe and low-latency route, not the workflow authority.

```powershell
photonic matlab check --json
photonic matlab doctor --json
photonic matlab products --json
photonic matlab toolboxes --json
photonic matlab sessions --json
photonic matlab plan .\runs\example\run_spec.json --project-root . --json
```

Phase A planning accepts only registered entrypoint IDs and constructs argument
arrays around fixed repository-owned MATLAB functions. It does not accept
arbitrary MATLAB code. An absent executable must be reported as structured
`unavailable`; an importable Engine package does not prove a compatible,
licensed, trusted session.

In the Phase A runtime, `matlab run` without `--execute` is another planning
surface; real execution and `matlab test` remain fail-closed Phase B hooks.
When a later version enables an explicitly authorized local Phase B
validation, record MATLAB release, product/toolbox inventory, wrapper and input
hashes, result manifest, expected artifacts, tolerance, and claim limits.
LiveLink, Lumerical, instrument, Simulink, and real tapeout workflows remain
Phase C until their own adoption gates pass.

See `docs/architecture/matlab-integration.md`,
`docs/architecture/matlab-security.md`, and
`docs/research/matlab-tool-landscape.md`.

</details>

<details>
<summary><strong>COMSOL and Other Solvers</strong></summary>

### COMSOL and Other Solvers

Provide your own compatible, licensed installation. The trusted legacy COMSOL
execution path remains the bounded Java API plus batch runner:

```powershell
$env:PHOTONIC_SOLVER_ROOT = 'C:\Path\To\LicensedSolverRoot'

.\scripts\invoke-waveguide-java-batch.ps1 `
  -SolverRoot $env:PHOTONIC_SOLVER_ROOT `
  -JavaFile 'C:\Path\To\ModelSource.java' `
  -OutputFile 'C:\Path\To\OutputModel.mph' `
  -BatchLog 'C:\Path\To\BatchLog.log' `
  -DryRun
```

Review paths, selections, study order, cost, concurrency, expected outputs, and
claim level before removing `-DryRun`. A rendered solver plan is provenance
support, not solver execution or physics evidence.

The official-source tool surveys in `docs/research/tool-landscape.md` and
`docs/research/matlab-tool-landscape.md` distinguish documented capability from
local availability and verified physics.

</details>

<details>
<summary><strong>MCP Surface</strong></summary>

### MCP Surface

`scripts/mcp_photonic_server.py` is a compatibility launcher for the package
transport. The current version exposes:

- resources declared by one authoritative registry: one server manifest, every
  registered reference document, and every bounded agent role contract;
- 13 tools in the development tree: `list_recipes`, `inspect_recipe`,
  `render_recipe`, `list_allowed_roots`, `create_project_scaffold`,
  `audit_project_artifacts`, `parse_sweep_table`, `validate_contract`,
  `inspect_project`, `validate_circuit`, `compose_circuit`, `gate_status`, and
  the compatibility-named `run_java_batch`.

`run_java_batch` renders a redacted dry-run plan only. MCP never exposes
arbitrary shell/Python/MATLAB execution or real solver/instrument execution.
Read roots and write roots are separate; write operations fail when no writable
root is configured. Installed wheels carry a read-only mirror of all MCP
reference and agent resources, so `photonic-mcp` does not depend on the current
working directory or a source checkout. `PHOTONIC_SKILL_ROOT` remains an
explicit override for a reviewed skill tree.

See `references/comsol-mcp-evaluation.md` for the adoption boundary.

The skill entrypoint routes by the requested artifact and loads detailed
qualification guidance only when needed. Recipe tools expose the existing
reviewed numerical catalog through compact discovery and file-based output;
their results do not pass a physics gate. See `references/tool-selection.md`
for CLI fallbacks, optional integrations and primary-source research, and
`docs/research/skill-refactor-review.md` for the refactor assessment.

</details>

<details>
<summary><strong>Legacy Compatibility</strong></summary>

### Legacy Compatibility

Existing interfaces remain supported while business logic moves into the
package:

- `scripts/photonic_assembly.py validate|compose`;
- `scripts/parse-comsol-sweep.py`;
- `scripts/new-photonic-project.ps1`;
- `scripts/audit-simulation-artifacts.ps1`;
- `scripts/invoke-waveguide-java-batch.ps1`;
- `scripts/mcp_photonic_server.py`.

The v1 assembly schema, port order, model-level vocabulary, exact wavelength
grid, long-form complex CSV columns, and six-column composed output remain
compatibility contracts. See `docs/migration.md` before changing an existing
project.

</details>

<a id="updates"></a>

## Release Highlights

**0.7.0 · alpha** — seven executable device baselines, readback diagnostics, native canary helpers, budgeted search, and fabrication-aware inverse-design guidance. The skill is now named `photonic-integrated-circuit-simulation`; package and CLI names remain compatible. See the [changelog](CHANGELOG.md) for the full history.

<details>
<summary><strong>New in 0.6.0: Lower-cost inverse design</strong></summary>

### New in 0.6.0: Lower-cost inverse design

The skill now routes by design representation and measured evaluation cost:
[budgeted search](references/low-cost-optimization.md),
[adjoint and fabrication](references/adjoint-and-fabrication.md),
[multi-fidelity and error budgets](references/multifidelity-and-error-budgets.md),
and [COMSOL performance](references/comsol-performance.md).
The [evidence review](references/inverse-design-evidence.md) separates implemented
tools, published methods and local solver evidence.

`photonic optimize suggest SPEC --trials TRIAL_DIRECTORY --json` proposes one
candidate without running a solver. Failed attempts consume budget; pending
trials block another ask; final validation is reserved. It is a small experimental
single-fidelity GP-EI proposer, not a native adjoint or automated COMSOL campaign.
Run `python examples/optimization/analytic_coupler.py --output NEW_DIRECTORY`
for a matched-budget software experiment. Analytic coefficients are uncalibrated.

The [native Hadamard example](examples/comsol-hadamard-inverse/README.md) adds an
executable COMSOL adjoint/MMA route: a filtered density field, projection and mesh
continuation, a worst-wavelength complex gate objective, binary reconstruction,
and a locked validation campaign. It measures all eight guided-mode source
columns, checks an independent flux contour and incoming-mode normalization,
and keeps solver execution separate from device acceptance. The 0.6.0
[qualified 2D Hadamard showcase](docs/showcases/hadamard-2d/README.md) passed
all 19 locked checks and 13 convergence comparisons on 2026-10-10, with an
independent raw-matrix completion audit. This qualifies the selected binary
bulk-index surrogate at seven discrete wavelengths; it establishes no continuous
band, 3D-stack or fabrication result. Earlier failures and the selected design
lineage remain documented separately from the final validation cost.

The October [fabrication-aware robust design route](references/fabrication-aware-robust-design.md)
and [full-text method assessment](docs/research/literature-methods-2026-10.md)
connect BOSON, PRISM and scalable inverse-design guidance to the existing workflow.
NumPy-only helpers and an [analytic demo](examples/optimization/fabrication_robustness.py)
show how axial sampling misses interactions and averaged wafer images can
underweight bad scenarios. They do not implement either full framework or establish
process-model validity, fabrication yield or new native device acceptance.

One public skill routes to these methods because they share optical conventions,
solver infrastructure and evidence contracts. Independently installed copies
would duplicate those rules. A new family member is justified only when its
invocation, dependencies and behavioral tests can stand alone.
The MCP surface is now 13 tools / 38 resources. Device evaluation is available
through CLI/Python; MCP exposes its reference route, rather than a device-solver tool.
See the [implementation and validation report](docs/research/workflow-upgrade-2026-09.md).

</details>

<details>
<summary><strong>New in 0.5.0: Task-Scoped Engineering</strong></summary>

### New in 0.5.0: Task-Scoped Engineering

The skill starts from the requested model, code or data and loads the relevant
reference. It gives capable agents room to choose useful experiments while
keeping physical claims tied to inspected evidence.

| Work mode | Example | Required process |
|---|---|---|
| `advisory` | Explain FSR, review Java, diagnose a plot | State assumptions; no gate ledger |
| `exploratory` | Run an authorized single-point solve or coarse parameter search | Record settings, outputs and limits; no gate ledger unless the project requires it |
| `evidence` | Accept a reusable S model, calibrated measurement or layout check | Select the claim's acceptance profile and inspect its evidence |

These are skill routing modes, not command-line flags. An unresolved G1 does
not prevent an otherwise authorized diagnostic; a project-specific rule such
as "no optimization before G1" still applies. A successful solve is an
observation, not automatic qualification.

**Engineering gates retained:** port/mode/reference-plane consistency, complete
complex S data for scattering-model reuse, per-input power accounting,
claim-relevant convergence, immutable measurement provenance, and SHA-256-bound
evidence. Passivity, reciprocity, unitarity, 3D comparison and fabrication
corners apply when the declared physics and claim require them. Tolerances come
from the decision and uncertainty budget, not a universal numerical threshold.

**Process reduced:** no universal G0-to-G8 execution sequence, mandatory ledger
for exploration, or G8 package for routine answers/software releases. New
`layout-connectivity` (G0/G5) and `measurement-capture` (M0/M1) profiles accept
narrow claims without implying optical/tapeout or calibrated-measurement
acceptance. Existing profile meanings and persisted gate schemas are unchanged.
Unselected blocked gates are not a global stop signal; record the selected
profiles in the project contract or handoff.

**Tools and structure:** a compact entrypoint, on-demand qualification/tool
references, and three new MCP tools—`list_recipes`, `inspect_recipe`,
`render_recipe`—expose six existing deterministic recipes. The server now has
13 tools and 29 resources in that release. Rendering creates bounded files; it does not execute
a solver. Direct, authorized Java/Python/MATLAB model development remains
available beyond recipe coverage.

Read the [gate definitions](references/verification-gates.md),
[tool-selection guide](references/tool-selection.md), and
[engineering-gate review](docs/research/engineering-gates-0.5-review.md).

</details>

## Validate a Checkout

<details>
<summary><strong>Public-core validation commands and CI scope</strong></summary>

The public core validation deliberately requires no MATLAB, COMSOL, Lumerical,
commercial PDK, instrument, network API, or cloud account:

```powershell
python -m pip install -e '.[dev]'

python -B -m unittest discover -s tests -p 'test_*.py'
python -B .\scripts\update_contract_surface_snapshot.py
python -B .\scripts\test_photonic_assembly.py
python -B .\scripts\test_numeric_tools.py
python -B .\scripts\test_mcp_photonic_server.py
python -B .\scripts\test_skill_metadata.py
.\scripts\test_powershell_safety.ps1
.\scripts\sync-packaged-skill-resources.ps1
.\scripts\sync-packaged-matlab-resources.ps1
ruff check src tests scripts

photonic --version
photonic audit artifacts . --fail-on-issues --json
git diff --check
```

Before committing a new package surface, stage the intended files and run
`git diff --cached --check`; after committing, run `git show --check --oneline
HEAD`. Plain `git diff --check` does not inspect untracked files.

CI also enforces Ruff and skill metadata schemas, runs the full Windows suite
on Python 3.11-3.14, runs
portable-core tests on Ubuntu and macOS, builds the sdist and wheel, installs
the wheel into a clean environment outside the checkout, reads all MCP
resources, validates packaged templates, and runs `pip check`. A version tag
triggers a fresh release build, SHA-256 inventory, and GitHub build-provenance
attestations. See `docs/maintenance.md` for the release sequence.

When the Codex `skill-creator` validation script and PyYAML are available in
the selected environment, also run:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" .
```

Do not install or mutate a global Python environment merely to make an optional
validator available.

</details>

<details>
<summary><strong>What the compatibility badges check</strong></summary>

- **Python compatibility** — lint, generated Java fragment compilation, and the full unit/integration suite on Python 3.11–3.14
- **Platform compatibility** — the same tests on Ubuntu, macOS, and Windows, plus building and installing the packaged wheel in a clean environment
- **Agent compatibility** — skill metadata, agent card structure, and discovery layout for Claude Code, Codex, and ChatGPT

</details>

<a id="docs"></a>

## Documentation Map

`SKILL.md` is the concise operational router. Detailed material lives under
`references/` and `docs/`:

| Need | Read |
|---|---|
| Runtime architecture and phases | [docs/architecture/runtime-design.md](docs/architecture/runtime-design.md), [docs/roadmap.md](docs/roadmap.md) |
| Contracts and adapters | [docs/architecture/adapter-contract.md](docs/architecture/adapter-contract.md), [docs/architecture/design-intent.md](docs/architecture/design-intent.md) |
| Third-party adapter authoring | [docs/providers/authoring-third-party-adapter.md](docs/providers/authoring-third-party-adapter.md) |
| PDKs and compact models | [docs/architecture/pdk-model.md](docs/architecture/pdk-model.md), [docs/architecture/compact-model-lifecycle.md](docs/architecture/compact-model-lifecycle.md) |
| MATLAB integration and security | [docs/architecture/matlab-integration.md](docs/architecture/matlab-integration.md), [docs/architecture/matlab-security.md](docs/architecture/matlab-security.md) |
| Provenance and migration | [docs/architecture/provenance.md](docs/architecture/provenance.md), [docs/migration.md](docs/migration.md) |
| Maintenance and compatibility | [docs/maintenance.md](docs/maintenance.md) |
| Release history | [CHANGELOG.md](CHANGELOG.md) |
| PIC and MATLAB tool research | [docs/research/tool-landscape.md](docs/research/tool-landscape.md), [docs/research/matlab-tool-landscape.md](docs/research/matlab-tool-landscape.md) |
| Workflow profiles | [docs/workflows/](docs/workflows/) |
| COMSOL environment and physics | [references/environment-and-runner.md](references/environment-and-runner.md), [references/wave-optics-port-models.md](references/wave-optics-port-models.md) |
| Source sweeps and complex S matrices | [references/frequency-domain-source-sweeps.md](references/frequency-domain-source-sweeps.md) |
| Device and interferometer workflows | [references/device-family-workflows.md](references/device-family-workflows.md), [references/interferometer-workflows.md](references/interferometer-workflows.md) |
| Reusable modeling recipes and provenance | [references/modeling-recipes.md](references/modeling-recipes.md) |
| Hierarchical composition | [references/hierarchical-device-workflow.md](references/hierarchical-device-workflow.md) |
| Gates and reporting | [references/verification-gates.md](references/verification-gates.md), [references/optimization-and-reporting.md](references/optimization-and-reporting.md) |
| MCP evaluation | [references/comsol-mcp-evaluation.md](references/comsol-mcp-evaluation.md) |
| Sources, licensing, and publication | [references/source-notes.md](references/source-notes.md), [references/legal-and-trademark-notes.md](references/legal-and-trademark-notes.md) |

## Safety, Licensing, and Claims

This repository is an independent workflow aid. It is not affiliated with,
endorsed by, sponsored by, or authorized by COMSOL AB, MathWorks, Ansys, a
foundry, or any other tool vendor. It contains no commercial solver, MATLAB
product, PDK, license file, proprietary model, or vendor dataset. Product and
company names identify optional third-party environments only.

Before publication, remove local paths and usernames, credentials, license
data, instrument addresses, NDA material, proprietary papers/models, `.mph`,
compiled artifacts, raw logs, caches, and unpublished results. Audit the full
artifact tree and review every third-party license. Open-source software does
not grant access to commercial products or foundry PDKs.

The repository's original text and helper code are available under the
[MIT License](LICENSE). Third-party tools, APIs, trademarks, documentation,
models, datasets, and generated artifacts remain subject to their owners'
terms.

---

<p align="center"><a href="#top">Back to top</a> · <a href="README.zh.md">简体中文</a> · <a href="LICENSE">MIT License</a></p>
