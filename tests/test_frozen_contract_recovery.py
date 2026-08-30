"""Frozen-contract recovery for runs sealed under superseded contract versions.

Regression coverage for the production failure of 2026-08-28: a P4 run sealed
under contract 2.3.0 could not be corrected after the registry moved to 2.5.0,
because plan resolution only consulted the live registry. The fix preserves the
exact contract bytes at seal time and resolves orphaned runs from them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from model_forge.application.run_coordinator import RunCoordinator
from model_forge.digests.jcs import canonicalize
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def specification() -> SpecificationPackage:
    return SpecificationPackage.load(ROOT / "architecture")


@pytest.fixture
def stores(tmp_path: Path):
    paths = WorkspacePaths(tmp_path / "workspace", create=True)
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project("prj_frozen", {"name": "Frozen contract test"})
    artifacts = ArtifactStore(paths)
    return repository, artifacts


def _recipe_document(specification: SpecificationPackage, *, stale_version: str) -> dict:
    identity = specification.phases.identity("P1")
    return {
        "phase": "P1",
        "mode": "p1.literature_update",
        "phase_contract_version": stale_version,
        "phase_contract_sha256": str(identity.phase_contract_sha256),
        "project_id": "prj_frozen",
        "user_request": {
            "choice_values": {
                "p1.instructions": "Continue the literature sweep.",
                "p1.scope": "broad_update",
            },
            "context_policy": "current_only",
        },
    }


def test_frozen_contract_resolves_after_registry_bump(
    specification: SpecificationPackage, stores
) -> None:
    repository, artifacts = stores
    document = specification.phases.contract_document("P1")
    identity = specification.phases.identity("P1")
    stored = artifacts.put_bytes(canonicalize(document))
    repository.record_artifact(
        "artifact.phase_contract.test",
        "prj_frozen",
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {"purpose": "phase_contract_frozen", "phase_id": "P1"},
    )

    coordinator = RunCoordinator.__new__(RunCoordinator)
    coordinator.specification = specification
    coordinator.repository = repository
    coordinator.artifacts = artifacts

    class _Recipe:
        document = _recipe_document(specification, stale_version="0.0.0-superseded")

    recovered = coordinator._recover_frozen_contract(_Recipe())
    assert recovered == document

    plan = coordinator._plan_from_recipe(_Recipe())
    assert plan.mode_id == "p1.literature_update"
    assert str(plan.identity.phase_contract_sha256) == str(identity.phase_contract_sha256)


def test_frozen_contract_recovery_rejects_tampered_bytes(
    specification: SpecificationPackage, stores
) -> None:
    repository, artifacts = stores
    document = specification.phases.contract_document("P1")
    tampered = dict(document)
    tampered["contract_version"] = "99.0.0"  # digest no longer matches the pin
    stored = artifacts.put_bytes(canonicalize(tampered))
    repository.record_artifact(
        "artifact.phase_contract.tampered",
        "prj_frozen",
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {"purpose": "phase_contract_frozen", "phase_id": "P1"},
    )

    coordinator = RunCoordinator.__new__(RunCoordinator)
    coordinator.specification = specification
    coordinator.repository = repository
    coordinator.artifacts = artifacts

    class _Recipe:
        document = _recipe_document(specification, stale_version="0.0.0-superseded")

    assert coordinator._recover_frozen_contract(_Recipe()) is None
    with pytest.raises(ValueError, match="Frozen phase contract is unavailable"):
        coordinator._plan_from_recipe(_Recipe())


def test_resolve_frozen_rejects_unknown_phase(specification: SpecificationPackage) -> None:
    with pytest.raises(Exception, match="Unknown phase contract"):
        specification.resolve_phase_frozen(
            {"phase_id": "P9", "contract_version": "1.0.0"},
            "p1.literature_update",
            {},
            "current_only",
        )


def test_seal_time_preservation_stores_pinned_bytes(
    specification: SpecificationPackage, stores
) -> None:
    repository, artifacts = stores
    coordinator = RunCoordinator.__new__(RunCoordinator)
    coordinator.specification = specification
    coordinator.repository = repository
    coordinator.artifacts = artifacts

    coordinator._preserve_frozen_contract("prj_frozen", "P1")
    # Idempotent: a second seal of the same contract records nothing new.
    coordinator._preserve_frozen_contract("prj_frozen", "P1")

    rows = repository.find_artifacts_by_purpose("prj_frozen", "phase_contract_frozen")
    assert len(rows) == 1
    document = json.loads(artifacts.read_bytes(str(rows[0]["sha256"])))
    identity = specification.phases.identity("P1")
    assert (
        specification.digests.compute("phase_contract.content", document)
        == str(identity.phase_contract_sha256)
    )


def test_backfill_preserves_recoverable_manifests_only(
    specification: SpecificationPackage, stores
) -> None:
    """Manifests sealed before the preservation feature get their frozen
    contract bytes at startup when the pinned digest still matches the
    loaded registry; unknown or stale pins are left untouched."""
    repository, artifacts = stores
    coordinator = RunCoordinator.__new__(RunCoordinator)
    coordinator.specification = specification
    coordinator.repository = repository
    coordinator.artifacts = artifacts

    # The stores fixture already creates the "prj_frozen" project.
    raw = repository.record_raw_command(
        "request.backfill", "prj_frozen", "a" * 64, {"artifact": "raw"}
    )
    identity = specification.phases.identity("P1")
    documents = [
        # Recoverable: pinned digest matches the loaded registry.
        {
            "project_id": "prj_frozen",
            "phase": "P1",
            "phase_contract_sha256": str(identity.phase_contract_sha256),
        },
        # Unrecoverable: pinned digest matches nothing we hold.
        {
            "project_id": "prj_frozen",
            "phase": "P1",
            "phase_contract_sha256": "f" * 64,
        },
        # Malformed: missing fields.
        {"project_id": "prj_frozen"},
    ]
    for index, document in enumerate(documents):
        repository.seal_command(
            f"command.backfill.{index}",
            "prj_frozen",
            raw.row["request_id"],
            f"request-backfill-{index}",
            "b" * 64,
            {"command_id": f"command.backfill.{index}"},
        )
        repository.create_run(
            f"run.backfill.{index}",
            "prj_frozen",
            f"command.backfill.{index}",
            "published",
            {"phase": document.get("phase", "P1")},
            f"event.backfill.{index}",
            "c" * 64,
            {"event_type": "run.published"},
        )
    with repository.database.connect() as connection:
        for index, document in enumerate(documents):
            connection.execute(
                "INSERT INTO run_manifests (run_id, manifest_sha256,"
                " payload_json, sealed_at) VALUES (?, ?, ?, ?)",
                (
                    f"run.backfill.{index}",
                    hashlib.sha256(json.dumps(document).encode()).hexdigest(),
                    json.dumps(document),
                    "2026-08-28T00:00:00Z",
                ),
            )

    assert coordinator.backfill_frozen_contracts() == 1
    rows = repository.find_artifacts_by_purpose(
        "prj_frozen", "phase_contract_frozen"
    )
    assert len(rows) == 1
    # Idempotent: a second startup backfill preserves nothing new.
    assert coordinator.backfill_frozen_contracts() == 0
