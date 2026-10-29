# Tool Selection and Capability Discovery

Use this reference to choose an execution surface or assess an optional tool.
The assistant can write and inspect model source directly; the runtime provides
reliable domain operations where their contracts fit the task.

## Choose by the operation

| Need | Preferred surface | Verify before relying on it |
|---|---|---|
| Explain or patch a supplied artifact | Read/search the artifact and relevant reference; edit source directly | Assumptions, units, actual model stage; no project runtime required |
| Inspect a tracked project | `photonic status --project-root <project> --json` or MCP `inspect_project` | Correct project, source run, artifact integrity and claim limits |
| Geometry/material/port/S diagnostic recipe | MCP `list_recipes` -> `inspect_recipe` -> `render_recipe`; CLI `photonic recipe` is equivalent | Exact version, parameter units/limits, supported renderer, recipe claim boundary |
| Validate/compose complex S networks | MCP `validate_circuit`/`compose_circuit` or CLI `photonic circuit` | Complete matrices, conventions, grid, connections and applicability |
| COMSOL model construction and solve | Reviewed Java source plus `scripts/invoke-waveguide-java-batch.ps1` | Dry-run plan, compiler/batch availability, authorized budget and resulting artifacts |
| Lumerical discovery, native diagnostic solve or model/data migration | `photonic lumerical` and [lumerical-workflows.md](lumerical-workflows.md) | Matched installation/API, product license, geometry/material readback, complete complex data and declared diagnostic scope |
| Lumerical discovery/planning and saved-result processing through MCP | `discover_lumerical_install`, `plan_lumerical_run`, `inspect_lumerical_result`, `compare_lumerical_results`, `export_lumerical_result` | Explicit read/write roots; these share CLI services and never start a vendor process |
| Compare COMSOL and Lumerical under one physical question | `photonic lumerical plan-benchmark` / `compare-solvers`; [dual-solver workflows](dual-solver-workflows.md) | Same geometry, model level, material, channels and spectral grid; retain a declared budget and failed configurations |
| Diagnose MATLAB integration | CLI `photonic matlab check`, `doctor`, `plan`; installed MATLAB tools if available and authorized | Local version, products, session identity, wrapper/result parity |
| Live COMSOL state, plotting, GUI inspection | Available vendor API or computer-use tool suited to the task | Current model/dataset, session ownership, supported host; do not assume a GUI-control tool exists |
| Find an optional integration | Discover current tools first, then consult the primary sources below | Tool callable now vs documented, environment/license vs physics acceptance |

Paths in examples are placeholders; resolve the skill root and user project
explicitly. Do not run package commands in an unrelated working directory.
For a source checkout without an installed console script, a configured Python
environment can use `python -m photonic_workflow.cli`; check its dependencies first.

MCP `render_recipe` takes an absolute `request_file` and `output` path. It
evaluates an exact-version strict JSON request and writes a new canonical JSON
artifact, a fixed `comsol-java-fragment` with `instance_id`, or supported
`lumerical-lsf-fragment` geometry with an explicit instance, height and index. It returns a
compact receipt with hash, byte count and claim limits, leaving arrays/code in
the file. It refuses overwrites and output symlinks/junctions. It neither
compiles nor solves nor changes gates. If the host exposes an older server,
use the CLI recipe route; do not invent tool names or claim the server updated.

For MCP protocol and roots, read [comsol-mcp-evaluation.md](comsol-mcp-evaluation.md).
Tool annotations describe side effects; they are hints, not authorization or
security enforcement. The existing plan-only boundary remains enforced in code.

## Focused tool survey

Primary-source refresh: **2026-09-05**. `DOC-VERIFIED` below means the linked
project/vendor documentation was read. All optional integrations remain
`LOCAL-UNVERIFIED` and `PHYSICS-UNVERIFIED` in this survey. Host discovery and
task-specific tests must establish stronger status. The recommendations are
engineering choices based on those documented capabilities, not benchmarks.

| Candidate and source | Useful addition | Adoption decision |
|---|---|---|
| [MathWorks MATLAB MCP Server](https://github.com/matlab/matlab-mcp-server) | Official MATLAB execution/code-analysis interface; supports custom tools | First candidate for MATLAB-heavy interactive work. Use task-scoped sessions and reviewed operations. Its general code execution is broader than this package's fixed adapters; it does not inherit their guarantees. No installation or licensed session is implied. |
| [GDSFactory/gplugins](https://gdsfactory.github.io/gplugins/) and [SAX guide](https://gdsfactory.github.io/gplugins/notebooks/sax_01_sax/) | Layout-to-solver adapters, mode solvers, EME and differentiable circuit simulation | Select the backend needed by a real workflow. Existing optional extras/descriptors are starting points, not working executors. SAX circuit gradients are not a native COMSOL full-wave adjoint. |
| [MPh](https://github.com/MPh-py/MPh) | Community Python/JPype wrapper for COMSOL model manipulation, evaluation and export | Optional for repeated Python-driven inspection. It is vendor-independent and still requires COMSOL. Establish lifecycle, API compatibility and direct-batch parity before treating it as an accepted execution route. |
| [Tidy3D through gplugins](https://gdsfactory.github.io/gplugins/notebooks/tidy3d_00_tidy3d/) | Optional cloud FDTD and component S-parameter workflows | Relevant when cloud execution is requested. Verify data-transfer authorization and cost before submission; an installed client is not a free solver entitlement. |
| [Meep/MPB installation notes](https://gdsfactory.github.io/gplugins/#non-pip-plugins) | Open FDTD/mode checks on an independently qualified backend | Windows route needs a suitable WSL/conda environment. Add only when the cross-check warrants the environment and convergence work. |

The official MATLAB repository now redirects from `matlab-mcp-core-server` to
`matlab-mcp-server`. Resolve the current release documentation when configuring
it instead of persisting a guessed executable or tool schema. COMSOL community
MCP wrappers likewise need provenance checks; an MCP label does not establish
vendor support or improve solver accuracy.

Do not install a broad plugin bundle solely to increase tool count. A useful
addition removes a repeated task or supplies an independent validation path.
Record version, selected capability, bounded inputs/outputs, expected evidence,
failure behavior, and a minimal fixture before adopting an executor.

## Runtime and integration development

These documents are for package/integration work, not ordinary model diagnosis.
Paths below are relative to the skill repository root. A wheel's MCP reference
mirror does not include the developer `docs/` tree; use a reviewed source
checkout when these documents are needed, rather than assuming an MCP URI.

| Development topic | Repository document |
|---|---|
| CLI, run lifecycle, implementation phases | `docs/architecture/runtime-design.md`, `docs/roadmap.md` |
| Contracts, design intent, adapters | `docs/architecture/adapter-contract.md`, `docs/architecture/design-intent.md` |
| Third-party descriptor providers | `docs/providers/authoring-third-party-adapter.md` |
| PDK and compact-model lifecycle | `docs/architecture/pdk-model.md`, `docs/architecture/compact-model-lifecycle.md` |
| MATLAB contracts and security | `docs/architecture/matlab-integration.md`, `docs/architecture/matlab-security.md` |
| Provenance, migrations and compatibility | `docs/architecture/provenance.md`, `docs/migration.md`, `docs/maintenance.md` |
| PDK-first / layout-first / custom-device workflow | Corresponding file in `docs/workflows/` |
| MATLAB layout, optimization, COMSOL, Lumerical or measurement | Matching `matlab-*.md` in `docs/workflows/` |
| Broader tool/license research | `docs/research/tool-landscape.md`, `docs/research/matlab-tool-landscape.md`; these retain their original snapshot dates |

Use JSON CLI output for machine work. Exit codes remain: invalid input 2,
unavailable 3, incompatible 4, execution failure 5, acceptance rejection 6,
security violation 7, timeout 8. A provider descriptor or dependency import
does not prove an executor exists; retain existing Phase A/B/C adoption gates.
