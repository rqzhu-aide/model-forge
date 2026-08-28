"""Atomic role-definition provisioning with customization-safe conflict detection.

The provisioner writes role-definition assets (SOUL, base configuration, and
library guidance) into a Hermes profile directory. It never silently overwrites
a file whose content differs from the expected reference — a customization
conflict is surfaced so the user can make an explicit choice.

Provisioning is atomic: if any step fails, all partial writes are rolled back
and the profile directory is restored to its prior state.

Skill installation delegates to :mod:`configuration.skill_installer`, which
already implements verified, non-overwriting installation of bundled skills.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .profiles import (
    AUTHOR_PROFILE_ROLES,
    PROFILE_ROLES,
    REVIEWER_PROFILE_ROLE,
    ProfileDiscovery,
    discover_profiles,
    resolve_hermes_root,
)
from .resources import (
    BaseConfiguration,
    CustomSkill,
    LibraryGuidance,
    RoleResource,
    RoleResourceCatalog,
)
from .skill_installer import (
    SkillConflictError,
    SkillInstallation,
    SkillInstallationError,
    directory_sha256,
    install_bundled_skill,
)


class ProvisioningError(RuntimeError):
    """Raised when provisioning fails. Partial state is rolled back."""


class CustomizationConflict(ProvisioningError):
    """Raised when a target file differs from the reference and cannot be overwritten."""

    def __init__(
        self,
        role_id: str,
        asset_type: str,
        path: Path,
        expected_sha256: str,
        actual_sha256: str,
    ) -> None:
        self.role_id = role_id
        self.asset_type = asset_type
        self.path = path
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256
        super().__init__(
            f"Customization conflict for {asset_type} of role {role_id!r} at "
            f"{path}: expected sha256 {expected_sha256[:16]}…, found "
            f"{actual_sha256[:16]}…"
        )


@dataclass(frozen=True, slots=True)
class AssetStatus:
    """Status of a single role-definition asset relative to its reference."""

    asset_type: str  # "soul", "base_configuration", "library_guidance", "skill"
    file_name: str
    status: str  # "present", "missing", "customized", "unavailable"
    expected_sha256: str
    actual_sha256: str | None = None
    source: str | None = None
    recommended_version: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RoleProvisionResult:
    """Result of provisioning one role definition."""

    role_id: str
    profile_home: Path
    assets_written: tuple[str, ...]
    skills_installed: tuple[SkillInstallation, ...]
    rolled_back: bool
    backups_created: tuple[str, ...] = ()
    kept_custom: tuple[str, ...] = ()
    skills_pruned: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoleHealthReport:
    """Health assessment for one role definition."""

    role_id: str
    profile_available: bool
    profile_name: str | None
    soul_status: AssetStatus
    configuration_status: AssetStatus
    guidance_status: AssetStatus
    skill_statuses: tuple[AssetStatus, ...]
    overall_status: str  # "healthy", "incomplete", "customized", "unavailable"
    detail: str


class HealthCondition(str, Enum):
    """High-level health conditions surfaced by the configuration service."""

    HERMES_MISSING = "hermes_missing"
    PROFILE_MISSING = "profile_missing"
    SOUL_CUSTOMIZED = "soul_customized"
    SOUL_MISSING = "soul_missing"
    CONFIG_CUSTOMIZED = "config_customized"
    CONFIG_MISSING = "config_missing"
    SKILL_MISMATCH = "skill_mismatch"
    SKILL_MISSING = "skill_missing"
    SKILL_UNAVAILABLE = "skill_unavailable"
    BUNDLE_MISSING = "bundle_missing"
    HEALTHY = "healthy"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes())
    except (OSError, UnicodeDecodeError):
        return None


def _read_profile_file(profile_home: Path, file_name: str) -> tuple[bool, str | None]:
    """Read a text file from the profile directory.

    Returns ``(exists, content)``:

    - ``(False, None)`` — the file is absent.
    - ``(True, None)`` — the file exists but could not be read or decoded as
      UTF-8 (a binary file, or an I/O error).
    - ``(True, str)`` — the decoded file content.

    Callers must treat ``(True, None)`` as "customized/unverifiable", never
    as "missing", so that unreadable files are never silently overwritten.
    """
    path = profile_home / file_name
    try:
        if not path.exists():
            return False, None
    except OSError:
        return True, None
    try:
        data = path.read_bytes()
        return True, data.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return True, None


def _check_asset(
    profile_home: Path | None,
    file_name: str,
    expected_content: str,
    expected_sha256: str,
    asset_type: str,
    source: str | None = None,
    recommended_version: str | None = None,
) -> AssetStatus:
    """Compare a single file on disk against its expected content."""
    if profile_home is None:
        return AssetStatus(
            asset_type=asset_type,
            file_name=file_name,
            status="unavailable",
            expected_sha256=expected_sha256,
            actual_sha256=None,
            source=source,
            recommended_version=recommended_version,
            detail="Profile directory is unavailable.",
        )
    exists, actual = _read_profile_file(profile_home, file_name)
    if not exists:
        return AssetStatus(
            asset_type=asset_type,
            file_name=file_name,
            status="missing",
            expected_sha256=expected_sha256,
            actual_sha256=None,
            source=source,
            recommended_version=recommended_version,
            detail=f"{file_name} is not present in the profile.",
        )
    if actual is None:
        # The file exists but cannot be read or decoded. It cannot be proven
        # to match the reference, so it is customized/unverifiable — never
        # report it as missing, which would invite a silent overwrite.
        return AssetStatus(
            asset_type=asset_type,
            file_name=file_name,
            status="customized",
            expected_sha256=expected_sha256,
            actual_sha256=_sha256_file(profile_home / file_name),
            source=source,
            recommended_version=recommended_version,
            detail=(
                f"{file_name} exists but could not be read or decoded as "
                f"UTF-8; it was not overwritten."
            ),
        )
    actual_sha = _sha256_text(actual)
    if actual_sha == expected_sha256:
        return AssetStatus(
            asset_type=asset_type,
            file_name=file_name,
            status="present",
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha,
            source=source,
            recommended_version=recommended_version,
            detail=f"{file_name} matches the configuration-managed reference.",
        )
    return AssetStatus(
        asset_type=asset_type,
        file_name=file_name,
        status="customized",
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha,
        source=source,
        recommended_version=recommended_version,
        detail=(
            f"{file_name} differs from the reference and was not overwritten."
        ),
    )


def _check_skill_asset(
    profile_home: Path | None,
    bundle_root: Path | None,
    skill_id: str,
    skill_name: str,
    skill_source: str,
    skill_version: str,
) -> AssetStatus:
    """Check the status of a recommended skill in a profile."""
    expected_sha = ""
    if bundle_root is not None:
        source_dir = bundle_root / skill_id
        try:
            if source_dir.is_dir() and not source_dir.is_symlink():
                expected_sha = directory_sha256(source_dir)
        except (OSError, SkillInstallationError):
            expected_sha = ""
    if profile_home is None or bundle_root is None or not expected_sha:
        return AssetStatus(
            asset_type="skill",
            file_name=skill_id,
            status="unavailable",
            expected_sha256=expected_sha or "0" * 64,
            actual_sha256=None,
            source=skill_source,
            recommended_version=skill_version,
            detail=f"Skill {skill_id} ({skill_name}) source is unavailable.",
        )
    dest = profile_home / "skills" / skill_id
    try:
        if not dest.exists():
            return AssetStatus(
                asset_type="skill",
                file_name=skill_id,
                status="missing",
                expected_sha256=expected_sha,
                actual_sha256=None,
                source=skill_source,
                recommended_version=skill_version,
                detail=f"Skill {skill_id} ({skill_name}) is not installed.",
            )
        if not dest.is_dir() or dest.is_symlink():
            return AssetStatus(
                asset_type="skill",
                file_name=skill_id,
                status="customized",
                expected_sha256=expected_sha,
                actual_sha256=None,
                source=skill_source,
                recommended_version=skill_version,
                detail=f"Skill {skill_id} ({skill_name}) is not a real directory.",
            )
        actual_sha = directory_sha256(dest)
    except (OSError, SkillInstallationError):
        return AssetStatus(
            asset_type="skill",
            file_name=skill_id,
            status="unavailable",
            expected_sha256=expected_sha,
            actual_sha256=None,
            source=skill_source,
            recommended_version=skill_version,
            detail=f"Skill {skill_id} ({skill_name}) could not be inspected.",
        )
    if actual_sha == expected_sha:
        return AssetStatus(
            asset_type="skill",
            file_name=skill_id,
            status="present",
            expected_sha256=expected_sha,
            actual_sha256=actual_sha,
            source=skill_source,
            recommended_version=skill_version,
            detail=f"Skill {skill_id} ({skill_name}) is installed and matches.",
        )
    return AssetStatus(
        asset_type="skill",
        file_name=skill_id,
        status="customized",
        expected_sha256=expected_sha,
        actual_sha256=actual_sha,
        source=skill_source,
        recommended_version=skill_version,
        detail=f"Skill {skill_id} ({skill_name}) differs from the pinned bundle.",
    )


def assess_role_health(
    resource: RoleResource,
    profile_home: Path | None,
    bundle_root: Path | None,
) -> RoleHealthReport:
    """Assess the health of one role definition against a profile directory."""

    soul_status = _check_asset(
        profile_home,
        "SOUL.md",
        resource.soul_text,
        resource.soul_sha256,
        "soul",
    )
    config_status = _check_asset(
        profile_home,
        resource.base_configuration.file_name,
        resource.base_configuration.content,
        resource.base_configuration.sha256,
        "base_configuration",
    )
    guidance_status = _check_asset(
        profile_home,
        resource.library_guidance.file_name,
        resource.library_guidance.content,
        resource.library_guidance.sha256,
        "library_guidance",
    )
    skill_statuses: list[AssetStatus] = []
    for skill in resource.recommended_skills:
        skill_statuses.append(
            _check_skill_asset(
                profile_home,
                bundle_root,
                skill.skill_id,
                skill.name,
                skill.source,
                skill.recommended_version,
            )
        )

    statuses = [soul_status, config_status, guidance_status] + skill_statuses
    has_customized = any(s.status == "customized" for s in statuses)
    has_missing = any(s.status == "missing" for s in statuses)
    has_unavailable = any(s.status == "unavailable" for s in statuses)

    if profile_home is None or has_unavailable:
        overall = "unavailable"
    elif has_customized and not has_missing:
        overall = "customized"
    elif has_missing:
        overall = "incomplete"
    else:
        overall = "healthy"

    return RoleHealthReport(
        role_id=resource.role_id,
        profile_available=profile_home is not None,
        profile_name=profile_home.name if profile_home else None,
        soul_status=soul_status,
        configuration_status=config_status,
        guidance_status=guidance_status,
        skill_statuses=tuple(skill_statuses),
        overall_status=overall,
        detail=_health_detail(overall, statuses),
    )


def _health_detail(overall: str, statuses: list[AssetStatus]) -> str:
    if overall == "healthy":
        return "All role-definition assets are present and match the reference."
    if overall == "customized":
        customized = [s for s in statuses if s.status == "customized"]
        names = ", ".join(s.file_name for s in customized)
        return f"Customized assets differ from the reference: {names}."
    if overall == "incomplete":
        missing = [s for s in statuses if s.status == "missing"]
        names = ", ".join(s.file_name for s in missing)
        return f"Missing assets: {names}."
    return "One or more assets or the profile directory is unavailable."


def _backup_ignore(directory: str, names: list[str]) -> list[str]:
    """Skip entries copytree cannot duplicate (sockets, devices, fifos).

    Live profiles can contain runtime artifacts such as ``gateway.sock``;
    they are not profile state and must not block the rollback backup.
    """
    skipped: list[str] = []
    for name in names:
        try:
            mode = (Path(directory) / name).lstat().st_mode
        except OSError:
            continue
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
            skipped.append(name)
    return skipped


def _backup_profile(profile_home: Path) -> Path:
    """Create a temporary backup of the entire profile directory for rollback."""
    backup = profile_home.parent / f".{profile_home.name}.backup-{uuid.uuid4().hex}"
    shutil.copytree(profile_home, backup, ignore=_backup_ignore)
    return backup


def _restore_backup(profile_home: Path, backup: Path) -> None:
    """Restore a profile directory from its backup, replacing the current one.

    The restore is crash-safe: the current profile is first renamed aside
    (one atomic rename), then the backup is moved into place, and only then
    is the aside deleted. A process crash between the rename and the move
    leaves the original profile recoverable under the trash name — it is
    never deleted before the backup is in place.
    """
    trash = profile_home.parent / f".{profile_home.name}.trash-{uuid.uuid4().hex}"
    os.replace(profile_home, trash)
    try:
        os.replace(backup, profile_home)
    except BaseException:
        # The move failed; the original profile still exists under the trash
        # name. Try to put it back so the caller sees a consistent directory.
        try:
            os.replace(trash, profile_home)
        except OSError:
            pass
        raise
    shutil.rmtree(trash)


def _cleanup_backup(backup: Path) -> None:
    try:
        shutil.rmtree(backup)
    except (OSError, FileNotFoundError):
        pass


def _write_file_atomic(target: Path, content: str) -> None:
    """Write a text file using a temporary name + rename for atomicity."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.write-{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(staging, flags, 0o644)
    try:
        payload = content.encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ProvisioningError(f"Write to {target} stopped before completion.")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(staging, target)


def _backup_customized_file(target: Path) -> str | None:
    """Rename a soon-to-be-overwritten customized file to a recovery copy.

    Safety net for force-overwrite: the reference content will replace this
    file, so the user's custom version is kept as
    ``<file_name>.mf-custom-<UTC timestamp>`` beside it.  The backup is
    intentionally untracked and never cleaned up by the provisioner.
    """
    if not target.exists():
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_name = f"{target.name}.mf-custom-{stamp}"
    destination = target.parent / backup_name
    counter = 1
    while destination.exists():
        backup_name = f"{target.name}.mf-custom-{stamp}-{counter}"
        destination = target.parent / backup_name
        counter += 1
    os.replace(target, destination)
    return backup_name


def _provision_asset(
    profile_home: Path,
    file_name: str,
    content: str,
    expected_sha256: str,
    asset_type: str,
    role_id: str,
    *,
    force_overwrite: bool = False,
    skip: bool = False,
    backups: list[str] | None = None,
    kept: list[str] | None = None,
) -> bool:
    """
    Write one asset file if it is missing or already matches.
    Returns True if the file was created or updated, False if already present.

    Raises CustomizationConflict if the file exists with different content
    and force_overwrite is False.  When ``skip`` is True the existing file is
    left completely untouched (the 'keep custom' action) and no conflict is
    raised.  When force-overwriting a customized file, a recovery copy
    ``<name>.mf-custom-<ts>`` is created first and recorded in ``backups``.
    """
    target = profile_home / file_name
    if skip and target.exists():
        if kept is not None:
            kept.append(file_name)
        return False
    exists, existing = _read_profile_file(profile_home, file_name)
    if exists:
        if existing is not None:
            existing_sha = _sha256_text(existing)
        else:
            # The file exists but could not be read/decoded. Hash the raw
            # bytes when possible; either way it cannot be proven to match.
            existing_sha = _sha256_file(target)
        if existing_sha == expected_sha256:
            return False  # already matches
        if not force_overwrite:
            raise CustomizationConflict(
                role_id=role_id,
                asset_type=asset_type,
                path=target,
                expected_sha256=expected_sha256,
                actual_sha256=existing_sha or ("0" * 64),
            )
        if force_overwrite and backups is not None:
            backup_name = _backup_customized_file(target)
            if backup_name is not None:
                backups.append(backup_name)
    _write_file_atomic(target, content)
    written_sha = _sha256_file(target)
    if written_sha != expected_sha256:
        raise ProvisioningError(
            f"Post-write verification failed for {asset_type} of role {role_id!r}."
        )
    return True


def provision_role_definition(
    resource: RoleResource,
    profile_home: Path,
    bundle_root: Path | None,
    *,
    install_skills: bool = True,
    force_overwrite_assets: bool = False,
    force_overwrite_skills: bool = False,
    skip_assets: tuple[str, ...] = (),
    pre_skill_hook: Callable[[str], None] | None = None,
) -> RoleProvisionResult:
    """
    Provision a role definition into a profile directory atomically.

    Writes SOUL.md, base configuration, and library guidance. Optionally
    installs recommended skills. If any step fails, all changes are rolled
    back and the profile is restored to its prior state.

    A ``CustomizationConflict`` is raised when a file exists with different
    content and the corresponding force flag is False. The conflict is NOT
    auto-resolved — it must be surfaced to the user for an explicit choice.
    """

    if not profile_home.is_dir() or profile_home.is_symlink():
        raise ProvisioningError(
            f"Profile directory is not available: {profile_home}"
        )

    if profile_home.name == "default":
        raise ProvisioningError(
            f"Profile name {profile_home.name!r} is reserved: it resolves to "
            f"the Hermes root directory itself. Refusing to provision role "
            f"{resource.role_id!r} into {profile_home}; assign a dedicated "
            f"profile for this role."
        )

    backup = _backup_profile(profile_home)
    assets_written: list[str] = []
    skills_installed: list[SkillInstallation] = []
    rolled_back = False
    backups_created: list[str] = []
    kept_custom: list[str] = []
    skills_pruned: list[str] = []

    # Validate skip entries against the asset file names this role owns.
    known_assets = {
        "SOUL.md",
        resource.base_configuration.file_name,
        resource.library_guidance.file_name,
    }
    unknown_skips = set(skip_assets) - known_assets
    if unknown_skips:
        raise ProvisioningError(
            f"Unknown asset name(s) in skip_assets: "
            f"{sorted(unknown_skips)}. Known assets: {sorted(known_assets)}."
        )

    try:
        # Provision SOUL
        if _provision_asset(
            profile_home,
            "SOUL.md",
            resource.soul_text,
            resource.soul_sha256,
            "soul",
            resource.role_id,
            force_overwrite=force_overwrite_assets,
            skip="SOUL.md" in skip_assets,
            backups=backups_created,
            kept=kept_custom,
        ):
            assets_written.append("SOUL.md")

        # Provision base configuration
        if _provision_asset(
            profile_home,
            resource.base_configuration.file_name,
            resource.base_configuration.content,
            resource.base_configuration.sha256,
            "base_configuration",
            resource.role_id,
            force_overwrite=force_overwrite_assets,
            skip=resource.base_configuration.file_name in skip_assets,
            backups=backups_created,
            kept=kept_custom,
        ):
            assets_written.append(resource.base_configuration.file_name)

        # Provision library guidance
        if _provision_asset(
            profile_home,
            resource.library_guidance.file_name,
            resource.library_guidance.content,
            resource.library_guidance.sha256,
            "library_guidance",
            resource.role_id,
            force_overwrite=force_overwrite_assets,
            skip=resource.library_guidance.file_name in skip_assets,
            backups=backups_created,
            kept=kept_custom,
        ):
            assets_written.append(resource.library_guidance.file_name)

        # Install the curated skill union: recommended skills plus bundled
        # custom skills. The role's profile carries exactly this set.
        if install_skills and bundle_root is not None:
            install_set = [skill.skill_id for skill in resource.recommended_skills]
            install_set += [
                skill.skill_id
                for skill in resource.custom_skills
                if skill.source == "model-forge/bundled"
            ]
            for skill_id in install_set:
                if pre_skill_hook is not None:
                    pre_skill_hook(skill_id)
                try:
                    result = install_bundled_skill(
                        bundle_root=bundle_root,
                        profile_home=profile_home,
                        skill_id=skill_id,
                    )
                    if result.created:
                        skills_installed.append(result)
                except SkillConflictError:
                    if force_overwrite_skills:
                        dest = profile_home / "skills" / skill_id
                        shutil.rmtree(dest)
                        result = install_bundled_skill(
                            bundle_root=bundle_root,
                            profile_home=profile_home,
                            skill_id=skill_id,
                        )
                        if result.created:
                            skills_installed.append(result)
                    else:
                        raise
            # Prune unmanaged skills: a provisioned role profile carries
            # exactly the curated union, so members never load skills that
            # are not theirs (the default Hermes bundle copied at profile
            # creation is the common case). Pruned ids are reported; the
            # profile backup taken above covers rollback on failure.
            skills_dir = profile_home / "skills"
            if skills_dir.is_dir():
                managed = set(install_set)
                for entry in sorted(skills_dir.iterdir()):
                    if entry.name.startswith(".") or entry.name in managed:
                        continue
                    if entry.is_dir() and not entry.is_symlink():
                        shutil.rmtree(entry)
                        skills_pruned.append(entry.name)
                    elif entry.is_file():
                        entry.unlink()
                        skills_pruned.append(entry.name)

    except Exception:
        # Rollback: restore the profile to its pre-provisioning state.
        _restore_backup(profile_home, backup)
        rolled_back = True
        raise
    else:
        _cleanup_backup(backup)

    return RoleProvisionResult(
        role_id=resource.role_id,
        profile_home=profile_home,
        assets_written=tuple(assets_written),
        skills_installed=tuple(skills_installed),
        rolled_back=rolled_back,
        backups_created=tuple(backups_created),
        kept_custom=tuple(kept_custom),
        skills_pruned=tuple(skills_pruned),
    )


def discover_profile_home(
    hermes_root: Path,
    profile_name: str,
) -> Path | None:
    """Return the profile directory if it exists and is a safe directory, else None."""
    discoveries = discover_profiles(hermes_root)
    for item in discoveries:
        if item.name == profile_name and item.is_safe_directory:
            return item.home
    return None


def hermes_available(hermes_root: Path) -> bool:
    """Check whether the Hermes root directory exists."""
    return hermes_root.is_dir()


__all__ = [
    "AssetStatus",
    "CustomizationConflict",
    "HealthCondition",
    "ProvisioningError",
    "RoleHealthReport",
    "RoleProvisionResult",
    "assess_role_health",
    "discover_profile_home",
    "hermes_available",
    "provision_role_definition",
]
