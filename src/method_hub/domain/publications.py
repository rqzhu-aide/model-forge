"""Formal-generation and publication projections used by the application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .identities import ArtifactPointer, MethodIdentity, StableId
from .runs import isoformat_utc, thaw_json


@dataclass(frozen=True, slots=True)
class FormalGeneration:
    generation_id: StableId
    project_id: StableId
    record_type: str
    artifact: ArtifactPointer
    source_run_id: StableId | None
    published_at: datetime
    logical_slot: str | None = None
    method_identity: MethodIdentity | None = None
    supersedes_generation_id: StableId | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": str(self.generation_id),
            "project_id": str(self.project_id),
            "record_type": self.record_type,
            "logical_slot": self.logical_slot,
            "artifact": self.artifact.to_dict(),
            "source_run_id": str(self.source_run_id) if self.source_run_id else None,
            "method_identity": self.method_identity.to_dict() if self.method_identity else None,
            "supersedes_generation_id": (
                str(self.supersedes_generation_id) if self.supersedes_generation_id else None
            ),
            "published_at": isoformat_utc(self.published_at),
        }


@dataclass(frozen=True, slots=True)
class PublicationReceiptView:
    receipt_id: StableId
    project_id: StableId
    run_id: StableId
    phase: str
    committed_at: datetime
    generations: tuple[FormalGeneration, ...]
    collection_appends: Mapping[str, tuple[str, ...]]
    prior_current: Mapping[str, str | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": str(self.receipt_id),
            "project_id": str(self.project_id),
            "run_id": str(self.run_id),
            "phase": self.phase,
            "committed_at": isoformat_utc(self.committed_at),
            "generations": [item.to_dict() for item in self.generations],
            "collection_appends": thaw_json(self.collection_appends),
            "prior_current": thaw_json(self.prior_current),
        }


__all__ = ["FormalGeneration", "PublicationReceiptView"]
