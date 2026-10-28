# Reusable Modeling Recipes

Use this reference when a task needs a reviewed geometry, port-window,
bulk-material, or common-basis S-matrix building block without copying a full
device model. Recipes are deterministic Python functions. They do not start a
solver, accept a physical result, or change a G/M gate.

## Contents

- [Public Surfaces](#public-surfaces)
- [Built-In Recipes](#built-in-recipes)
- [Request Contract](#request-contract)
- [CLI Examples](#cli-examples)
- [Python API](#python-api)
- [COMSOL Java Fragments](#comsol-java-fragments)
- [Provenance And Claim Boundaries](#provenance-and-claim-boundaries)
- [Maintenance Rules](#maintenance-rules)

## Public Surfaces

Use one of these stable routes:

```text
photonic recipe list
photonic recipe inspect <recipe-id>
photonic recipe render <recipe-id> --input <request.json>
```

or:

```python
from photonic_workflow.recipes import (
    evaluate_recipe,
    inspect_recipe,
    list_recipes,
    render_recipe,
)
```

The CLI and Python API call the same frozen catalog. Legacy scripts are thin
compatibility launchers and must not carry a second algorithm implementation.

MCP also exposes `list_recipes`, `inspect_recipe`, and `render_recipe`. List
returns compact identities; inspect returns one full parameter/provenance
contract. Render takes an absolute `request_file` and new absolute `output`
under separately allowed read/write roots, plus optional `renderer` and
`instance_id`. The default renderer is `canonical-json`; Java uses the same
fixed renderer and limits as the CLI. A successful render returns an artifact
path, SHA-256, byte count, output field names and claim limits. Read the file
for arrays or source; the response intentionally omits those large payloads.
No project scaffold is required for MCP recipe evaluation. Existing outputs
are never replaced, and output symlinks/junctions are rejected. An older live
MCP server may need a restart; use the CLI if these tools are absent.

## Built-In Recipes

| Recipe ID | Role | Highest code evidence | Explicit boundary |
|---|---|---|---|
| `geometry.circular-route` | tangent points, circle centers, cutbacks, exact centerline length | unit-tested | no bend-loss, mesh, or full-wave claim |
| `geometry.symmetric-euler-bend` | symmetric curvature ramp and interpolation-solid boundary table | unit-tested plus legacy configuration fixture | no qualified component matrix or 3D claim |
| `waveguide.segmented-port-window` | background slabs, exterior port windows, scattering-boundary subtraction, entity-count rules | configuration-audited | no mode identity, power closure, or G1 pass |
| `materials.li-silicon-1980` | Li Eq. 22 bulk crystalline-silicon index and analytic derivative | formula/API-readback subcheck | bulk index is not modal index or foundry data |
| `materials.malitson-fused-silica-1965` | Malitson bulk fused-silica Sellmeier relation | formula/API-readback subcheck | fused silica is a surrogate, not deposited-oxide metrology |
| `scattering.two-port-common-basis` | source-conditioned column mapping, per-input accounting, stable `S^H S` diagnostics | configuration/parser-audited | caller-declared basis is not independent gauge proof; no broadband or convergence claim |

Read `smooth-bend-geometry.md` for geometry construction rules,
`wave-optics-port-models.md` for port and boundary requirements, and
`frequency-domain-source-sweeps.md` before interpreting complex source-sweep
columns.

## Request Contract

Every request is strict JSON:

```json
{
  "schema_version": "1.0",
  "recipe_id": "materials.li-silicon-1980",
  "recipe_version": "1.0.0",
  "parameters": {
    "wavelength_um": 1.55,
    "temperature_k": 293.15
  }
}
```

Rules:

- reject duplicate JSON keys, `NaN`, and infinities;
- reject missing or unknown root and parameter fields;
- require an exact recipe version;
- use the units encoded in parameter names;
- do not silently extrapolate a material formula;
- do not supply Java expressions, model tags, shell fragments, or paths as
  recipe parameters.

Reviewed requests live under `examples/recipes/`. They use synthetic geometry
and scattering values, not private LT-aMZI results.

`recipe inspect --json` returns a structured `parameter_contract` for every
field: name, JSON type, unit, required/default state, numeric or item bounds,
enum, item shape, and description. The same immutable `ParameterSpec` objects
apply defaults and enforce common constraints before recipe-specific
cross-field validation. Request text is limited to 2,000,000 UTF-8 bytes and
64 JSON nesting levels.

## CLI Examples

List and inspect the catalog:

```powershell
photonic recipe list --json
photonic recipe inspect geometry.symmetric-euler-bend --json
```

Evaluate and render canonical JSON without writing a file:

```powershell
photonic recipe render geometry.circular-route `
  --input examples/recipes/circular-route.json `
  --renderer canonical-json `
  --json
```

Preview a fixed COMSOL-compatible Java fragment. This still performs no solver
execution:

```powershell
photonic recipe render geometry.symmetric-euler-bend `
  --input examples/recipes/symmetric-euler-bend.json `
  --renderer comsol-java-fragment `
  --instance-id mzi-upper-arm `
  --output generated/euler-bend.java `
  --project-root . `
  --dry-run `
  --json
```

Remove `--dry-run` only to create the reviewed fragment. The output must remain
inside the configured project root, may not traverse a symlink or junction,
and is created without overwriting an existing file. The path chain is
rechecked before and after temporary-file creation and the final hard link.
As with the rest of the local workflow, the project directory must not be
mutated concurrently by an untrusted process with the same filesystem
permissions; serialize writers per project.

## Python API

Direct material evaluation:

```python
from photonic_workflow.recipes import evaluate_recipe

result = evaluate_recipe(
    "materials.malitson-fused-silica-1965",
    {"wavelength_um": 1.55},
    version="1.0.0",
)
payload = result.to_payload()
```

Render without filesystem side effects:

```python
from photonic_workflow.recipes import render_recipe

rendered = render_recipe(
    "geometry.circular-route",
    {
        "vertices_um": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0]],
        "radius_um": 5.0,
        "width_um": 0.5,
    },
    version="1.0.0",
    renderer="canonical-json",
)
assert rendered.result.descriptor.recipe_id == "geometry.circular-route"
assert rendered.content.endswith("\n")
```

Every result reports `will_execute=false`, `physics_accepted=false`, a code
support level, and claim-boundary statements.

The two-port diagnostic additionally requires the exact declarations
`nonport_flux_sign_convention="positive_outward"` and
`material_absorption_sign_convention="positive_absorbed"`. Missing or opposite
conventions fail closed before closure arithmetic is evaluated.

Its v1 aggregate diagnostic combines reciprocity, passivity and unitarity even
when a device does not require all three. Do not use that aggregate as a physical
acceptance flag for a lossy, active or nonreciprocal model. Keep v1 reproducibility
and use the N-channel conditional checks in `executable-diagnostics.md` for those
cases. A four-channel task needs four actual source columns, not two-port padding.

## COMSOL Java Fragments

Only the three geometry/port recipes support `comsol-java-fragment` in v1.
The renderer:

- selects a fixed allowlisted template by recipe ID and exact version;
- requires a unique safe `instance_id`, from which it derives deterministic,
  collision-resistant Java feature tags without accepting raw tags;
- explicitly sets `g.lengthUnit("um")`; use a fresh reviewed 2D geometry, or
  first confirm an existing geometry already uses micrometres so this repeated
  declaration cannot reinterpret earlier features;
- interpolates finite numeric data only;
- emits no solver command, local path, model load, save, or solve call;
- does not accept arbitrary Java, expressions, feature tags, or labels;
- returns deterministic LF text and SHA-256 metadata.

Renderer-specific compilation guards are intentionally narrower than pure
recipe evaluation: Euler Java output accepts at most 256 samples, circular
route Java output accepts at most 16 vertices, and every fragment is capped at
48,000 UTF-8 bytes. Use multiple uniquely named instances or a solver-owned
table/file ingestion adapter for larger geometry; do not raise these limits
without a maximum-bound Java syntax regression and a reviewed
`comsolcompile` test against the target COMSOL version.

Treat a fragment as a configuration artifact. Compile/run it only through an
authorized solver workflow after selections, materials, physics, mesh, modes,
reference planes, and evidence requirements are supplied by the target
project.

The historical `emit-analytic-bend-java-helper.py --output` path is retired
because it lacked project-root and no-overwrite enforcement. Use the recipe CLI
for bounded file creation; invoking the legacy helper without `--output` still
prints its compatibility skeleton to standard output.

## Provenance And Claim Boundaries

`src/photonic_workflow/data/recipes/provenance-v1.json` records:

- stable project aliases rather than absolute local paths;
- source/evidence relative paths and SHA-256 fingerprints;
- recipe-semantic versions;
- behavioral or public-formula reimplementation method;
- supported and explicitly excluded claims.

The executable catalog is statically bound in Python. Provenance data cannot
select a callable or import a module. Catalog and manifest identities must
match exactly.

The initial recipes were distilled from two read-only LT-aMZI project trees.
Their complete Java models were not copied because they contain project-fixed
geometry, old local paths, solver-specific details, and no standalone public
license. No `.mph`, `.class`, solver log, fixed domain/face number, mode phase,
or private numerical matrix is packaged.

Historic evidence remains scoped:

- legacy Euler and segmented-port fixtures are 2D EIM/configuration evidence;
- Li/Malitson checks establish bulk formula and API readback only;
- a same-model two-column diagnostic does not establish broadband phase,
  group delay, convergence, or current material/PML G1 closure;
- the current material/PML G1 remains blocked until its independent driven and
  convergence evidence closes.

## Maintenance Rules

When adding or changing a recipe:

1. Keep `recipe_id` stable and version recipe semantics independently from the
   package version.
2. Publish a new recipe major version for breaking input/output semantics;
   never reinterpret an existing version in place.
3. Bind evaluators statically; never import a callable named by JSON.
4. Keep the pure algorithm free of filesystem, solver, shell, network, and
   environment side effects.
5. Require explicit units and validity envelopes.
6. Add positive and rejection tests, including non-finite numbers, wrong
   types, missing/unknown keys, degenerate geometry, and wrong source columns.
7. Add or update relative source/evidence hashes in the provenance manifest;
   never store an absolute path, user name, license detail, or secret.
8. Keep support levels limited to `documented`, `unit-tested`, or
   `configuration-audited`. Physical acceptance belongs to run and gate
   records.
9. Synchronize the packaged skill reference and verify the complete resource
   set rather than updating a hard-coded count.
10. Run the full Python, legacy compatibility, MCP, PowerShell, artifact,
    package-build, clean-install, and contract-snapshot checks before release.
