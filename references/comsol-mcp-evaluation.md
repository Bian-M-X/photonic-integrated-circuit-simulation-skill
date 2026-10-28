# COMSOL Automation and MCP Evaluation

Use this reference when choosing between the trusted COMSOL Java/batch route,
interactive vendor APIs, the `photonic` CLI, and the local MCP transport.

## Current Decision

| Route | Current role | Claim boundary |
|---|---|---|
| `photonic` CLI | Workflow authority for contracts, status, validation, composition, audit, and bounded plans | A successful command is workflow evidence, not solver or physics evidence |
| Java API source + `comsolcompile` + `comsolbatch` | Trusted local COMSOL execution route after explicit review and authorization | Requires declared outputs, logs, convergence, mesh/boundary/mode checks, and independent acceptance |
| `photonic-workflow` MCP 0.7.0 | Narrow assistant integration for resources and non-executing package services | No COMSOL, MATLAB, instrument, Python, or shell execution |
| `mphserver` / LiveLink-style control | Optional stateful Phase C integration | Unverified until version, lifecycle, cleanup, redaction, failure, and parity adoption gates pass |

MCP is a transport over the same package services used by the CLI. It is not a
second workflow authority and does not replace direct batch execution.

## Implemented MCP Surface

The compatibility launcher is `scripts/mcp_photonic_server.py`; the package
implementation is `photonic_workflow.mcp.server`. The stdio server speaks
JSON-RPC 2.0 and reports package/server version `0.7.0`.

### Resources

The current repository exposes the resources declared by the package registry:

- one `photonic://server/manifest`;
- every registered `photonic://skill/reference/<name>` document mirrored from
  `references/`;
- every registered `photonic://skill/agent/<name>` bounded role contract
  mirrored from `agents/`.

The server manifest is the authoritative machine-readable summary of version,
root policy, exact tool/resource lists, and the fact that execution is not
exposed. Tests compare the registry, source tree, packaged mirror, and installed
wheel instead of maintaining a second hard-coded resource count.

### Tools

The current development surface contains 13 narrow tools. Query the live
manifest: an already-running server may still expose an earlier surface.

| Tool | Operation |
|---|---|
| `list_allowed_roots` | Return separate read and write roots |
| `list_recipes` | List compact identities/versions of built-in modeling recipes |
| `inspect_recipe` | Read one exact recipe contract, units, limits and provenance |
| `render_recipe` | Create a new canonical JSON or fixed Java artifact; return a compact hash receipt |
| `create_project_scaffold` | Create a package-based project scaffold without copying business logic |
| `audit_project_artifacts` | Scan eligible files completely for blocked or sensitive artifacts |
| `parse_sweep_table` | Validate a legacy COMSOL scalar sweep and write bounded summaries |
| `validate_contract` | Validate a versioned JSON contract through the shared registry |
| `inspect_project` | Return bounded project, gate, and run-directory metadata |
| `validate_circuit` | Validate assembly v1 and complete complex component data |
| `compose_circuit` | Compose an assembly and write the external complex S matrix |
| `gate_status` | Read G0-G8 and M0-M4 without changing the ledger |
| `run_java_batch` | Compatibility name for a redacted COMSOL Java dry-run plan only |

`run_java_batch` rejects non-dry-run and execution-enabling flags. Its result
must report `will_execute: false` and `execution_enabled: false`. Keep the name
only for compatibility; do not describe it as solver execution.

Recipe tools reuse the CLI's catalog, numerical functions, renderers and output
path policy. `render_recipe` accepts strict versioned request files, refuses
overwrites and output links/junctions, and keeps generated arrays/code outside
the response. Read/write roots remain separate; no solver process or gate
mutation is added. See [modeling-recipes.md](modeling-recipes.md).

All tools declare MCP `readOnlyHint`, `destructiveHint`, `idempotentHint` and
`openWorldHint`. File-writing operations are not marked read-only. These hints
assist tool selection; path checks and non-execution rules remain enforced
independently. No protocol-version change is needed for these 2025-06-18 fields.

## Security Contract

- Read and write roots are distinct. The skill root is read-only unless it is
  also supplied explicitly as a writable root.
- A write fails when no write root is configured.
- Every path is resolved and checked beneath the applicable root.
- Output labels reject traversal, absolute paths, separators, empty/dot names,
  and reserved basenames.
- JSON rejects NaN and infinity.
- Artifact audit reads the full eligible text file, not only an initial chunk,
  while excluding binary and cache/VCS data.
- Returned plans redact the solver root and do not expose arbitrary command
  strings.
- MCP exposes no arbitrary shell, Python, MATLAB, COMSOL script, Lumerical
  script, SCPI, or instrument operation.
- MCP owns no hidden interactive state and starts no licensed process.

Legacy `--allow-root` makes a root both readable and writable. New
configurations should use `--read-root` and `--write-root` explicitly, or their
`PHOTONIC_MCP_READ_ROOTS` and `PHOTONIC_MCP_WRITE_ROOTS` environment
counterparts.

## Local Protocol Acceptance

`scripts/test_mcp_photonic_server.py` exercises:

- initialization and strict invalid-request handling;
- exact resource/tool discovery and source-sweep reference access;
- recipe discovery, strict request handling, and bounded artifact receipt;
- server-manifest readback;
- safe sweep parsing, strict JSON, plateau/descending spectra, and zero spectra;
- unsafe output-label rejection;
- project scaffold and clean-artifact audit;
- credential-name/content detection, binary exclusion, and sensitive text
  beyond the first MiB;
- redacted `run_java_batch` dry-run behavior;
- output-model, log, runtime, timeout, and allow-root validation.

This is protocol and service-parity evidence only. It is not a COMSOL
installation probe, license check, compile/run smoke, source-sweep parity, PML
validation, modal alignment proof, field-accuracy result, or convergence study.

`tests/integration/test_mcp_recipes.py` additionally compares all six recipe
artifacts with CLI output, checks Java rendering without process startup, and
tests rejected inputs, separated roots, no overwrite and compact responses.

## Why Direct Batch Remains the Execution Baseline

- Java source keeps the model construction auditable.
- The runner can use the solver-bundled JDK and native batch executable.
- Isolated runtime directories, exit propagation, expected `.mph` output, and
  batch logs are explicit.
- Long jobs do not depend on a hidden interactive session.
- The output trail is easier to inspect and compare across revisions.

Use `scripts/invoke-waveguide-java-batch.ps1 -DryRun` first. Removing
`-DryRun` requires the user's authorization and a reviewed local plan. Exit
code zero is insufficient when the declared output model or batch log is
missing.

## Phase Boundaries

### Phase A: local core and dry-run integration

Phase A includes the thin MCP transport, package-service parity, separated root
policy, strict JSON, complete artifact audit, scaffold/validate/compose/status
tools, and redacted COMSOL plan rendering. It requires no COMSOL license.

Phase A does not enable solver execution or pass a device gate.

### Phase B: licensed local direct-batch validation

On an authorized non-confidential fixture, compare the trusted PowerShell
runner with the same package-generated plan:

1. straight-waveguide compile and batch smoke;
2. analytic-bend geometry smoke;
3. same-model source sweep and parsed complex/scalar outputs;
4. missing-output, timeout, compile-failure, and solve-failure behavior;
5. redaction and artifact audit;
6. hashes and numeric parity against the direct route.

These checks validate a local execution route. They do not automatically pass
G1-G7; the physical evidence must still satisfy the appropriate gate.

### Phase C: bounded interactive or commercial integrations

Consider `mphserver`, LiveLink for MATLAB, a sim-cli, remote/HPC execution, or
MCP-triggered commercial execution only after a backend-specific adoption
gate proves:

1. exact product/release/platform compatibility and entitlement;
2. explicit approval, dry-run, timeout, and concurrency isolation;
3. fixed allowlisted operations with no arbitrary code;
4. startup, authentication, cancellation, cleanup, and orphan recovery;
5. redacted logs and artifact inspection;
6. success and failure parity with direct batch;
7. rollback to the trusted route.

Commercial concurrency remains one unless the user explicitly authorizes and
the environment proves license, memory, runtime-directory, and cleanup
isolation.

## Evidence and Adoption Rule

Use MCP as the assistant-facing interface for its implemented narrow services.
Do not adopt it as a trusted solver-execution backend unless it matches direct
batch on the same approved fixtures without weakening security,
reproducibility, or evidence quality.

Keep these distinctions explicit:

- MCP/CLI plan rendered;
- executable located;
- licensed process started;
- process completed and artifacts exist;
- artifacts inspected;
- numerical parity passed;
- physics gate accepted.

No earlier state implies a later one. Configuration-only, modal-only, sparse,
single-mesh, no-PML, or dry-run evidence cannot be promoted to full-wave
validation.

## MCP Specification Sources

- Tools: `https://modelcontextprotocol.io/specification/2025-06-18/server/tools`
- Resources: `https://modelcontextprotocol.io/specification/2025-06-18/server/resources`
- Tool annotations: [2025-06-18 schema](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations), checked 2026-09-05.

Refresh these links and the protocol version before changing the transport
contract.
