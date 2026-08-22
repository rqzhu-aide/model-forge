from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from method_hub import __version__
from method_hub.api import create_app
from method_hub.api.models import (
    CreateProjectRequest,
    ReasonedActionRequest,
    StartRunRequest,
    UpdateProjectBriefRequest,
)
from method_hub.api.ports import RawRequestBody
from method_hub.application.service import MethodHubService
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.digests.jcs import canonicalize
from method_hub.specification import SpecificationPackage
from method_hub.storage.artifacts import ArtifactStore
from method_hub.storage.paths import WorkspacePaths
from method_hub.storage.repository import HubRepository


ROOT = Path(__file__).resolve().parents[1]


async def _do_nothing(_run_id: str) -> None:
    return None


def _service(
    tmp_path: Path,
) -> tuple[MethodHubService, HubRepository, ArtifactStore]:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    artifacts = ArtifactStore(workspace)
    service = MethodHubService(
        settings=ApplicationSettings(data_root=workspace.root),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=artifacts,
        role_resources=RoleResourceCatalog.load(ROOT / "resources" / "team"),
        run_launcher=_do_nothing,
    )
    return service, repository, artifacts


def _raw(
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str | None,
) -> RawRequestBody:
    return RawRequestBody(
        body=body,
        byte_length=len(body),
        media_type="application/json",
        content_sha256=hashlib.sha256(body).hexdigest(),
        method="PATCH" if family == "update_project_brief" else "POST",
        path="/api/v1/test",
        command_family=family,  # type: ignore[arg-type]
        project_id=project_id,
        idempotency_key=key,
    )


async def _create_project(service: MethodHubService) -> str:
    command = CreateProjectRequest(
        name="Researcher view test",
        research_question="Which estimator remains reliable under weak overlap?",
        domains=["statistics", "machine learning"],
        intended_use="Develop and assess a statistical method.",
        scope="Semiparametric estimation under limited overlap.",
        decision_criteria=["Valid inference", "Stable finite-sample performance"],
        constraints=["Use reproducible simulations"],
    )
    body = json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    receipt = await service.preserve_raw_request(
        _raw(body, family="create_project", key="create-project", project_id=None)
    )
    return (await service.create_project(command, raw_request=receipt)).project_id


def _artifact(
    repository: HubRepository,
    artifacts: ArtifactStore,
    project_id: str,
    artifact_id: str,
    document: Any,
) -> tuple[str, str]:
    payload = canonicalize(document)
    stored = artifacts.put_bytes(payload)
    repository.record_artifact(
        artifact_id,
        project_id,
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {"purpose": "test formal record"},
    )
    return artifact_id, str(stored.sha256)


def _publish_method_catalog(
    repository: HubRepository,
    artifacts: ArtifactStore,
    project_id: str,
    *,
    method_mutator: Any = None,
) -> dict[str, Any]:
    method = json.loads(
        (ROOT / "architecture" / "examples" / "method.example.json").read_text(
            encoding="utf-8"
        )
    )
    if method_mutator is not None:
        method_mutator(method)
    method_id = str(method["identity"]["stable_id"])
    method_artifact, _ = _artifact(
        repository, artifacts, project_id, "artifact.test.method", method
    )
    catalog = {
        "format": "method-hub.method-catalog-index",
        "format_version": "1.0.0",
        "record_type": "method_catalog",
        "method_count": 1,
        "active_method_count": 1,
        "methods": [method],
        "projections": [
            {
                "identity": method["identity"],
                "title": method["title"],
                "summary": method["summary"],
                "lifecycle_state": method["lifecycle_state"],
            }
        ],
    }
    catalog_sha = hashlib.sha256(canonicalize(catalog)).hexdigest()
    catalog_artifact, _ = _artifact(
        repository, artifacts, project_id, "artifact.test.catalog", catalog
    )

    project = repository.get_project(project_id)
    sequence = int(project["authority_sequence"])
    root = str(project["authority_root_sha256"])
    revision = int(project["current_revision"])
    events = []
    for label, generation, digest in (
        ("method", str(method["generation_id"]), str(method["content_sha256"])),
        ("catalog", "generation.test.catalog", catalog_sha),
    ):
        event = {
            "event_id": f"authority_event.test.{label}",
            "event_type": "formal_generation_published",
            "project_id": project_id,
            "generation_id": generation,
        }
        event_sha = hashlib.sha256(canonicalize(event)).hexdigest()
        root = hashlib.sha256(
            bytes.fromhex(root) + bytes.fromhex(event_sha)
        ).hexdigest()
        events.append((event, event_sha, root))
    receipt = {
        "receipt_id": "receipt.test.method_catalog",
        "project_id": project_id,
        "generations": [str(method["generation_id"]), "generation.test.catalog"],
    }
    with repository.publication_transaction(
        project_id,
        "receipt.test.method_catalog",
        sequence,
        str(project["authority_root_sha256"]),
        expected_current_revision=revision,
    ) as publication:
        publication.add_formal_generation(
            str(method["generation_id"]),
            "method_record",
            method_artifact,
            str(method["content_sha256"]),
            method,
            logical_slot=f"methods/{method_id}/current",
        )
        publication.add_formal_generation(
            "generation.test.catalog",
            "method_catalog",
            catalog_artifact,
            catalog_sha,
            catalog,
            logical_slot="p2.method_catalog.current",
        )
        publication.replace_current_slot(
            f"methods/{method_id}/current",
            str(method["generation_id"]),
            expected_generation_id=None,
        )
        publication.replace_current_slot(
            "p2.method_catalog.current",
            "generation.test.catalog",
            expected_generation_id=None,
        )
        for event, digest, event_root in events:
            publication.append_authority_event(
                str(event["event_id"]),
                str(event["event_type"]),
                digest,
                event_root,
                event,
            )
        publication.record_receipt(
            hashlib.sha256(canonicalize(receipt)).hexdigest(),
            receipt,
        )
    return method


def _sealed_evaluation() -> dict[str, Any]:
    axis = {
        "score": 8,
        "justification": "Complete and internally consistent on this axis.",
        "issue_refs": [],
    }
    return {
        "theoretical_validity": dict(axis),
        "literature_positioning": {**axis, "score": 6},
        "empirical_feasibility": {**axis, "score": 9},
        "adjudicated_at": "2026-08-21T00:00:00+00:00",
        "review_basis_ids": ["report.p2.theory_review.test"],
    }


def test_list_methods_surfaces_sealed_evaluation(tmp_path: Path) -> None:
    """ADR-017 wiring: a sealed evaluation block must reach MethodRow."""

    async def scenario() -> None:
        service, repository, artifacts = _service(tmp_path)
        project_id = await _create_project(service)

        def inject(method: dict[str, Any]) -> None:
            method["evaluation"] = _sealed_evaluation()

        _publish_method_catalog(
            repository, artifacts, project_id, method_mutator=inject
        )
        scored = (await service.list_methods(project_id))[0]
        assert scored.evaluation is not None
        assert scored.evaluation.theoretical_validity.score == 8
        assert scored.evaluation.literature_positioning.score == 6
        assert scored.evaluation.empirical_feasibility.score == 9

    asyncio.run(scenario())


def test_overview_restores_phase_navigation_and_storage_boundary(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, _repository, _artifacts = _service(tmp_path)
        project_id = await _create_project(service)

        overview = await service.get_project_overview(project_id)
        settings = await service.get_system_settings()

        assert [item.phase_id for item in overview.phases] == [
            "P1",
            "P2",
            "P3",
            "P4",
            "P5",
        ]
        assert all(
            item.navigation_state == "no_current_record"
            for item in overview.phases
        )
        assert overview.project_brief.scope is not None
        assert overview.storage.open_folder_supported is False
        assert overview.storage.display_path is None
        assert settings.service_version == __version__
        assert settings.project_count == 1
        assert settings.settings_editable_in_ui is False
        assert settings.database_path.endswith("hub.sqlite3")

    asyncio.run(scenario())


def test_project_brief_update_is_formal_audited_and_starts_no_run(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service, repository, _artifacts = _service(tmp_path)
        project_id = await _create_project(service)
        before = await service.get_project_brief(project_id)
        action = before.actions[0]
        command = UpdateProjectBriefRequest(
            action_descriptor_id=action.descriptor_id,
            reason="Narrow the primary decision to inferential validity.",
            scope="Weak-overlap settings with prespecified nuisance estimators.",
            decision_criteria=["Valid confidence intervals", "Stable mean squared error"],
        )
        body = json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                body,
                family="update_project_brief",
                key="update-brief",
                project_id=project_id,
            )
        )

        after = await service.update_project_brief(
            project_id, command, raw_request=receipt
        )

        assert after.generation_id != before.generation_id
        assert after.research_question == before.research_question
        assert after.constraints == before.constraints
        assert after.scope == (
            "Weak-overlap settings with prespecified nuisance estimators."
        )
        assert repository.list_incomplete_runs() == ()
        history = service.queries.list_formal_generations(
            project_id, record_type="project_brief"
        )
        assert len(history) == 2
        project = repository.get_project(project_id)
        assert int(project["authority_sequence"]) == 3

        repeated = await service.update_project_brief(
            project_id, command, raw_request=receipt
        )
        assert repeated.generation_id == after.generation_id
        assert len(
            service.queries.list_formal_generations(
                project_id, record_type="project_brief"
            )
        ) == 2

    asyncio.run(scenario())


def test_method_lifecycle_preserves_identity_catalog_and_history(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service, repository, artifacts = _service(tmp_path)
        project_id = await _create_project(service)
        original = _publish_method_catalog(
            repository, artifacts, project_id
        )
        method_id = str(original["identity"]["stable_id"])
        method_generation = repository.get_current_record(
            project_id, f"methods/{method_id}/current"
        )
        assert method_generation is not None
        before = (await service.list_methods(project_id))[0]
        assert before.actions[0].target_id == method_generation["generation_id"]
        retire = ReasonedActionRequest(
            action_descriptor_id=before.actions[0].descriptor_id,
            reason="Retire this method from ordinary Phase 3 and Phase 4 work.",
        )
        body = json.dumps(retire.model_dump(mode="json"), sort_keys=True).encode()
        raw = await service.preserve_raw_request(
            _raw(
                body,
                family="method_lifecycle",
                key="retire-method",
                project_id=project_id,
            )
        )

        await service.change_method_lifecycle(
            project_id, method_id, retire, raw_request=raw
        )
        retired = (await service.list_methods(project_id))[0]

        assert retired.lifecycle_state == "retired"
        assert retired.identity == before.identity
        assert retired.actions[0].action_type == "reactivate_method"
        assert retired.definition_artifact is not None
        assert "Estimating equation:" in retired.mathematical_summary
        catalog = repository.get_current_record(
            project_id, "p2.method_catalog.current"
        )
        assert catalog is not None
        assert json.loads(catalog["payload_json"])["methods"][0][
            "lifecycle_state"
        ] == "retired"
        assert len(
            service.queries.list_formal_generations(
                project_id, record_type="method_record"
            )
        ) == 2
        assert service.queries.list_runs(project_id) == ()

        reactivate = ReasonedActionRequest(
            action_descriptor_id=retired.actions[0].descriptor_id,
            reason="Return the method to the active research portfolio.",
        )
        reactivation_body = json.dumps(
            reactivate.model_dump(mode="json"), sort_keys=True
        ).encode()
        reactivation_raw = await service.preserve_raw_request(
            _raw(
                reactivation_body,
                family="method_lifecycle",
                key="reactivate-method",
                project_id=project_id,
            )
        )
        await service.change_method_lifecycle(
            project_id, method_id, reactivate, raw_request=reactivation_raw
        )
        active = (await service.list_methods(project_id))[0]
        assert active.lifecycle_state == "active"
        assert active.identity == before.identity

    asyncio.run(scenario())


def test_retired_method_blocks_direct_phase_five_run(tmp_path: Path) -> None:
    service, repository, artifacts = _service(tmp_path)
    project_id = asyncio.run(_create_project(service))
    original = _publish_method_catalog(repository, artifacts, project_id)
    method_id = str(original["identity"]["stable_id"])
    method = asyncio.run(service.list_methods(project_id))[0]
    retire = ReasonedActionRequest(
        action_descriptor_id=method.actions[0].descriptor_id,
        reason="Retire this method before manuscript assembly.",
    )
    retire_body = json.dumps(retire.model_dump(mode="json"), sort_keys=True).encode()
    retire_raw = asyncio.run(
        service.preserve_raw_request(
            _raw(
                retire_body,
                family="method_lifecycle",
                key="retire-before-p5",
                project_id=project_id,
            )
        )
    )
    asyncio.run(
        service.change_method_lifecycle(
            project_id,
            method_id,
            retire,
            raw_request=retire_raw,
        )
    )
    retired = asyncio.run(service.list_methods(project_id))[0]
    phase = asyncio.run(
        service.get_phase_view(
            project_id,
            "P5",
            mode="p5.assembly",
            method_id=method_id,
        )
    )
    action = next(item for item in phase.actions if item.action_type == "start_run")
    assert action.enabled is False
    assert action.reason_code == "method.not_active"

    command = StartRunRequest(
        action_descriptor_id=action.descriptor_id,
        phase="P5",
        mode="p5.assembly",
        choice_values={
            "p5.selected_method": retired.identity.model_dump(mode="json"),
            "p5.instructions": "Attempt manuscript assembly for a retired method.",
            "p5.selected_history": [],
        },
        context_policy="current_only",
        selected_context_option_ids=[
            item.option_id for item in phase.run_configuration.current_inputs
        ],
    )
    client = TestClient(create_app(service))
    response = client.post(
        f"/api/v1/projects/{project_id}/runs",
        headers={"Idempotency-Key": "direct-retired-p5"},
        json=command.model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "DEPENDENCY_CLOSURE_INCOMPLETE"
    assert "active current method" in response.json()["researcher_message"]
    assert service.queries.list_runs(project_id) == ()


def test_control_routes_return_current_views_and_reject_stale_descriptors(
    tmp_path: Path,
) -> None:
    service, repository, artifacts = _service(tmp_path)
    project_id = asyncio.run(_create_project(service))
    method = _publish_method_catalog(repository, artifacts, project_id)
    method_id = str(method["identity"]["stable_id"])
    client = TestClient(create_app(service))

    settings = client.get("/api/v1/system/settings")
    brief = client.get(f"/api/v1/projects/{project_id}/brief")
    assert settings.status_code == 200
    assert brief.status_code == 200
    brief_action = brief.json()["actions"][0]

    updated = client.patch(
        f"/api/v1/projects/{project_id}/brief",
        headers={"Idempotency-Key": "api-update-brief"},
        json={
            "action_descriptor_id": brief_action["descriptor_id"],
            "reason": "Clarify the focused scientific setting.",
            "scope": "Weak overlap under prespecified nuisance estimation.",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["scope"].startswith("Weak overlap")

    stale_brief = client.patch(
        f"/api/v1/projects/{project_id}/brief",
        headers={"Idempotency-Key": "api-stale-brief"},
        json={
            "action_descriptor_id": brief_action["descriptor_id"],
            "reason": "Attempt an update from an old formal basis.",
            "scope": "A different stale scope.",
        },
    )
    assert stale_brief.status_code == 409
    assert stale_brief.json()["code"] == "CONTROL_HEAD_STALE"

    method_view = client.get(
        f"/api/v1/projects/{project_id}/methods"
    ).json()[0]
    lifecycle_action = method_view["actions"][0]
    assert lifecycle_action["target_id"]
    retired = client.post(
        f"/api/v1/projects/{project_id}/methods/{method_id}/lifecycle",
        headers={"Idempotency-Key": "api-retire-method"},
        json={
            "action_descriptor_id": lifecycle_action["descriptor_id"],
            "reason": "Retire this method from ordinary new work.",
        },
    )
    assert retired.status_code == 204
    assert client.get(
        f"/api/v1/projects/{project_id}/methods"
    ).json()[0]["lifecycle_state"] == "retired"

    stale_lifecycle = client.post(
        f"/api/v1/projects/{project_id}/methods/{method_id}/lifecycle",
        headers={"Idempotency-Key": "api-stale-lifecycle"},
        json={
            "action_descriptor_id": lifecycle_action["descriptor_id"],
            "reason": "Attempt a lifecycle change from an old method basis.",
        },
    )
    assert stale_lifecycle.status_code == 409
    assert stale_lifecycle.json()["code"] == "CONTROL_HEAD_STALE"
