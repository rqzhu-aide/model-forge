"""WP-F0 API tests: supervised-run read surface (list + detail endpoints).

Builds fixture state exactly as the WP-D/E tests do — sealing through
``RunProfileAssembler.seal_invocation`` and recording launch, validation,
and promotion rows through ``RunSealStore`` directly — over the SAME
``<data_root>/hub.sqlite3`` that the application service's lazy
``run_seal_store`` opens (``ModelForgeService.run_seal_store`` resolves
``settings.data_root / "hub.sqlite3"``), so the HTTP surface reads the
seeded durable state.

Covers: list summaries with digest-verified manifest fields; the full
detail view (manifest summary, launch records, validation report,
promotion records); project-scoped 404 for an invocation sealed under a
different project id; empty list for a project without supervised runs;
empty list (not an error) when no hub.sqlite3 exists at all; the
digest-verification behavior of ``read_manifest_document`` when the
stored manifest bytes no longer match the registry digest; and WP-F1c
preflight-report persistence (a started run shows its stored PASS
report with all eight checks, a refused start persists its FAIL report,
and a sealed-but-never-started invocation still shows null + note).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from model_forge.api import create_app
from model_forge.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    RunSealStore,
    SealedRun,
)
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.domain.runs import isoformat_utc, utc_now
from model_forge.executors.local_hermes import LocalHermesExecutorSettings
from model_forge.profiles.project_profiles import MemoryPolicy
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.database import Database
from model_forge.storage.migrations import HUB_MIGRATIONS
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

FAKE_HERMES = HermesProbe("/fake/hermes", "9.9.9")

PROJECT = "proj-001"
OTHER_PROJECT = "proj-002"

#: The WP-D2b preflight's eight named checks, in report order.
PREFLIGHT_CHECK_NAMES = [
    "hermes_executable",
    "role_assets",
    "selected_state",
    "paths_permissions",
    "free_space",
    "lock_ownership",
    "task_brief",
    "output_contract",
]

#: Stub Hermes executable for start-endpoint tests: answers ``--version``
#: (the seal probe and the preflight's hermes_executable check both run
#: it) and otherwise exits 0 after a short pause so the launch settles
#: quickly (mirrors the WP-F1a stub).
_STUB_SCRIPT = r'''#!/usr/bin/env python3
"""Stub Hermes executable for WP-F1c preflight-persistence tests."""
import argparse
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    parser.add_argument("-z", dest="prompt")
    parser.add_argument("-p", dest="profile")
    parser.add_argument("--usage-file", dest="usage_file")
    parser.add_argument("-m", dest="model")
    parser.add_argument("--provider", dest="provider")
    parser.add_argument("--skills", dest="skills")
    args, _ = parser.parse_known_args()

    if args.version:
        print("stub-hermes 0.0.1")
        sys.exit(0)

    time.sleep(0.5)

    if args.usage_file:
        with open(args.usage_file, "w") as f:
            f.write('{"tokens": 1}')
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _environment(
    tmp_path: Path,
    *,
    seed_store: bool = True,
    hermes_executable: str | None = None,
    supervised_executor_settings: LocalHermesExecutorSettings | None = None,
) -> dict[str, Any]:
    """Service + TestClient over one tmp data root, seeded like WP-E tests.

    The hub repository lives at ``model-forge.sqlite3`` (the production
    layout); the supervised-run machinery — and the service's lazy
    ``run_seal_store`` — lives at ``hub.sqlite3`` under the same root.
    ``hermes_executable``/``supervised_executor_settings`` wire the
    service for start-endpoint tests (WP-F1c); without them the
    environment serves the WP-F0 read surface only.
    """
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "model-forge.sqlite3")
    repository.initialize()
    settings = ApplicationSettings(data_root=workspace.root)
    if hermes_executable is not None:
        settings.hermes_executable = hermes_executable
    service = ModelForgeService(
        settings=settings,
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
        supervised_executor_settings=supervised_executor_settings,
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


@pytest.fixture
def stub_hermes(tmp_path: Path) -> Path:
    """Create the stub Hermes executable and return its absolute path."""
    stub = tmp_path / "stub-hermes"
    stub.write_text(_STUB_SCRIPT)
    stub.chmod(0o755)
    return stub


def _start_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invocation_id": "inv-001",
        "idempotency_key": "key-001",
        "role": "theorist",
        "phase": "P3",
        "method_identity": {"method_id": "mf-1", "version": "1.0"},
        "brief_text": "# Brief\nProduce the declared output.\n",
        "expected_outputs": [
            {
                "output_id": "out-1",
                "path": "results/summary.json",
                "required_fields": ["conclusion"],
            },
        ],
        "memory_policy": "persistent",
    }
    payload.update(overrides)
    return payload


def _post_start(client: TestClient, **overrides: Any):
    return client.post(
        f"/api/v1/projects/{PROJECT}/supervised-runs",
        json=_start_payload(**overrides),
    )


def _start_environment(
    tmp_path: Path, stub_hermes: Path
) -> dict[str, Any]:
    """WP-F1c start-capable environment: real stub binary + fast executor."""
    return _environment(
        tmp_path,
        hermes_executable=str(stub_hermes),
        supervised_executor_settings=LocalHermesExecutorSettings(
            hermes_binary=str(stub_hermes),
            poll_interval_seconds=0.05,
            output_limit_bytes=65536,
            terminate_grace_seconds=1,
            kill_grace_seconds=1,
        ),
    )


def _seal_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        invocation_id="inv-001",
        idempotency_key="key-001",
        project_id=PROJECT,
        role="theorist",
        phase="P3",
        method_identity={"method_id": "mf-1", "version": "1.0"},
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
    assert first["method_identity"] == {"method_id": "mf-1", "version": "1.0"}
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
    assert manifest["method_identity"] == {"method_id": "mf-1", "version": "1.0"}
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

    # Sealed but never started: no preflight report was recorded (the
    # start command persists reports; this run was never started).
    assert "preflight_report" not in detail
    assert "No preflight report" in detail["preflight_note"]


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


# --------------------------------------------------------------------------- #
# Preflight report persistence (WP-F1c)                                        #
# --------------------------------------------------------------------------- #


def test_start_persists_pass_preflight_report_visible_in_detail(
    tmp_path: Path, stub_hermes: Path
) -> None:
    """A started run persists its preflight report: the detail endpoint
    shows the verdict plus all eight named checks (WP-F1c)."""
    environment = _start_environment(tmp_path, stub_hermes)
    client = environment["client"]
    store = environment["store"]
    assert store is not None

    response = _post_start(client)
    assert response.status_code == 202

    # The report was persisted by the start command before the launch
    # was dispatched.
    stored = store.get_preflight_report("inv-001")
    assert stored is not None
    assert stored["verdict"] == "pass"
    assert len(json.loads(stored["report_json"])["checks"]) == 8

    # The WP-F0 detail endpoint surfaces the persisted report.
    detail = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    preflight = detail["preflight_report"]
    assert preflight["verdict"] == "pass"
    assert preflight["report_id"]
    assert preflight["created_at"]
    names = [check["name"] for check in preflight["checks"]]
    assert names == PREFLIGHT_CHECK_NAMES
    assert all(
        check["status"] in ("pass", "fail", "warning")
        for check in preflight["checks"]
    )
    assert "preflight_note" not in detail

    # The run itself still reaches its terminal state as before.
    assert detail["launches"][0]["status"] == "succeeded"


def test_preflight_failure_persists_fail_report_visible_in_detail(
    tmp_path: Path, stub_hermes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused start (tampered SOUL after sealing) persists the FAIL
    report: the 409 carries it and the detail endpoint shows it."""
    environment = _start_environment(tmp_path, stub_hermes)
    service: ModelForgeService = environment["service"]
    client = environment["client"]
    store = environment["store"]
    assert store is not None

    # Tamper the run profile's SOUL between sealing and preflight, so the
    # role_assets check fails deterministically.
    assembler = service.run_profile_assembler
    original_seal = assembler.seal_invocation

    def seal_then_tamper_soul(**kwargs: Any) -> SealedRun:
        sealed = original_seal(**kwargs)
        soul = sealed.run_dir / "profile" / "SOUL.md"
        soul.write_text(
            soul.read_text(encoding="utf-8") + "\n# tampered after sealing\n",
            encoding="utf-8",
        )
        return sealed

    monkeypatch.setattr(assembler, "seal_invocation", seal_then_tamper_soul)

    response = _post_start(client)
    assert response.status_code == 409
    payload = response.json()
    assert payload["code"] == "SUPERVISED_RUN_PREFLIGHT_FAILED"
    assert "role_assets" in payload["detail"]["failed_checks"]

    # The FAIL report was persisted before the 409 was raised.
    stored = store.get_preflight_report("inv-001")
    assert stored is not None
    assert stored["verdict"] == "fail"
    assert "role_assets" in json.loads(stored["report_json"])["failed_checks"]

    # The detail endpoint shows the persisted FAIL report with all eight
    # checks; no process was ever launched.
    detail = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    preflight = detail["preflight_report"]
    assert preflight["verdict"] == "fail"
    names = [check["name"] for check in preflight["checks"]]
    assert names == PREFLIGHT_CHECK_NAMES
    role_assets = next(
        check for check in preflight["checks"] if check["name"] == "role_assets"
    )
    assert role_assets["status"] == "fail"
    assert "SOUL.md" in role_assets["detail"]
    assert "preflight_note" not in detail
    assert detail["launches"] == []


def test_sealed_but_never_started_shows_preflight_null_and_note(
    environment: dict[str, Any],
) -> None:
    """A sealed-but-never-started invocation has no stored preflight
    report: the detail view keeps the null report plus the note."""
    assembler = environment["assembler"]
    assert assembler is not None
    client = environment["client"]

    sealed = _seal(assembler)

    detail = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/{sealed.invocation_id}"
    ).json()
    assert "preflight_report" not in detail
    assert "No preflight report" in detail["preflight_note"]
