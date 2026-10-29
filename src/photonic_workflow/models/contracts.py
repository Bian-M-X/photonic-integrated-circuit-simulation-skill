from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from photonic_workflow.compatibility import (
    CURRENT_ADAPTER_SPI_VERSION,
    CURRENT_CONTRACT_SCHEMA_VERSION,
)
from photonic_workflow.security import enforce_commercial_concurrency, validate_stable_id


def utc_now() -> datetime:
    return datetime.now(UTC)


class Validity(StrEnum):
    UNKNOWN = "unknown"
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    OUT_OF_ENVELOPE = "out_of_envelope"


class WorkflowProfile(StrEnum):
    PDK_FIRST = "pdk-first"
    LAYOUT_FIRST = "layout-first"
    CUSTOM_DEVICE_FIRST = "custom-device-first"
    MATLAB_LEGACY_LAYOUT = "matlab-legacy-layout"
    MATLAB_ASSISTED_DESIGN = "matlab-assisted-design"


class ImplementationStatus(StrEnum):
    IMPLEMENTED = "implemented"
    EXPERIMENTAL = "experimental"
    PLANNED = "planned"
    UNVERIFIED = "unverified"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"
    UNVERIFIED = "unverified"


class FidelityLevel(StrEnum):
    ANALYTIC = "analytic"
    REDUCED = "reduced"
    MODE = "mode"
    CIRCUIT = "circuit"
    LAYOUT_EXTRACTED = "layout-extracted"
    MATLAB_FDFD_2D = "matlab-fdfd-2d"
    MATLAB_VARFDFD_2_5D = "matlab-varfdfd-2.5d"
    FULL_WAVE_2D_EIM = "full-wave-2d-eim"
    FULL_WAVE_2D_SCALAR = "full-wave-2d-scalar"
    FULL_WAVE_3D = "full-wave-3d"
    MULTIPHYSICS = "multiphysics"
    MEASURED = "measured"


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class GateName(StrEnum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"
    M0 = "M0"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"


class ExecutionStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AcceptanceStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TimeConvention(StrEnum):
    POSITIVE = "exp(+iwt)"
    NEGATIVE = "exp(-iwt)"


class ContractBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
    )
    contract_type: ClassVar[str] = "ContractBase"
    current_schema_version: ClassVar[str] = CURRENT_CONTRACT_SCHEMA_VERSION

    schema_version: str = CURRENT_CONTRACT_SCHEMA_VERSION
    stable_id: str
    name: str
    revision: str = "1"
    source: str
    created_at: datetime = Field(default_factory=utc_now)
    provenance: list[str] = Field(default_factory=list)
    status: str = "draft"
    validity: Validity = Validity.UNKNOWN

    @field_validator("stable_id")
    @classmethod
    def _stable_id(cls, value: str) -> str:
        return validate_stable_id(value)

    @field_validator("name", "revision", "source")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def _supported_schema_version(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("schema_version must be a non-empty string")
        if value != cls.current_schema_version:
            raise ValueError(
                f"{cls.contract_type} requires schema_version "
                f"{cls.current_schema_version!r}, got {value!r}"
            )
        return value


class ProjectIdentity(ContractBase):
    contract_type = "ProjectIdentity"
    project_root_alias: str = "."
    repository: str | None = None


class ProjectConfig(ContractBase):
    contract_type = "ProjectConfig"
    profile: WorkflowProfile = WorkflowProfile.CUSTOM_DEVICE_FIRST
    workspace: str = "."
    pdk_alias: str | None = None
    adapter_defaults: dict[str, str] = Field(default_factory=dict)
    adapter_entrypoint_allowlist: list[str] = Field(default_factory=list)
    allowed_roots: list[str] = Field(default_factory=lambda: ["."])
    dry_run: bool = True
    timeout_s: int = Field(default=3600, ge=1, le=7 * 24 * 60 * 60)
    commercial_concurrency: int = Field(default=1, ge=1)
    commercial_parallel_authorized: bool = False
    matlab_executable_alias: str = "matlab"
    matlab_execution_model: str = "batch"
    matlab_toolbox_path_aliases: dict[str, str] = Field(default_factory=dict)
    matlab_product_requirements: list[str] = Field(default_factory=list)
    comsol_livelink: bool = False
    lumerical_api_alias: str | None = None
    instrument_aliases: dict[str, str] = Field(default_factory=dict)
    redaction: bool = True
    artifact_limit_mb: int = Field(default=25, ge=1)
    packaging_profile: str | None = None
    test_profile: str | None = None

    @model_validator(mode="after")
    def _concurrency(self) -> ProjectConfig:
        enforce_commercial_concurrency(
            self.commercial_concurrency,
            self.commercial_parallel_authorized,
        )
        return self

    @field_validator("adapter_entrypoint_allowlist")
    @classmethod
    def _adapter_entrypoint_names(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("adapter_entrypoint_allowlist contains duplicates")
        for value in values:
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None:
                raise ValueError(f"invalid adapter entry-point name: {value!r}")
        return values


class DesignIntent(ContractBase):
    contract_type = "DesignIntent"
    problem: str = ""
    topology: str = ""
    external_ports: list[str] = Field(default_factory=list)
    wavelength_band_nm: tuple[float, float] | None = None
    modes: list[str] = Field(default_factory=list)
    process_stack: str | None = None
    metrics: dict[str, str | float] = Field(default_factory=dict)
    tolerances: dict[str, str | float] = Field(default_factory=dict)
    intended_claim: str = "exploratory"


class PortContract(ContractBase):
    contract_type = "PortContract"
    mode: str = ""
    normalization: str = "power-wave"
    reference_plane: str = ""
    orientation_deg: float | None = None
    cross_section: str | None = None


class DeviceContract(ContractBase):
    contract_type = "DeviceContract"
    family: str = ""
    topology: str = ""
    intent_id: str | None = None
    ports: list[PortContract] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    wavelength_band_nm: tuple[float, float] | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)


class DesignVariant(ContractBase):
    contract_type = "DesignVariant"
    parent_design_id: str | None = None
    parameters: dict[str, str | float | int | bool] = Field(default_factory=dict)
    process_corner: str | None = None


class Instance(ContractBase):
    contract_type = "Instance"
    component_id: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)
    transform: dict[str, float] = Field(default_factory=dict)


class Connection(ContractBase):
    contract_type = "Connection"
    source_endpoint: str = ""
    target_endpoint: str = ""
    transition_component_id: str | None = None


class BaseNetlist(ContractBase):
    instances: list[Instance] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    external_ports: dict[str, str] = Field(default_factory=dict)


class LogicalNetlist(BaseNetlist):
    contract_type = "LogicalNetlist"


class ExtractedNetlist(BaseNetlist):
    contract_type = "ExtractedNetlist"
    layout_manifest_id: str | None = None
    extraction_backend: str | None = None


class SimulationNetlist(BaseNetlist):
    contract_type = "SimulationNetlist"
    model_bindings: dict[str, str] = Field(default_factory=dict)


class ComponentContract(ContractBase):
    contract_type = "ComponentContract"
    family: str = ""
    ports: list[PortContract] = Field(default_factory=list)
    parameters: dict[str, str | float | int | bool] = Field(default_factory=dict)
    model_cards: list[str] = Field(default_factory=list)
    validity_envelope: dict[str, Any] = Field(default_factory=dict)


class PCellContract(ComponentContract):
    contract_type = "PCellContract"
    backend: str = ""
    layer_map: dict[str, str | int] = Field(default_factory=dict)
    footprint: dict[str, float] = Field(default_factory=dict)


class ModelCard(ContractBase):
    contract_type = "ModelCard"
    producer: str = ""
    model_source: str = ""
    fidelity: FidelityLevel = FidelityLevel.ANALYTIC
    parameter_axes: dict[str, list[str | float]] = Field(default_factory=dict)
    validity_envelope: dict[str, Any] = Field(default_factory=dict)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)


class MultiPhysicsModelCard(ModelCard):
    contract_type = "MultiPhysicsModelCard"
    coupled_physics: list[str] = Field(default_factory=list)
    coupling_sequence: list[str] = Field(default_factory=list)


class SParameterMetadata(ContractBase):
    contract_type = "SParameterMetadata"
    wavelength_unit: str = "nm"
    port_order: list[str] = Field(default_factory=list)
    mode_order: list[str] = Field(default_factory=list)
    normalization: str = "power-wave"
    reference_planes: dict[str, str] = Field(default_factory=dict)
    time_convention: TimeConvention = TimeConvention.POSITIVE
    reference_impedance_ohm: float | None = None
    impedance_is_file_compatibility_only: bool = True
    producer: str = ""
    producer_version: str | None = None
    sha256: str | None = None


class SParameterDataset(ContractBase):
    contract_type = "SParameterDataset"
    representation: str = "long-form-complex-csv"
    data_path: str = ""
    metadata_id: str | None = None
    wavelength_count: int = 0
    shape: list[int] = Field(default_factory=list)
    dtype: str = "complex128"
    interpolation: str | None = None
    extrapolation: str = "forbidden"


class CircuitManifest(ContractBase):
    contract_type = "CircuitManifest"
    logical_netlist_id: str | None = None
    simulation_netlist_id: str | None = None
    component_models: dict[str, str] = Field(default_factory=dict)
    external_ports: dict[str, str] = Field(default_factory=dict)


class LayoutManifest(ContractBase):
    contract_type = "LayoutManifest"
    backend: str = ""
    top_cell: str = ""
    layout_path: str | None = None
    layer_map: dict[str, str | int] = Field(default_factory=dict)
    bounding_box_um: list[float] = Field(default_factory=list)
    cell_hierarchy: list[str] = Field(default_factory=list)
    port_metadata_path: str | None = None
    waveguide_length_path: str | None = None
    polygon_count: int | None = None
    extracted_netlist_id: str | None = None
    drc_status: str = "unverified"
    lvs_status: str = "unverified"


class LayerDefinition(ContractBase):
    contract_type = "LayerDefinition"
    layer: int | None = None
    datatype: int | None = None
    material: str | None = None
    purpose: str | None = None


class CrossSection(ContractBase):
    contract_type = "CrossSection"
    layers: list[str] = Field(default_factory=list)
    width_nm: float | None = None
    thickness_nm: float | None = None
    etch_depth_nm: float | None = None


class ProcessCorner(ContractBase):
    contract_type = "ProcessCorner"
    parameter_offsets: dict[str, float] = Field(default_factory=dict)


class StatisticalVariationModel(ContractBase):
    contract_type = "StatisticalVariationModel"
    variables: dict[str, dict[str, Any]] = Field(default_factory=dict)
    correlations: dict[str, float] = Field(default_factory=dict)
    foundry_supplied: bool = False


class TechnologyStack(ContractBase):
    contract_type = "TechnologyStack"
    materials: list[str] = Field(default_factory=list)
    layers: list[LayerDefinition] = Field(default_factory=list)
    cross_sections: list[CrossSection] = Field(default_factory=list)


class PdkManifest(ContractBase):
    contract_type = "PdkManifest"
    foundry_alias: str = ""
    pdk_version: str = ""
    access: str = "public"
    local_path_alias: str | None = None
    fingerprint: str | None = None
    technology_stack_id: str | None = None
    pcells: list[str] = Field(default_factory=list)
    compact_models: list[str] = Field(default_factory=list)
    drc_deck_alias: str | None = None
    lvs_deck_alias: str | None = None
    process_corners: list[str] = Field(default_factory=list)
    compatibility: dict[str, str] = Field(default_factory=dict)
    matlab_support: list[str] = Field(default_factory=list)


class PackagingConstraint(ContractBase):
    contract_type = "PackagingConstraint"
    coupling: str | None = None
    optical_ports: dict[str, Any] = Field(default_factory=dict)
    electrical_pads: dict[str, Any] = Field(default_factory=dict)
    die_outline_um: list[float] = Field(default_factory=list)
    keep_outs: list[dict[str, Any]] = Field(default_factory=list)


class TestPlan(ContractBase):
    contract_type = "TestPlan"
    instruments: dict[str, str] = Field(default_factory=dict)
    wiring: dict[str, str] = Field(default_factory=dict)
    calibration: list[str] = Field(default_factory=list)
    sweeps: list[dict[str, Any]] = Field(default_factory=list)
    safety_limits: dict[str, Any] = Field(default_factory=dict)
    raw_data_policy: str = "immutable"
    cleanup: list[str] = Field(default_factory=list)


class TapeoutManifest(ContractBase):
    contract_type = "TapeoutManifest"
    layout_manifest_id: str | None = None
    pdk_manifest_id: str | None = None
    test_plan_id: str | None = None
    packaging_constraint_id: str | None = None
    frozen: bool = False
    frozen_at: datetime | None = None


class MeasurementManifest(ContractBase):
    contract_type = "MeasurementManifest"
    chip_id: str | None = None
    die_id: str | None = None
    reticle_id: str | None = None
    component_id: str | None = None
    design_revision: str | None = None
    test_setup: str | None = None
    adapter_version: str | None = None
    calibration: list[str] = Field(default_factory=list)
    raw_data: list[str] = Field(default_factory=list)
    processed_data: list[str] = Field(default_factory=list)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    analysis_hash: str | None = None
    linked_model_id: str | None = None


class OptimizationSpec(ContractBase):
    contract_type = "OptimizationSpec"
    variables: list[dict[str, Any]] = Field(default_factory=list)
    objectives: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    fidelity: FidelityLevel = FidelityLevel.ANALYTIC
    solver_backend: str = ""
    evaluation_budget: int = Field(default=0, ge=0)
    timeout_s: int = Field(default=3600, ge=1)
    random_seed: int | None = None
    checkpoint_interval: int = Field(default=1, ge=1)
    failure_penalty: float | None = None
    acceptance_criterion_id: str | None = None
    promotion_rule: dict[str, Any] = Field(default_factory=dict)
    process_corners: list[str] = Field(default_factory=list)

    @field_validator("evaluation_budget", "random_seed", mode="before")
    @classmethod
    def _no_boolean_counts(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("optimization budget and seed must not be boolean")
        return value


class OptimizationTrial(ContractBase):
    contract_type = "OptimizationTrial"
    optimization_spec_id: str = ""
    run_id: str = ""
    parameters: dict[str, str | float | int | bool] = Field(default_factory=dict)
    objectives: dict[str, float] = Field(default_factory=dict)
    constraint_results: dict[str, float | bool] = Field(default_factory=dict)
    failure: str | None = None

    @field_validator("objectives", mode="before")
    @classmethod
    def _no_boolean_objectives(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(isinstance(item, bool) for item in value.values()):
            raise ValueError("optimization objective values must be numeric, not boolean")
        return value


class PromotionDecision(ContractBase):
    contract_type = "PromotionDecision"
    current_fidelity: FidelityLevel = FidelityLevel.ANALYTIC
    target_fidelity: FidelityLevel = FidelityLevel.REDUCED
    answerable_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    reason: str = ""
    comparison_metrics: dict[str, float | str] = Field(default_factory=dict)
    tolerances: dict[str, float | str] = Field(default_factory=dict)
    calibration_requirements: list[str] = Field(default_factory=list)


class RunSpec(ContractBase):
    contract_type = "RunSpec"
    operation: str = ""
    adapter: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(default_factory=list)
    timeout_s: int = Field(default=3600, ge=1, le=7 * 24 * 60 * 60)
    dry_run: bool = True
    worker_count: int = Field(default=1, ge=1)
    commercial_parallel_authorized: bool = False
    acceptance_criteria: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _worker_policy(self) -> RunSpec:
        if self.adapter in {"comsol", "lumerical", "matlab-comsol", "matlab-lumerical"}:
            enforce_commercial_concurrency(self.worker_count, self.commercial_parallel_authorized)
        return self


class ArtifactRecord(ContractBase):
    contract_type = "ArtifactRecord"
    relative_path: str = ""
    media_type: str = "application/octet-stream"
    byte_count: int = Field(default=0, ge=0)
    sha256: str | None = None
    immutable: bool = False
    parent_artifacts: list[str] = Field(default_factory=list)


class ProvenanceRecord(ContractBase):
    contract_type = "ProvenanceRecord"
    activity: str = ""
    tool: str = ""
    tool_version: str | None = None
    command_shape: list[str] = Field(default_factory=list)
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    transformations: list[dict[str, Any]] = Field(default_factory=list)


class AcceptanceCriterion(ContractBase):
    contract_type = "AcceptanceCriterion"
    metric: str = ""
    operator: str = ""
    threshold: float | str | None = None
    units: str | None = None
    evidence_level: str = ""


class AcceptanceResult(ContractBase):
    contract_type = "AcceptanceResult"
    criterion_id: str = ""
    passed: bool = False
    observed: float | str | None = None
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)


class RunManifest(ContractBase):
    contract_type = "RunManifest"
    run_spec_id: str = ""
    status: RunStatus = RunStatus.PLANNED
    execution_status: ExecutionStatus = ExecutionStatus.PLANNED
    acceptance_status: AcceptanceStatus = AcceptanceStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    error: str | None = None

    @staticmethod
    def _derived_status(
        execution_status: ExecutionStatus,
        acceptance_status: AcceptanceStatus,
    ) -> RunStatus:
        if acceptance_status == AcceptanceStatus.ACCEPTED:
            if execution_status != ExecutionStatus.SUCCEEDED:
                raise ValueError("accepted run must have succeeded execution")
            return RunStatus.ACCEPTED
        if acceptance_status == AcceptanceStatus.REJECTED:
            if execution_status != ExecutionStatus.SUCCEEDED:
                raise ValueError("rejected run must have succeeded execution")
            return RunStatus.REJECTED
        return RunStatus(execution_status.value)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_status(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        legacy_value = payload.get("status")
        legacy_status = RunStatus(legacy_value) if legacy_value is not None else None

        legacy_pairs = {
            RunStatus.PLANNED: (ExecutionStatus.PLANNED, AcceptanceStatus.PENDING),
            RunStatus.RUNNING: (ExecutionStatus.RUNNING, AcceptanceStatus.PENDING),
            RunStatus.SUCCEEDED: (ExecutionStatus.SUCCEEDED, AcceptanceStatus.PENDING),
            RunStatus.FAILED: (ExecutionStatus.FAILED, AcceptanceStatus.PENDING),
            RunStatus.CANCELLED: (ExecutionStatus.CANCELLED, AcceptanceStatus.PENDING),
            RunStatus.ACCEPTED: (ExecutionStatus.SUCCEEDED, AcceptanceStatus.ACCEPTED),
            RunStatus.REJECTED: (ExecutionStatus.SUCCEEDED, AcceptanceStatus.REJECTED),
        }
        if legacy_status is not None:
            legacy_execution, legacy_acceptance = legacy_pairs[legacy_status]
            payload.setdefault("execution_status", legacy_execution)
            payload.setdefault("acceptance_status", legacy_acceptance)

        acceptance_status = AcceptanceStatus(
            payload.get("acceptance_status", AcceptanceStatus.PENDING)
        )
        if "execution_status" in payload:
            execution_status = ExecutionStatus(payload["execution_status"])
        elif acceptance_status in {
            AcceptanceStatus.ACCEPTED,
            AcceptanceStatus.REJECTED,
        }:
            execution_status = ExecutionStatus.SUCCEEDED
        else:
            execution_status = ExecutionStatus.PLANNED

        derived_status = cls._derived_status(execution_status, acceptance_status)
        if legacy_status is not None and legacy_status != derived_status:
            raise ValueError(
                "legacy status conflicts with execution_status and acceptance_status"
            )
        payload["execution_status"] = execution_status
        payload["acceptance_status"] = acceptance_status
        payload["status"] = derived_status
        return payload


class GateRecord(ContractBase):
    contract_type = "GateRecord"
    gate: GateName = GateName.G0
    status: GateStatus = GateStatus.BLOCKED
    evidence: list[str] = Field(default_factory=list)
    metrics: dict[str, float | str] = Field(default_factory=dict)
    reason: str = ""
    next_action: str = ""

    @model_validator(mode="after")
    def _pass_requires_evidence(self) -> GateRecord:
        if self.status == GateStatus.PASS and not self.evidence:
            raise ValueError("a passing gate requires explicit evidence")
        return self


class CapabilityReport(ContractBase):
    contract_type = "CapabilityReport"
    capability: str = ""
    implementation: ImplementationStatus = ImplementationStatus.UNVERIFIED
    availability: AvailabilityStatus = AvailabilityStatus.UNVERIFIED
    version: str | None = None
    platform: str | None = None
    reasons: list[str] = Field(default_factory=list)
    features: dict[str, bool | str | int | float | None] = Field(default_factory=dict)
    probe_method: str = "none"


class AdapterDescriptor(ContractBase):
    contract_type = "AdapterDescriptor"
    adapter: str = ""
    adapter_spi_version: str = CURRENT_ADAPTER_SPI_VERSION
    contract_schema_versions: dict[str, str] = Field(default_factory=dict)
    implementation: ImplementationStatus = ImplementationStatus.PLANNED
    commercial: bool = False
    optional: bool = True
    version_sensitive: bool = True
    execution_modes: list[str] = Field(default_factory=list)
    input_contracts: list[str] = Field(default_factory=list)
    output_contracts: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    default_dry_run: bool = True
    default_concurrency: int = 1


class MatlabToolboxRecord(ContractBase):
    contract_type = "MatlabToolboxRecord"
    product_name: str = ""
    release: str | None = None
    version: str | None = None
    installed: bool = False
    license_verified: bool = False
    path_alias: str | None = None
    fingerprint: str | None = None


class MatlabEnvironmentReport(ContractBase):
    contract_type = "MatlabEnvironmentReport"
    availability: AvailabilityStatus = AvailabilityStatus.UNVERIFIED
    executable_alias: str = "matlab"
    root_alias: str | None = None
    release: str | None = None
    version: str | None = None
    platform: str | None = None
    architecture: str | None = None
    batch_capable: bool = False
    products: list[MatlabToolboxRecord] = Field(default_factory=list)
    engine_importable: bool = False
    engine_compatible: bool | None = None
    shared_session_count: int | None = None
    community_toolboxes: list[MatlabToolboxRecord] = Field(default_factory=list)
    comsol_livelink: AvailabilityStatus = AvailabilityStatus.UNVERIFIED
    lumerical_api: AvailabilityStatus = AvailabilityStatus.UNVERIFIED
    instrument_control: AvailabilityStatus = AvailabilityStatus.UNVERIFIED
    simulink: AvailabilityStatus = AvailabilityStatus.UNVERIFIED
    redacted: bool = True


class MatlabRunSpec(RunSpec):
    contract_type = "MatlabRunSpec"
    adapter: str = "matlab"
    execution_model: str = "batch"
    entrypoint_id: Literal["photonic.environment.validate.v1"] = (
        "photonic.environment.validate.v1"
    )
    run_spec_path: str = ""
    result_path: str = ""
    runtime_directory: str = ""
    matlab_paths: list[str] = Field(default_factory=list)
    toolbox_requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_entry_function(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "entry_function" not in payload:
            return payload
        legacy_entry = payload.pop("entry_function")
        if legacy_entry != "photonic.entry":
            raise ValueError(
                "entry_function is not executable input; only the legacy "
                "'photonic.entry' alias is accepted"
            )
        registered_id = "photonic.environment.validate.v1"
        if payload.get("entrypoint_id", registered_id) != registered_id:
            raise ValueError("legacy entry_function conflicts with entrypoint_id")
        payload["entrypoint_id"] = registered_id
        return payload


class MatlabResultManifest(ContractBase):
    contract_type = "MatlabResultManifest"
    run_id: str = ""
    execution_status: ExecutionStatus = ExecutionStatus.PLANNED
    exit_code: int | None = None
    duration_s: float | None = None
    matlab_release: str | None = None
    toolbox_versions: dict[str, str] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    log_path: str | None = None


from .adoption import (  # noqa: E402
    BACKEND_ADOPTION_DEFINITIONS,
    BackendAdoptionCheck,
    BackendAdoptionCheckRecord,
    BackendAdoptionDefinition,
    BackendAdoptionGateRecord,
    BackendAdoptionPhase,
    BackendAdoptionTarget,
)

MODEL_CLASSES: tuple[type[ContractBase], ...] = (
    ProjectConfig,
    ProjectIdentity,
    DesignIntent,
    DeviceContract,
    DesignVariant,
    LogicalNetlist,
    ExtractedNetlist,
    SimulationNetlist,
    Instance,
    Connection,
    PortContract,
    ComponentContract,
    PCellContract,
    ModelCard,
    MultiPhysicsModelCard,
    SParameterDataset,
    SParameterMetadata,
    CircuitManifest,
    LayoutManifest,
    PdkManifest,
    TechnologyStack,
    LayerDefinition,
    CrossSection,
    ProcessCorner,
    StatisticalVariationModel,
    PackagingConstraint,
    TestPlan,
    TapeoutManifest,
    MeasurementManifest,
    OptimizationSpec,
    OptimizationTrial,
    PromotionDecision,
    RunSpec,
    RunManifest,
    ArtifactRecord,
    ProvenanceRecord,
    AcceptanceCriterion,
    AcceptanceResult,
    GateRecord,
    CapabilityReport,
    AdapterDescriptor,
    MatlabEnvironmentReport,
    MatlabToolboxRecord,
    MatlabRunSpec,
    MatlabResultManifest,
    BackendAdoptionCheckRecord,
    BackendAdoptionGateRecord,
)
MODEL_REGISTRY: dict[str, type[ContractBase]] = {model.contract_type: model for model in MODEL_CLASSES}
if len(MODEL_REGISTRY) != len(MODEL_CLASSES):
    raise RuntimeError("MODEL_CLASSES contains duplicate contract_type values")


def validate_contract_model_versions(
    model_classes: tuple[type[ContractBase], ...],
) -> None:
    """Fail fast when a model version and its construction default diverge.

    A single contract type may advance independently. Such a model must
    override both ``current_schema_version`` and the ``schema_version`` field
    default; this invariant prevents new internal instances from silently
    retaining the previous version.
    """

    for model_class in model_classes:
        field = model_class.model_fields["schema_version"]
        if field.default != model_class.current_schema_version:
            raise RuntimeError(
                f"{model_class.contract_type} current_schema_version "
                f"{model_class.current_schema_version!r} does not match its "
                f"schema_version default {field.default!r}; override both"
            )


def current_contract_schema_versions(
    contract_types: list[str] | tuple[str, ...] | set[str],
) -> dict[str, str]:
    """Return canonical per-contract versions for an adapter boundary."""

    versions: dict[str, str] = {}
    for contract_type in sorted(set(contract_types)):
        model_class = MODEL_REGISTRY.get(contract_type)
        if model_class is None:
            raise ValueError(f"unknown contract_type: {contract_type!r}")
        versions[contract_type] = model_class.current_schema_version
    return versions


validate_contract_model_versions(MODEL_CLASSES)

__all__ = [
    "AcceptanceStatus",
    "AvailabilityStatus",
    "BACKEND_ADOPTION_DEFINITIONS",
    "BaseNetlist",
    "BackendAdoptionCheck",
    "BackendAdoptionDefinition",
    "BackendAdoptionPhase",
    "BackendAdoptionTarget",
    "ContractBase",
    "ExecutionStatus",
    "FidelityLevel",
    "GateName",
    "GateStatus",
    "ImplementationStatus",
    "MODEL_CLASSES",
    "MODEL_REGISTRY",
    "RunStatus",
    "TimeConvention",
    "Validity",
    "WorkflowProfile",
    "current_contract_schema_versions",
    "utc_now",
    "validate_contract_model_versions",
    *(model.__name__ for model in MODEL_CLASSES),
]
