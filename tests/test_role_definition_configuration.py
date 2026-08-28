"""Block 2: role-definition configuration service tests.

Covers: role definition CRUD for all four roles, skill install/update with
version+source+digest reporting, customization-conflict requires explicit
choice (silent overwrite fails), atomic rollback on injected partial failure,
and each status condition.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from model_forge.api.errors import CommandRejected
from model_forge.api.models import (
    ConfigurationHealthView,
    ProvisionRoleRequest,
    RoleDefinitionCatalogView,
    RoleDefinitionView,
    RoleHealthReportView,
)
from model_forge.application.role_views import (
    build_configuration_health_view,
    build_role_definition_catalog_view,
    build_role_health_view,
)
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.profiles import PROFILE_ROLES
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.configuration.role_provisioner import (
    CustomizationConflict,
    ProvisioningError,
    assess_role_health,
    provision_role_definition,
)
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
ARCH_ROOT = ROOT / "architecture"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def catalog() -> RoleResourceCatalog:
    return RoleResourceCatalog.load(RESOURCE_ROOT)


@pytest.fixture
def bundle_root() -> Path:
    return ROOT / "resources" / "skills"


def _make_service(tmp_path: Path) -> ModelForgeService:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    hermes = tmp_path / "hermes"
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    return ModelForgeService(
        settings=ApplicationSettings(data_root=workspace.root, hermes_root=hermes),
        specification=SpecificationPackage.load(ARCH_ROOT),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
    )


def _make_profile_dirs(hermes_root: Path) -> dict[str, Path]:
    """Create one profile directory per role."""
    result = {}
    for role in PROFILE_ROLES:
        name = role if role != "outside_reviewer" else "paper_reviewer"
        path = hermes_root / "profiles" / name
        path.mkdir(parents=True, exist_ok=True)
        result[role] = path
    return result


# --------------------------------------------------------------------------- #
# 1. Role definition CRUD: all four roles are present and inspectable
# --------------------------------------------------------------------------- #


def test_role_definition_catalog_has_all_four_roles(catalog: RoleResourceCatalog) -> None:
    view = build_role_definition_catalog_view(catalog)
    assert set(r.role_id for r in view.roles) == set(PROFILE_ROLES)
    assert len(view.roles) == 4


def test_role_definition_contains_soul_config_skills_guidance(
    catalog: RoleResourceCatalog,
) -> None:
    for resource in catalog.roles:
        view = build_role_definition_catalog_view(catalog)
        role_def = next(r for r in view.roles if r.role_id == resource.role_id)
        # SOUL
        assert role_def.soul_text == resource.soul_text
        assert role_def.soul_sha256 == resource.soul_sha256
        # Base configuration
        assert role_def.base_configuration.file_name is not None
        assert role_def.base_configuration.format in ("yaml", "json")
        assert len(role_def.base_configuration.content_sha256) == 64
        # Recommended skills
        assert len(role_def.recommended_skills) >= 1
        for skill_view, skill_resource in zip(
            role_def.recommended_skills, resource.recommended_skills
        ):
            assert skill_view.skill_id == skill_resource.skill_id
            assert skill_view.source == skill_resource.source
            assert skill_view.recommended_version == skill_resource.recommended_version
        # Custom skills
        assert len(role_def.custom_skills) >= 1
        # Library guidance
        assert role_def.library_guidance.file_name is not None
        assert len(role_def.library_guidance.content_sha256) == 64


def test_role_definition_soul_sha_matches_content(catalog: RoleResourceCatalog) -> None:
    view = build_role_definition_catalog_view(catalog)
    for role_def in view.roles:
        expected = hashlib.sha256(role_def.soul_text.encode("utf-8")).hexdigest()
        assert role_def.soul_sha256 == expected


def test_individual_role_definition_lookup(catalog: RoleResourceCatalog) -> None:
    from model_forge.application.role_views import build_role_definition_view

    for role_id in PROFILE_ROLES:
        view = build_role_definition_view(catalog, role_id)
        assert view.role_id == role_id


def test_individual_role_definition_unknown_role_raises(
    catalog: RoleResourceCatalog,
) -> None:
    from model_forge.application.role_views import build_role_definition_view

    with pytest.raises(ValueError):
        build_role_definition_view(catalog, "nonexistent_role")


def test_role_definition_default_profile_matches_settings(
    catalog: RoleResourceCatalog,
) -> None:
    view = build_role_definition_catalog_view(catalog)
    for role_def in view.roles:
        assert role_def.default_profile is not None
        assert len(role_def.default_profile) > 0


# --------------------------------------------------------------------------- #
# 2. Skill install/update with version, source, digest, and customization
# --------------------------------------------------------------------------- #


def test_provision_writes_soul_config_and_guidance(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    result = provision_role_definition(resource, profile_home, bundle)

    assert "SOUL.md" in result.assets_written
    assert resource.base_configuration.file_name in result.assets_written
    assert resource.library_guidance.file_name in result.assets_written
    soul_on_disk = (profile_home / "SOUL.md").read_text(encoding="utf-8")
    assert soul_on_disk == resource.soul_text
    config_on_disk = (profile_home / resource.base_configuration.file_name).read_text(encoding="utf-8")
    assert config_on_disk == resource.base_configuration.content


def test_provision_reports_installed_skill_digest(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("research_lead")
    profile_home = profiles["research_lead"]

    result = provision_role_definition(resource, profile_home, bundle)

    assert len(result.skills_installed) >= 1
    installed = result.skills_installed[0]
    assert installed.skill_id == "stat-paper-writing"
    assert installed.created is True
    assert len(installed.content_sha256) == 64
    # Verify the digest matches the bundle
    from model_forge.configuration.skill_installer import directory_sha256

    bundle_digest = directory_sha256(bundle / "stat-paper-writing")
    assert installed.content_sha256 == bundle_digest


def test_provision_idempotent_on_second_call(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("data_analyst")
    profile_home = profiles["data_analyst"]

    first = provision_role_definition(resource, profile_home, bundle)
    second = provision_role_definition(resource, profile_home, bundle)

    # First call writes assets; second finds them already present.
    assert len(first.assets_written) > 0
    assert len(second.assets_written) == 0
    assert len(second.skills_installed) == 0


def test_health_report_shows_installed_skill_with_source_and_version(
    tmp_path: Path,
) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("research_lead")
    profile_home = profiles["research_lead"]

    provision_role_definition(resource, profile_home, bundle)
    report = assess_role_health(resource, profile_home, bundle)

    assert report.overall_status == "healthy"
    assert report.soul_status.status == "present"
    assert report.configuration_status.status == "present"
    assert report.guidance_status.status == "present"
    for skill_status in report.skill_statuses:
        assert skill_status.status == "present"
        assert skill_status.source is not None
        assert skill_status.recommended_version is not None
        assert skill_status.expected_sha256 == skill_status.actual_sha256


# --------------------------------------------------------------------------- #
# 3. Customization conflict requires explicit choice (silent overwrite fails)
# --------------------------------------------------------------------------- #


def test_provision_refuses_to_overwrite_customized_soul(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Pre-write a customized SOUL.md
    (profile_home / "SOUL.md").write_text("# Custom soul\n", encoding="utf-8")

    with pytest.raises(CustomizationConflict) as exc_info:
        provision_role_definition(resource, profile_home, bundle)

    conflict = exc_info.value
    assert conflict.role_id == "theorist"
    assert conflict.asset_type == "soul"
    assert conflict.expected_sha256 != conflict.actual_sha256
    # The customized file must be preserved
    assert (profile_home / "SOUL.md").read_text(encoding="utf-8") == "# Custom soul\n"


def test_provision_refuses_to_overwrite_customized_config(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Pre-write the canonical SOUL.md so provisioning gets past it
    (profile_home / "SOUL.md").write_text(resource.soul_text, encoding="utf-8")
    # Pre-write a customized config
    config_file = resource.base_configuration.file_name
    config_path = profile_home / config_file
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("# custom: true\n", encoding="utf-8")

    with pytest.raises(CustomizationConflict) as exc_info:
        provision_role_definition(resource, profile_home, bundle)

    assert exc_info.value.asset_type == "base_configuration"
    # Customized config must be preserved
    assert config_path.read_text(encoding="utf-8") == "# custom: true\n"


def test_provision_force_overwrite_replaces_customized_soul(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Pre-write a customized SOUL.md
    (profile_home / "SOUL.md").write_text("# Custom soul\n", encoding="utf-8")

    result = provision_role_definition(
        resource, profile_home, bundle, force_overwrite_assets=True
    )

    assert "SOUL.md" in result.assets_written
    soul = (profile_home / "SOUL.md").read_text(encoding="utf-8")
    assert soul == resource.soul_text


def test_provision_does_not_overwrite_customized_skill(tmp_path: Path) -> None:
    """A customized skill (different content) is not overwritten silently."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Write canonical SOUL and config first so we get to the skill step
    (profile_home / "SOUL.md").write_text(resource.soul_text, encoding="utf-8")
    config_path = profile_home / resource.base_configuration.file_name
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(resource.base_configuration.content, encoding="utf-8")
    guidance_path = profile_home / resource.library_guidance.file_name
    guidance_path.parent.mkdir(parents=True, exist_ok=True)
    guidance_path.write_text(resource.library_guidance.content, encoding="utf-8")
    # Pre-install a different skill under the same name
    from model_forge.configuration.skill_installer import SkillConflictError

    custom_skill_dir = profile_home / "skills" / "stat-paper-writing"
    custom_skill_dir.mkdir(parents=True)
    (custom_skill_dir / "SKILL.md").write_text("# Custom skill\n", encoding="utf-8")

    with pytest.raises(SkillConflictError):
        provision_role_definition(resource, profile_home, bundle)

    # The customized skill must be preserved
    assert (custom_skill_dir / "SKILL.md").read_text(encoding="utf-8") == "# Custom skill\n"


def test_health_report_detects_customization(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Write the canonical assets
    provision_role_definition(resource, profile_home, bundle)
    # Then customize the SOUL
    (profile_home / "SOUL.md").write_text("# Modified\n", encoding="utf-8")

    report = assess_role_health(resource, profile_home, bundle)
    assert report.overall_status == "customized"
    assert report.soul_status.status == "customized"
    assert report.soul_status.expected_sha256 != report.soul_status.actual_sha256


# --------------------------------------------------------------------------- #
# 4. Atomic rollback on injected partial failure
# --------------------------------------------------------------------------- #


def test_atomic_rollback_on_injected_failure(tmp_path: Path) -> None:
    """If provisioning fails partway through, the profile is restored."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Pre-write a file that exists before provisioning
    pre_existing = profile_home / "pre-existing.txt"
    pre_existing.write_text("original\n", encoding="utf-8")

    # Inject a failure in the pre_skill_hook to simulate partial failure
    def fail_hook(skill_id: str) -> None:
        raise RuntimeError("Injected failure during skill install")

    with pytest.raises(RuntimeError, match="Injected failure"):
        provision_role_definition(
            resource,
            profile_home,
            bundle,
            pre_skill_hook=fail_hook,
        )

    # Rollback: the profile must be in its original state
    # SOUL.md should NOT have been written (because rollback restored)
    assert not (profile_home / "SOUL.md").exists()
    # Pre-existing file must be intact
    assert pre_existing.read_text(encoding="utf-8") == "original\n"


def test_atomic_rollback_preserves_pre_existing_content(tmp_path: Path) -> None:
    """Pre-existing profile content survives a failed provisioning attempt."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("research_lead")
    profile_home = profiles["research_lead"]

    # Pre-write some existing files
    existing_file = profile_home / "existing.txt"
    existing_file.write_text("important data\n", encoding="utf-8")

    # Create a directory structure that should survive rollback
    sub_dir = profile_home / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file.txt").write_text("nested\n", encoding="utf-8")

    # Inject failure
    def fail_hook(skill_id: str) -> None:
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        provision_role_definition(
            resource, profile_home, bundle, pre_skill_hook=fail_hook
        )

    assert existing_file.read_text(encoding="utf-8") == "important data\n"
    assert (sub_dir / "file.txt").read_text(encoding="utf-8") == "nested\n"


# --------------------------------------------------------------------------- #
# 5. Status conditions: missing Hermes, missing profiles, invalid role files,
#    skill mismatch, unsupported versions
# --------------------------------------------------------------------------- #


def test_health_hermes_missing(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "nonexistent_hermes"

    from model_forge.configuration.role_provisioner import hermes_available

    assert not hermes_available(hermes_root)

    effective = {role: role for role in PROFILE_ROLES}
    effective["outside_reviewer"] = "paper_reviewer"
    view = build_configuration_health_view(catalog, hermes_root, bundle, effective)

    assert view.hermes_available is False
    assert "hermes_missing" in view.conditions
    assert view.overall_status == "unavailable"


def test_health_profile_missing(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    hermes_root.mkdir(parents=True)
    # No profiles directory created → profiles are missing

    effective = {role: role for role in PROFILE_ROLES}
    effective["outside_reviewer"] = "paper_reviewer"
    view = build_configuration_health_view(catalog, hermes_root, bundle, effective)

    # Every role should report profile_missing
    assert view.overall_status == "unavailable"
    assert "profile_missing" in view.conditions
    for role_report in view.roles:
        assert role_report.profile_available is False


def test_health_soul_missing(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]
    # Profile exists but is empty — soul is missing

    report = assess_role_health(resource, profile_home, bundle)
    assert report.soul_status.status == "missing"
    assert report.overall_status == "incomplete"


def test_health_config_missing(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]
    # Write SOUL but not config
    (profile_home / "SOUL.md").write_text(resource.soul_text, encoding="utf-8")

    report = assess_role_health(resource, profile_home, bundle)
    assert report.configuration_status.status == "missing"


def test_health_skill_missing(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]
    # Write SOUL and config but not the skill
    (profile_home / "SOUL.md").write_text(resource.soul_text, encoding="utf-8")
    config_path = profile_home / resource.base_configuration.file_name
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(resource.base_configuration.content, encoding="utf-8")
    guidance_path = profile_home / resource.library_guidance.file_name
    guidance_path.parent.mkdir(parents=True, exist_ok=True)
    guidance_path.write_text(resource.library_guidance.content, encoding="utf-8")

    report = assess_role_health(resource, profile_home, bundle)
    for skill_status in report.skill_statuses:
        assert skill_status.status == "missing"


def test_health_skill_mismatch(tmp_path: Path) -> None:
    """A skill with different content is flagged as mismatched/customized."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Provision everything correctly
    provision_role_definition(resource, profile_home, bundle)
    # Then modify the installed skill
    skill_dir = profile_home / "skills" / "stat-paper-writing"
    (skill_dir / "SKILL.md").write_text("# Modified\n", encoding="utf-8")

    report = assess_role_health(resource, profile_home, bundle)
    assert report.overall_status == "customized"
    skill_status = report.skill_statuses[0]
    assert skill_status.status == "customized"
    assert skill_status.expected_sha256 != skill_status.actual_sha256


def test_health_all_present_is_healthy(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("research_lead")
    profile_home = profiles["research_lead"]

    provision_role_definition(resource, profile_home, bundle)
    report = assess_role_health(resource, profile_home, bundle)
    assert report.overall_status == "healthy"


def test_health_all_four_roles_in_aggregate(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)

    # Provision all four roles
    for resource in catalog.roles:
        provision_role_definition(resource, profiles[resource.role_id], bundle)

    effective = {role: role for role in PROFILE_ROLES}
    effective["outside_reviewer"] = "paper_reviewer"
    view = build_configuration_health_view(catalog, hermes_root, bundle, effective)

    assert view.overall_status == "healthy"
    assert "healthy" in view.conditions
    assert len(view.roles) == 4
    for role_report in view.roles:
        assert role_report.overall_status == "healthy"


# --------------------------------------------------------------------------- #
# 6. Service-layer integration tests (async)
# --------------------------------------------------------------------------- #


def test_service_get_role_definitions(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        result = await service.get_role_definitions()
        assert set(r.role_id for r in result.roles) == set(PROFILE_ROLES)

    asyncio.run(run())


def test_service_get_role_definition(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        result = await service.get_role_definition("theorist")
        assert result.role_id == "theorist"
        assert result.soul_sha256 is not None

    asyncio.run(run())


def test_service_get_role_definition_unknown_raises(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        with pytest.raises(CommandRejected):
            await service.get_role_definition("nonexistent")

    asyncio.run(run())


def test_service_get_configuration_health_hermes_missing(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        # Hermes root is tmp_path / "hermes" which doesn't exist yet
        health = await service.get_configuration_health()
        assert health.hermes_available is False
        assert "hermes_missing" in health.conditions

    asyncio.run(run())


def test_service_provision_role(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        # Create the Hermes profiles
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        _make_profile_dirs(hermes_root)
        command = ProvisionRoleRequest()
        result = await service.provision_role("theorist", command)
        assert result.role_id == "theorist"
        assert "SOUL.md" in result.assets_written
        assert len(result.skills_installed) >= 1
        assert result.rolled_back is False

    asyncio.run(run())


def test_service_provision_role_customization_conflict(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        profiles = _make_profile_dirs(hermes_root)
        # Pre-write a customized SOUL
        (profiles["theorist"] / "SOUL.md").write_text("# Custom\n", encoding="utf-8")

        command = ProvisionRoleRequest()
        with pytest.raises(CommandRejected) as exc_info:
            await service.provision_role("theorist", command)
        assert exc_info.value.error.code == "CUSTOMIZATION_CONFLICT"

    asyncio.run(run())


def test_service_provision_role_force_overwrite(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        profiles = _make_profile_dirs(hermes_root)
        # Pre-write a customized SOUL
        (profiles["theorist"] / "SOUL.md").write_text("# Custom\n", encoding="utf-8")

        command = ProvisionRoleRequest(force_overwrite_assets=True)
        result = await service.provision_role("theorist", command)
        assert "SOUL.md" in result.assets_written

    asyncio.run(run())


def test_service_provision_role_hermes_missing(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        command = ProvisionRoleRequest()
        with pytest.raises(CommandRejected) as exc_info:
            await service.provision_role("theorist", command)
        # Hermes root doesn't exist
        assert exc_info.value.error.code == "DEPENDENCY_CLOSURE_INCOMPLETE"

    asyncio.run(run())


def test_service_provision_role_profile_missing(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        # Create Hermes root but no profiles
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        hermes_root.mkdir(parents=True)
        command = ProvisionRoleRequest()
        with pytest.raises(CommandRejected) as exc_info:
            await service.provision_role("theorist", command)
        assert exc_info.value.error.code == "TARGET_NOT_FOUND"

    asyncio.run(run())


def test_service_get_role_health(tmp_path: Path) -> None:
    async def run() -> None:
        service = _make_service(tmp_path)
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        _make_profile_dirs(hermes_root)
        # Provision the role
        await service.provision_role("research_lead", ProvisionRoleRequest())
        health = await service.get_role_health("research_lead")
        assert health.overall_status == "healthy"

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# 7. Invalid role files / catalog validation
# --------------------------------------------------------------------------- #


def test_invalid_role_files_missing_base_configuration(tmp_path: Path) -> None:
    """Catalog without base_configuration raises an error."""
    bad_root = tmp_path / "bad_team"
    bad_root.mkdir()
    (bad_root / "souls").mkdir()
    # Write a soul
    (bad_root / "souls" / "theorist.md").write_text("# Theorist\n", encoding="utf-8")
    # Write roles.json without base_configuration
    roles_doc = {
        "schema_version": "1.0.0",
        "roles": [
            {
                "role_id": "theorist",
                "display_name": "Theorist",
                "profile_version": "1.0.0",
                "default_profile": "theorist",
                "soul_file": "souls/theorist.md",
                "applicable_phases": ["P3"],
                "recommended_skills": [],
            }
        ],
        "skills": [],
    }
    for role in PROFILE_ROLES[1:]:
        roles_doc["roles"].append(
            {
                "role_id": role,
                "display_name": role,
                "profile_version": "1.0.0",
                "default_profile": role,
                "soul_file": f"souls/{role}.md",
                "applicable_phases": ["P5"],
                "recommended_skills": [],
            }
        )
        (bad_root / "souls" / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")
    (bad_root / "roles.json").write_text(json.dumps(roles_doc), encoding="utf-8")

    with pytest.raises(ValueError, match="base_configuration"):
        RoleResourceCatalog.load(bad_root)


def test_invalid_role_files_missing_library_guidance(tmp_path: Path) -> None:
    """Catalog without library_guidance raises an error."""
    bad_root = tmp_path / "bad_team"
    bad_root.mkdir()
    (bad_root / "souls").mkdir()
    (bad_root / "configs").mkdir()
    for role in PROFILE_ROLES:
        (bad_root / "souls" / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")
        (bad_root / "configs" / f"{role}.yaml").write_text("profile: {}\n", encoding="utf-8")
    roles_doc = {
        "schema_version": "1.0.0",
        "roles": [
            {
                "role_id": role,
                "display_name": role,
                "profile_version": "1.0.0",
                "default_profile": role,
                "soul_file": f"souls/{role}.md",
                "base_configuration": {
                    "file": f"configs/{role}.yaml",
                    "format": "yaml",
                },
                # Missing library_guidance
                "applicable_phases": ["P5"],
                "recommended_skills": [],
            }
            for role in PROFILE_ROLES
        ],
        "skills": [],
    }
    (bad_root / "roles.json").write_text(json.dumps(roles_doc), encoding="utf-8")

    with pytest.raises(ValueError, match="library_guidance"):
        RoleResourceCatalog.load(bad_root)


def test_unsupported_configuration_format_rejected(tmp_path: Path) -> None:
    """An unsupported config format raises an error."""
    bad_root = tmp_path / "bad_team"
    bad_root.mkdir()
    (bad_root / "souls").mkdir()
    (bad_root / "configs").mkdir()
    (bad_root / "guidance").mkdir()
    for role in PROFILE_ROLES:
        (bad_root / "souls" / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")
        (bad_root / "configs" / f"{role}.yaml").write_text("profile: {}\n", encoding="utf-8")
        (bad_root / "guidance" / f"{role}.md").write_text(f"# Guidance {role}\n", encoding="utf-8")
    roles_doc = {
        "schema_version": "1.0.0",
        "roles": [
            {
                "role_id": role,
                "display_name": role,
                "profile_version": "1.0.0",
                "default_profile": role,
                "soul_file": f"souls/{role}.md",
                "base_configuration": {
                    "file": f"configs/{role}.yaml",
                    "format": "xml",  # unsupported
                },
                "library_guidance": {"file": f"guidance/{role}.md"},
                "applicable_phases": ["P5"],
                "recommended_skills": [],
            }
            for role in PROFILE_ROLES
        ],
        "skills": [],
    }
    (bad_root / "roles.json").write_text(json.dumps(roles_doc), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported configuration format"):
        RoleResourceCatalog.load(bad_root)


# --------------------------------------------------------------------------- #
# 8. Project-role memory and session state are NOT part of role definition
# --------------------------------------------------------------------------- #


def test_role_definition_excludes_memory_and_session_state(
    catalog: RoleResourceCatalog,
) -> None:
    """Role definitions must not include project-role memory or session state."""
    view = build_role_definition_catalog_view(catalog)
    for role_def in view.roles:
        # Verify the view fields — no memory or session fields
        assert not hasattr(role_def, "memory")
        assert not hasattr(role_def, "session_state")
        assert not hasattr(role_def, "project_role_memory")
        # The role definition should have soul, config, skills, guidance only
        field_names = set(type(role_def).model_fields.keys())
        assert "soul_text" in field_names
        assert "base_configuration" in field_names
        assert "recommended_skills" in field_names
        assert "library_guidance" in field_names


# --------------------------------------------------------------------------- #
# 9. All four roles can be provisioned and then inspected
# --------------------------------------------------------------------------- #


def test_all_four_roles_provision_and_inspect(tmp_path: Path) -> None:
    """End-to-end: provision all four roles and verify health is healthy."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)

    for resource in catalog.roles:
        result = provision_role_definition(resource, profiles[resource.role_id], bundle)
        assert result.rolled_back is False

    # Verify all are healthy
    effective = {role: role for role in PROFILE_ROLES}
    effective["outside_reviewer"] = "paper_reviewer"
    view = build_configuration_health_view(catalog, hermes_root, bundle, effective)
    assert view.overall_status == "healthy"
    for role_report in view.roles:
        assert role_report.overall_status == "healthy"
        assert role_report.soul_status.status == "present"
        assert role_report.configuration_status.status == "present"
        assert role_report.guidance_status.status == "present"
        for skill in role_report.skill_statuses:
            assert skill.status == "present"


# --------------------------------------------------------------------------- #
# 10. Hardening: skill conflict → 409, unreadable files, crash-safe rollback,
#     default-profile rejection, unavailable-skill condition codes
# --------------------------------------------------------------------------- #


def test_service_provision_role_skill_conflict_maps_to_409(tmp_path: Path) -> None:
    """A customized skill directory surfaces as CUSTOMIZATION_CONFLICT, not a 500."""

    async def run() -> None:
        service = _make_service(tmp_path)
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        profiles = _make_profile_dirs(hermes_root)
        resource = service.role_resources.role("theorist")
        profile_home = profiles["theorist"]
        # Write canonical assets so provisioning reaches the skill step
        (profile_home / "SOUL.md").write_text(resource.soul_text, encoding="utf-8")
        config_path = profile_home / resource.base_configuration.file_name
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(resource.base_configuration.content, encoding="utf-8")
        guidance_path = profile_home / resource.library_guidance.file_name
        guidance_path.parent.mkdir(parents=True, exist_ok=True)
        guidance_path.write_text(resource.library_guidance.content, encoding="utf-8")
        # Pre-install a customized skill under the same name
        custom_skill = profile_home / "skills" / "stat-paper-writing"
        custom_skill.mkdir(parents=True)
        (custom_skill / "SKILL.md").write_text("# Custom\n", encoding="utf-8")

        with pytest.raises(CommandRejected) as exc_info:
            await service.provision_role("theorist", ProvisionRoleRequest())
        assert exc_info.value.error.code == "CUSTOMIZATION_CONFLICT"
        # Rollback preserved the user's customized skill
        assert (custom_skill / "SKILL.md").read_text(encoding="utf-8") == "# Custom\n"

    asyncio.run(run())


def test_service_provision_role_unreadable_soul_is_conflict(tmp_path: Path) -> None:
    """A binary (non-UTF-8) SOUL.md is a conflict, never silently overwritten."""

    async def run() -> None:
        service = _make_service(tmp_path)
        hermes_root = Path(service.settings.hermes_root or (tmp_path / "hermes"))
        profiles = _make_profile_dirs(hermes_root)
        binary = profiles["theorist"] / "SOUL.md"
        payload = b"\xff\xfe\x00 binary soul not utf-8"
        binary.write_bytes(payload)

        with pytest.raises(CommandRejected) as exc_info:
            await service.provision_role("theorist", ProvisionRoleRequest())
        assert exc_info.value.error.code == "CUSTOMIZATION_CONFLICT"
        # The binary file is untouched after rollback
        assert (profiles["theorist"] / "SOUL.md").read_bytes() == payload

    asyncio.run(run())


def test_provision_unreadable_asset_conflict_and_force_overwrite(tmp_path: Path) -> None:
    """Provisioner level: an unreadable file is a conflict, not 'missing'."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]
    binary = profile_home / "SOUL.md"
    payload = b"\xff\xfe not utf-8"
    binary.write_bytes(payload)

    with pytest.raises(CustomizationConflict):
        provision_role_definition(resource, profile_home, bundle)
    assert binary.read_bytes() == payload

    # With explicit force-overwrite the user's choice is honored
    result = provision_role_definition(
        resource, profile_home, bundle, force_overwrite_assets=True
    )
    assert "SOUL.md" in result.assets_written
    assert (profile_home / "SOUL.md").read_text(encoding="utf-8") == resource.soul_text


def test_health_unreadable_asset_reported_customized_not_missing(tmp_path: Path) -> None:
    """Health assessment treats unreadable files as customized, not missing."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]
    # Provision canonically first, then replace SOUL.md with a binary file
    provision_role_definition(resource, profile_home, bundle)
    (profile_home / "SOUL.md").write_bytes(b"\xff\xfe binary")

    report = assess_role_health(resource, profile_home, bundle)
    assert report.soul_status.status == "customized"
    assert report.soul_status.actual_sha256 is not None
    assert report.overall_status == "customized"


def test_restore_backup_recovers_profile_when_move_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the backup cannot be moved into place, the original profile is recovered."""
    from model_forge.configuration import role_provisioner as provisioner_module

    profile_home = tmp_path / "profiles" / "theorist"
    profile_home.mkdir(parents=True)
    marker = profile_home / "pre-existing.txt"
    marker.write_text("original\n", encoding="utf-8")
    backup = provisioner_module._backup_profile(profile_home)

    real_replace = os.replace
    calls = {"count": 0}

    def failing_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:  # the backup → profile_home move
            raise OSError("injected move failure")
        return real_replace(src, dst)

    monkeypatch.setattr(provisioner_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="injected move failure"):
        provisioner_module._restore_backup(profile_home, backup)

    # Recovery moved the original profile back into place
    assert profile_home.is_dir()
    assert marker.read_text(encoding="utf-8") == "original\n"


def test_restore_backup_crash_between_rename_and_move_leaves_recoverable_trash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash after the rename (before the move) never deletes the original."""
    from model_forge.configuration import role_provisioner as provisioner_module

    profile_home = tmp_path / "profiles" / "theorist"
    profile_home.mkdir(parents=True)
    marker = profile_home / "pre-existing.txt"
    marker.write_text("original\n", encoding="utf-8")
    backup = provisioner_module._backup_profile(profile_home)

    real_replace = os.replace
    calls = {"count": 0}

    def failing_replace(src, dst):
        calls["count"] += 1
        if calls["count"] >= 2:  # move AND recovery both fail (process crash)
            raise OSError("injected failure")
        return real_replace(src, dst)

    monkeypatch.setattr(provisioner_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="injected failure"):
        provisioner_module._restore_backup(profile_home, backup)

    # The original profile was renamed aside, not deleted: its content is
    # fully recoverable from the trash directory.
    assert not profile_home.exists()
    trash_dirs = [
        p
        for p in (tmp_path / "profiles").iterdir()
        if p.name.startswith(".theorist.trash-")
    ]
    assert len(trash_dirs) == 1
    assert (trash_dirs[0] / "pre-existing.txt").read_text(encoding="utf-8") == "original\n"


def test_provision_rejects_default_profile_name(tmp_path: Path) -> None:
    """Provisioning must never target the reserved 'default' (Hermes root) profile."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    resource = catalog.role("theorist")
    default_home = tmp_path / "default"
    default_home.mkdir()

    with pytest.raises(ProvisioningError, match="default"):
        provision_role_definition(resource, default_home, bundle)
    # Nothing was written into the root directory
    assert not (default_home / "SOUL.md").exists()
    assert not (default_home / "skills").exists()


def test_service_provision_rejects_default_profile(tmp_path: Path) -> None:
    """A role mapped to the 'default' profile is rejected before any write."""

    async def run() -> None:
        workspace = WorkspacePaths(tmp_path / "data", create=True)
        hermes = tmp_path / "hermes"
        hermes.mkdir(parents=True)
        repository = HubRepository(workspace.root / "hub.sqlite3")
        repository.initialize()
        service = ModelForgeService(
            settings=ApplicationSettings(
                data_root=workspace.root,
                hermes_root=hermes,
                theorist_profile="default",
            ),
            specification=SpecificationPackage.load(ARCH_ROOT),
            repository=repository,
            artifacts=ArtifactStore(workspace),
            role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
        )

        with pytest.raises(CommandRejected) as exc_info:
            await service.provision_role("theorist", ProvisionRoleRequest())
        assert exc_info.value.error.code == "ROLE_PROVISIONING_FAILED"
        # Nothing was written into the Hermes root
        assert not (hermes / "SOUL.md").exists()
        assert not (hermes / "skills").exists()

    asyncio.run(run())


def test_health_unavailable_skill_condition_codes(tmp_path: Path) -> None:
    """Unavailable skills produce skill_unavailable and bundle_missing codes."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    hermes_root = tmp_path / "hermes"
    _make_profile_dirs(hermes_root)

    view = build_role_health_view(
        catalog,
        "theorist",
        hermes_root,
        bundle_root=None,  # skill bundle unavailable
        effective_profiles={"theorist": "theorist"},
    )
    assert view.overall_status == "unavailable"
    assert "skill_unavailable" in view.conditions
    assert "bundle_missing" in view.conditions
    assert "profile_missing" not in view.conditions


def test_health_unavailable_skill_without_profile_has_no_bundle_code(
    tmp_path: Path,
) -> None:
    """When the profile itself is missing, unavailable skills imply no bundle code."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    hermes_root = tmp_path / "hermes"
    hermes_root.mkdir(parents=True)  # Hermes root exists, but no profiles

    view = build_role_health_view(
        catalog,
        "theorist",
        hermes_root,
        bundle_root=None,
        effective_profiles={"theorist": "theorist"},
    )
    assert "profile_missing" in view.conditions
    assert "skill_unavailable" in view.conditions
    assert "bundle_missing" not in view.conditions


def test_configuration_health_unavailable_skills_conditions(tmp_path: Path) -> None:
    """Aggregate health carries the new codes when the bundle is missing."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    hermes_root = tmp_path / "hermes"
    _make_profile_dirs(hermes_root)

    effective = {role: role for role in PROFILE_ROLES}
    effective["outside_reviewer"] = "paper_reviewer"
    view = build_configuration_health_view(
        catalog,
        hermes_root,
        bundle_root=None,
        effective_profiles=effective,
    )
    assert view.overall_status == "unavailable"
    assert "skill_unavailable" in view.conditions
    assert "bundle_missing" in view.conditions


# --------------------------------------------------------------------------- #
# Safety net: backup-before-overwrite, skip_assets ('keep custom')
# --------------------------------------------------------------------------- #


def test_force_overwrite_creates_recovery_backup(tmp_path: Path) -> None:
    """Force-overwrite of a customized SOUL leaves an .mf-custom-* copy."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    provision_role_definition(resource, profile_home, bundle)
    custom_text = "My very own theorist soul that I spent hours on.\n"
    (profile_home / "SOUL.md").write_text(custom_text, encoding="utf-8")

    result = provision_role_definition(
        resource, profile_home, bundle, force_overwrite_assets=True
    )

    backups = list(profile_home.glob("SOUL.md.mf-custom-*"))
    assert len(backups) == 1, "force-overwrite must create one recovery copy"
    assert backups[0].read_text(encoding="utf-8") == custom_text
    assert (profile_home / "SOUL.md").read_text(encoding="utf-8") == (
        resource.soul_text
    )
    assert len(result.backups_created) == 1
    assert result.backups_created[0].startswith("SOUL.md.mf-custom-")


def test_skip_assets_keeps_customized_file_untouched(tmp_path: Path) -> None:
    """skip_assets leaves the customized file byte-identical, provisions the rest."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    provision_role_definition(resource, profile_home, bundle)
    custom_text = "Keep my custom soul exactly as it is.\n"
    (profile_home / "SOUL.md").write_text(custom_text, encoding="utf-8")

    result = provision_role_definition(
        resource, profile_home, bundle, skip_assets=("SOUL.md",)
    )

    assert (profile_home / "SOUL.md").read_text(encoding="utf-8") == custom_text
    assert result.kept_custom == ("SOUL.md",)
    assert "SOUL.md" not in result.assets_written
    # No conflict was raised and the other assets are present and matching.
    config_on_disk = profile_home / resource.base_configuration.file_name
    assert config_on_disk.read_text(encoding="utf-8") == (
        resource.base_configuration.content
    )


def test_skip_assets_without_conflict_still_reports_kept(tmp_path: Path) -> None:
    """Skipping a present-but-matching file still records it as kept."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    provision_role_definition(resource, profile_home, bundle)

    result = provision_role_definition(
        resource, profile_home, bundle, skip_assets=("SOUL.md",)
    )
    assert result.kept_custom == ("SOUL.md",)


def test_skip_assets_unknown_name_rejected(tmp_path: Path) -> None:
    """An unknown asset name in skip_assets is a provisioning error."""
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")

    with pytest.raises(ProvisioningError, match="skip_assets"):
        provision_role_definition(
            resource,
            profiles["theorist"],
            bundle,
            skip_assets=("NOT_A_FILE.md",),
        )


# --------------------------------------------------------------------------- #
# SK-8: provision installs the curated union and prunes unmanaged skills
# --------------------------------------------------------------------------- #


def test_provision_installs_bundled_custom_skills(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    result = provision_role_definition(resource, profile_home, bundle)

    installed_ids = {item.skill_id for item in result.skills_installed}
    assert installed_ids == {
        "stat-paper-writing",
        "stat-method-design",
        "mf-proof-dependency",
    }
    assert (profile_home / "skills" / "mf-proof-dependency" / "SKILL.md").is_file()


def test_provision_prunes_unmanaged_skills_and_reports_them(
    tmp_path: Path,
) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("theorist")
    profile_home = profiles["theorist"]

    # Simulate the default Hermes bundle copied at profile creation, plus
    # a stray file, plus dot-prefixed installer metadata.
    skills_dir = profile_home / "skills"
    for stray in ("arxiv", "comfyui", "youtube-content"):
        (skills_dir / stray).mkdir(parents=True)
        (skills_dir / stray / "SKILL.md").write_text("stray", encoding="utf-8")
    (skills_dir / "stray-note.txt").write_text("stray", encoding="utf-8")
    (skills_dir / ".bundled_manifest").write_text("meta", encoding="utf-8")
    (skills_dir / ".hub").mkdir(exist_ok=True)

    result = provision_role_definition(resource, profile_home, bundle)

    remaining = {p.name for p in skills_dir.iterdir()}
    assert remaining == {
        "stat-paper-writing",
        "stat-method-design",
        "mf-proof-dependency",
        ".bundled_manifest",
        ".hub",
    }
    assert set(result.skills_pruned) == {
        "arxiv",
        "comfyui",
        "youtube-content",
        "stray-note.txt",
    }


def test_second_provision_prunes_nothing_new(tmp_path: Path) -> None:
    catalog = RoleResourceCatalog.load(RESOURCE_ROOT)
    bundle = ROOT / "resources" / "skills"
    hermes_root = tmp_path / "hermes"
    profiles = _make_profile_dirs(hermes_root)
    resource = catalog.role("data_analyst")
    profile_home = profiles["data_analyst"]

    (profile_home / "skills" / "old-skill").mkdir(parents=True)
    first = provision_role_definition(resource, profile_home, bundle)
    second = provision_role_definition(resource, profile_home, bundle)

    assert first.skills_pruned == ("old-skill",)
    assert second.skills_pruned == ()
    assert second.skills_installed == ()
