"""Per-invocation runtime profile provisioning (H0.3).

The canonical project profile is never directly writable by a diagnostic
invocation.  Instead, a per-invocation runtime profile is created from a
snapshot of the canonical profile, Hermes writes to it, and on validated
success the changes are atomically promoted back.  On failure, cancel,
or timeout, the snapshot is quarantined for inspection.

This implements the copy-on-write pattern required by H0.3:

* ``snapshot_canonical_profile()`` — atomic copy of the canonical profile
* ``promote_snapshot()`` — atomically promote validated changes back
* ``quarantine_snapshot()`` — move failed snapshots to quarantine
* Memory policy realization at snapshot time (ephemeral, read_only, persistent)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from ..profiles.project_profiles import (
    CREDENTIAL_FILES,
    IDENTITY_FILES,
    MemoryPolicy,
    ProfileProvisioningError,
)

# --------------------------------------------------------------------------- #
# Runtime snapshot lifecycle                                                   #
# --------------------------------------------------------------------------- #


class SnapshotState(StrEnum):
    """Lifecycle of a per-invocation runtime profile snapshot."""

    CREATED = "created"
    PROMOTED = "promoted"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"


class SnapshotError(RuntimeError):
    """Raised when a snapshot operation fails."""


# --------------------------------------------------------------------------- #
# Snapshot record                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Record of a per-invocation runtime profile snapshot.

    The snapshot directory is the writable profile that Hermes sees
    during execution.  On success, ``promote()`` merges changes back
    into the canonical profile.  On failure, ``quarantine()`` moves
    it aside.
    """

    snapshot_id: str
    canonical_profile_dir: Path
    snapshot_dir: Path
    quarantine_dir: Path
    memory_policy: MemoryPolicy
    state: SnapshotState
    created_at: str
    memory_digest_before: str
    config_digest_before: str

    @property
    def runtime_profile_dir(self) -> Path:
        """The writable directory Hermes should be pointed at."""
        return self.snapshot_dir


# --------------------------------------------------------------------------- #
# Snapshot manager                                                             #
# --------------------------------------------------------------------------- #


#: Directories that contain per-invocation mutable state — promoted on success.
MUTABLE_DIRS: tuple[str, ...] = ("sessions", "memories", "checkpoints", "cache")

#: Files that are mutable per-invocation — promoted on success.
MUTABLE_FILES: tuple[str, ...] = ("state.db",)

#: Directories that are per-invocation only — never promoted.
EPHEMERAL_DIRS: tuple[str, ...] = ("logs", "workspace", "home")

#: Maximum quarantine directory entries before automatic cleanup.
MAX_QUARANTINE_ENTRIES = 20


class RuntimeProfileManager:
    """Manages per-invocation runtime profile snapshots.

    Snapshot directory layout::

        <hermes_root>/runtime-snapshots/
            <snapshot_id>/
                SOUL.md        # identity (read-only)
                config.yaml    # identity (read-only)
                state.db       # mutable
                memories/      # mutable (if persistent/read_only policy)
                sessions/      # mutable
                ...

    Quarantine directory layout::

        <hermes_root>/quarantine/
            <snapshot_id>/
                ...            # full snapshot at time of failure
                _quarantine_metadata.json
    """

    def __init__(self, hermes_root: Path) -> None:
        self._hermes_root = hermes_root.resolve()
        self._snapshots_root = self._hermes_root / "runtime-snapshots"
        self._quarantine_root = self._hermes_root / "quarantine"
        self._snapshots_root.mkdir(parents=True, exist_ok=True)
        self._quarantine_root.mkdir(parents=True, exist_ok=True)
        # Track snapshot state transitions in memory (frozen dataclass can't mutate).
        self._snapshot_states: dict[str, SnapshotState] = {}

    @property
    def hermes_root(self) -> Path:
        return self._hermes_root

    @property
    def snapshots_root(self) -> Path:
        return self._snapshots_root

    @property
    def quarantine_root(self) -> Path:
        return self._quarantine_root

    # ------------------------------------------------------------------ #
    # Create snapshot                                                    #
    # ------------------------------------------------------------------ #

    def snapshot_canonical_profile(
        self,
        *,
        canonical_profile_dir: Path,
        invocation_id: str,
        memory_policy: MemoryPolicy = MemoryPolicy.PERSISTENT,
    ) -> RuntimeSnapshot:
        """Create a per-invocation writable copy of the canonical profile.

        The canonical profile is read-locked (caller holds the profile mutex).
        The snapshot is an independent directory that Hermes writes to.

        Memory policy realization:
        - ``persistent``: memories/ and state.db are copied so changes persist.
        - ``read_only``: memories/ copied read-only (enforced at mount time by
          the executor, not here — but the snapshot includes the data).
        - ``ephemeral``: memories/ and sessions/ start empty.  state.db is
          a fresh copy of the schema only (no data rows).
        """
        if not canonical_profile_dir.is_dir():
            raise SnapshotError(
                f"Canonical profile not found: {canonical_profile_dir}"
            )

        snapshot_id = invocation_id
        snapshot_dir = self._snapshots_root / snapshot_id

        if snapshot_dir.exists():
            raise SnapshotError(
                f"Snapshot already exists: {snapshot_dir}"
            )

        snapshot_dir.mkdir(parents=True, exist_ok=False)

        # Copy identity files (always present, read-only at runtime).
        for item in IDENTITY_FILES:
            src = canonical_profile_dir / item
            if src.exists():
                if src.is_dir():
                    shutil.copytree(src, snapshot_dir / item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, snapshot_dir / item)

        # Copy skills directory if present.
        skills_src = canonical_profile_dir / "skills"
        if skills_src.is_dir():
            shutil.copytree(skills_src, snapshot_dir / "skills", dirs_exist_ok=True)

        # Realize memory policy.
        if memory_policy is MemoryPolicy.EPHEMERAL:
            self._realize_ephemeral(canonical_profile_dir, snapshot_dir)
        elif memory_policy is MemoryPolicy.READ_ONLY:
            self._realize_read_only(canonical_profile_dir, snapshot_dir)
        else:
            self._realize_persistent(canonical_profile_dir, snapshot_dir)

        # Ensure ephemeral writable directories exist.
        for dirname in EPHEMERAL_DIRS:
            (snapshot_dir / dirname).mkdir(exist_ok=True)

        # Compute before-digests.
        memory_digest = _digest_directory(snapshot_dir / "memories")
        config_digest = _sha256_file(snapshot_dir / "config.yaml")

        self._snapshot_states[snapshot_id] = SnapshotState.CREATED

        return RuntimeSnapshot(
            snapshot_id=snapshot_id,
            canonical_profile_dir=canonical_profile_dir,
            snapshot_dir=snapshot_dir,
            quarantine_dir=self._quarantine_root / snapshot_id,
            memory_policy=memory_policy,
            state=SnapshotState.CREATED,
            created_at=datetime.now(timezone.utc).isoformat(),
            memory_digest_before=memory_digest,
            config_digest_before=config_digest,
        )

    def _realize_persistent(
        self, canonical: Path, snapshot: Path
    ) -> None:
        """Copy all mutable state (memories, sessions, state.db, etc.)."""
        for dirname in MUTABLE_DIRS:
            src = canonical / dirname
            if src.is_dir():
                shutil.copytree(src, snapshot / dirname, dirs_exist_ok=True)
            else:
                (snapshot / dirname).mkdir(exist_ok=True)

        for filename in MUTABLE_FILES:
            src = canonical / filename
            if src.exists():
                shutil.copy2(src, snapshot / filename)

    def _realize_read_only(
        self, canonical: Path, snapshot: Path
    ) -> None:
        """Copy memories read-only; fresh sessions; copy state.db schema only."""
        # Memories are copied (the executor enforces read-only at mount time).
        memories_src = canonical / "memories"
        if memories_src.is_dir():
            shutil.copytree(memories_src, snapshot / "memories", dirs_exist_ok=True)
        else:
            (snapshot / "memories").mkdir(exist_ok=True)

        # Fresh empty sessions.
        (snapshot / "sessions").mkdir(exist_ok=True)
        (snapshot / "checkpoints").mkdir(exist_ok=True)
        (snapshot / "cache").mkdir(exist_ok=True)

        # Copy state.db schema only (no session data).
        state_db_src = canonical / "state.db"
        if state_db_src.exists():
            self._copy_sqlite_schema_only(state_db_src, snapshot / "state.db")

    def _realize_ephemeral(
        self, canonical: Path, snapshot: Path
    ) -> None:
        """Empty memories and sessions; copy state.db schema only."""
        (snapshot / "memories").mkdir(exist_ok=True)
        (snapshot / "sessions").mkdir(exist_ok=True)
        (snapshot / "checkpoints").mkdir(exist_ok=True)
        (snapshot / "cache").mkdir(exist_ok=True)

        state_db_src = canonical / "state.db"
        if state_db_src.exists():
            self._copy_sqlite_schema_only(state_db_src, snapshot / "state.db")

    @staticmethod
    def _copy_sqlite_schema_only(src: Path, dest: Path) -> None:
        """Copy a SQLite database's schema but not its data rows."""
        src_conn = sqlite3.connect(str(src))
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
            # Delete all data rows from user tables.
            tables = dest_conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE '_litestream%'"
            ).fetchall()
            for (table_name,) in tables:
                dest_conn.execute(f"DELETE FROM [{table_name}]")
            dest_conn.commit()
        except sqlite3.Error:
            # If backup fails, create a fresh empty database.
            pass
        finally:
            src_conn.close()
            dest_conn.close()

    # ------------------------------------------------------------------ #
    # Promote (success path)                                             #
    # ------------------------------------------------------------------ #

    def promote_snapshot(
        self,
        snapshot: RuntimeSnapshot,
        *,
        expected_token: int | None = None,
    ) -> str:
        """Atomically promote validated changes back to the canonical profile.

        This is called only after the diagnostic output has been validated.
        It copies mutable state from the snapshot back to the canonical
        profile using an atomic rename strategy.

        Returns the promotion digest (SHA-256 of the promoted state).

        Raises SnapshotError if the snapshot is not in CREATED state or
        if the promotion fails.
        """
        if snapshot.state is not SnapshotState.CREATED:
            raise SnapshotError(
                f"Cannot promote snapshot in state {snapshot.state.value}"
            )
        current_state = self._snapshot_states.get(
            snapshot.snapshot_id, SnapshotState.CREATED
        )
        if current_state is not SnapshotState.CREATED:
            raise SnapshotError(
                f"Cannot promote snapshot in state {current_state.value}"
            )

        canonical = snapshot.canonical_profile_dir
        runtime = snapshot.snapshot_dir

        # Create a temporary staging directory for atomic swap.
        staging = canonical.parent / f".{canonical.name}.promote-staging"
        if staging.exists():
            shutil.rmtree(staging)

        try:
            # Copy the canonical profile to staging as the base.
            shutil.copytree(canonical, staging)

            # Overwrite mutable items from the runtime snapshot.
            for dirname in MUTABLE_DIRS:
                src = runtime / dirname
                dest = staging / dirname
                if src.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(src, dest)

            for filename in MUTABLE_FILES:
                src = runtime / filename
                if src.exists():
                    shutil.copy2(src, staging / filename)

            # Atomic swap: rename canonical → backup, staging → canonical.
            backup = canonical.parent / f".{canonical.name}.backup"
            if backup.exists():
                shutil.rmtree(backup)
            os.rename(canonical, backup)
            try:
                os.rename(staging, canonical)
            except OSError:
                # Rollback on failure.
                os.rename(backup, canonical)
                raise SnapshotError("Atomic promotion failed during rename.")
            # Clean up backup.
            shutil.rmtree(backup, ignore_errors=True)

            # Compute promotion digest.
            promoted_digest = _digest_directory(canonical / "memories")
            self._snapshot_states[snapshot.snapshot_id] = SnapshotState.PROMOTED
            return promoted_digest

        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, SnapshotError):
                raise
            raise SnapshotError(f"Promotion failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Quarantine (failure path)                                          #
    # ------------------------------------------------------------------ #

    def quarantine_snapshot(
        self,
        snapshot: RuntimeSnapshot,
        *,
        reason: str,
        diagnostic_text: str = "",
    ) -> Path:
        """Move a failed snapshot to quarantine for inspection.

        The canonical profile is untouched — only the runtime snapshot
        is preserved for debugging.

        Returns the quarantine directory path.
        """
        if snapshot.state is not SnapshotState.CREATED:
            raise SnapshotError(
                f"Cannot quarantine snapshot in state {snapshot.state.value}"
            )
        current_state = self._snapshot_states.get(
            snapshot.snapshot_id, SnapshotState.CREATED
        )
        if current_state is not SnapshotState.CREATED:
            raise SnapshotError(
                f"Cannot quarantine snapshot in state {current_state.value}"
            )

        quarantine_dir = snapshot.quarantine_dir
        if quarantine_dir.exists():
            shutil.rmtree(quarantine_dir)

        # Move the snapshot directory to quarantine.
        shutil.move(str(snapshot.snapshot_dir), str(quarantine_dir))

        # Write quarantine metadata.
        metadata = {
            "format": "model-forge.quarantine-metadata",
            "format_version": "1.0.0",
            "snapshot_id": snapshot.snapshot_id,
            "quarantined_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "diagnostic_text": diagnostic_text,
            "memory_policy": snapshot.memory_policy.value,
            "memory_digest_before": snapshot.memory_digest_before,
            "config_digest_before": snapshot.config_digest_before,
            "canonical_profile_dir": str(snapshot.canonical_profile_dir),
        }
        (quarantine_dir / "_quarantine_metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        # Auto-cleanup old quarantine entries.
        self._cleanup_quarantine()

        self._snapshot_states[snapshot.snapshot_id] = SnapshotState.QUARANTINED

        return quarantine_dir

    # ------------------------------------------------------------------ #
    # Cleanup                                                            #
    # ------------------------------------------------------------------ #

    def cleanup_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        """Remove a snapshot directory (after promote/quarantine)."""
        if snapshot.snapshot_dir.exists():
            shutil.rmtree(snapshot.snapshot_dir, ignore_errors=True)

    def cleanup_stale_snapshots(self, max_age_hours: int = 24) -> list[str]:
        """Remove snapshot directories older than max_age_hours.

        Returns the cleaned-up snapshot IDs.
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        cleaned: list[str] = []
        if not self._snapshots_root.is_dir():
            return cleaned

        for entry in sorted(self._snapshots_root.iterdir()):
            if not entry.is_dir():
                continue
            stat = entry.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if now - mtime > timedelta(hours=max_age_hours):
                shutil.rmtree(entry, ignore_errors=True)
                cleaned.append(entry.name)
        return cleaned

    def _cleanup_quarantine(self) -> None:
        """Keep quarantine directory under MAX_QUARANTINE_ENTRIES."""
        if not self._quarantine_root.is_dir():
            return
        entries = sorted(
            self._quarantine_root.iterdir(),
            key=lambda p: p.stat().st_mtime if p.is_dir() else 0,
            reverse=True,
        )
        dirs = [e for e in entries if e.is_dir()]
        if len(dirs) <= MAX_QUARANTINE_ENTRIES:
            return
        for entry in dirs[MAX_QUARANTINE_ENTRIES:]:
            shutil.rmtree(entry, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return "0" * 64
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_directory(directory: Path) -> str:
    """Compute a SHA-256 digest of a directory's file contents.

    Walks the directory tree, concatenates file contents sorted by path,
    and hashes the result.  Empty or missing directories return the
    zero hash.
    """
    if not directory.is_dir():
        return "0" * 64
    hasher = hashlib.sha256()
    for filepath in sorted(directory.rglob("*")):
        if filepath.is_file():
            relative = filepath.relative_to(directory)
            hasher.update(str(relative).encode("utf-8"))
            hasher.update(filepath.read_bytes())
    return hasher.hexdigest()


__all__ = [
    "MAX_QUARANTINE_ENTRIES",
    "MUTABLE_DIRS",
    "MUTABLE_FILES",
    "EPHEMERAL_DIRS",
    "RuntimeProfileManager",
    "RuntimeSnapshot",
    "SnapshotError",
    "SnapshotState",
]
