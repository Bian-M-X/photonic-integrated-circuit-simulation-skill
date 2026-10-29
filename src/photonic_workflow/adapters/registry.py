from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from photonic_workflow.compatibility import (
    ADAPTER_ENTRY_POINT_GROUP,
    CURRENT_ADAPTER_SPI_VERSION,
)
from photonic_workflow.exceptions import InvalidInputError
from photonic_workflow.models.contracts import (
    MODEL_REGISTRY,
    AdapterDescriptor,
    ProjectConfig,
)

from .base import Adapter

AdapterFactory = Callable[..., Adapter]


@dataclass(frozen=True)
class AdapterRegistration:
    """One descriptor and its optional runtime factory."""

    descriptor: AdapterDescriptor
    factory: AdapterFactory | None = None
    spi_version: str = CURRENT_ADAPTER_SPI_VERSION


@dataclass(frozen=True)
class LoadedAdapterProvider:
    """Auditable identity for explicitly imported provider code."""

    name: str
    target: str | None = None
    distribution: str | None = None
    distribution_version: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "target": self.target,
            "distribution": self.distribution,
            "distribution_version": self.distribution_version,
        }


def _provider_registrations(
    provider: object,
    *,
    provider_name: str,
) -> tuple[AdapterRegistration, ...]:
    if not callable(provider):
        raise InvalidInputError(
            f"adapter provider {provider_name!r} is not callable"
        )
    try:
        supplied = provider()
    except Exception as exc:
        raise InvalidInputError(
            f"adapter provider {provider_name!r} failed: {exc}"
        ) from exc
    if not isinstance(supplied, tuple):
        raise InvalidInputError(
            f"adapter provider {provider_name!r} must return a tuple"
        )
    if not supplied:
        raise InvalidInputError(
            f"adapter provider {provider_name!r} returned no registrations"
        )
    if not all(isinstance(item, AdapterRegistration) for item in supplied):
        raise InvalidInputError(
            f"adapter provider {provider_name!r} returned an invalid registration"
        )
    if any(item.factory is not None for item in supplied):
        raise InvalidInputError(
            "third-party adapter SPI 1.0 is descriptor-only; provider factories "
            "are not an executable ABI"
        )
    return supplied


class AdapterRegistry:
    """Descriptor-first registry.

    Planned adapters may publish a descriptor without exposing a factory. This
    keeps roadmap visibility separate from executable availability.
    """

    def __init__(self) -> None:
        self._descriptors: dict[str, AdapterDescriptor] = {}
        self._factories: dict[str, AdapterFactory] = {}
        self._loaded_providers: list[LoadedAdapterProvider] = []

    def register(self, registration: AdapterRegistration) -> None:
        self.register_many((registration,))

    def register_many(self, registrations: Iterable[AdapterRegistration]) -> None:
        pending = tuple(registrations)
        descriptor_names = set(self._descriptors)
        factory_names = set(self._factories)
        for registration in pending:
            if not isinstance(registration, AdapterRegistration):
                raise InvalidInputError("invalid adapter registration")
            if registration.spi_version != CURRENT_ADAPTER_SPI_VERSION:
                raise InvalidInputError(
                    f"adapter registration SPI {registration.spi_version!r} is incompatible; "
                    f"expected {CURRENT_ADAPTER_SPI_VERSION!r}"
                )
            descriptor = registration.descriptor
            if descriptor.adapter_spi_version != registration.spi_version:
                raise InvalidInputError(
                    f"adapter {descriptor.adapter!r} descriptor SPI "
                    "does not match its registration"
                )
            declared_contracts = set(
                descriptor.input_contracts + descriptor.output_contracts
            )
            if set(descriptor.contract_schema_versions) != declared_contracts:
                raise InvalidInputError(
                    f"adapter {descriptor.adapter!r} must declare one canonical "
                    "schema version for every input/output contract"
                )
            for contract_type in sorted(declared_contracts):
                model_class = MODEL_REGISTRY.get(contract_type)
                if model_class is None:
                    raise InvalidInputError(
                        f"adapter {descriptor.adapter!r} references unknown "
                        f"contract_type {contract_type!r}"
                    )
                actual_version = descriptor.contract_schema_versions[contract_type]
                if actual_version != model_class.current_schema_version:
                    raise InvalidInputError(
                        f"adapter {descriptor.adapter!r} contract schema for "
                        f"{contract_type} is {actual_version!r}; expected "
                        f"{model_class.current_schema_version!r}"
                    )
            if descriptor.adapter in descriptor_names:
                raise InvalidInputError(
                    f"adapter descriptor is already registered: {descriptor.adapter}"
                )
            descriptor_names.add(descriptor.adapter)
            if registration.factory is not None:
                if not callable(registration.factory):
                    raise InvalidInputError(
                        f"adapter factory is not callable: {descriptor.adapter}"
                    )
                if descriptor.adapter in factory_names:
                    raise InvalidInputError(
                        f"adapter factory is already registered: {descriptor.adapter}"
                    )
                factory_names.add(descriptor.adapter)

        for registration in pending:
            name = registration.descriptor.adapter
            self._descriptors[name] = registration.descriptor
            if registration.factory is not None:
                self._factories[name] = registration.factory

    def descriptor(self, name: str) -> AdapterDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as exc:
            raise InvalidInputError(f"unknown adapter: {name}") from exc

    def descriptors(self) -> tuple[AdapterDescriptor, ...]:
        return tuple(self._descriptors[name] for name in sorted(self._descriptors))

    def has_factory(self, name: str) -> bool:
        return name in self._factories

    def loaded_entry_points(self) -> tuple[str, ...]:
        return tuple(provider.name for provider in self._loaded_providers)

    def loaded_providers(self) -> tuple[LoadedAdapterProvider, ...]:
        return tuple(self._loaded_providers)

    def create(self, name: str, **kwargs: Any) -> Adapter:
        self.descriptor(name)
        try:
            factory = self._factories[name]
        except KeyError as exc:
            raise InvalidInputError(
                f"adapter {name!r} publishes a descriptor but has no Phase-A runtime factory"
            ) from exc
        adapter = factory(**kwargs)
        if not isinstance(adapter, Adapter):
            raise InvalidInputError(
                f"adapter factory {name!r} did not return an Adapter instance"
            )
        if adapter.descriptor != self._descriptors[name]:
            raise InvalidInputError(
                f"adapter factory {name!r} returned a descriptor that does not "
                "match its registration"
            )
        return adapter

    def load_entrypoint_adapters(
        self,
        allowed_entry_points: Iterable[str],
        *,
        entry_points_reader: Callable[..., Any] = importlib.metadata.entry_points,
    ) -> tuple[str, ...]:
        """Load explicitly allowlisted third-party adapter providers.

        Entry-point loading imports third-party Python code. It is therefore
        never called by ``default_adapter_registry`` and requires a concrete
        allowlist from the embedding application.
        """

        allowed = {name for name in allowed_entry_points if name}
        if not allowed:
            return ()
        discovered = entry_points_reader(group=ADAPTER_ENTRY_POINT_GROUP)
        selected = sorted(
            (entry_point for entry_point in discovered if entry_point.name in allowed),
            key=lambda entry_point: entry_point.name,
        )
        selected_names = [entry_point.name for entry_point in selected]
        if len(selected_names) != len(set(selected_names)):
            raise InvalidInputError(
                "multiple adapter entry points use the same allowlisted name"
            )
        missing = sorted(allowed - set(selected_names))
        if missing:
            raise InvalidInputError(
                "allowlisted adapter entry points were not found: " + ", ".join(missing)
            )

        loaded: list[LoadedAdapterProvider] = []
        pending_registrations: list[AdapterRegistration] = []
        for entry_point in selected:
            try:
                provider = entry_point.load()
                registrations = _provider_registrations(
                    provider,
                    provider_name=entry_point.name,
                )
            except Exception as exc:
                raise InvalidInputError(
                    f"failed to load adapter entry point {entry_point.name!r}: {exc}"
                ) from exc
            pending_registrations.extend(registrations)
            distribution = getattr(entry_point, "dist", None)
            loaded.append(
                LoadedAdapterProvider(
                    name=entry_point.name,
                    target=getattr(entry_point, "value", None),
                    distribution=getattr(distribution, "name", None),
                    distribution_version=getattr(distribution, "version", None),
                )
            )
        self.register_many(pending_registrations)
        self._loaded_providers.extend(loaded)
        return tuple(provider.name for provider in loaded)


def default_adapter_registry() -> AdapterRegistry:
    from .descriptors import EXTERNAL_ADAPTER_DESCRIPTORS
    from .lumerical import LumericalAdapter
    from .matlab.descriptors import MATLAB_ADAPTER_DESCRIPTORS
    from .matlab.engine import MatlabEngineAdapter
    from .matlab.runtime import MatlabRuntimeAdapter

    registry = AdapterRegistry()
    for descriptor in (*EXTERNAL_ADAPTER_DESCRIPTORS, *MATLAB_ADAPTER_DESCRIPTORS):
        factory = {
            "lumerical": LumericalAdapter,
            "matlab-runtime": MatlabRuntimeAdapter,
            "matlab-engine": MatlabEngineAdapter,
        }.get(descriptor.adapter)
        registry.register(AdapterRegistration(descriptor, factory))
    return registry


def registry_for_project(
    config: ProjectConfig,
    *,
    load_entry_points: bool = False,
    entry_points_reader: Callable[..., Any] = importlib.metadata.entry_points,
) -> AdapterRegistry:
    """Build the project registry without implicit third-party imports."""

    registry = default_adapter_registry()
    if load_entry_points:
        registry.load_entrypoint_adapters(
            config.adapter_entrypoint_allowlist,
            entry_points_reader=entry_points_reader,
        )
    return registry
