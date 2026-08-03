from __future__ import annotations

from pathlib import Path

from method_hub.configuration.resources import RoleResourceCatalog


RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "team"


def test_bundled_role_resources_cover_team_and_recommended_skills() -> None:
    catalog = RoleResourceCatalog.load(RESOURCES)

    assert [item.role_id for item in catalog.roles] == [
        "research_lead",
        "theorist",
        "data_analyst",
        "outside_reviewer",
    ]
    assert catalog.role("outside_reviewer").recommended_skills[0].skill_id == (
        "stat-paper-reviewer"
    )
    assert catalog.role("theorist").recommended_skills[0].skill_id == (
        "stat-paper-writing"
    )
    assert all(len(item.soul_sha256) == 64 for item in catalog.roles)
