from __future__ import annotations

from pathlib import Path

import pytest

from model_forge.configuration.profiles import (
    ProfileConfigurationError,
    ProfileMapping,
    discover_profiles,
    resolve_hermes_root,
    validate_profile_name,
)


def test_explicit_hermes_root_has_priority(tmp_path: Path) -> None:
    root = tmp_path / "hermes"
    assert resolve_hermes_root(
        environ={"MODEL_FORGE_HERMES_ROOT": str(root)},
        home=tmp_path / "home",
        platform_name="posix",
    ) == root.resolve()


def test_named_hermes_home_resolves_to_base(tmp_path: Path) -> None:
    profile = tmp_path / ".hermes" / "profiles" / "analyst"
    assert resolve_hermes_root(
        environ={"HERMES_HOME": str(profile)},
        home=tmp_path,
        platform_name="posix",
    ) == (tmp_path / ".hermes").resolve()


def test_profile_names_are_canonical() -> None:
    assert validate_profile_name("data_analyst") == "data_analyst"
    with pytest.raises(ProfileConfigurationError):
        validate_profile_name("Data Analyst")


def test_discovery_rejects_symlink_as_safe_profile(tmp_path: Path) -> None:
    root = tmp_path / "hermes"
    real = tmp_path / "real"
    real.mkdir()
    (root / "profiles").mkdir(parents=True)
    link = root / "profiles" / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable for this test account.")
    profiles = {item.name: item for item in discover_profiles(root)}
    assert profiles["linked"].is_safe_directory is False


def test_profile_mapping_is_role_specific() -> None:
    mapping = ProfileMapping("lead", "theory", "analysis", "reviewer")
    assert mapping.for_role("data_analyst") == "analysis"
