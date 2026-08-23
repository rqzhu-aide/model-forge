"""Fail-closed resolution of exact orchestration adapters."""

from __future__ import annotations

from collections.abc import Iterable

from .protocol import (
    OrchestrationBinding,
    OrchestratorRegistryError,
    PhaseOrchestrator,
)


class OrchestratorRegistry:
    """Startup registry keyed by exact adapter identity and version."""

    def __init__(self, orchestrators: Iterable[PhaseOrchestrator] = ()) -> None:
        self._orchestrators: dict[tuple[str, str], PhaseOrchestrator] = {}
        for orchestrator in orchestrators:
            self.register(orchestrator)

    def register(self, orchestrator: PhaseOrchestrator) -> None:
        key = (str(orchestrator.adapter_id), str(orchestrator.adapter_version))
        if key in self._orchestrators:
            raise OrchestratorRegistryError(
                "orchestration.duplicate_adapter",
                f"Adapter {key[0]!r} version {key[1]!r} is already registered.",
            )
        self._orchestrators[key] = orchestrator

    def resolve(self, binding: OrchestrationBinding) -> PhaseOrchestrator:
        key = (str(binding.adapter_id), str(binding.adapter_version))
        orchestrator = self._orchestrators.get(key)
        if orchestrator is None:
            raise OrchestratorRegistryError(
                "orchestration.adapter_not_found",
                f"No adapter is registered for {key[0]!r} version {key[1]!r}.",
            )
        if not orchestrator.supports(binding):
            raise OrchestratorRegistryError(
                "orchestration.binding_not_supported",
                f"Adapter {key[0]!r} version {key[1]!r} does not support the "
                "exact frozen workflow binding.",
            )
        return orchestrator

    def __len__(self) -> int:
        return len(self._orchestrators)


__all__ = ["OrchestratorRegistry"]
