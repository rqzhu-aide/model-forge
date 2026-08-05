"""WP-F0 API tests: supervised-run read surface (list + detail endpoints).

Builds fixture state exactly as the WP-D/E tests do — sealing through
``RunProfileAssembler.seal_invocation`` and recording launch, validation,
and promotion rows through ``RunSealStore`` directly — over the SAME
``<data_root>/hub.sqlite3`` that the application service's lazy
``run_seal_store`` opens (``MethodHubService.run_seal_store`` resolves
``settings.data_root / "hub.sqlite3"``), so the HTTP surface reads the
seeded durable state.

Covers: list summaries with digest-verified manifest fields; the full
detail view (manifest summary, launch records, validation report,
promotion records); project-scoped 404 for an invocation sealed under a
different project id; empty list for a project without supervised runs;
empty list (not an error) when no hub.sqlite3 exists at all; and the
digest-verification behavior of ``read_manifest_document`` when the
stored manifest bytes no longer match the registry digest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from method_hub.api import create_app
from method_hub.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    RunSealStore,
    SealedRun,
)
from method_hub.application.service import MethodHubService
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.domain.runs import isoformat_utc, utc_now
from method_hub.profiles.project_profiles import MemoryPolicy
from method_hub.specification import SpecificationPackage
from method_hub.storage.artifacts import ArtifactStore
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS
from method_hub.storage.paths import WorkspacePaths
from method_hub.storage.repository import HubRepository

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

FAKE_HERMES = HermesProbe("/fake/hermes", "9.9.9")

PROJECT = "proj-001"
OTHER_PROJECT = "proj-002"


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _environment(tmp_path: Path, *, seed_store: bool = True) -> dict[str, Any]:
    """Service + TestClient over one tmp data root, seeded like WP-E tests.

    The hub repository lives at ``method-hub.sqlite3`` (the production
    layout); the supervised-run machinery — and the service's lazy
    ``run_seal_store`` — lives at ``hub.sqlite3`` under the same root.
    """
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "method-hub.sqlite3")
    repository.initialize()
    service = MethodHubService(
        settings=ApplicationSettings(data_root=workspace.root),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
    )
    assembler: RunProfileAssembler | None = None
    store: RunSealStore | None = None
    if seed_store:
        # The exact file the service's lazy store will open: the fixture
        # state and the HTTP surface share one hub.sqlite3.
        database = Database(
            workspace.root / "hub.sqlite3", migrations=HUB_MIGRATIONS
        )
        database.initialize()
        store = RunSealStore(database)
        hermes_root = tmp_path / "hermes"
        hermes_root.mkdir()
        assembler = RunProfileAssembler(
            data_root=workspace.root,
            role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
            database=database,
            bundle_root=SKILL_BUNDLE,
            hermes_root=hermes_root,
            hermes_binary="hermes",
            hermes_probe=lambda binary: FAKE_HERMES,
        )
    return {
        "service": service,
        "store": store,
        "assembler": assembler,
        "client": TestClient(create_app(service)),
        "data_root": workspace.root,
    }


@pytest.fixture
def environment(tmp_path: Path) -> dict[str, Any]:
    return _environment(tmp_path)


def _seal_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        invocation_id="inv-001",
        idempotency_key="key-001",
        project_id=PROJECT,
        role="theorist",
        phase="P3",
        method_identity={"method_id": "mh-1", "version": "1.0"},
        user_choices={"mode": "headless", "context_policy": "strict"},
        selected_context_references=[
            {"context_id": "ctx-1", "record_id": "rec-1"},
        ],
        expected_outputs=[
            {"output_id": "out-1", "kind": "scientific_record", "required": True},
        ],
        memory_policy=MemoryPolicy.PERSISTENT,
    )
    kwargs.update(overrides)
    return kwargs


def _seal(assembler: RunProfileAssembler, **overrides: Any) -> SealedRun:
    return assembler.seal_invocation(**_seal_kwargs(**overrides))


def _record_launch_validation_promotion(
    store: RunSealStore, sealed: SealedRun
) -> None:
    """One closed, validated, promoted run: launch + validation + promotion."""
    now = isoformat_utc(utc_now())
    store.create_launch_record(
        launch_id="launch-001",
        seal_id=sealed.seal_id,
        invocation_id=sealed.invocation_id,
        launched_at=now,
    )
    store.close_launch_record(
        "launch-001",
        status="succeeded",
        external_execution_id="ext-001",
        exit_code=0,
        closed_at=now,
    )
    store.record_validation_report(
        launch_id="launch-001",
        invocation_id=sealed.invocation_id,
        seal_id=sealed.seal_id,
        verdict="pass",
        report_json=json.dumps(
            {
                "verdict": "pass",
                "checks": [
                    {"name": "expected outputs", "status": "ok", "detail": "all present"},
                ],
            }
        ),
        validated_at=now,
    )
    store.record_promotion(
        record_id="prom-001",
        seal_id=sealed.seal_id,
        invocation_id=sealed.invocation_id,
        project_id=sealed.project_id,
        role=sealed.role,
        promoted_at=now,
        before_digest=json.dumps({"memories/MEMORY.md": "a" * 64}),
        after_digest=json.dumps({"memories/MEMORY.md": "b" * 64}),
        backup_paths=json.dumps({"memories/MEMORY.md": "backup/MEMORY.md"}),
        status="succeeded",
    )


# --------------------------------------------------------------------------- #
# List endpoint                                                               #
# --------------------------------------------------------------------------- #


def test_list_returns_sealed_invocations_with_summaries(
    environment: dict[str, Any],
) -> None:
    assembler = environment["assembler"]
    assert assembler is not None
    client = environment["client"]

    sealed_theorist = _seal(assembler)
    _seal(
        assembler,
        invocation_id="inv-002",
        idempotency_key="key-002",
        role="outside_reviewer",
        memory_policy=MemoryPolicy.PERSISTENT,  # reviewer is always fresh
    )

    response = client.get(f"/api/v1/projects/{PROJECT}/supervised-runs")

    assert response.status_code == 200
    rows = response.json()
    assert [row["invocation_id"] for row in rows] == [
        "inv-002",
        "inv-001",
    ]  # newest seal first

    by_invocation = {row["invocation_id"]: row for row in rows}
    first = by_invocation[sealed_theorist.invocation_id]
    assert first["seal_id"] == sealed_theorist.seal_id
    assert first["role"] == "theorist"
    assert first["phase"] == "P3"
    assert first["memory_policy"] == "persistent"
    assert first["sealed_at"] == sealed_theorist.sealed_at
    assert first["method_identity"] == {"method_id": "mh-1", "version": "1.0"}
    assert first["promoted"] is False
    assert "latest_launch_status" not in first
    assert "validation_verdict" not in first

    second = by_invocation["inv-002"]
    assert second["role"] == "outside_reviewer"
    assert second["phase"] == "P3"
    assert second["memory_policy"] == "ephemeral"
    assert second["sealed_at"]


def test_list_for_project_without_supervised_runs_is_empty(
    environment: dict[str, Any],
) -> None:
    assembler = environment["assembler"]
    assert assembler is not None
    client = environment["client"]
    _seal(assembler)

    response = client.get(f"/api/v1/projects/{OTHER_PROJECT}/supervised-runs")

    assert response.status_code == 200
    assert response.json() == []


def test_list_without_hub_sqlite_is_empty_not_an_error(tmp_path: Path) -> None:
    environment = _environment(tmp_path, seed_store=False)
    client = environment["client"]
    data_root = environment["data_root"]

    response = client.get(f"/api/v1/projects/{PROJECT}/supervised-runs")

    assert response.status_code == 200
    assert response.json() == []
    # The lazy store opened and migrated the store on first use.
    assert (data_root / "hub.sqlite3").is_file()


# --------------------------------------------------------------------------- #
# Detail endpoint                                                             #
# --------------------------------------------------------------------------- #


def test_detail_returns_manifest_launches_validation_and_promotions(
    environment: dict[str, Any],
) -> None:
    assembler = environment["assembler"]
    store = environment["store"]
    assert assembler is not None and store is not None
    client = environment["client"]

    sealed = _seal(assembler)
    _record_launch_validation_promotion(store, sealed)

    response = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/{sealed.invocation_id}"
    )

    assert response.status_code == 200
    detail = response.json()

    assert detail["invocation_id"] == "inv-001"
    assert detail["seal_id"] == sealed.seal_id
    assert detail["project_id"] == PROJECT
    assert detail["role"] == "theorist"
    assert detail["sealed_at"] == sealed.sealed_at

    # Manifest summary — digest-verified from the stored manifest JSON.
    manifest = detail["manifest"]
    assert manifest["project_id"] == PROJECT
    assert manifest["role"] == "theorist"
    assert manifest["phase"] == "P3"
    assert manifest["sealed_at"] == sealed.sealed_at
    assert manifest["method_identity"] == {"method_id": "mh-1", "version": "1.0"}
    assert manifest["memory_snapshot"]["policy"] == "persistent"
    assert isinstance(manifest["session_snapshot"], dict)
    assert manifest["expected_outputs"] == [
        {"output_id": "out-1", "kind": "scientific_record", "required": True},
    ]
    assert manifest["hermes"] == {"executable": "/fake/hermes", "version": "9.9.9"}
    assert len(manifest["role_asset_digests"]) >= 3
    assert all(
        len(digest) == 64 for digest in manifest["role_asset_digests"].values()
    )
    assert "manifest_note" not in detail

    # Launch records.
    assert len(detail["launches"]) == 1
    launch = detail["launches"][0]
    assert launch["launch_id"] == "launch-001"
    assert launch["status"] == "succeeded"
    assert launch["exit_code"] == 0
    assert launch["external_execution_id"] == "ext-001"
    assert launch["launched_at"]
    assert launch["closed_at"]

    # Validation report.
    validation = detail["validation"]
    assert validation["launch_id"] == "launch-001"
    assert validation["verdict"] == "pass"
    assert validation["validated_at"]
    assert validation["checks"] == [
        {"name": "expected outputs", "status": "ok", "detail": "all present"},
    ]

    # Promotion records.
    assert len(detail["promotions"]) == 1
    promotion = detail["promotions"][0]
    assert promotion["record_id"] == "prom-001"
    assert promotion["status"] == "succeeded"
    assert promotion["promoted_at"]
    assert promotion["before_digest"] == {"memories/MEMORY.md": "a" * 64}
    assert promotion["after_digest"] == {"memories/MEMORY.md": "b" * 64}
    assert promotion["backup_paths"] == {"memories/MEMORY.md": "backup/MEMORY.md"}

    # Preflight reports are not persisted (WP-D2b) — by design.
    assert "preflight_report" not in detail
    assert "not persisted" in detail["preflight_note"]


def test_detail_for_invocation_sealed_under_other_project_is_404(
    environment: dict[str, Any],
) -> None:
    assembler = environment["assembler"]
    assert assembler is not None
    client = environment["client"]
    sealed = _seal(assembler)

    response = client.get(
        f"/api/v1/projects/{OTHER_PROJECT}/supervised-runs/{sealed.invocation_id}"
    )

    assert response.status_code == 404
    assert response.json()["code"] == "TARGET_NOT_FOUND"

    unknown = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-unknown"
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "TARGET_NOT_FOUND"


def test_detail_with_tampered_manifest_degrades_to_note(
    environment: dict[str, Any],
) -> None:
    assembler = environment["assembler"]
    assert assembler is not None
    client = environment["client"]

    sealed = _seal(assembler)
    manifest_path = sealed.run_dir / "manifest" / "manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["phase"] = "P9"  # registry digest no longer matches the bytes
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    response = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/{sealed.invocation_id}"
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail.get("manifest") is None
    assert "digest" in detail["manifest_note"]
    # Registry fields survive; only manifest-derived fields are lost.
    assert detail["invocation_id"] == sealed.invocation_id
    assert detail["role"] == "theorist"

    # The list view degrades the same way: manifest-derived fields null.
    rows = client.get(f"/api/v1/projects/{PROJECT}/supervised-runs").json()
    summary = rows[0]
    assert summary["invocation_id"] == sealed.invocation_id
    assert "phase" not in summary
    assert "memory_policy" not in summary
    assert summary["sealed_at"] == sealed.sealed_at
