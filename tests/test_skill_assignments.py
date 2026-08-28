"""SK-1: per-phase skill assignment matrix load and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.configuration.skill_assignments import (
    SkillAssignmentMatrix,
    SkillDefaults,
)
from model_forge.harness.role_resource_snapshot import load_skill_manifest

TEAM_ROOT = Path(__file__).resolve().parents[1] / "resources" / "team"
SKILLS_ROOT = Path(__file__).resolve().parents[1] / "resources"


@pytest.fixture
def catalog() -> RoleResourceCatalog:
    return RoleResourceCatalog.load(TEAM_ROOT)


@pytest.fixture
def manifest() -> dict:
    return load_skill_manifest(SKILLS_ROOT)


def _write_matrix(tmp_path: Path, document: dict) -> Path:
    root = tmp_path / "team"
    root.mkdir()
    (root / "skill-assignments.json").write_text(
        json.dumps(document), encoding="utf-8"
    )
    return root


class TestSkillDefaults:
    def test_bundled_defaults_cover_every_role_phase_pair(
        self, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        defaults = SkillDefaults.load(TEAM_ROOT, catalog, manifest)
        pairs = {(entry.role, entry.phase) for entry in defaults.entries}
        for role in ("research_lead", "theorist", "data_analyst"):
            for phase in ("P1", "P2", "P3", "P4", "P5"):
                assert (role, phase) in pairs
        assert ("outside_reviewer", "P5") in pairs
        # The curated lead default for P1 is the literature pick.
        assert defaults.default_for("research_lead", "P1") == (
            "stat-literature-synthesis",
            "mf-contribution-boundary",
        )

    def test_curated_default_beats_catalog_union(
        self, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        matrix = SkillAssignmentMatrix.empty()
        defaults = SkillDefaults.load(TEAM_ROOT, catalog, manifest)
        resource = catalog.role("research_lead")
        assert matrix.effective_skills(resource, "P1", defaults) == (
            "stat-literature-synthesis",
            "mf-contribution-boundary",
        )
        # Without the defaults layer the union applies.
        assert "stat-paper-writing" in matrix.effective_skills(resource, "P1")

    def test_assignment_beats_curated_default(
        self, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        matrix = SkillAssignmentMatrix.empty().with_assignment(
            "research_lead", "P1", ("stat-paper-writing",)
        )
        defaults = SkillDefaults.load(TEAM_ROOT, catalog, manifest)
        resource = catalog.role("research_lead")
        assert matrix.effective_skills(resource, "P1", defaults) == (
            "stat-paper-writing",
        )

    def test_invalid_defaults_rejected(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "skill-defaults.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "defaults": [
                        {"role": "theorist", "phase": "P3", "skills": ["ghost"]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown bundled skill"):
            SkillDefaults.load(tmp_path, catalog, manifest)


class TestLoad:
    def test_bundled_file_is_zero_configuration(
        self, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        matrix = SkillAssignmentMatrix.load(TEAM_ROOT, catalog, manifest)
        assert matrix.assignments == ()
        # Defaults everywhere: the catalog's per-role union.
        resource = catalog.role("theorist")
        assert matrix.effective_skills(resource, "P3") == (
            "stat-paper-writing",
            "stat-method-design",
            "mf-proof-dependency",
        )

    def test_missing_file_means_defaults(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        matrix = SkillAssignmentMatrix.load(tmp_path, catalog, manifest)
        assert matrix.assignments == ()

    def test_assignment_replaces_default_for_the_pair(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        root = _write_matrix(
            tmp_path,
            {
                "schema_version": "1.0.0",
                "assignments": [
                    {
                        "role": "research_lead",
                        "phase": "P5",
                        "skills": ["stat-paper-writing"],
                    }
                ],
            },
        )
        matrix = SkillAssignmentMatrix.load(root, catalog, manifest)
        resource = catalog.role("research_lead")
        # Assigned pair: exactly the entry, never the default extended.
        assert matrix.effective_skills(resource, "P5") == ("stat-paper-writing",)
        # Other pairs keep the default.
        assert matrix.effective_skills(resource, "P4") == (
            "stat-paper-writing",
            "stat-literature-synthesis",
            "stat-method-design",
            "mf-contribution-boundary",
        )

    def test_empty_skills_list_is_legal(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        root = _write_matrix(
            tmp_path,
            {
                "schema_version": "1.0.0",
                "assignments": [
                    {"role": "data_analyst", "phase": "P1", "skills": []}
                ],
            },
        )
        matrix = SkillAssignmentMatrix.load(root, catalog, manifest)
        assert matrix.effective_skills(catalog.role("data_analyst"), "P1") == ()

    def test_cross_role_skill_assignment_allowed(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        root = _write_matrix(
            tmp_path,
            {
                "schema_version": "1.0.0",
                "assignments": [
                    {
                        "role": "theorist",
                        "phase": "P3",
                        "skills": ["mf-reproducibility-checklist"],
                    }
                ],
            },
        )
        matrix = SkillAssignmentMatrix.load(root, catalog, manifest)
        assert matrix.effective_skills(catalog.role("theorist"), "P3") == (
            "mf-reproducibility-checklist",
        )


class TestValidation:
    @pytest.mark.parametrize(
        ("entry", "match"),
        [
            ({"role": "nobody", "phase": "P1", "skills": []}, "unknown role"),
            ({"role": "theorist", "phase": "P9", "skills": []}, "unknown phase"),
            (
                {"role": "theorist", "phase": "P1", "skills": ["ghost-skill"]},
                "unknown bundled skill",
            ),
            (
                {
                    "role": "theorist",
                    "phase": "P1",
                    "skills": ["stat-paper-writing", "stat-paper-writing"],
                },
                "repeats",
            ),
        ],
    )
    def test_invalid_entries_rejected(
        self,
        tmp_path: Path,
        catalog: RoleResourceCatalog,
        manifest: dict,
        entry: dict,
        match: str,
    ) -> None:
        root = _write_matrix(
            tmp_path,
            {"schema_version": "1.0.0", "assignments": [entry]},
        )
        with pytest.raises(ValueError, match=match):
            SkillAssignmentMatrix.load(root, catalog, manifest)

    def test_duplicate_pair_rejected(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        root = _write_matrix(
            tmp_path,
            {
                "schema_version": "1.0.0",
                "assignments": [
                    {"role": "theorist", "phase": "P3", "skills": []},
                    {"role": "theorist", "phase": "P3", "skills": []},
                ],
            },
        )
        with pytest.raises(ValueError, match="Duplicate Skill assignment matrix"):
            SkillAssignmentMatrix.load(root, catalog, manifest)

    def test_wrong_schema_version_rejected(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        root = _write_matrix(
            tmp_path, {"schema_version": "0.9.0", "assignments": []}
        )
        with pytest.raises(ValueError, match="schema_version"):
            SkillAssignmentMatrix.load(root, catalog, manifest)


class TestUpdateAndSave:
    def test_with_assignment_and_save_round_trip(
        self, tmp_path: Path, catalog: RoleResourceCatalog, manifest: dict
    ) -> None:
        matrix = SkillAssignmentMatrix.empty()
        updated = matrix.with_assignment(
            "outside_reviewer", "P5", ("stat-paper-reviewer",)
        )
        assert matrix.assignments == ()  # original untouched (immutable)
        digest = updated.save(tmp_path)
        reloaded = SkillAssignmentMatrix.load(tmp_path, catalog, manifest)
        assert reloaded.assigned("outside_reviewer", "P5") == (
            "stat-paper-reviewer",
        )
        assert len(digest) == 64
        # Clearing the pair returns to the default.
        cleared = reloaded.with_assignment("outside_reviewer", "P5", None)
        assert cleared.assigned("outside_reviewer", "P5") is None
        assert cleared.effective_skills(
            catalog.role("outside_reviewer"), "P5"
        ) == ("stat-paper-reviewer", "mf-review-calibration")

    def test_save_is_atomic_and_formatted(self, tmp_path: Path) -> None:
        matrix = SkillAssignmentMatrix.empty().with_assignment(
            "research_lead", "P1", ()
        )
        matrix.save(tmp_path)
        text = (tmp_path / "skill-assignments.json").read_text(encoding="utf-8")
        assert json.loads(text)["assignments"][0]["skills"] == []
        assert text.endswith("\n")
        assert not (tmp_path / "skill-assignments.json.tmp").exists()
