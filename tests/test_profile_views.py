from __future__ import annotations

from pathlib import Path

from model_forge.application.profile_views import build_profile_configuration_view
from model_forge.configuration.profiles import (
    ProfileMapping,
    discover_profiles,
)
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.configuration.skill_installer import install_bundled_skill


RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "team"
BUNDLED_SKILLS = Path(__file__).resolve().parents[1] / "resources" / "skills"


def test_profile_view_reports_recommended_skill_per_role(tmp_path: Path) -> None:
    hermes = tmp_path / "hermes"
    hermes.mkdir()
    (hermes / "profiles").mkdir()
    for name in ("research_lead", "theorist", "data_analyst", "paper_reviewer"):
        (hermes / "profiles" / name).mkdir()
    install_bundled_skill(
        bundle_root=BUNDLED_SKILLS,
        profile_home=hermes / "profiles" / "paper_reviewer",
        skill_id="stat-paper-reviewer",
    )

    view = build_profile_configuration_view(
        project_id="project.example",
        catalog=RoleResourceCatalog.load(RESOURCES),
        mapping=ProfileMapping(
            research_lead="research_lead",
            theorist="theorist",
            data_analyst="data_analyst",
            outside_reviewer="paper_reviewer",
        ),
        mapping_revisions={
            "research_lead": 0,
            "theorist": 0,
            "data_analyst": 0,
            "outside_reviewer": 0,
        },
        discoveries=discover_profiles(hermes),
        bundle_root=BUNDLED_SKILLS,
    )

    by_role = {item.role_id: item for item in view.profiles}
    assert by_role["outside_reviewer"].skills[0].status == "installed"
    assert by_role["theorist"].skills[0].status == "missing"
    assert by_role["theorist"].skills[0].actions[0].enabled is True
