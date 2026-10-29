from __future__ import annotations

from photonic_workflow.models import (
    AdapterDescriptor,
    ImplementationStatus,
    current_contract_schema_versions,
)


def _descriptor(
    adapter: str,
    name: str,
    *,
    implementation: ImplementationStatus,
    commercial: bool,
    capabilities: list[str],
    limitations: list[str],
) -> AdapterDescriptor:
    input_contracts = ["RunSpec"]
    output_contracts = ["CapabilityReport", "ArtifactRecord", "ProvenanceRecord"]
    return AdapterDescriptor(
        stable_id=f"adapter:{adapter}",
        name=name,
        source="photonic_workflow Phase A external adapter registry",
        status="phase-a",
        adapter=adapter,
        implementation=implementation,
        commercial=commercial,
        optional=True,
        version_sensitive=True,
        execution_modes=["descriptor", "capability-probe-contract", "dry-run-plan"],
        input_contracts=input_contracts,
        output_contracts=output_contracts,
        contract_schema_versions=current_contract_schema_versions(
            [*input_contracts, *output_contracts]
        ),
        capabilities=capabilities,
        limitations=limitations,
        default_dry_run=True,
        default_concurrency=1,
    )


EXTERNAL_ADAPTER_DESCRIPTORS: tuple[AdapterDescriptor, ...] = (
    _descriptor(
        "comsol-native-java-batch",
        "COMSOL native Java batch",
        implementation=ImplementationStatus.IMPLEMENTED,
        commercial=True,
        capabilities=["redacted batch planning", "fail-closed legacy PowerShell execution"],
        limitations=[
            "requires a local COMSOL installation and license",
            "command success is not full-wave acceptance",
        ],
    ),
    _descriptor(
        "sim-cli",
        "sim-cli photonic simulation bridge",
        implementation=ImplementationStatus.EXPERIMENTAL,
        commercial=False,
        capabilities=["interactive inspection handoff contract"],
        limitations=["no Phase-A execution adapter or compatibility claim"],
    ),
    _descriptor(
        "lumerical",
        "Ansys Lumerical product bridge",
        implementation=ImplementationStatus.EXPERIMENTAL,
        commercial=True,
        capabilities=[
            "built-in allowlisted filesystem check and fixed-operation RunSpec dry plans",
            "explicit local CLI for native MODE/FDTD diagnostics, CAD and complete device source sweeps",
            "shared geometry/material recipes, verified complex-S circuit exchange and candidate evaluation",
            "nonexecuting MCP discovery, planning and retained-result inspection/export",
        ],
        limitations=[
            "generic adapter factory enables check/plan only; execution remains in the explicit local CLI",
            "licensed solver validation is product-specific; DEVICE, EME and INTERCONNECT remain unverified",
        ],
    ),
    _descriptor(
        "gdsfactory",
        "GDSFactory layout bridge",
        implementation=ImplementationStatus.PLANNED,
        commercial=False,
        capabilities=["LayoutManifest and PCell handoff contract"],
        limitations=["package presence and PDK semantics require a local probe"],
    ),
    _descriptor(
        "klayout",
        "KLayout inspection and verification bridge",
        implementation=ImplementationStatus.PLANNED,
        commercial=False,
        capabilities=["DRC/LVS/layout-to-netlist handoff contract"],
        limitations=["no deck, PDK or signoff result is bundled"],
    ),
    _descriptor(
        "sax",
        "SAX circuit simulation bridge",
        implementation=ImplementationStatus.PLANNED,
        commercial=False,
        capabilities=["compact-model circuit evaluation contract"],
        limitations=["model normalization and producer versions require explicit evidence"],
    ),
    _descriptor(
        "meep",
        "Meep full-wave bridge",
        implementation=ImplementationStatus.PLANNED,
        commercial=False,
        capabilities=["open-source full-wave plan contract"],
        limitations=["no Phase-A solver execution or convergence evidence"],
    ),
    _descriptor(
        "femwell",
        "Femwell finite-element bridge",
        implementation=ImplementationStatus.PLANNED,
        commercial=False,
        capabilities=["mode and finite-element plan contract"],
        limitations=["no Phase-A solver execution or validation evidence"],
    ),
    _descriptor(
        "tidy3d",
        "Tidy3D simulation bridge",
        implementation=ImplementationStatus.PLANNED,
        commercial=True,
        capabilities=["local or cloud simulation plan contract"],
        limitations=["no API key, cloud credential or execution is exposed by core"],
    ),
)

EXTERNAL_DESCRIPTOR_BY_NAME = {
    descriptor.adapter: descriptor for descriptor in EXTERNAL_ADAPTER_DESCRIPTORS
}
