from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from method_hub.contracts import PhaseContractRepository
from method_hub.digests import DigestContractRegistry
from method_hub.harness.publication import (
    ContractPublicationService,
    FrozenPublicationHead,
    PreparedPublisherTransform,
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from method_hub.schemas import SchemaCatalog
from method_hub.storage.repository import HubRepository, ZERO_SHA256


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
NOW = datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _register(
    repository: HubRepository, output_id: str, document: object
) -> RegisteredValidatedOutput:
    raw = (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
    digest = _sha(raw)
    artifact = RegisteredArtifactMetadata(
        artifact_id=f"artifact.{output_id.replace('.', '_')}",
        sha256=digest,
        byte_length=len(raw),
        media_type="application/json",
        storage_uri=f"artifact://sha256/{digest}",
    )
    repository.record_artifact(
        artifact.artifact_id,
        "project.plan",
        digest,
        len(raw),
        artifact.media_type,
        artifact.storage_uri,
        {"output_id": output_id},
        recorded_at=NOW,
    )
    return RegisteredValidatedOutput(output_id, document, artifact)


def test_resolved_phase_plan_is_accepted_without_thawing_frozen_bindings(
    tmp_path: Path,
) -> None:
    schemas = SchemaCatalog.load(ARCHITECTURE / "schemas")
    digests = DigestContractRegistry.load(
        ARCHITECTURE / "contracts" / "digest-contracts.json", schemas
    )
    contracts = PhaseContractRepository.load(ARCHITECTURE, schemas, digests)
    plan = contracts.resolve(
        contracts.identity("P1"),
        "p1.literature_update",
        {"p1.scope": "broad_update", "p1.instructions": "Update literature."},
        "current_only",
    )

    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project("project.plan", {"name": "Plan source"})
    repository.record_raw_command(
        "request.plan", "project.plan", _sha(b"raw"), {"request": "plan"}
    )
    repository.seal_command(
        "command.plan",
        "project.plan",
        "request.plan",
        "idempotency.plan",
        _sha(b"command"),
        {"command": "plan"},
    )
    repository.create_run(
        "run.plan",
        "project.plan",
        "command.plan",
        "submitted",
        {"state": "submitted"},
        "event.plan",
        _sha(b"event"),
        {"to": "submitted"},
        recorded_at=NOW,
    )

    outputs = {
        "p1.attention_items": _register(
            repository, "p1.attention_items", [{"attention": "coverage gap"}]
        ),
        "p1.source_changes": _register(
            repository, "p1.source_changes", [{"source_id": "source.alpha"}]
        ),
        "p1.synthesis_candidate": _register(
            repository, "p1.synthesis_candidate", {"synthesis": "Mixed evidence"}
        ),
        "p1.coverage_candidate": _register(
            repository, "p1.coverage_candidate", {"coverage": "partial"}
        ),
        "p1.decision": _register(
            repository, "p1.decision", {"decision": "Continue discovery"}
        ),
    }
    reduced = _register(
        repository,
        "prepared.p1.library",
        {"source_ids": ["source.alpha"]},
    )
    transform = PreparedPublisherTransform(
        publication_binding_id="p1.rebuild_literature_library",
        transform="deterministic_index",
        document=reduced.document,
        artifact=reduced.artifact,
        source_output_sha256={
            "p1.source_changes": outputs["p1.source_changes"].document_sha256
        },
    )

    result = ContractPublicationService(repository).publish(
        project_id="project.plan",
        run_id="run.plan",
        command_id="command.plan",
        bindings=plan,
        outputs=outputs,
        expected_head=FrozenPublicationHead(
            authority_sequence=0,
            authority_root_sha256=ZERO_SHA256,
            current_revision=0,
            current_generations={
                "p1.literature_library.current": None,
                "p1.literature_synthesis.current": None,
                "p1.literature_coverage.current": None,
                "p1.phase_decision.current": None,
            },
        ),
        prepared_transforms={
            "p1.rebuild_literature_library": transform,
        },
        published_at=NOW,
    )

    assert len(result.generation_ids) == 4
    assert len(result.collection_item_ids) == 2
    assert result.new_authority_sequence == 6
