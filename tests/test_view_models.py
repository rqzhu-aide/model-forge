from __future__ import annotations

from pathlib import Path

from model_forge.api.models import CreateProjectRequest
from model_forge.application.project_commands import ProjectCommandService
from model_forge.application.view_models import ResearchProjectionService
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_fresh_project_phase_views_communicate_backend_readiness(tmp_path) -> None:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    project = ProjectCommandService(repository, ArtifactStore(workspace)).create(
        CreateProjectRequest(
            name="Example",
            research_question="Can the estimator be stabilized?",
            domains=["statistics"],
            intended_use="Method development",
        ),
        owner_user_id="researcher.local",
    )
    projections = ResearchProjectionService(
        repository,
        SpecificationPackage.load(ARCHITECTURE).phases,
        execution_available=True,
    )

    p1 = projections.phase_view(
        project["project_id"], "P1", mode=None, method_id=None, active_runs=[], recent_runs=[]
    )
    p2 = projections.phase_view(
        project["project_id"], "P2", mode=None, method_id=None, active_runs=[], recent_runs=[]
    )

    assert p1.actions[0].enabled is True
    assert p2.actions[0].enabled is False
    assert p2.actions[0].reason_code == "input.required_current_record_missing"
