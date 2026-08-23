from __future__ import annotations

from model_forge.api.models import CreateProjectRequest
from model_forge.application.project_commands import ProjectCommandService
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository


def test_project_creation_establishes_formal_current_brief(tmp_path) -> None:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    service = ProjectCommandService(repository, ArtifactStore(workspace))

    project = service.create(
        CreateProjectRequest(
            name="Selective inference",
            research_question="How should uncertainty account for selection?",
            domains=["statistics"],
            intended_use="Develop a methodological paper.",
        ),
        owner_user_id="researcher.local",
    )

    current = repository.get_current_record(
        project["project_id"], "project.brief.current"
    )
    assert current is not None
    assert current["record_type"] == "project_brief"
    stored = service.artifacts.read_bytes(current["artifact_sha256"])
    assert b"selection" in stored
