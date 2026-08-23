from __future__ import annotations

import asyncio
import json
from pathlib import Path

from model_forge.api.models import CreateProjectRequest
from model_forge.api.ports import RawRequestBody
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository


ROOT = Path(__file__).resolve().parents[1]


def _service(tmp_path: Path) -> ModelForgeService:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    return ModelForgeService(
        settings=ApplicationSettings(data_root=workspace.root),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(ROOT / "resources" / "team"),
    )


def test_application_service_creates_project_and_disables_execution(tmp_path) -> None:
    asyncio.run(_exercise_project_creation(tmp_path))


async def _exercise_project_creation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    command = CreateProjectRequest(
        name="Example",
        research_question="What should be estimated?",
        domains=["statistics"],
        intended_use="Develop a method",
    )
    body = json.dumps(command.model_dump()).encode()
    receipt = await service.preserve_raw_request(
        RawRequestBody(
            body=body,
            byte_length=len(body),
            media_type="application/json",
            content_sha256=__import__("hashlib").sha256(body).hexdigest(),
            method="POST",
            path="/api/v1/projects",
            command_family="create_project",
            project_id=None,
            idempotency_key="create-example",
        )
    )
    project = await service.create_project(command, raw_request=receipt)

    phase = await service.get_phase_view(
        project.project_id, "P1", mode=None, method_id=None
    )

    assert phase.actions[0].enabled is False
    assert phase.actions[0].reason_code == "executor.unavailable"
    assert (await service.list_projects())[0].project_id == project.project_id
