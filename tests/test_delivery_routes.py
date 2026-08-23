from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from model_forge.api import create_app
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.digests.jcs import canonicalize
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository, ZERO_SHA256


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-08-02T12:00:00Z"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _service(
    tmp_path: Path,
) -> tuple[ModelForgeService, HubRepository, ArtifactStore]:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    artifacts = ArtifactStore(workspace)
    service = ModelForgeService(
        settings=ApplicationSettings(data_root=workspace.root),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=artifacts,
        role_resources=RoleResourceCatalog.load(ROOT / "resources" / "team"),
    )
    return service, repository, artifacts


def _record_run(repository: HubRepository, project_id: str) -> tuple[str, str]:
    request_id = "request.delivery"
    command_id = "command.delivery"
    run_id = "run.delivery"
    repository.record_raw_command(
        request_id,
        project_id,
        _sha(b"request"),
        {"kind": "delivery test request"},
        received_at=NOW,
    )
    repository.seal_command(
        command_id,
        project_id,
        request_id,
        "delivery-key",
        _sha(b"command"),
        {"kind": "delivery test command"},
        sealed_at=NOW,
    )
    repository.create_run(
        run_id,
        project_id,
        command_id,
        "submitted",
        {"phase": "P1", "mode": "p1.broad_update"},
        "event.delivery.created",
        _sha(b"run created"),
        {"event_type": "run.created"},
        recorded_at=NOW,
    )
    return run_id, command_id


def _record_receipt(
    repository: HubRepository, project_id: str, run_id: str, command_id: str
) -> tuple[str, str]:
    receipt_id = "receipt.delivery"
    event_document = {"event_id": "authority.delivery", "change": "test"}
    event_sha256 = _sha(canonicalize(event_document))
    new_root = _sha(bytes.fromhex(ZERO_SHA256) + bytes.fromhex(event_sha256))
    unsigned = {
        "format": "model-forge.publication-receipt",
        "format_version": "1.0.0",
        "receipt_id": receipt_id,
        "project_id": project_id,
        "run_id": run_id,
        "command_id": command_id,
        "phase": "P1",
        "record_changes": [],
        "cumulative_object_changes": [],
        "authority_events": [event_document],
        "prior_authority_sequence": 0,
        "new_authority_sequence": 1,
        "prior_authority_root_sha256": ZERO_SHA256,
        "new_authority_root_sha256": new_root,
        "prior_current_revision": 0,
        "new_current_revision": 1,
        "atomic": True,
        "published_at": NOW,
    }
    receipt_sha256 = _sha(canonicalize(unsigned))
    document = {**unsigned, "content_sha256": receipt_sha256}
    with repository.publication_transaction(
        project_id,
        receipt_id,
        0,
        ZERO_SHA256,
        expected_current_revision=0,
    ) as publication:
        publication.append_authority_event(
            "authority.delivery",
            "delivery_test",
            event_sha256,
            new_root,
            event_document,
            committed_at=NOW,
        )
        publication.record_receipt(
            receipt_sha256,
            document,
            run_id=run_id,
            command_id=command_id,
            committed_at=NOW,
        )
    return receipt_id, receipt_sha256


def test_delivery_routes_verify_bytes_receipts_and_project_scope(tmp_path: Path) -> None:
    service, repository, artifacts = _service(tmp_path)
    repository.create_project("project.delivery", {"name": "Delivery"}, created_at=NOW)
    repository.create_project("project.other", {"name": "Other"}, created_at=NOW)

    artifact_bytes = b'{"finding":"verified"}\n'
    stored = artifacts.put_bytes(artifact_bytes)
    repository.record_artifact(
        "artifact.delivery",
        "project.delivery",
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {"kind": "test"},
        recorded_at=NOW,
    )
    active_bytes = b"<html><script>window.test = true</script></html>"
    active_stored = artifacts.put_bytes(active_bytes)
    repository.record_artifact(
        "artifact.active",
        "project.delivery",
        str(active_stored.sha256),
        active_stored.size,
        "text/html",
        f"artifact://sha256/{active_stored.sha256}",
        {"kind": "active content test"},
        recorded_at=NOW,
    )
    run_id, command_id = _record_run(repository, "project.delivery")
    receipt_id, receipt_sha256 = _record_receipt(
        repository, "project.delivery", run_id, command_id
    )
    client = TestClient(create_app(service))

    artifact = client.get(
        "/api/v1/projects/project.delivery/artifacts/artifact.delivery"
    )
    receipt = client.get(
        f"/api/v1/projects/project.delivery/publications/{receipt_id}"
    )
    active = client.get(
        "/api/v1/projects/project.delivery/artifacts/artifact.active"
    )
    hidden_artifact = client.get(
        "/api/v1/projects/project.other/artifacts/artifact.delivery"
    )
    hidden_receipt = client.get(
        f"/api/v1/projects/project.other/publications/{receipt_id}"
    )

    assert artifact.status_code == 200
    assert artifact.content == artifact_bytes
    assert artifact.headers["x-content-sha256"] == str(stored.sha256)
    assert receipt.status_code == 200
    assert receipt.json()["content_sha256"] == receipt_sha256
    assert active.content == active_bytes
    assert active.headers["content-type"] == "application/octet-stream"
    assert active.headers["content-disposition"].startswith("attachment;")
    assert hidden_artifact.status_code == 404
    assert hidden_artifact.json()["code"] == "TARGET_NOT_FOUND"
    assert hidden_receipt.status_code == 404
    assert hidden_receipt.json()["code"] == "TARGET_NOT_FOUND"
