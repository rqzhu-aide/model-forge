from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from model_forge.api.models import CreateProjectRequest, InstallSkillRequest
from model_forge.api.ports import RawRequestBody
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository


ROOT = Path(__file__).resolve().parents[1]


def _raw(body: bytes, family: str, key: str, project_id: str | None) -> RawRequestBody:
    return RawRequestBody(
        body=body,
        byte_length=len(body),
        media_type="application/json",
        content_sha256=hashlib.sha256(body).hexdigest(),
        method="POST",
        path="/api/v1/command",
        command_family=family,
        project_id=project_id,
        idempotency_key=key,
    )


def test_user_skill_action_installs_exact_bundle(tmp_path) -> None:
    asyncio.run(_exercise_install(tmp_path))


async def _exercise_install(tmp_path: Path) -> None:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    hermes = tmp_path / "hermes"
    profile = hermes / "profiles" / "theorist"
    profile.mkdir(parents=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    service = ModelForgeService(
        settings=ApplicationSettings(data_root=workspace.root, hermes_root=hermes),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(ROOT / "resources" / "team"),
    )
    create = CreateProjectRequest(
        name="Example",
        research_question="What is estimable?",
        domains=["statistics"],
        intended_use="Method development",
    )
    body = json.dumps(create.model_dump()).encode()
    receipt = await service.preserve_raw_request(_raw(body, "create_project", "create-1", None))
    project = await service.create_project(create, raw_request=receipt)
    profiles = await service.get_profiles(project.project_id)
    theorist = next(item for item in profiles.profiles if item.role_id == "theorist")
    skill = theorist.skills[0]
    assert skill.status == "missing"
    install = InstallSkillRequest(action_descriptor_id=skill.actions[0].descriptor_id)
    install_body = json.dumps(install.model_dump()).encode()
    install_receipt = await service.preserve_raw_request(
        _raw(install_body, "install_skill", "install-1", project.project_id)
    )

    updated = await service.install_skill(
        project.project_id,
        "theorist",
        "stat-paper-writing",
        install,
        raw_request=install_receipt,
    )

    updated_theorist = next(item for item in updated.profiles if item.role_id == "theorist")
    assert updated_theorist.skills[0].status == "installed"
    assert (profile / "skills" / "stat-paper-writing" / "SKILL.md").is_file()
