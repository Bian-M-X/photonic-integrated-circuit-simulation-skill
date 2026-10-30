# Authoring a Third-Party Adapter Provider

Status: adapter SPI 1.0 descriptor-provider contract

Adapter SPI `1.0` is intentionally narrow. A third-party distribution may
publish reviewed adapter descriptors through Python package entry points. It
may not publish a stable execution factory through this SPI. Importing a
provider proves only that its metadata contract loaded; it does not prove that
a backend, license, solver, model, or physical result is available or valid.

## Compatibility axes

Track these independently:

1. host package range, such as `photonic-workflow>=0.5,<0.10`;
2. exact provider SPI, currently the literal string `"1.0"`;
3. canonical schema version for each named input/output contract;
4. provider distribution version;
5. optional backend/solver versions and local license state;
6. backend-specific numerical and physics evidence.

Do not derive a provider's SPI or contract versions from the host's current
constants. A host change must fail closed until the provider has been reviewed
and retested.

## Packaging

Declare one zero-argument provider function:

```toml
[project]
name = "acme-photonic-adapter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["photonic-workflow>=0.5,<0.10"]

[project.entry-points."photonic_workflow.adapters"]
acme = "acme_photonic_adapter:provide_adapters"
```

The entry-point module and provider call must work without importing an
optional backend SDK. Backend imports belong behind a later explicit operation,
not module import.

## Provider shape

The provider returns a non-empty tuple of `AdapterRegistration`. SPI `1.0`
requires `factory=None`, exact per-contract versions, dry-run defaults, and a
planned or unverified implementation:

```python
from photonic_workflow.adapters import AdapterRegistration
from photonic_workflow.models import AdapterDescriptor, ImplementationStatus

SUPPORTED_ADAPTER_SPI = "1.0"
SUPPORTED_CONTRACT_SCHEMAS = {
    "CapabilityReport": "1.0",
    "RunSpec": "1.0",
}

def provide_adapters() -> tuple[AdapterRegistration, ...]:
    descriptor = AdapterDescriptor(
        stable_id="adapter:acme",
        name="ACME adapter",
        source="acme-photonic-adapter 0.1.0",
        adapter="acme",
        adapter_spi_version=SUPPORTED_ADAPTER_SPI,
        contract_schema_versions=dict(SUPPORTED_CONTRACT_SCHEMAS),
        implementation=ImplementationStatus.PLANNED,
        execution_modes=["descriptor"],
        input_contracts=["RunSpec"],
        output_contracts=["CapabilityReport"],
        capabilities=["bounded capability description"],
        limitations=["no execution through adapter SPI 1.0"],
        default_dry_run=True,
        default_concurrency=1,
    )
    return (
        AdapterRegistration(
            descriptor=descriptor,
            factory=None,
            spi_version=SUPPORTED_ADAPTER_SPI,
        ),
    )
```

The complete runnable source example is under
`examples/minimal-adapter-provider/`.

## Provider contract suite

Provider tests should call:

```python
from photonic_workflow.adapters import validate_adapter_provider_contract

validate_adapter_provider_contract(
    provide_adapters,
    provider_name="acme",
)
```

The helper checks the tuple shape, repeatability, adapter IDs, built-in
collisions, exact SPI and per-contract schemas, descriptor-only maturity and
modes, safe defaults, and obvious changes to the process working directory or
environment. It invokes the provider twice. It does not sandbox Python or undo
arbitrary import side effects.

Run provider tests against the lowest supported host version and the latest
host patch. Also install the provider wheel in an isolated environment and
verify real entry-point discovery. Test with backend extras absent so metadata
discovery cannot accidentally depend on the solver SDK.

## Project authorization

After reviewing the provider distribution and version, add only its
entry-point name to:

```toml
adapter_entrypoint_allowlist = ["acme"]
```

Normal `photonic check`, `photonic status`, and `photonic doctor` do not import
the provider. The explicit command is:

```powershell
photonic doctor --load-configured-adapters --json
```

The doctor record includes the entry-point name, target, distribution, and
distribution version when packaging metadata exposes them. The allowlist
authorizes importing third-party Python for diagnosis. It is not a sandbox,
solver-execution authorization, or physics acceptance.

## Execution boundary

Core CLI and MCP do not execute third-party providers under SPI `1.0`.
Supporting third-party planning requires a future immutable factory context
covering project/allowed roots, dry-run, timeout, concurrency, redaction, and
artifact policy. Real execution additionally requires backend-specific
failure, timeout, artifact, parity, authorization, and claim-boundary tests.
Until those contracts exist, third-party execution remains `BLOCKED`.
