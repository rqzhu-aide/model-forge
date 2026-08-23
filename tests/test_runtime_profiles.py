"""Tests for H0.3: per-invocation runtime profile provisioning.

Tests the copy-on-write pattern:
- snapshot creation from canonical profile
- memory policy realization (persistent, read_only, ephemeral)
- atomic promotion on success
- quarantine on failure
- cleanup
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from model_forge.diagnostics.runtime_profiles import (
    MAX_QUARANTINE_ENTRIES,
    RuntimeProfileManager,
    SnapshotError,
    SnapshotState,
)
from model_forge.profiles.project_profiles import MemoryPolicy


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def hermes_root(tmp_path: Path) -> Path:
    root = tmp_path / "hermes"
    root.mkdir()
    return root


@pytest.fixture
def canonical_profile(hermes_root: Path) -> Path:
    """Create a canonical profile with identity, memories, and state.db."""
    profiles_root = hermes_root / "profiles"
    profile_dir = profiles_root / "proj-001-theorist"
    profile_dir.mkdir(parents=True)

    # Identity files.
    (profile_dir / "SOUL.md").write_text("# Theorist soul\n")
    (profile_dir / "config.yaml").write_text("model:\n  default: glm-5.2\n")

    # Memories with content.
    memories = profile_dir / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("# Memory\nSome prior knowledge.\n")
    (memories / "USER.md").write_text("# User\nResearcher.\n")

    # Sessions.
    sessions = profile_dir / "sessions"
    sessions.mkdir()
    (sessions / "session-001.json").write_text("{}")
    (sessions / "session-002.json").write_text("{}")

    # state.db with schema and data.
    state_db = profile_dir / "state.db"
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, data TEXT)")
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO sessions VALUES ('s1', 'data1')")
    conn.execute("INSERT INTO config VALUES ('model', 'glm-5.2')")
    conn.commit()
    conn.close()

    # Skills.
    skills = profile_dir / "skills"
    skills.mkdir()
    (skills / "research.md").write_text("# Research skill\n")

    # Scrubbed credentials (should not exist).
    return profile_dir


@pytest.fixture
def rpm(hermes_root: Path) -> RuntimeProfileManager:
    return RuntimeProfileManager(hermes_root)


# --------------------------------------------------------------------------- #
# Snapshot creation                                                            #
# --------------------------------------------------------------------------- #


class TestSnapshotCreation:
    def test_snapshot_creates_independent_directory(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-test-001",
            memory_policy=MemoryPolicy.PERSISTENT,
        )

        assert snap.state is SnapshotState.CREATED
        assert snap.snapshot_dir.is_dir()
        assert snap.snapshot_dir != canonical_profile
        assert snap.snapshot_id == "inv-test-001"

    def test_snapshot_copies_identity_files(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-001",
        )
        assert (snap.snapshot_dir / "SOUL.md").read_text() == "# Theorist soul\n"
        assert (snap.snapshot_dir / "config.yaml").exists()

    def test_snapshot_copies_skills(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-001",
        )
        assert (snap.snapshot_dir / "skills" / "research.md").exists()

    def test_snapshot_creates_ephemeral_dirs(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-001",
        )
        for d in ("logs", "workspace", "home"):
            assert (snap.snapshot_dir / d).is_dir()

    def test_duplicate_snapshot_id_rejected(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-dup",
        )
        with pytest.raises(SnapshotError, match="already exists"):
            rpm.snapshot_canonical_profile(
                canonical_profile_dir=canonical_profile,
                invocation_id="inv-dup",
            )

    def test_missing_canonical_raises(
        self, rpm: RuntimeProfileManager, tmp_path: Path
    ) -> None:
        with pytest.raises(SnapshotError, match="not found"):
            rpm.snapshot_canonical_profile(
                canonical_profile_dir=tmp_path / "nonexistent",
                invocation_id="inv-x",
            )


# --------------------------------------------------------------------------- #
# Memory policy realization                                                    #
# --------------------------------------------------------------------------- #


class TestMemoryPolicyRealization:
    def test_persistent_copies_memories_and_state(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-pers",
            memory_policy=MemoryPolicy.PERSISTENT,
        )
        # Memories should be present.
        assert (snap.snapshot_dir / "memories" / "MEMORY.md").read_text() == (
            "# Memory\nSome prior knowledge.\n"
        )
        assert (snap.snapshot_dir / "memories" / "USER.md").exists()

        # state.db should contain data.
        conn = sqlite3.connect(str(snap.snapshot_dir / "state.db"))
        rows = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(rows) == 1
        conn.close()

        # Sessions should be copied.
        sessions = list((snap.snapshot_dir / "sessions").iterdir())
        assert len(sessions) == 2

    def test_read_only_copies_memories_clears_sessions(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-ro",
            memory_policy=MemoryPolicy.READ_ONLY,
        )
        # Memories should be present (read at execution time).
        assert (snap.snapshot_dir / "memories" / "MEMORY.md").exists()

        # Sessions should be empty.
        sessions = list((snap.snapshot_dir / "sessions").iterdir())
        assert len(sessions) == 0

    def test_ephemeral_starts_empty(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-eph",
            memory_policy=MemoryPolicy.EPHEMERAL,
        )
        # Memories should be empty.
        assert not (snap.snapshot_dir / "memories" / "MEMORY.md").exists()
        mem_files = list((snap.snapshot_dir / "memories").iterdir())
        assert len(mem_files) == 0

        # Sessions should be empty.
        sessions = list((snap.snapshot_dir / "sessions").iterdir())
        assert len(sessions) == 0

        # state.db should have schema but no data.
        conn = sqlite3.connect(str(snap.snapshot_dir / "state.db"))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row[0] for row in tables}
        assert "sessions" in table_names or "config" in table_names
        for tname in table_names:
            if tname.startswith("sqlite_"):
                continue
            rows = conn.execute(f"SELECT * FROM [{tname}]").fetchall()
            assert len(rows) == 0, f"Table {tname} should be empty"
        conn.close()


# --------------------------------------------------------------------------- #
# Atomic promotion                                                             #
# --------------------------------------------------------------------------- #


class TestPromotion:
    def test_promote_writes_back_to_canonical(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-promote",
        )

        # Simulate Hermes writing to the snapshot.
        (snap.snapshot_dir / "memories" / "MEMORY.md").write_text(
            "# Updated memory\nNew knowledge discovered.\n"
        )
        (snap.snapshot_dir / "sessions" / "session-003.json").write_text("{}")

        digest = rpm.promote_snapshot(snap)

        # Canonical profile should now have the updated content.
        assert (
            canonical_profile / "memories" / "MEMORY.md"
        ).read_text() == "# Updated memory\nNew knowledge discovered.\n"
        assert (canonical_profile / "sessions" / "session-003.json").exists()
        assert len(digest) == 64  # SHA-256 hex

    def test_promote_preserves_identity_files(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-keep-id",
        )
        original_soul = (canonical_profile / "SOUL.md").read_text()
        original_config = (canonical_profile / "config.yaml").read_text()

        rpm.promote_snapshot(snap)

        # Identity files should be unchanged by promotion.
        assert (canonical_profile / "SOUL.md").read_text() == original_soul
        assert (canonical_profile / "config.yaml").read_text() == original_config

    def test_promote_creates_ephemeral_writable_dirs(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-dirs",
        )
        rpm.promote_snapshot(snap)
        # The canonical profile should not gain ephemeral dirs.
        assert not (canonical_profile / "logs").exists()

    def test_double_promote_rejected(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-double",
        )
        rpm.promote_snapshot(snap)
        with pytest.raises(SnapshotError, match="Cannot promote"):
            rpm.promote_snapshot(snap)


# --------------------------------------------------------------------------- #
# Quarantine                                                                   #
# --------------------------------------------------------------------------- #


class TestQuarantine:
    def test_quarantine_preserves_snapshot(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-quarantine",
        )
        # Simulate a failure.
        (snap.snapshot_dir / "memories" / "MEMORY.md").write_text("corrupt")

        q_dir = rpm.quarantine_snapshot(
            snap, reason="exit_code_nonzero", diagnostic_text="Process crashed"
        )

        assert q_dir.is_dir()
        assert (q_dir / "SOUL.md").exists()
        assert (q_dir / "_quarantine_metadata.json").exists()
        # Snapshot dir should be moved (no longer in snapshots root).
        assert not snap.snapshot_dir.exists()

    def test_quarantine_metadata_recorded(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-meta",
        )
        q_dir = rpm.quarantine_snapshot(
            snap, reason="validation_failed", diagnostic_text="Missing output"
        )
        meta = json.loads(
            (q_dir / "_quarantine_metadata.json").read_text()
        )
        assert meta["reason"] == "validation_failed"
        assert meta["diagnostic_text"] == "Missing output"
        assert meta["snapshot_id"] == "inv-meta"
        assert "quarantined_at" in meta

    def test_quarantine_does_not_touch_canonical(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        """The canonical profile is untouched when a snapshot is quarantined."""
        original_memory = (
            canonical_profile / "memories" / "MEMORY.md"
        ).read_text()

        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-notouch",
        )
        (snap.snapshot_dir / "memories" / "MEMORY.md").write_text("corrupt")
        rpm.quarantine_snapshot(snap, reason="failed")

        assert (
            canonical_profile / "memories" / "MEMORY.md"
        ).read_text() == original_memory

    def test_quarantine_auto_cleanup_old_entries(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        """Quarantine directory stays under MAX_QUARANTINE_ENTRIES."""
        # Create more snapshots than the limit.
        for i in range(MAX_QUARANTINE_ENTRIES + 5):
            snap = rpm.snapshot_canonical_profile(
                canonical_profile_dir=canonical_profile,
                invocation_id=f"inv-q-{i}",
            )
            rpm.quarantine_snapshot(snap, reason="test")

        q_entries = [
            e for e in rpm.quarantine_root.iterdir() if e.is_dir()
        ]
        assert len(q_entries) <= MAX_QUARANTINE_ENTRIES


# --------------------------------------------------------------------------- #
# Cleanup                                                                      #
# --------------------------------------------------------------------------- #


class TestCleanup:
    def test_cleanup_snapshot_removes_dir(
        self, rpm: RuntimeProfileManager, canonical_profile: Path
    ) -> None:
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-cleanup",
        )
        assert snap.snapshot_dir.exists()
        rpm.cleanup_snapshot(snap)
        assert not snap.snapshot_dir.exists()

    def test_cleanup_stale_snapshots(
        self, rpm: RuntimeProfileManager, canonical_profile: Path, tmp_path: Path
    ) -> None:
        import os
        import time

        # Create a snapshot and make it old.
        snap = rpm.snapshot_canonical_profile(
            canonical_profile_dir=canonical_profile,
            invocation_id="inv-stale",
        )
        old_time = time.time() - (48 * 3600)  # 48 hours ago
        os.utime(snap.snapshot_dir, (old_time, old_time))

        cleaned = rpm.cleanup_stale_snapshots(max_age_hours=24)
        assert "inv-stale" in cleaned
        assert not snap.snapshot_dir.exists()
