"""Tests for the diagnostic lane: profiles, executor, fencing, and service.

Covers the plan's key requirements:
- C1: profile directory is writable (identity files read-only overlays)
- C2: growth bounds and retention pruning
- C3: memory-state digests recorded per invocation
- C4: per-role memory policy (persistent/read_only/ephemeral)
- C5: per-profile execution mutex
- C7: credential scrubbing after clone
- S5.7: DB-backed fencing tokens
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from method_hub.diagnostics.store import (
    DiagnosticStore,
    FencingError,
    ProfileLockHeld,
    utc_now_iso,
)
from method_hub.diagnostics.service import (
    DiagnosticRequest,
    DiagnosticResult,
    DiagnosticService,
)
from method_hub.executors.oneshot import (
    OneShotExecutor,
    OneShotExecutorSettings,
)
from method_hub.executors.protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)
from method_hub.profiles.project_profiles import (
    CREDENTIAL_FILES,
    MemoryPolicy,
    MemoryStateDigest,
    ProfileProvisioningError,
    ProjectProfileManager,
    RoleProfileSpec,
    project_role_profile_name,
)
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def hermes_root(tmp_path: Path) -> Path:
    """Create a fake Hermes root with a base profile to clone from."""
    root = tmp_path / "hermes-home"
    profiles = root / "profiles"
    base = profiles / "base-role"
    base.mkdir(parents=True)

    # Write identity files.
    (base / "SOUL.md").write_text("# Base role soul\nYou are a test agent.")
    (base / "config.yaml").write_text(
        "model:\n  default: test-model\n  provider: test-provider\n"
    )
    # Credential files that must be scrubbed (C7).
    (base / ".env").write_text("SECRET_API_KEY=sk-leaked123456789012345")
    (base / "auth.json").write_text('{"providers": {"secret": "token"}}')

    # Skills and memories.
    skills = base / "skills"
    skills.mkdir()
    (skills / "test-skill").mkdir()
    (skills / "test-skill" / "SKILL.md").write_text("# Test skill")

    memories = base / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("# Test memory")

    # Writable dirs (C1).
    for dirname in ("sessions", "logs", "checkpoints", "cache"):
        (base / dirname).mkdir()

    return root


@pytest.fixture
def profile_manager(hermes_root: Path) -> ProjectProfileManager:
    return ProjectProfileManager(hermes_root=hermes_root)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(
        tmp_path / "diagnostic.sqlite3",
        migrations=HUB_MIGRATIONS,
    )


@pytest.fixture
def store(database: Database) -> DiagnosticStore:
    database.initialize()
    return DiagnosticStore(database)


@pytest.fixture
def observer() -> ExecutionObserver:
    """A minimal observer for executor tests."""
    obs = AsyncMock(spec=ExecutionObserver)
    obs.external_execution_id = None
    return obs


# --------------------------------------------------------------------------- #
# Profile name and naming                                                      #
# --------------------------------------------------------------------------- #


class TestProfileNaming:
    def test_project_role_profile_name_valid(self) -> None:
        assert project_role_profile_name("proj-004", "theorist") == "proj-004-theorist"

    def test_project_role_profile_name_normalises_case(self) -> None:
        assert project_role_profile_name("Proj-004", "Research_Lead") == "proj-004-research-lead"

    def test_project_role_profile_name_invalid_chars(self) -> None:
        with pytest.raises(ProfileProvisioningError):
            project_role_profile_name("proj 004", "theorist")


# --------------------------------------------------------------------------- #
# C7: Credential scrubbing                                                     #
# --------------------------------------------------------------------------- #


class TestCredentialScrubbing:
    def test_env_scrubbed_after_clone(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """C7: .env must be removed after cloning."""
        record = profile_manager.create_project_profiles(
            project_id="test-proj",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist\nYou are a theorist.",
                ),
            ),
        )
        profile_dir = record[0].home
        assert not (profile_dir / ".env").exists(), ".env must be scrubbed (C7)"

    def test_auth_json_scrubbed_after_clone(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """C7: auth.json must be removed after cloning."""
        record = profile_manager.create_project_profiles(
            project_id="test-proj",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        profile_dir = record[0].home
        assert not (profile_dir / "auth.json").exists()

    def test_no_credential_files_in_created_profile(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """All credential files defined in CREDENTIAL_FILES must be absent."""
        record = profile_manager.create_project_profiles(
            project_id="test-proj",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        profile_dir = record[0].home
        for cred_file in CREDENTIAL_FILES:
            assert not (profile_dir / cred_file).exists(), (
                f"{cred_file} must be absent"
            )


# --------------------------------------------------------------------------- #
# SOUL.md baking                                                               #
# --------------------------------------------------------------------------- #


class TestSoulBaking:
    def test_soul_written_at_creation(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """SOUL.md is baked at creation, not per-run."""
        soul = "# Project Theorist\nYou are the theorist for proj-004."
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text=soul,
                ),
            ),
        )
        assert (record[0].home / "SOUL.md").read_text() == soul

    def test_empty_soul_rejected(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        with pytest.raises(ProfileProvisioningError):
            profile_manager.create_project_profiles(
                project_id="proj-004",
                specs=(
                    RoleProfileSpec(
                        role="theorist",
                        base_profile="base-role",
                        soul_text="   ",
                    ),
                ),
            )

    def test_soul_sha256_recorded(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        import hashlib

        soul = "# Theorist"
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text=soul,
                ),
            ),
        )
        expected = hashlib.sha256(soul.encode()).hexdigest()
        assert record[0].soul_sha256 == expected


# --------------------------------------------------------------------------- #
# C1: Writable profile directory                                               #
# --------------------------------------------------------------------------- #


class TestProfileWritability:
    def test_writable_dirs_created(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """C1: state.db, logs, sessions, checkpoints dirs must exist."""
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        profile_dir = record[0].home
        for dirname in ("sessions", "logs", "checkpoints", "cache"):
            assert (profile_dir / dirname).is_dir(), f"{dirname} must exist"


# --------------------------------------------------------------------------- #
# C4: Memory policy                                                            #
# --------------------------------------------------------------------------- #


class TestMemoryPolicy:
    def test_default_persistent_for_authors(self) -> None:
        assert MemoryPolicy.default_for_role("theorist") is MemoryPolicy.PERSISTENT
        assert MemoryPolicy.default_for_role("research_lead") is MemoryPolicy.PERSISTENT

    def test_default_ephemeral_for_reviewer(self) -> None:
        assert MemoryPolicy.default_for_role("outside_reviewer") is MemoryPolicy.EPHEMERAL

    def test_policy_metadata_written(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """Memory policy is recorded in the sidecar metadata (C4)."""
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="outside_reviewer",
                    base_profile="base-role",
                    soul_text="# Reviewer",
                    memory_policy=MemoryPolicy.EPHEMERAL,
                ),
            ),
        )
        policy = profile_manager.read_policy_metadata("proj-004", "outside_reviewer")
        assert policy is MemoryPolicy.EPHEMERAL

    def test_policy_default_persistent(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        policy = profile_manager.read_policy_metadata("proj-004", "theorist")
        assert policy is MemoryPolicy.PERSISTENT


# --------------------------------------------------------------------------- #
# C3: Memory-state digests                                                     #
# --------------------------------------------------------------------------- #


class TestMemoryStateDigests:
    def test_digests_returned(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """C3: memory_state_digests returns sha256 of MEMORY.md and USER.md."""
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        # Write a memory file.
        memories_dir = record[0].home / "memories"
        (memories_dir / "MEMORY.md").write_text("# Updated memory")
        (memories_dir / "USER.md").write_text("# User profile")

        digests = profile_manager.memory_state_digests("proj-004", "theorist")
        assert digests.memory_md5 is not None
        assert digests.user_md5 is not None
        assert digests.session_count >= 0
        assert digests.state_db_size == 0  # No state.db yet.


# --------------------------------------------------------------------------- #
# C2: Growth bounds / retention                                                #
# --------------------------------------------------------------------------- #


class TestRetention:
    def test_prune_old_sessions(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """C2: maintain_profiles prunes sessions exceeding the budget."""
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        sessions_dir = record[0].home / "sessions"
        # Create 10 session files.
        for i in range(10):
            (sessions_dir / f"session_{i:03d}.json").write_text("{}")

        actions = profile_manager.maintain_profiles(
            "proj-004", budgets={"max_sessions": 3}
        )
        remaining = list(sessions_dir.iterdir())
        assert len(remaining) == 3
        assert len(actions) > 0

    def test_maintain_never_touches_memories(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        """C2: maintenance never deletes memory files."""
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )
        memories_dir = record[0].home / "memories"
        memory_file = memories_dir / "MEMORY.md"
        memory_file.write_text("# Important research context")
        original = memory_file.read_text()

        profile_manager.maintain_profiles("proj-004")
        assert memory_file.read_text() == original


# --------------------------------------------------------------------------- #
# Model/provider config                                                        #
# --------------------------------------------------------------------------- #


class TestModelConfig:
    def test_model_override_applied(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        record = profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                    model="deepseek-v4-pro",
                    provider="deepseek",
                ),
            ),
        )
        import yaml

        config = yaml.safe_load(
            (record[0].home / "config.yaml").read_text()
        )
        assert config["model"]["default"] == "deepseek-v4-pro"
        assert config["model"]["provider"] == "deepseek"


# --------------------------------------------------------------------------- #
# Retire                                                                       #
# --------------------------------------------------------------------------- #


class TestRetire:
    def test_retire_removes_all_profiles(
        self, profile_manager: ProjectProfileManager
    ) -> None:
        profile_manager.create_project_profiles(
            project_id="proj-004",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
                RoleProfileSpec(
                    role="research_lead",
                    base_profile="base-role",
                    soul_text="# Lead",
                ),
            ),
        )
        removed = profile_manager.retire_profiles("proj-004")
        assert len(removed) == 2
        assert not profile_manager.profile_exists("proj-004", "theorist")


# --------------------------------------------------------------------------- #
# S5.7: Fencing tokens                                                         #
# --------------------------------------------------------------------------- #


class TestFencingTokens:
    def test_issue_and_validate(
        self, store: DiagnosticStore
    ) -> None:
        """S5.7: tokens are issued and validated atomically."""
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        token = store.issue_fencing_token("inv-001")
        assert token.token == 1
        store.validate_fencing_token("inv-001", 1)  # No exception.

    def test_stale_token_rejected(
        self, store: DiagnosticStore
    ) -> None:
        """S5.7: a stale token raises FencingError."""
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.issue_fencing_token("inv-001")  # Token 1
        store.issue_fencing_token("inv-001")  # Token 2

        # Token 1 is now stale.
        with pytest.raises(FencingError):
            store.validate_fencing_token("inv-001", 1)

        # Token 2 is current.
        store.validate_fencing_token("inv-001", 2)

    def test_token_monotonic(
        self, store: DiagnosticStore
    ) -> None:
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        t1 = store.issue_fencing_token("inv-001")
        t2 = store.issue_fencing_token("inv-001")
        t3 = store.issue_fencing_token("inv-001")
        assert t1.token < t2.token < t3.token


# --------------------------------------------------------------------------- #
# C5: Profile mutex                                                            #
# --------------------------------------------------------------------------- #


class TestProfileMutex:
    def test_acquire_and_release(
        self, store: DiagnosticStore
    ) -> None:
        """C5: a lock is acquired and released cleanly."""
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-001",
        )
        assert store.profile_is_locked("proj-001-theorist") == "inv-001"
        store.release_profile_lock("proj-001-theorist")
        assert store.profile_is_locked("proj-001-theorist") is None

    def test_second_acquire_rejected(
        self, store: DiagnosticStore
    ) -> None:
        """C5: a second invocation cannot acquire the same profile lock."""
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.create_invocation(
            invocation_id="inv-002",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-001",
        )
        with pytest.raises(ProfileLockHeld) as exc_info:
            store.acquire_profile_lock(
                profile_name="proj-001-theorist",
                invocation_id="inv-002",
            )
        assert exc_info.value.profile_name == "proj-001-theorist"
        assert exc_info.value.holder_invocation_id == "inv-001"

    def test_expired_lock_can_be_reclaimed(
        self, store: DiagnosticStore
    ) -> None:
        """C5: an expired lease allows re-acquisition."""
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.create_invocation(
            invocation_id="inv-002",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        # Acquire with a 0-second lease (immediately expired).
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-001",
            lease_seconds=0,
        )
        # Second invocation can now acquire.
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-002",
        )
        assert store.profile_is_locked("proj-001-theorist") == "inv-002"

    def test_reconcile_cleans_expired(
        self, store: DiagnosticStore
    ) -> None:
        store.create_invocation(
            invocation_id="inv-001",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-001",
            lease_seconds=0,
        )
        freed = store.reconcile_locks()
        assert "proj-001-theorist" in freed


# --------------------------------------------------------------------------- #
# Diagnostic store lifecycle                                                   #
# --------------------------------------------------------------------------- #


class TestDiagnosticStore:
    def test_create_and_get(
        self, store: DiagnosticStore
    ) -> None:
        store.create_invocation(
            invocation_id="inv-test",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
            memory_policy="ephemeral",
            payload={"custom": "data"},
        )
        inv = store.get_invocation("inv-test")
        assert inv is not None
        assert inv["status"] == "pending"
        assert inv["memory_policy"] == "ephemeral"

    def test_update_status(
        self, store: DiagnosticStore
    ) -> None:
        store.create_invocation(
            invocation_id="inv-test",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        # Full state machine path:
        # pending → preflight → creating → launch_acknowledged → running → closing → succeeded
        for s in ("preflight", "creating", "launch_acknowledged", "running", "closing"):
            store.update_status("inv-test", status=s)
        store.update_status(
            "inv-test",
            status="succeeded",
            exit_code=0,
            summary="OK",
        )
        inv = store.get_invocation("inv-test")
        assert inv["status"] == "succeeded"
        assert inv["exit_code"] == 0
        assert inv["summary"] == "OK"

    def test_invalid_transition_rejected(
        self, store: DiagnosticStore
    ) -> None:
        """H0.6: invalid state transitions must be rejected."""
        from method_hub.diagnostics.contracts import StateTransitionError

        store.create_invocation(
            invocation_id="inv-bad",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        with pytest.raises(StateTransitionError):
            # pending -> succeeded is NOT a valid direct transition.
            store.update_status("inv-bad", status="succeeded")

    def test_token_guarded_mutation(
        self, store: DiagnosticStore
    ) -> None:
        """H0.6: update_status with wrong token must fail."""
        from method_hub.diagnostics.contracts import StateTransitionError

        store.create_invocation(
            invocation_id="inv-tok",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        token = store.issue_fencing_token("inv-tok")
        # Correct token: should work.
        store.update_status(
            "inv-tok", status="preflight", expected_token=token.token
        )
        # Wrong token: should fail.
        with pytest.raises(FencingError):
            store.update_status(
                "inv-tok", status="creating", expected_token=token.token + 999
            )

    def test_lease_renewal(
        self, store: DiagnosticStore
    ) -> None:
        """H0.6: lease renewal requires correct invocation + token."""
        store.create_invocation(
            invocation_id="inv-lease",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        token = store.issue_fencing_token("inv-lease")
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-lease",
            token=token.token,
        )
        # Renew with correct credentials.
        store.renew_profile_lease(
            "proj-001-theorist",
            invocation_id="inv-lease",
            expected_token=token.token,
        )
        # Renew with wrong token should fail.
        with pytest.raises(FencingError):
            store.renew_profile_lease(
                "proj-001-theorist",
                invocation_id="inv-lease",
                expected_token=token.token + 1,
            )

    def test_restart_reconciliation(
        self, store: DiagnosticStore
    ) -> None:
        """H0.6: non-terminal invocations are found after restart."""
        store.create_invocation(
            invocation_id="inv-restart-1",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.create_invocation(
            invocation_id="inv-restart-2",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        # Walk inv-restart-1 to running, then leave it.
        for s in ("preflight", "creating", "launch_acknowledged", "running"):
            store.update_status("inv-restart-1", status=s)
        # Walk inv-restart-2 to succeeded (terminal).
        for s in ("preflight", "creating", "launch_acknowledged", "running", "closing", "succeeded"):
            store.update_status("inv-restart-2", status=s)

        # Reconcile: inv-restart-1 is non-terminal, inv-restart-2 is terminal.
        nonterminal = store.list_nonterminal_invocations()
        assert len(nonterminal) == 1
        assert nonterminal[0]["invocation_id"] == "inv-restart-1"

    def test_idempotent_create(
        self, store: DiagnosticStore
    ) -> None:
        """H0.2: duplicate idempotency key returns existing invocation."""
        store.create_invocation(
            invocation_id="inv-idem-1",
            idempotency_key="key-abc",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        returned = store.create_invocation(
            invocation_id="inv-idem-2",
            idempotency_key="key-abc",  # Same key.
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        assert returned == "inv-idem-1"  # Returns existing, not new.

    def test_owner_checked_release(
        self, store: DiagnosticStore
    ) -> None:
        """H0.6: profile lock release is owner-checked."""
        store.create_invocation(
            invocation_id="inv-owner-1",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        token1 = store.issue_fencing_token("inv-owner-1")
        store.acquire_profile_lock(
            profile_name="proj-001-theorist",
            invocation_id="inv-owner-1",
            token=token1.token,
        )
        # Release with correct owner + token.
        store.release_profile_lock(
            "proj-001-theorist",
            expected_invocation_id="inv-owner-1",
            expected_token=token1.token,
        )
        assert store.profile_is_locked("proj-001-theorist") is None

    def test_record_memory_state(
        self, store: DiagnosticStore
    ) -> None:
        store.create_invocation(
            invocation_id="inv-test",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        store.record_memory_state(
            "inv-test",
            before={"memory_sha256": "abc123"},
            after={"memory_sha256": "def456"},
        )
        inv = store.get_invocation("inv-test")
        before = json.loads(inv["memory_state_before"])
        after = json.loads(inv["memory_state_after"])
        assert before["memory_sha256"] == "abc123"
        assert after["memory_sha256"] == "def456"

    def test_list_invocations(
        self, store: DiagnosticStore
    ) -> None:
        for i in range(5):
            store.create_invocation(
                invocation_id=f"inv-{i:03d}",
                project_id="proj-001",
                role="theorist",
                profile_name="proj-001-theorist",
            )
        all_inv = store.list_invocations()
        assert len(all_inv) == 5

        # Walk first 3 through the full state machine to succeeded.
        for i in range(3):
            for s in ("preflight", "creating", "launch_acknowledged", "running", "closing", "succeeded"):
                store.update_status(f"inv-{i:03d}", status=s)
        succeeded = store.list_invocations(status="succeeded")
        assert len(succeeded) == 3


# --------------------------------------------------------------------------- #
# OneShotExecutor command construction                                         #
# --------------------------------------------------------------------------- #


class TestOneShotCommand:
    def test_brief_mounted_as_file_not_inline(
        self, tmp_path: Path
    ) -> None:
        """The task brief is mounted as a file, NOT inlined in the command."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"
        brief.write_text("# Very long task brief content")

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="proj-001-theorist",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(hermes_home=tmp_path / "hermes")
        )
        command = executor._build_command(invocation)

        # The brief content must NOT appear in the command line.
        command_str = " ".join(command)
        assert "Very long task brief content" not in command_str

        # The brief must be mounted as a read-only bind.
        assert "--ro-bind" in command_str
        assert str(brief) in command_str

        # The one-shot prompt must reference the brief path, not contain the content.
        z_index = command.index("-z")
        prompt = command[z_index + 1]
        assert "task.md" in prompt or "brief" in prompt.lower()
        assert "Very long" not in prompt

    def test_identity_files_read_only_overlay(
        self, tmp_path: Path
    ) -> None:
        """C1: SOUL.md and config.yaml are mounted read-only."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"
        brief.write_text("# Brief")

        hermes_home = tmp_path / "hermes"
        profile_dir = hermes_home / "profiles" / "test-profile"
        profile_dir.mkdir(parents=True)
        (profile_dir / "SOUL.md").write_text("# Soul")
        (profile_dir / "config.yaml").write_text("model: {}")

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="test-profile",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(hermes_home=hermes_home)
        )
        command = executor._build_command(invocation)
        command_str = " ".join(command)

        # SOUL.md should appear in a --ro-bind.
        ro_binds = [
            command[i + 2]
            for i in range(len(command))
            if command[i] == "--ro-bind" and i + 2 < len(command)
        ]
        assert any("SOUL.md" in p for p in ro_binds)

    def test_secret_env_injected_via_setenv(
        self, tmp_path: Path
    ) -> None:
        """C7: secrets are injected via bwrap --setenv, not host env."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"
        brief.write_text("# Brief")

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="test-profile",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(
                hermes_home=tmp_path / "hermes",
                secret_env={"API_KEY": "sk-secret123456789012"},
            )
        )
        command = executor._build_command(invocation)
        command_str = " ".join(command)

        # The secret should be injected via --setenv, not visible in the host env.
        env = executor._build_environment(invocation)
        assert "API_KEY" not in env  # Not in host env.

        # But should be in the bwrap command via --setenv.
        assert "--setenv" in command_str
        assert "API_KEY" in command_str

    def test_pid_extraction_from_external_id(self) -> None:
        assert OneShotExecutor._extract_pid("oneshot:pid:12345") == 12345
        assert OneShotExecutor._extract_pid("oneshot:pid:abc") is None
        assert OneShotExecutor._extract_pid("bwrap:something") is None

    def test_profile_flag_in_command(
        self, tmp_path: Path
    ) -> None:
        """H0.4: ``-p <profile>`` flag selects the profile."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"
        brief.write_text("# Brief")

        hermes_home = tmp_path / "hermes"
        profile_dir = hermes_home / "profiles" / "my-profile"
        profile_dir.mkdir(parents=True)
        (profile_dir / "SOUL.md").write_text("# Soul")
        (profile_dir / "config.yaml").write_text("model: {}")

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="my-profile",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(hermes_home=hermes_home)
        )
        command = executor._build_command(invocation)
        assert "-p" in command
        p_index = command.index("-p")
        assert command[p_index + 1] == "my-profile"

    def test_runtime_profile_dir_metadata_used(
        self, tmp_path: Path
    ) -> None:
        """H0.4: runtime_profile_dir metadata overrides canonical profile path."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"
        brief.write_text("# Brief")

        hermes_home = tmp_path / "hermes"
        runtime_dir = tmp_path / "runtime-snapshot"
        runtime_dir.mkdir()
        (runtime_dir / "SOUL.md").write_text("# Runtime Soul")
        (runtime_dir / "config.yaml").write_text("model: {}")

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="my-profile",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
            metadata={"runtime_profile_dir": str(runtime_dir)},
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(hermes_home=hermes_home)
        )
        command = executor._build_command(invocation)
        command_str = " ".join(command)

        # The runtime snapshot directory should be in the bind mounts.
        assert str(runtime_dir) in command_str

    def test_mount_verification_passes(
        self, tmp_path: Path
    ) -> None:
        """H0.4: _verify_mounts returns empty when all mounts exist."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"
        brief.write_text("# Brief")

        hermes_home = tmp_path / "hermes"
        profile_dir = hermes_home / "profiles" / "test-profile"
        profile_dir.mkdir(parents=True)
        (profile_dir / "SOUL.md").write_text("# Soul")
        (profile_dir / "config.yaml").write_text("model: {}")

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="test-profile",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(hermes_home=hermes_home)
        )
        problems = executor._verify_mounts(invocation)
        assert problems == []

    def test_mount_verification_fails_on_missing_brief(
        self, tmp_path: Path
    ) -> None:
        """H0.4: _verify_mounts detects missing task brief."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = tmp_path / "brief.md"  # NOT created.

        hermes_home = tmp_path / "hermes"
        hermes_home.mkdir()

        invocation = RoleInvocation(
            execution_id="exec-001",
            invocation_id="inv-001",
            run_id="run-001",
            project_id="proj-001",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile="test-profile",
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OneShotExecutor(
            OneShotExecutorSettings(hermes_home=hermes_home)
        )
        problems = executor._verify_mounts(invocation)
        assert any("Task brief" in p for p in problems)


# --------------------------------------------------------------------------- #
# OneShotExecutor memory-state recording (C3)                                  #
# --------------------------------------------------------------------------- #


class TestOneShotMemoryState:
    def test_record_memory_state(
        self, tmp_path: Path
    ) -> None:
        """C3: record_memory_state returns sha256 digests."""
        profile_dir = tmp_path / "profile"
        memories = profile_dir / "memories"
        memories.mkdir(parents=True)
        (memories / "MEMORY.md").write_text("# Memory content")
        (memories / "USER.md").write_text("# User content")

        result = OneShotExecutor.record_memory_state(profile_dir)
        assert result["memory_sha256"] is not None
        assert result["user_sha256"] is not None
        assert len(result["memory_sha256"]) == 64  # SHA-256 hex.


# --------------------------------------------------------------------------- #
# Bootstrap: oneshot executor kind                                             #
# --------------------------------------------------------------------------- #


class TestBootstrapOneshot:
    def test_oneshot_executor_kind_rejected(self) -> None:
        """H0.2: 'oneshot' is NOT a valid scientific executor kind."""
        from method_hub.application.settings import ApplicationSettings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApplicationSettings(
                executor_kind="oneshot",
                development_mode=True,
            )


# --------------------------------------------------------------------------- #
# Integration: diagnostic service with mocked executor                         #
# --------------------------------------------------------------------------- #


class TestDiagnosticService:
    def test_successful_diagnostic_run(
        self,
        store: DiagnosticStore,
        hermes_root: Path,
    ) -> None:
        """Full diagnostic service run with a mocked executor."""
        pm = ProjectProfileManager(hermes_root=hermes_root)
        pm.create_project_profiles(
            project_id="diag-proj",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Diagnostic Theorist",
                ),
            ),
        )

        workspace = hermes_root / "diag-workspace"
        workspace.mkdir()
        brief = workspace / "task.md"
        brief.write_text("# Diagnostic brief")

        # Mock executor must write the expected diagnostic output file
        # so the independent validation (H0.5) passes.
        brief_sha = hashlib.sha256(brief.read_bytes()).hexdigest()

        async def mock_execute(invocation, observer):
            # Drive the observer through the lifecycle to match what
            # a real executor does (Slice 1: observer-driven transitions).
            await observer.launch_intent(invocation)
            await observer.launch_acknowledged(invocation, "oci:test:123")
            await observer.heartbeat(invocation, "running")
            output = workspace / "diagnostic_result.json"
            output.write_text(json.dumps({
                "status": "ok",
                "brief_sha256": brief_sha,
                "agent_profile": "diag-proj-theorist",
            }))
            return RoleExecutionResult(
                status=RoleExecutionStatus.SUCCEEDED,
                external_execution_id="oneshot:pid:99999",
                exit_code=0,
                summary="OK",
            )

        mock_executor = AsyncMock(spec=OneShotExecutor)
        mock_executor.execute.side_effect = mock_execute

        service = DiagnosticService(
            store=store,
            executor=mock_executor,
            profile_manager=pm,
        )

        request = DiagnosticRequest(
            project_id="diag-proj",
            role="theorist",
            profile_name="diag-proj-theorist",
            workspace=workspace,
            task_brief=brief,
        )

        result = asyncio.run(service.run_diagnostic(request))
        assert result.status == "succeeded"
        assert result.exit_code == 0

        # Verify the invocation is persisted.
        inv = store.get_invocation(result.invocation_id)
        assert inv is not None
        assert inv["status"] == "succeeded"
        assert inv["memory_state_before"] is not None
        assert inv["memory_state_after"] is not None

        # Verify the profile lock was released.
        assert store.profile_is_locked("diag-proj-theorist") is None

    def test_profile_mutex_blocks_concurrent(
        self,
        store: DiagnosticStore,
        hermes_root: Path,
    ) -> None:
        """C5: two concurrent diagnostics on the same profile can't run."""
        pm = ProjectProfileManager(hermes_root=hermes_root)
        pm.create_project_profiles(
            project_id="diag-proj",
            specs=(
                RoleProfileSpec(
                    role="theorist",
                    base_profile="base-role",
                    soul_text="# Theorist",
                ),
            ),
        )

        # Pre-acquire the profile lock to simulate a running invocation.
        store.create_invocation(
            invocation_id="inv-blocking",
            project_id="diag-proj",
            role="theorist",
            profile_name="diag-proj-theorist",
        )
        store.acquire_profile_lock(
            profile_name="diag-proj-theorist",
            invocation_id="inv-blocking",
        )

        mock_executor = AsyncMock(spec=OneShotExecutor)
        mock_executor.execute.return_value = RoleExecutionResult(
            status=RoleExecutionStatus.SUCCEEDED,
            external_execution_id="x",
            exit_code=0,
            summary="OK",
        )

        service = DiagnosticService(
            store=store,
            executor=mock_executor,
            profile_manager=pm,
        )

        workspace = hermes_root / "ws"
        workspace.mkdir()
        brief = workspace / "task.md"
        brief.write_text("# Brief")

        request = DiagnosticRequest(
            project_id="diag-proj",
            role="theorist",
            profile_name="diag-proj-theorist",
            workspace=workspace,
            task_brief=brief,
        )

        # The second diagnostic should fail because the profile is locked.
        result = asyncio.run(service.run_diagnostic(request))
        assert result.status == "failed"
        assert "locked" in result.summary.lower()

        # Verify the mock executor was never called.
        mock_executor.execute.assert_not_called()

        # The original lock should still be held.
        assert store.profile_is_locked("diag-proj-theorist") == "inv-blocking"


def yield_async() -> None:
    """Give the event loop a chance to run pending tasks."""
    pass
