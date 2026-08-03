from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from method_hub.api import create_app
from method_hub.api.errors import CommandRejected
from method_hub.api.models import (
    CreateProjectRequest,
    InstallSkillRequest,
    SaveProfileRequest,
)
from method_hub.api.ports import RawRequestBody
from method_hub.application.profile_views import build_profile_configuration_view
from method_hub.application.run_coordinator import RunCoordinator
from method_hub.application.service import MethodHubService
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.profiles import (
    AUTHOR_PROFILE_ROLES,
    PROFILE_ROLES,
    REVIEWER_PROFILE_ISOLATION_MESSAGE,
    ProfileConfigurationError,
    ProfileMapping,
    discover_profiles,
)
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.executors import DeterministicFakeExecutor
from method_hub.specification import SpecificationPackage
from method_hub.storage.artifacts import ArtifactStore
from method_hub.storage.paths import WorkspacePaths
from method_hub.storage.repository import (
    HubRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources" / "team"
BUNDLED_SKILLS = ROOT / "resources" / "skills"


def _raw(
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str,
) -> RawRequestBody:
    return RawRequestBody(
        body=body,
        byte_length=len(body),
        media_type="application/json",
        content_sha256=hashlib.sha256(body).hexdigest(),
        method="PATCH" if family == "save_profile" else "POST",
        path="/api/v1/profile-command",
        command_family=family,
        project_id=project_id,
        idempotency_key=key,
    )


async def _service_project(
    tmp_path: Path,
) -> tuple[MethodHubService, str, Path]:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    hermes = tmp_path / "hermes"
    (hermes / "profiles").mkdir(parents=True)
    for name in (
        "research_lead",
        "theorist",
        "data_analyst",
        "paper_reviewer",
        "alternate",
        "shared_author",
    ):
        (hermes / "profiles" / name).mkdir()
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    service = MethodHubService(
        settings=ApplicationSettings(
            data_root=workspace.root,
            hermes_root=hermes,
        ),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(RESOURCES),
    )
    create = CreateProjectRequest(
        name="Profile isolation",
        research_question="Which estimator is valid?",
        domains=["statistics"],
        intended_use="Method development",
    )
    payload = json.dumps(create.model_dump(mode="json")).encode()
    receipt = await service.preserve_raw_request(
        RawRequestBody(
            body=payload,
            byte_length=len(payload),
            media_type="application/json",
            content_sha256=hashlib.sha256(payload).hexdigest(),
            method="POST",
            path="/api/v1/projects",
            command_family="create_project",
            project_id=None,
            idempotency_key="create-profile-isolation",
        )
    )
    project = await service.create_project(create, raw_request=receipt)
    return service, project.project_id, hermes


def _profile(
    view,
    role_id: str,
):
    return next(item for item in view.profiles if item.role_id == role_id)


def _option(role, profile_id: str):
    return next(item for item in role.profile_options if item.profile_id == profile_id)


def test_profile_mapping_allows_author_sharing_but_rejects_reviewer_sharing() -> None:
    shared = ProfileMapping(
        research_lead="shared_author",
        theorist="shared_author",
        data_analyst="shared_author",
        outside_reviewer="paper_reviewer",
    )
    assert all(
        shared.for_role(role) == "shared_author"
        for role in AUTHOR_PROFILE_ROLES
    )
    for author_role in AUTHOR_PROFILE_ROLES:
        values = {
            "research_lead": "research_lead",
            "theorist": "theorist",
            "data_analyst": "data_analyst",
            "outside_reviewer": author_role,
        }
        values[author_role] = author_role
        with pytest.raises(
            ProfileConfigurationError,
            match="persistent memory",
        ):
            ProfileMapping(**values)


def test_profile_view_projects_repair_options_and_state_bound_descriptors(
    tmp_path: Path,
) -> None:
    hermes = tmp_path / "hermes"
    (hermes / "profiles").mkdir(parents=True)
    for name in (
        "research_lead",
        "theorist",
        "data_analyst",
        "paper_reviewer",
        "alternate",
    ):
        (hermes / "profiles" / name).mkdir()
    discoveries = discover_profiles(hermes)
    mapping = {
        "research_lead": "research_lead",
        "theorist": "theorist",
        "data_analyst": "data_analyst",
        "outside_reviewer": "theorist",
    }
    revisions = {role: 0 for role in PROFILE_ROLES}
    view = build_profile_configuration_view(
        project_id="project.profile-isolation",
        catalog=RoleResourceCatalog.load(RESOURCES),
        mapping=mapping,
        mapping_revisions=revisions,
        discoveries=discoveries,
        bundle_root=BUNDLED_SKILLS,
    )
    reviewer = _profile(view, "outside_reviewer")
    theorist = _profile(view, "theorist")
    assert _option(reviewer, "theorist").enabled is False
    assert (
        _option(reviewer, "theorist").researcher_message
        == REVIEWER_PROFILE_ISOLATION_MESSAGE
    )
    assert _option(reviewer, "paper_reviewer").enabled is True
    assert _option(theorist, "theorist").enabled is False
    assert theorist.skills[0].actions[0].enabled is False
    assert reviewer.skills[0].actions[0].enabled is False
    assert "Repair this current assignment" in reviewer.memory_policy_summary
    lead = _profile(view, "research_lead")
    assert _option(lead, "data_analyst").enabled is True

    clean_mapping = dict(mapping)
    clean_mapping["outside_reviewer"] = "paper_reviewer"
    first = build_profile_configuration_view(
        project_id="project.profile-isolation",
        catalog=RoleResourceCatalog.load(RESOURCES),
        mapping=clean_mapping,
        mapping_revisions=revisions,
        discoveries=discoveries,
        bundle_root=BUNDLED_SKILLS,
    )
    changed_revisions = dict(revisions)
    changed_revisions["research_lead"] = 1
    revised = build_profile_configuration_view(
        project_id="project.profile-isolation",
        catalog=RoleResourceCatalog.load(RESOURCES),
        mapping=clean_mapping,
        mapping_revisions=changed_revisions,
        discoveries=discoveries,
        bundle_root=BUNDLED_SKILLS,
    )
    locked = build_profile_configuration_view(
        project_id="project.profile-isolation",
        catalog=RoleResourceCatalog.load(RESOURCES),
        mapping=clean_mapping,
        mapping_revisions=revisions,
        discoveries=discoveries,
        bundle_root=BUNDLED_SKILLS,
        skill_mutation_locked=True,
    )
    locked_action = _profile(locked, "theorist").skills[0].actions[0]
    assert locked_action.enabled is False
    assert locked_action.reason_code == "control.active_run"
    assert "research run is active" in str(locked_action.researcher_message)

    first_theorist = _profile(first, "theorist")
    revised_theorist = _profile(revised, "theorist")
    selected = _option(first_theorist, "theorist")
    assert selected.enabled is False
    assert selected.researcher_message == "This profile is already assigned."
    assert (
        _option(first_theorist, "alternate").action_descriptor_id
        != _option(revised_theorist, "alternate").action_descriptor_id
    )
    assert (
        first_theorist.skills[0].actions[0].descriptor_id
        != revised_theorist.skills[0].actions[0].descriptor_id
    )

    local_skill = (
        hermes
        / "profiles"
        / "theorist"
        / "skills"
        / "stat-paper-writing"
    )
    local_skill.mkdir(parents=True)
    (local_skill / "local.txt").write_text("different local copy", encoding="utf-8")
    changed_status = build_profile_configuration_view(
        project_id="project.profile-isolation",
        catalog=RoleResourceCatalog.load(RESOURCES),
        mapping=clean_mapping,
        mapping_revisions=revisions,
        discoveries=discoveries,
        bundle_root=BUNDLED_SKILLS,
    )
    assert (
        first_theorist.skills[0].actions[0].descriptor_id
        != _profile(changed_status, "theorist").skills[0].actions[0].descriptor_id
    )


def test_current_profile_no_op_is_rejected_without_revision(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        view = await service.get_profiles(project_id)
        theorist = _profile(view, "theorist")
        option = _option(theorist, "theorist")
        assert option.enabled is False
        assert option.researcher_message == "This profile is already assigned."
        command = SaveProfileRequest(
            profile_id=option.profile_id,
            action_descriptor_id=option.action_descriptor_id,
        )
        payload = json.dumps(command.model_dump(mode="json")).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                payload,
                family="save_profile",
                key="reject-profile-no-op",
                project_id=project_id,
            )
        )
        with pytest.raises(CommandRejected) as caught:
            await service.save_profile(
                project_id,
                "theorist",
                command,
                raw_request=receipt,
            )
        assert caught.value.error.code == "TARGET_STATE_MISMATCH"
        assert service.repository.get_profile_mapping(project_id, "theorist") is None
        with pytest.raises(RepositoryNotFoundError):
            service.repository.get_artifact(receipt.request_artifact_id)

    asyncio.run(scenario())


def test_disabled_conflict_is_rejected_without_mutation(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        view = await service.get_profiles(project_id)
        reviewer = _profile(view, "outside_reviewer")
        option = _option(reviewer, "theorist")
        assert option.enabled is False
        command = SaveProfileRequest(
            profile_id=option.profile_id,
            action_descriptor_id=option.action_descriptor_id,
        )
        payload = json.dumps(command.model_dump(mode="json")).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                payload,
                family="save_profile",
                key="reject-profile-conflict",
                project_id=project_id,
            )
        )
        with pytest.raises(CommandRejected) as caught:
            await service.save_profile(
                project_id,
                "outside_reviewer",
                command,
                raw_request=receipt,
            )
        assert caught.value.error.code == "TARGET_STATE_MISMATCH"
        assert (
            service.repository.get_profile_mapping(project_id, "outside_reviewer")
            is None
        )
        with pytest.raises(RepositoryNotFoundError):
            service.repository.get_artifact(receipt.request_artifact_id)

    asyncio.run(scenario())


def test_legacy_conflict_is_visible_repairable_and_blocks_skill_actions(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        service.repository.set_profile_mapping(
            project_id,
            "outside_reviewer",
            "theorist",
            {"source": "legacy"},
            expected_revision=0,
        )
        view = await service.get_profiles(project_id)
        reviewer = _profile(view, "outside_reviewer")
        assert reviewer.profile_id == "theorist"
        assert _option(reviewer, "theorist").enabled is False
        assert reviewer.skills[0].actions[0].enabled is False
        repair = _option(reviewer, "paper_reviewer")
        assert repair.enabled is True
        command = SaveProfileRequest(
            profile_id=repair.profile_id,
            action_descriptor_id=repair.action_descriptor_id,
        )
        payload = json.dumps(command.model_dump(mode="json")).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                payload,
                family="save_profile",
                key="repair-legacy-profile",
                project_id=project_id,
            )
        )
        repaired = await service.save_profile(
            project_id,
            "outside_reviewer",
            command,
            raw_request=receipt,
        )
        assert _profile(repaired, "outside_reviewer").profile_id == "paper_reviewer"
        assert service.repository.get_profile_mapping(
            project_id,
            "outside_reviewer",
        )["revision"] == 2

    asyncio.run(scenario())


def test_stale_profile_target_cannot_overwrite_newer_revision(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        view = await service.get_profiles(project_id)
        theorist = _profile(view, "theorist")
        stale_option = _option(theorist, "research_lead")
        assert stale_option.enabled is True
        service.repository.set_profile_mapping(
            project_id,
            "theorist",
            "shared_author",
            {"source": "newer"},
            expected_revision=0,
        )
        command = SaveProfileRequest(
            profile_id=stale_option.profile_id,
            action_descriptor_id=stale_option.action_descriptor_id,
        )
        payload = json.dumps(command.model_dump(mode="json")).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                payload,
                family="save_profile",
                key="stale-profile-save",
                project_id=project_id,
            )
        )
        with pytest.raises(CommandRejected) as caught:
            await service.save_profile(
                project_id,
                "theorist",
                command,
                raw_request=receipt,
            )
        assert caught.value.error.code == "CONTROL_HEAD_STALE"
        row = service.repository.get_profile_mapping(project_id, "theorist")
        assert row is not None
        assert row["profile_name"] == "shared_author"
        assert row["revision"] == 1
        with pytest.raises(RepositoryNotFoundError):
            service.repository.get_artifact(receipt.request_artifact_id)

    asyncio.run(scenario())


def test_stale_skill_action_after_local_change_cannot_install(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, project_id, hermes = await _service_project(tmp_path)
        view = await service.get_profiles(project_id)
        theorist = _profile(view, "theorist")
        action = theorist.skills[0].actions[0]
        assert action.enabled is True
        local_skill = (
            hermes
            / "profiles"
            / "theorist"
            / "skills"
            / "stat-paper-writing"
        )
        local_skill.mkdir(parents=True)
        marker = local_skill / "local.txt"
        marker.write_text("keep this local copy", encoding="utf-8")
        command = InstallSkillRequest(
            action_descriptor_id=action.descriptor_id,
        )
        payload = json.dumps(command.model_dump(mode="json")).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                payload,
                family="install_skill",
                key="stale-skill-state",
                project_id=project_id,
            )
        )
        with pytest.raises(CommandRejected) as caught:
            await service.install_skill(
                project_id,
                "theorist",
                "stat-paper-writing",
                command,
                raw_request=receipt,
            )
        assert caught.value.error.code == "CONTROL_HEAD_STALE"
        assert marker.read_text(encoding="utf-8") == "keep this local copy"
        assert not (local_skill / "SKILL.md").exists()
        with pytest.raises(RepositoryNotFoundError):
            service.repository.get_artifact(receipt.request_artifact_id)

    asyncio.run(scenario())


def test_coordinator_rejects_injected_conflict_before_executor_invocation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        service.repository.set_profile_mapping(
            project_id,
            "outside_reviewer",
            "theorist",
            {"source": "injected"},
            expected_revision=0,
        )
        executor = DeterministicFakeExecutor()
        coordinator = RunCoordinator(
            settings=service.settings,
            specification=service.specification,
            repository=service.repository,
            artifacts=service.artifacts,
            role_resources=service.role_resources,
            executor=executor,
        )
        with pytest.raises(ProfileConfigurationError, match="persistent memory"):
            coordinator._freeze_role_resources(project_id, {"research_lead"})
        assert executor.invocations == []

    asyncio.run(scenario())


def test_repository_profile_cas_rejects_peer_mapping_change(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        profiles, revisions = service._effective_profile_state(project_id)
        service.repository.set_profile_mapping(
            project_id,
            "research_lead",
            "alternate",
            {"source": "peer"},
            expected_revision=0,
        )
        with pytest.raises(RepositoryConflictError):
            service.repository.compare_and_set_profile_mapping(
                project_id,
                "theorist",
                "research_lead",
                {"source": "stale"},
                expected_profiles=profiles,
                expected_revisions=revisions,
            )
        assert service.repository.get_profile_mapping(project_id, "theorist") is None
        peer = service.repository.get_profile_mapping(project_id, "research_lead")
        assert peer is not None
        assert peer["profile_name"] == "alternate"

    asyncio.run(scenario())


def test_service_profile_cas_rejects_peer_race_without_target_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service, project_id, _hermes = await _service_project(tmp_path)
        view = await service.get_profiles(project_id)
        option = _option(_profile(view, "theorist"), "research_lead")
        command = SaveProfileRequest(
            profile_id=option.profile_id,
            action_descriptor_id=option.action_descriptor_id,
        )
        payload = json.dumps(command.model_dump(mode="json")).encode()
        receipt = await service.preserve_raw_request(
            _raw(
                payload,
                family="save_profile",
                key="profile-peer-race",
                project_id=project_id,
            )
        )
        original = HubRepository.compare_and_set_profile_mapping

        def race(repository, *args, **kwargs):
            service.repository.set_profile_mapping(
                project_id,
                "research_lead",
                "alternate",
                {"source": "peer"},
                expected_revision=0,
            )
            return original(repository, *args, **kwargs)

        monkeypatch.setattr(
            HubRepository,
            "compare_and_set_profile_mapping",
            race,
        )
        with pytest.raises(CommandRejected) as caught:
            await service.save_profile(
                project_id,
                "theorist",
                command,
                raw_request=receipt,
            )
        assert caught.value.error.code == "CONTROL_HEAD_STALE"
        assert service.repository.get_profile_mapping(project_id, "theorist") is None
        peer = service.repository.get_profile_mapping(project_id, "research_lead")
        assert peer is not None
        assert peer["profile_name"] == "alternate"
        artifact = service.repository.get_artifact(receipt.request_artifact_id)
        assert artifact["project_id"] == project_id

    asyncio.run(scenario())


def test_active_run_lock_is_projected_and_rejected_by_skill_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project_id, hermes = asyncio.run(_service_project(tmp_path))
    monkeypatch.setattr(service, "_any_active_run", lambda: True)
    view = asyncio.run(service.get_profiles(project_id))
    theorist = _profile(view, "theorist")
    action = theorist.skills[0].actions[0]
    assert action.enabled is False
    assert action.reason_code == "control.active_run"
    assert "research run is active" in str(action.researcher_message)

    client = TestClient(create_app(service))
    response = client.post(
        (
            f"/api/v1/projects/{project_id}/configuration/profiles/"
            "theorist/skills/stat-paper-writing/install"
        ),
        headers={"Idempotency-Key": "active-run-skill-lock"},
        json={"action_descriptor_id": action.descriptor_id},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "TARGET_STATE_MISMATCH"
    assert not (
        hermes
        / "profiles"
        / "theorist"
        / "skills"
        / "stat-paper-writing"
        / "SKILL.md"
    ).exists()
