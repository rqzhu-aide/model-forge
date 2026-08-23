from __future__ import annotations

import pytest

from model_forge.configuration.skill_installer import (
    SkillConflictError,
    install_bundled_skill,
)


def test_bundled_skill_install_is_verified_and_idempotent(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    source = bundle / "stat-paper-writing"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Writing\n", encoding="utf-8")
    profile = tmp_path / "profile"
    profile.mkdir()

    first = install_bundled_skill(
        bundle_root=bundle,
        profile_home=profile,
        skill_id="stat-paper-writing",
    )
    second = install_bundled_skill(
        bundle_root=bundle,
        profile_home=profile,
        skill_id="stat-paper-writing",
    )

    assert first.created is True
    assert second.created is False
    assert first.content_sha256 == second.content_sha256


def test_bundled_skill_install_refuses_different_local_copy(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    source = bundle / "stat-paper-reviewer"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Pinned\n", encoding="utf-8")
    profile = tmp_path / "profile"
    installed = profile / "skills" / "stat-paper-reviewer"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("# Local edit\n", encoding="utf-8")

    with pytest.raises(SkillConflictError):
        install_bundled_skill(
            bundle_root=bundle,
            profile_home=profile,
            skill_id="stat-paper-reviewer",
        )

    assert (installed / "SKILL.md").read_text(encoding="utf-8") == "# Local edit\n"
