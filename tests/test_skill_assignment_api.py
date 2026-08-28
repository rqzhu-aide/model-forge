"""SK-3: role skill-assignment API (service level)."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from model_forge.api.errors import CommandRejected
from model_forge.api.models import UpdateSkillAssignmentsRequest
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository

ROOT = Path(__file__).resolve().parents[1]
ARCH_ROOT = ROOT / "architecture"
RESOURCE_ROOT = ROOT / "resources"


def _make_service(tmp_path: Path) -> ModelForgeService:
    """A real service whose skill bundle + team roots are tmp copies.

    The update endpoint writes the matrix file; tests must never write into
    the repository's real resources tree.
    """
    bundle = tmp_path / "resources" / "skills"
    team = tmp_path / "resources" / "team"
    bundle.mkdir(parents=True)
    team.mkdir(parents=True)
    shutil.copy(RESOURCE_ROOT / "skills" / "manifest.json", bundle / "manifest.json")
    shutil.copy(
        RESOURCE_ROOT / "team" / "skill-assignments.json",
        team / "skill-assignments.json",
    )
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    service = ModelForgeService(
        settings=ApplicationSettings(data_root=workspace.root, hermes_root=tmp_path),
        specification=SpecificationPackage.load(ARCH_ROOT),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(RESOURCE_ROOT / "team"),
    )
    service.skill_bundle_root = bundle
    return service


def _run(coroutine):
    return asyncio.run(coroutine)


class TestGetRoleSkillAssignments:
    def test_defaults_across_phases(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        view = _run(service.get_role_skill_assignments("theorist"))
        assert view.role_id == "theorist"
        assert [entry.phase for entry in view.phases] == [
            "P1",
            "P2",
            "P3",
            "P4",
            "P5",
        ]
        assert all(entry.source == "default" for entry in view.phases)
        assert view.phases[2].skills == ["stat-paper-writing", "stat-method-design", "mf-proof-dependency"]
        catalog_ids = {entry.skill_id for entry in view.available_skills}
        assert catalog_ids == {
            "stat-paper-writing",
            "stat-paper-reviewer",
            "stat-literature-synthesis",
            "stat-method-design",
            "stat-simulation-design",
            "mf-contribution-boundary",
            "mf-proof-dependency",
            "mf-reproducibility-checklist",
            "mf-review-calibration",
        }
        assert view.matrix_sha256 is not None and len(view.matrix_sha256) == 64

    def test_unknown_role_is_not_found(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        with pytest.raises(Exception, match="role"):
            _run(service.get_role_skill_assignments("nobody"))


class TestUpdateRoleSkillAssignments:
    def test_set_assignment_persists_and_reflects(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        view = _run(
            service.update_role_skill_assignments(
                "research_lead",
                "P5",
                UpdateSkillAssignmentsRequest(skills=["stat-paper-writing"]),
            )
        )
        p5 = next(entry for entry in view.phases if entry.phase == "P5")
        assert p5.source == "assigned"
        assert p5.skills == ["stat-paper-writing"]
        # Other phases keep the default.
        p4 = next(entry for entry in view.phases if entry.phase == "P4")
        assert p4.source == "default"
        # The matrix file was written in the tmp tree.
        text = (
            tmp_path / "resources" / "team" / "skill-assignments.json"
        ).read_text(encoding="utf-8")
        assert '"role": "research_lead"' in text
        # The cached matrix reflects the edit (no reload needed).
        assert service.skill_assignments.assigned("research_lead", "P5") == (
            "stat-paper-writing",
        )
        # The assembler cache was dropped so the next seal re-resolves.
        assert service._run_assembler is None

    def test_empty_list_runs_phase_with_no_skills(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        view = _run(
            service.update_role_skill_assignments(
                "data_analyst",
                "P1",
                UpdateSkillAssignmentsRequest(skills=[]),
            )
        )
        p1 = next(entry for entry in view.phases if entry.phase == "P1")
        assert p1.source == "assigned"
        assert p1.skills == []

    def test_null_clears_back_to_default(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        _run(
            service.update_role_skill_assignments(
                "theorist",
                "P3",
                UpdateSkillAssignmentsRequest(skills=["mf-review-calibration"]),
            )
        )
        view = _run(
            service.update_role_skill_assignments(
                "theorist", "P3", UpdateSkillAssignmentsRequest(skills=None)
            )
        )
        p3 = next(entry for entry in view.phases if entry.phase == "P3")
        assert p3.source == "default"
        assert p3.skills == ["stat-paper-writing", "stat-method-design", "mf-proof-dependency"]

    def test_unknown_skill_rejected(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        with pytest.raises(CommandRejected) as captured:
            _run(
                service.update_role_skill_assignments(
                    "theorist",
                    "P3",
                    UpdateSkillAssignmentsRequest(skills=["ghost-skill"]),
                )
            )
        assert captured.value.error.code == "COMMAND_SCHEMA_INVALID"
        # Nothing was written.
        assert service.skill_assignments.assigned("theorist", "P3") is None

    def test_duplicate_skill_rejected(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        with pytest.raises(CommandRejected):
            _run(
                service.update_role_skill_assignments(
                    "theorist",
                    "P3",
                    UpdateSkillAssignmentsRequest(
                        skills=["stat-paper-writing", "stat-paper-writing"]
                    ),
                )
            )

    def test_inapplicable_phase_rejected(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        with pytest.raises(CommandRejected) as captured:
            _run(
                service.update_role_skill_assignments(
                    "theorist",
                    "P9",
                    UpdateSkillAssignmentsRequest(skills=[]),
                )
            )
        assert captured.value.error.code == "COMMAND_SCHEMA_INVALID"
