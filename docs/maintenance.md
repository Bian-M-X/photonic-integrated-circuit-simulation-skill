# Maintenance and Compatibility

This document defines how to update `photonic-workflow` without silently
changing persisted evidence, public commands, packaged resources, or claim
boundaries. It is an engineering control, not a promise that every future
third-party solver, PDK, MATLAB release, or Python package will remain
compatible.

## Contents

- [Stable surfaces](#stable-surfaces)
- [Version and release updates](#version-and-release-updates)
- [GitHub publication controls](#github-publication-controls)
- [Static quality](#static-quality)
- [Contract evolution](#contract-evolution)
- [Recipe evolution](#recipe-evolution)
- [Adapter updates](#adapter-updates)
- [Mirrored and packaged resources](#mirrored-and-packaged-resources)
- [Run-store maintenance](#run-store-maintenance)
- [Backend-adoption store](#backend-adoption-store)
- [Next structural refactor](#next-structural-refactor)

## Stable surfaces

Treat these as reviewed compatibility surfaces:

- package version and installed console scripts;
- CLI group/command names, JSON envelope, and exit-code meanings;
- `contract_type`, `schema_version`, stable IDs, enums, and run-file layout;
- adapter IDs, descriptors, dry-run defaults, and explicit factory availability;
- MCP resource/tool schemas and its non-execution boundary;
- root skill references, packaged MCP mirrors, MATLAB mirrors, and templates;
- G0-G8/M0-M4 semantics and all fail-closed evidence labels.

The maintenance tests intentionally snapshot these surfaces. A snapshot change
must be reviewed as an API decision, not accepted as incidental test churn.
When a schema change is intentional and its migration/version work is complete,
regenerate the structural record with
`python scripts/update_contract_surface_snapshot.py --update`; review the JSON
diff before accepting it.

## Version and release updates

`src/photonic_workflow/_version.py` is the only code source for the package
version. Setuptools, `photonic --version`, MCP, and scaffold dependency ranges
derive from it. README and MCP compatibility prose remain human-facing release
records; the maintenance test rejects stale versions there.

For a release candidate:

1. update `_version.py` and the release-facing prose;
2. run the full solver-free test suite and legacy regressions;
3. build both sdist and wheel;
4. verify wheel runtime resources and sdist maintenance sources with
   `python scripts/test_distribution_contents.py dist`;
5. install the wheel in a clean environment outside the checkout;
6. read every registry-declared MCP resource and validate an installed project
   template;
7. run artifact, whitespace, checked-in skill/UI schema, and optional external
   skill-creator validation;
8. record any intentional compatibility or claim-boundary change.

After the pull request and the pushed `main` commit are green:

1. require the remote mainline commit verification record to report
   `verified=true`;
2. create `v<package-version>` at that exact commit, using an annotated signed
   tag when a pre-associated signing key is available;
3. push only that tag and let `.github/workflows/release.yml` first require it
   to equal the current GitHub-verified `main` commit with successful
   `python-compat.yml` push runs, then rebuild and revalidate under read-only
   permissions, upload the wheel, sdist, and SHA-256 inventory as one immutable
   artifact, and pass that exact artifact ID through separately permissioned
   attestation and publication jobs;
4. verify each downloaded wheel, sdist, and checksum inventory with
   `gh attestation verify <asset> -R Bian-M-X/photonic-integrated-circuit-simulation-skill`;
5. confirm the prerelease points to the intended tag and exposes only the
   workflow-built assets.

Do not publish merely because these checks pass. Licensed backend and physics
claims still require their separate Phase B/C evidence.

## GitHub publication controls

Do not assume a branch-protection context from documentation or a green badge.
This repository currently has no checked-in aggregate job named `validate`.
Before changing or relying on branch protection, query the active GitHub branch
protection/rulesets and compare their required contexts with the actual workflow
job names. If a stable aggregate context is desired, implement and test that job
first, then configure the remote rule in a separate administrator-approved
change. Never configure a required context that no workflow emits.

Publish through a pull request from an `agent/*` branch. Before pushing:

1. verify the GitHub CLI is authenticated to the intended repository owner;
2. verify the repository-local author name and email;
3. either create a cryptographically signed commit with a signing key already
   associated with that GitHub identity, or use a reviewed GitHub server-side
   squash/merge that produces the final signed mainline commit;
4. verify local signatures when used, then run artifact audit and
   `git diff --check`;
5. push without force, open a draft pull request, and wait for every status
   check emitted for the branch before merging;
6. query the final remote mainline commit and require GitHub's verification
   record to report `verified=true` before announcing the release.

Do not claim a commit is GitHub `Verified` from a local signing attempt alone;
confirm the remote commit verification record. Repository governance changes
such as requiring signed commits, reviews, or a ruleset are separate
administrator actions and must not be inferred from a green workflow.

The repository `.gitattributes` fixes reviewed text formats to LF so Windows
`core.autocrlf` settings cannot churn packaged resource mirrors or contract
snapshots. Keep generated build, cache, local configuration, and run
directories out of Git; use the artifact audit rather than globally ignoring
small scientific interchange fixtures such as GDS, MAT, HDF5, or Touchstone.

## Static quality

The `Static quality` Actions job pins Ruff and gates `src`, `tests`, and
`scripts`. It also parses `SKILL.md` and `agents/openai.yaml`, rejects duplicate
or unsupported metadata keys, checks the published skill token, and enforces
the UI metadata constraints. Update tool/action pins deliberately, apply
mechanical fixes separately from behavioral changes when practical, and rerun
the full test/package matrix after any formatter or lint migration.

Mypy remains an advisory development tool until the dynamic public-model
re-exports and existing type findings have a zero-error baseline. Do not add a
failing type-check step or suppress the entire package merely to claim a green
check; reduce that debt with explicit exports and narrow typed services first.

## Contract evolution

Every external contract must declare `schema_version`. Current-version unknown
fields and enum values remain invalid input. Unknown old or future versions
raise the distinct incompatible-version boundary instead of being interpreted
with current defaults.

Add a schema migration only when a real historical fixture exists:

1. add one pure `ContractMigration` step with a stable migration ID;
2. preserve `contract_type` and `stable_id`;
3. migrate one version at a time and never discard unknown input silently;
4. add frozen before/after fixtures, idempotence checks, and rejection tests;
5. update the model's current version only after every external reader routes
   through `parse_contract` or `parse_contract_body`.

Use `revalidate_internal` only for a payload derived from an already parsed
typed contract. A maintenance test rejects direct `.model_validate(...)` calls
outside the central I/O module so a new file reader cannot silently bypass
migration routing.

Production steps live in the immutable
`models/migration_catalog.py` manifest, which is frozen before the first parse.
Tests use a local registry and never mutate the production singleton. A single
contract type advances independently: override both its
`current_schema_version` class value and its `schema_version` field default.
Do not raise the global/default version to make one type appear upgraded.
Import-time invariants and the public-surface snapshot record both per-model
values and fail if they diverge.

Applied migrations add a provenance marker. Reading does not rewrite the source
file; a later explicit write emits the current canonical form.

## Recipe evolution

The recipe catalog is a closed, immutable public registry. A recipe request
version belongs to that recipe and does not automatically follow the package
version.

When adding or changing a recipe:

1. define explicit parameter names, JSON types, units, defaults, numeric/item
   bounds, enums, deterministic outputs, support level, and claim boundary as
   immutable `ParameterSpec` and descriptor records in the catalog;
2. reject unknown, duplicate, non-finite, boolean-as-number, and out-of-range
   input rather than coercing it;
3. use a new recipe major version for breaking parameter/output semantics; keep
   old behavior only when it can be maintained and tested safely;
4. add or update the package-owned provenance record with source aliases,
   relative paths, immutable SHA-256 hashes, distillation method, and excluded
   claims—never local absolute paths or copied proprietary/vendor code;
5. keep backend renderers on an allowlist and emit fixed numeric data only; a
   public parameter must never select Java tags, expressions, or executable
   templates;
6. keep backend renderer bindings in the single immutable renderer registry;
   renderer-only compilation/resource ceilings remain separate from pure
   evaluation bounds and require maximum-bound compile tests;
7. update unit, CLI, package-content, public-surface, reference-router, MCP
   resource, mirror, and clean-install tests in the same change;
8. regenerate and review the compatibility snapshot intentionally.

The source projects used for distillation remain read-only evidence. Recipe
tests establish software behavior, not full-wave validation, convergence,
fabrication readiness, or acceptance of any device.

## Adapter updates

Built-in adapters register a descriptor and an optional factory together.
Descriptor publication is not execution availability, and a capability probe
is not backend or physics validation.

Third-party adapters use the `photonic_workflow.adapters` Python entry-point
group. Adapter SPI `1.0` is descriptor-only: a provider must declare literal
SPI and per-contract versions and cannot expose an executable factory. Loading
imports third-party code, so the default registry never loads entry points
automatically. An embedding application must provide an explicit allowlist,
test the provider contract, and preserve core path, redaction, concurrency,
provenance, and claim controls. Use
`validate_adapter_provider_contract` and the runnable
`examples/minimal-adapter-provider/`; the full authoring contract is in
`docs/providers/authoring-third-party-adapter.md`.

Projects may list reviewed provider names in
`adapter_entrypoint_allowlist`. The CLI imports them only when the user also
passes `photonic doctor --load-configured-adapters`; ordinary project checks do
not execute third-party entry-point code.

Before enabling execution, add backend-specific compatibility, failure-mode,
artifact, timeout, and parity evidence. Keep unsupported providers
descriptor-only.

Registry publication is atomic only after provider calls return. Python import
and provider side effects cannot be rolled back; the allowlist is permission to
import reviewed code, not a sandbox.

## Mirrored and packaged resources

Root `references/*.md` and `agents/*-agent.md` are skill sources. Installed MCP
uses a package-owned read-only mirror so it works outside a Git checkout.
MATLAB source under `matlab/` is authoritative and has an equivalent package
mirror under `src/photonic_workflow/data/matlab/`. Runtime scaffold templates
under `src/photonic_workflow/data/templates/` are authoritative; the older
`assets/templates/hierarchical-device/` tree is a legacy assembly regression
fixture with different relative paths, not a byte mirror.

After changing a skill reference or agent role, run:

```powershell
.\scripts\sync-packaged-skill-resources.ps1 -Update
.\scripts\sync-packaged-skill-resources.ps1
```

Tests compare the complete relative file sets and bytes, so adding, deleting,
or editing only one side fails CI. Do not hand-edit the packaged mirror as an
independent source.

After changing MATLAB runtime files, run:

```powershell
.\scripts\sync-packaged-matlab-resources.ps1 -Update
.\scripts\sync-packaged-matlab-resources.ps1
```

## Run-store maintenance

The Phase-A `RunStore` is checkpoint-last and single-writer per run. Creation
uses a staging directory; failed creation must not leave a named partial run.
Recovery validates checkpoint identity, the complete hash set, events, every
structured contract file, and cross-file IDs/status.

Do not claim multi-process safety until a tested lock or generation/CAS
mechanism exists. Streaming logs are not trusted evidence unless recorded as
hashed artifacts.

## Backend-adoption store

Backend records live at `verification/adoption/<target>.json`; target names
come only from `BackendAdoptionTarget`. The store rechecks every derived path,
creates new records with atomic no-clobber semantics, and atomically replaces
record/evaluation updates. `--dry-run` must remain byte-for-byte side-effect
free, and initialization must never reset existing evidence.

Pass/fail evidence accepted through the store is a readable project-relative
file. Model-only helpers enforce contract shape and nonblank references but do
not inspect scientific meaning. Preserve this distinction in APIs and docs.
The store is single-writer per target until a tested lock or generation/CAS
mechanism lands; serialize automation that records or evaluates a target.

When adding a backend or required check, update the enum, canonical definition,
unit/integration tests, docs, and compatibility snapshot together. Existing
persisted records need an explicit schema migration; never silently fill a new
required check and report the old decision as current.

## Next structural refactor

The largest remaining maintenance item is the monolithic Click module and
duplicated CLI/MCP orchestration. Introduce typed application use cases first,
then move command groups into small registration modules without changing the
snapshotted surface. Keep transports responsible only for protocol parsing,
path-policy context, envelope rendering, and error mapping.
