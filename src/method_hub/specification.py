"""Integrated loader for the immutable greenfield specification package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import PhaseContractRepository, ResolvedPhasePlan
from .digests import DigestContractRegistry
from .domain import PhaseContractIdentity
from .schemas import SchemaCatalog


@dataclass(frozen=True, slots=True)
class SpecificationPackage:
    """Validated schemas, digest contracts, and executable phase contracts."""

    architecture_root: Path
    schemas: SchemaCatalog
    digests: DigestContractRegistry
    phases: PhaseContractRepository

    @classmethod
    def load(cls, architecture_root: str | Path) -> "SpecificationPackage":
        root = Path(architecture_root).resolve()
        schemas = SchemaCatalog.load(root / "schemas")
        digests = DigestContractRegistry.load(
            root / "contracts" / "digest-contracts.json",
            schemas,
        )
        phases = PhaseContractRepository.load(root, schemas, digests)
        return cls(
            architecture_root=root,
            schemas=schemas,
            digests=digests,
            phases=phases,
        )

    def resolve_phase(
        self,
        identity: PhaseContractIdentity,
        mode_id: str,
        choice_values: Mapping[str, Any],
        context_policy: str,
    ) -> ResolvedPhasePlan:
        return self.phases.resolve(
            identity,
            mode_id,
            choice_values,
            context_policy,
        )


__all__ = ["SpecificationPackage"]
