"""Per-project Hermes profile management.

Each Method Hub project gets its own set of Hermes profiles with persistent
memory and sessions.  Memory accumulates across runs within the same project
so a role remembers what it concluded in prior phases.

This module creates, configures, and maintains project-scoped profiles.
It does NOT execute anything — it only provisions the profile directory.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from ..configuration.profiles import resolve_hermes_root, validate_profile_name

# --------------------------------------------------------------------------- #
# Memory policy (C4)                                                           #
# --------------------------------------------------------------------------- #


class MemoryPolicy(StrEnum):
    """How a role profile's memory and sessions are handled across runs."""

    PERSISTENT = "persistent"
    """memories/ + sessions/ accumulate across runs within the project."""

    READ_ONLY = "read_only"
    """memories/ mounted read-only; agent may read but not write."""

    EPHEMERAL = "ephemeral"
    """Fresh empty memories/ + sessions/ per invocation; discarded after."""

    @classmethod
    def default_for_role(cls, role: str) -> "MemoryPolicy":
        """Return the default memory policy for a research role."""
        if role == "outside_reviewer":
            return cls.EPHEMERAL
        return cls.PERSISTENT


#: Files that must be scrubbed from a cloned profile (C7).
CREDENTIAL_FILES: tuple[str, ...] = (".env", "auth.json", "auth.lock")

#: Files that define role identity — baked at creation, read-only in container.
IDENTITY_FILES: tuple[str, ...] = ("SOUL.md", "config.yaml")


# --------------------------------------------------------------------------- #
# Data structures                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RoleProfileSpec:
    """Specification for one project role profile."""

    role: str
    base_profile: str
    soul_text: str
    model: str = ""
    provider: str = ""
    skills: tuple[str, ...] = ()
    memory_policy: MemoryPolicy = MemoryPolicy.PERSISTENT
    extra_config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoleProfileRecord:
    """Record of a provisioned project role profile."""

    role: str
    profile_name: str
    home: Path
    memory_policy: MemoryPolicy
    soul_sha256: str
    config_sha256: str


@dataclass(frozen=True, slots=True)
class MemoryStateDigest:
    """Digest of a profile's memory state at a point in time (C3)."""

    memory_md5: str | None
    user_md5: str | None
    session_count: int
    state_db_size: int


class ProfileProvisioningError(RuntimeError):
    """Raised when project profile provisioning fails."""


# --------------------------------------------------------------------------- #
# Name management                                                              #
# --------------------------------------------------------------------------- #

_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def project_role_profile_name(project_id: str, role: str) -> str:
    """Return the Hermes profile name for a project-role pair.

    Profile names must match ``^[a-z0-9][a-z0-9_-]*$``.  Both the project ID
    and the role must be lowercase alphanumeric with hyphens/underscores.
    """
    normalised_project = project_id.replace("_", "-").lower()
    normalised_role = role.replace("_", "-").lower()
    name = f"{normalised_project}-{normalised_role}"
    if not _PROFILE_NAME_RE.fullmatch(name):
        raise ProfileProvisioningError(
            f"Generated profile name {name!r} does not match required pattern."
        )
    return validate_profile_name(name)


# --------------------------------------------------------------------------- #
# Profile manager                                                              #
# --------------------------------------------------------------------------- #


class ProjectProfileManager:
    """Create and manage per-project Hermes profiles.

    Each project role gets a profile cloned from a base template, with
    credentials scrubbed (C7), a project-specific SOUL.md baked in, and a
    declared memory policy (C4).

    The manager operates directly on the filesystem — it does NOT invoke
    ``hermes profile create``.  This makes it testable without a live Hermes
    installation.
    """

    def __init__(
        self,
        *,
        hermes_root: Path | None = None,
    ) -> None:
        self._hermes_root = (
            hermes_root.resolve()
            if hermes_root is not None
            else resolve_hermes_root()
        )

    @property
    def hermes_root(self) -> Path:
        return self._hermes_root

    @property
    def profiles_root(self) -> Path:
        return self._hermes_root / "profiles"

    # ------------------------------------------------------------------ #
    # Create                                                             #
    # ------------------------------------------------------------------ #

    def create_project_profiles(
        self,
        *,
        project_id: str,
        specs: tuple[RoleProfileSpec, ...],
    ) -> tuple[RoleProfileRecord, ...]:
        """Provision one Hermes profile per role spec for this project.

        - Clones the base profile (config, SOUL, skills).
        - Scrubs credential files (C7).
        - Writes the project-specific SOUL.md.
        - Applies model/provider overrides in config.yaml.
        - Records the memory policy in a sidecar metadata file.
        - Returns one record per role.
        """
        if not specs:
            raise ProfileProvisioningError("At least one role spec is required.")

        records: list[RoleProfileRecord] = []
        for spec in specs:
            record = self._create_one(project_id, spec)
            records.append(record)
        return tuple(records)

    def _create_one(
        self,
        project_id: str,
        spec: RoleProfileSpec,
    ) -> RoleProfileRecord:
        name = project_role_profile_name(project_id, spec.role)
        profile_dir = self.profiles_root / name

        if profile_dir.exists():
            raise ProfileProvisioningError(
                f"Profile {name!r} already exists at {profile_dir}."
            )

        # Clone from the base profile
        source_dir = self.profiles_root / spec.base_profile
        if not source_dir.is_dir():
            raise ProfileProvisioningError(
                f"Base profile {spec.base_profile!r} not found at {source_dir}."
            )

        self._clone_profile(source_dir, profile_dir)
        self._scrub_credentials(profile_dir)
        self._write_soul(profile_dir, spec.soul_text)
        if spec.model or spec.provider:
            self._apply_model_config(profile_dir, spec)
        self._write_policy_metadata(profile_dir, spec.memory_policy)

        soul_sha = _sha256_file(profile_dir / "SOUL.md")
        config_sha = _sha256_file(profile_dir / "config.yaml")
        return RoleProfileRecord(
            role=spec.role,
            profile_name=name,
            home=profile_dir,
            memory_policy=spec.memory_policy,
            soul_sha256=soul_sha,
            config_sha256=config_sha,
        )

    # ------------------------------------------------------------------ #
    # Query                                                              #
    # ------------------------------------------------------------------ #

    def profile_path(self, project_id: str, role: str) -> Path:
        """Return the profile directory for a project role."""
        name = project_role_profile_name(project_id, role)
        return self.profiles_root / name

    def profile_exists(self, project_id: str, role: str) -> bool:
        return self.profile_path(project_id, role).is_dir()

    def memory_state_digests(
        self, project_id: str, role: str
    ) -> MemoryStateDigest:
        """Return digests of the profile's memory state at this moment (C3)."""
        profile_dir = self.profile_path(project_id, role)
        memories_dir = profile_dir / "memories"

        memory_md5: str | None = None
        user_md5: str | None = None
        if memories_dir.is_dir():
            memory_md5 = _md5_file(memories_dir / "MEMORY.md")
            user_md5 = _md5_file(memories_dir / "USER.md")

        sessions_dir = profile_dir / "sessions"
        session_count = 0
        if sessions_dir.is_dir():
            session_count = sum(1 for _ in sessions_dir.iterdir())

        state_db = profile_dir / "state.db"
        state_db_size = state_db.stat().st_size if state_db.exists() else 0

        return MemoryStateDigest(
            memory_md5=memory_md5,
            user_md5=user_md5,
            session_count=session_count,
            state_db_size=state_db_size,
        )

    def read_policy_metadata(self, project_id: str, role: str) -> MemoryPolicy | None:
        """Read the declared memory policy from a profile's sidecar metadata."""
        sidecar = self.profile_path(project_id, role) / ".method-hub-policy.json"
        if not sidecar.exists():
            return None
        import json

        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            return MemoryPolicy(data.get("memory_policy", "persistent"))
        except (ValueError, KeyError):
            return None

    # ------------------------------------------------------------------ #
    # Maintain (C2 — growth bounds)                                      #
    # ------------------------------------------------------------------ #

    #: Default retention budgets (configurable via constructor override).
    DEFAULT_BUDGETS: Mapping[str, int] = {
        "max_sessions": 50,
        "max_checkpoints_mb": 25,
        "max_logs_mb": 25,
        "state_db_warn_mb": 250,
    }

    def maintain_profiles(
        self,
        project_id: str,
        *,
        budgets: Mapping[str, int] | None = None,
    ) -> list[str]:
        """Prune sessions, checkpoints, and logs within budgets (C2).

        Returns a list of human-readable actions taken.  Never touches
        ``memories/`` content.  Must not be called during an active
        invocation (caller enforces the profile mutex — C5).
        """
        effective = {**self.DEFAULT_BUDGETS, **(budgets or {})}
        actions: list[str] = []
        profiles = self._project_profiles(project_id)
        for profile_dir in profiles:
            actions.extend(self._prune_sessions(profile_dir, effective["max_sessions"]))
            actions.extend(
                self._prune_directory_mb(
                    profile_dir / "checkpoints", effective["max_checkpoints_mb"]
                )
            )
            actions.extend(
                self._prune_directory_mb(
                    profile_dir / "logs", effective["max_logs_mb"]
                )
            )
        return actions

    # ------------------------------------------------------------------ #
    # Retire                                                             #
    # ------------------------------------------------------------------ #

    def retire_profiles(self, project_id: str) -> list[str]:
        """Remove all project profiles.  Returns the removed profile names."""
        removed: list[str] = []
        profiles = self._project_profiles(project_id)
        for profile_dir in profiles:
            name = profile_dir.name
            shutil.rmtree(profile_dir, ignore_errors=True)
            removed.append(name)
        return removed

    # ------------------------------------------------------------------ #
    # Internal: clone, scrub, configure                                  #
    # ------------------------------------------------------------------ #

    def _clone_profile(self, source: Path, dest: Path) -> None:
        """Copy a profile directory, excluding runtime-only state."""
        dest.mkdir(parents=True, exist_ok=False)
        # Files/dirs to copy: identity, config, skills, memories
        copy_items = (
            "SOUL.md",
            "config.yaml",
            "skills",
            "memories",
        )
        for item_name in copy_items:
            item = source / item_name
            if item.is_dir():
                shutil.copytree(item, dest / item_name, dirs_exist_ok=True)
            elif item.is_file():
                shutil.copy2(item, dest / item_name)
        # Ensure required writable directories exist (C1)
        for dirname in ("sessions", "logs", "checkpoints", "cache", "home", "workspace"):
            (dest / dirname).mkdir(exist_ok=True)

    def _scrub_credentials(self, profile_dir: Path) -> None:
        """Remove credential files from a cloned profile (C7)."""
        for name in CREDENTIAL_FILES:
            path = profile_dir / name
            if path.exists():
                path.unlink()

    def _write_soul(self, profile_dir: Path, soul_text: str) -> None:
        """Write the project-specific SOUL.md (baked once, not per-run)."""
        if not soul_text.strip():
            raise ProfileProvisioningError("SOUL.md text must not be empty.")
        (profile_dir / "SOUL.md").write_text(soul_text, encoding="utf-8")

    def _apply_model_config(self, profile_dir: Path, spec: RoleProfileSpec) -> None:
        """Apply model/provider overrides to config.yaml."""
        import yaml

        config_path = profile_dir / "config.yaml"
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            config = {}
        if not isinstance(config, dict):
            config = {}

        model_section = config.setdefault("model", {})
        if not isinstance(model_section, dict):
            model_section = {}
            config["model"] = model_section
        if spec.model:
            model_section["default"] = spec.model
        if spec.provider:
            model_section["provider"] = spec.provider

        config_path.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def _write_policy_metadata(
        self, profile_dir: Path, policy: MemoryPolicy
    ) -> None:
        """Write the memory policy sidecar metadata (C4)."""
        import json

        metadata = {
            "format": "method-hub.profile-policy",
            "format_version": "1.0.0",
            "memory_policy": policy.value,
        }
        (profile_dir / ".method-hub-policy.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

    def _project_profiles(self, project_id: str) -> list[Path]:
        """Return all profile directories belonging to a project."""
        normalised = project_id.replace("_", "-").lower()
        prefix = f"{normalised}-"
        result: list[Path] = []
        if not self.profiles_root.is_dir():
            return result
        for child in sorted(self.profiles_root.iterdir()):
            if child.is_dir() and child.name.startswith(prefix):
                result.append(child)
        return result

    def _prune_sessions(self, profile_dir: Path, max_count: int) -> list[str]:
        sessions_dir = profile_dir / "sessions"
        if not sessions_dir.is_dir():
            return []
        files = sorted(
            sessions_dir.iterdir(),
            key=lambda p: p.stat().st_mtime if p.is_file() else 0,
            reverse=True,
        )
        if len(files) <= max_count:
            return []
        pruned = len(files) - max_count
        for f in files[max_count:]:
            if f.is_file():
                f.unlink()
        return [f"{profile_dir.name}: pruned {pruned} old session files"]

    def _prune_directory_mb(self, directory: Path, max_mb: int) -> list[str]:
        if not directory.is_dir():
            return []
        max_bytes = max_mb * 1_048_576
        files = sorted(
            (f for f in directory.iterdir() if f.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        total = sum(f.stat().st_size for f in files)
        if total <= max_bytes:
            return []
        removed = 0
        for f in reversed(files):
            if total <= max_bytes:
                break
            size = f.stat().st_size
            f.unlink()
            total -= size
            removed += 1
        if removed:
            return [f"{directory.name}: removed {removed} files to fit {max_mb} MB"]
        return []


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return "0" * 64
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _md5_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.md5(path.read_bytes()).hexdigest()


__all__ = [
    "CREDENTIAL_FILES",
    "IDENTITY_FILES",
    "MemoryPolicy",
    "MemoryStateDigest",
    "ProfileProvisioningError",
    "ProjectProfileManager",
    "RoleProfileRecord",
    "RoleProfileSpec",
    "project_role_profile_name",
]
