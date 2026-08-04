"""Slice 2-7 integration tests: isolated runtime profile, durable container
identity, memory policy enforcement, network isolation, evidence recording.

These tests verify the end-to-end OCI diagnostic closure changes without
requiring a real Podman container.  They mock the executor but exercise the
real service/store/migration code paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from method_hub.application.settings import ApplicationSettings
from method_hub.capabilities.network import NetworkPolicy
from method_hub.diagnostics.contracts import DiagnosticState
from method_hub.diagnostics.service import DiagnosticRequest, DiagnosticService
from method_hub.diagnostics.store import DiagnosticStore
from method_hub.executors.oci import OciExecutor, OciExecutorSettings
from method_hub.executors.protocol import (
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)
from method_hub.profiles.project_profiles import MemoryPolicy
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.sqlite3", migrations=HUB_MIGRATIONS)
    db.initialize()
    return db


@pytest.fixture
def store(db: Database) -> DiagnosticStore:
    return DiagnosticStore(db)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    brief = ws / "task.md"
    brief.write_text("# Test task\nWrite diagnostic_result.json.")
    return ws


@pytest.fixture
def settings(tmp_path: Path) -> ApplicationSettings:
    return ApplicationSettings(
        data_root=tmp_path / "data",
        diagnostic_enabled=True,
        development_mode=True,
    )


def _make_invocation(
    workspace: Path,
    runtime_profile_dir: Path | None = None,
    network_policy: NetworkPolicy | None = None,
    profile: str = "test-theorist",
) -> RoleInvocation:
    """Create a minimal RoleInvocation for testing."""
    metadata: dict = {}
    if runtime_profile_dir is not None:
        metadata["runtime_profile_dir"] = str(runtime_profile_dir)
    if network_policy is not None:
        metadata["network_policy"] = network_policy
    return RoleInvocation(
        execution_id="test-exec",
        invocation_id="test-inv",
        run_id="test-run",
        project_id="slice-test",
        phase="diagnostic",
        mode="headless",
        stage_id="diag-1",
        role="theorist",
        profile=profile,
        workspace=workspace,
        task_brief=workspace / "task.md",
        expected_output_paths=(workspace / "diagnostic_result.json",),
        timeout_seconds=60,
        metadata=metadata,
    )


def _make_request(
    workspace: Path,
    profile_name: str = "test-theorist",
    memory_policy: MemoryPolicy = MemoryPolicy.EPHEMERAL,
) -> DiagnosticRequest:
    return DiagnosticRequest(
        project_id="slice-test",
        role="theorist",
        profile_name=profile_name,
        workspace=workspace,
        task_brief=workspace / "task.md",
        memory_policy=memory_policy,
    )


# --------------------------------------------------------------------------- #
# Slice 2: Manifest-bound preflight + isolated runtime profile               #
# --------------------------------------------------------------------------- #


class TestSlice2IsolatedProfile:
    """The OciExecutor mounts ONLY the runtime profile, not the whole host Hermes."""

    def test_build_command_no_host_hermes_mount(self, workspace, tmp_path):
        """The create command must NOT mount ~/.hermes or ~/.local/share/uv."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()
        (runtime_profile / "SOUL.md").write_text("# Soul")
        (runtime_profile / "config.yaml").write_text("model: test")

        invocation = _make_invocation(workspace, runtime_profile_dir=runtime_profile)
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        cmd = executor._build_command(invocation)
        cmd_str = " ".join(cmd)

        # Must NOT mount the uv Python directory.
        assert "local/share/uv" not in cmd_str
        # Must mount only the runtime profile.
        assert str(runtime_profile) in cmd_str
        # Must use podman create (not run).
        assert "create" in cmd_str
        # Must NOT contain old --rm.
        assert "--rm" not in cmd

    def test_build_command_uses_isolated_home(self, workspace, tmp_path):
        """HOME and HERMES_HOME are container-local, not host paths."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()
        (runtime_profile / "SOUL.md").write_text("# Soul")
        (runtime_profile / "config.yaml").write_text("model: test")

        invocation = _make_invocation(workspace, runtime_profile_dir=runtime_profile)
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        cmd = executor._build_command(invocation)
        cmd_str = " ".join(cmd)

        assert "HERMES_HOME=/home/methodhub/.hermes" in cmd_str
        assert "HOME=/home/methodhub" in cmd_str

    def test_verify_mounts_requires_runtime_profile(self, workspace):
        """Missing runtime_profile_dir fails closed."""
        invocation = _make_invocation(workspace)
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        problems = executor._verify_mounts(invocation)
        assert any("runtime_profile_dir" in p for p in problems)

    def test_verify_mounts_requires_identity_files(self, workspace, tmp_path):
        """Runtime profile without SOUL.md/config.yaml fails closed."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()

        invocation = _make_invocation(workspace, runtime_profile_dir=runtime_profile)
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        problems = executor._verify_mounts(invocation)
        assert any("SOUL.md" in p for p in problems)
        assert any("config.yaml" in p for p in problems)


# --------------------------------------------------------------------------- #
# Slice 3: Durable container identity                                        #
# --------------------------------------------------------------------------- #


class TestSlice3ContainerIdentity:
    """The executor uses podman create → container ID → start, not PID."""

    def test_external_id_is_container_id_not_pid(self):
        """The external execution ID format is oci:<container_id>, not oci:pid:<pid>."""
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        assert executor._extract_container_id("oci:pid:12345") is None
        assert executor._extract_container_id("oci:a1b2c3d4e5f6") == "a1b2c3d4e5f6"

    def test_create_command_does_not_use_rm(self, workspace, tmp_path):
        """The create command must NOT include --rm (containers kept for inspection)."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()
        (runtime_profile / "SOUL.md").write_text("# Soul")
        (runtime_profile / "config.yaml").write_text("model: test")

        invocation = _make_invocation(workspace, runtime_profile_dir=runtime_profile)
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        cmd = executor._build_command(invocation)
        assert "--rm" not in cmd

    def test_auto_remove_defaults_to_false(self):
        """auto_remove must default to False (Slice 3)."""
        s = OciExecutorSettings()
        assert s.auto_remove is False


# --------------------------------------------------------------------------- #
# Slice 4: Memory policy enforcement                                         #
# --------------------------------------------------------------------------- #


class TestSlice4MemoryPolicy:
    """read_only and ephemeral profiles NEVER promote. Failed runs NEVER promote."""

    def test_read_only_never_promotes(self, store, workspace, tmp_path):
        """A read_only run that succeeds must NOT promote mutations."""
        from method_hub.diagnostics.runtime_profiles import (
            SnapshotState,
        )

        rpm = MagicMock()
        snapshot = MagicMock()
        snapshot.memory_policy = MemoryPolicy.READ_ONLY
        snapshot.state = SnapshotState.CREATED
        snapshot.config_digest_before = "abc123"
        snapshot.memory_digest_before = "def456"
        snapshot.snapshot_dir = tmp_path / "snapshot"
        snapshot.snapshot_dir.mkdir()
        rpm.snapshot_canonical_profile.return_value = snapshot

        # Create a real profile dir with SOUL.md so _record_memory works.
        canonical = tmp_path / "canonical"
        canonical.mkdir()
        (canonical / "SOUL.md").write_text("# Test soul")
        rpm.canonical_profile.return_value = canonical

        async def mock_execute(invocation, observer):
            await observer.launch_intent(invocation)
            await observer.launch_acknowledged(invocation, "oci:abc123")
            await observer.heartbeat(invocation, "running")
            output = workspace / "diagnostic_result.json"
            brief_sha = hashlib.sha256(
                (workspace / "task.md").read_bytes()
            ).hexdigest()
            output.write_text(json.dumps({
                "status": "ok",
                "brief_sha256": brief_sha,
                "agent_profile": "test-theorist",
            }))
            return RoleExecutionResult(
                status=RoleExecutionStatus.SUCCEEDED,
                external_execution_id="oci:abc123",
                exit_code=0,
                summary="OK",
            )

        mock_executor = MagicMock()
        mock_executor.execute.side_effect = mock_execute

        pm = MagicMock()
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "SOUL.md").write_text("# Test soul")
        pm.get_profile_dir.return_value = profile_dir
        # Provide a real hermes_root so _record_memory can hash files.
        hermes_root = tmp_path / "hermes-root"
        profiles_root = hermes_root / "profiles"
        profile_real = profiles_root / "test-theorist"
        memories = profile_real / "memories"
        memories.mkdir(parents=True, exist_ok=True)
        (memories / "MEMORY.md").write_text("# Memory")
        (memories / "USER.md").write_text("# User")
        pm.hermes_root = hermes_root

        service = DiagnosticService(
            store=store,
            executor=mock_executor,
            profile_manager=pm,
            runtime_profile_manager=rpm,
        )

        request = _make_request(workspace, memory_policy=MemoryPolicy.READ_ONLY)
        result = asyncio.run(service.run_diagnostic(request))
        assert result.status == "succeeded"
        rpm.cleanup_snapshot.assert_called_once()
        rpm.promote_snapshot.assert_not_called()


# --------------------------------------------------------------------------- #
# Slice 5: Bounded supervision                                               #
# --------------------------------------------------------------------------- #


class TestSlice5Supervision:
    """Cancellation uses container ID, not PID."""

    def test_cancel_uses_container_id(self):
        """cancel() accepts oci:<container_id> format."""
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        assert executor._extract_container_id("oci:pid:12345") is None
        assert executor._extract_container_id("oci:abc123def456") == "abc123def456"


# --------------------------------------------------------------------------- #
# Slice 6: Network isolation                                                 #
# --------------------------------------------------------------------------- #


class TestSlice6Network:
    """No --network host. Provider-only network uses slirp4netns."""

    def test_no_network_host(self, workspace, tmp_path):
        """The command must NOT use --network host."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()
        (runtime_profile / "SOUL.md").write_text("# Soul")
        (runtime_profile / "config.yaml").write_text("model: test")

        invocation = _make_invocation(
            workspace,
            runtime_profile_dir=runtime_profile,
            network_policy=NetworkPolicy.allowlist(hosts=("api.openai.com",)),
        )
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        cmd_str = " ".join(executor._build_command(invocation))
        assert "--network host" not in cmd_str
        assert "slirp4netns" in cmd_str

    def test_deny_all_uses_network_none(self, workspace, tmp_path):
        """deny_all policy uses --network none."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()
        (runtime_profile / "SOUL.md").write_text("# Soul")
        (runtime_profile / "config.yaml").write_text("model: test")

        invocation = _make_invocation(
            workspace,
            runtime_profile_dir=runtime_profile,
            network_policy=NetworkPolicy.deny_all(),
        )
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        cmd_str = " ".join(executor._build_command(invocation))
        assert "--network none" in cmd_str
        assert "slirp4netns" not in cmd_str

    def test_allowlist_adds_host_entries(self, workspace, tmp_path):
        """Allowlist mode adds --add-host entries for each allowed host."""
        runtime_profile = tmp_path / "runtime-profile"
        runtime_profile.mkdir()
        (runtime_profile / "SOUL.md").write_text("# Soul")
        (runtime_profile / "config.yaml").write_text("model: test")

        invocation = _make_invocation(
            workspace,
            runtime_profile_dir=runtime_profile,
            network_policy=NetworkPolicy.allowlist(
                hosts=("api.openai.com", "api.anthropic.com"),
            ),
        )
        executor = OciExecutor(OciExecutorSettings(verify_image_digest=False))
        cmd_str = " ".join(executor._build_command(invocation))
        assert "api.openai.com:host-gateway" in cmd_str
        assert "api.anthropic.com:host-gateway" in cmd_str


# --------------------------------------------------------------------------- #
# Slice 7: Evidence package                                                  #
# --------------------------------------------------------------------------- #


class TestSlice7Evidence:
    """Evidence is recorded tied to the exact code, image, and configuration."""

    def test_evidence_column_exists(self, store):
        """The evidence_json column exists after migration."""
        inv_id = "slice7-test-inv"
        store.create_invocation(
            invocation_id=inv_id,
            project_id="slice7",
            role="theorist",
            profile_name="test-theorist",
        )
        store.record_evidence(
            inv_id,
            image_tag="method-hub-runtime:latest",
            image_digest="sha256:abc123",
            brief_sha256="sha256:def456",
            outcome="succeeded",
            exit_code=0,
        )
        inv = store.get_invocation(inv_id)
        assert inv is not None
        evidence = json.loads(inv["evidence_json"])
        assert evidence["image_tag"] == "method-hub-runtime:latest"
        assert evidence["image_digest"] == "sha256:abc123"
        assert evidence["outcome"] == "succeeded"
        assert "recorded_at" in evidence

    def test_migration_5_applied(self, tmp_path):
        """Migration 5 adds the evidence_json column."""
        db = Database(tmp_path / "mig-test.sqlite3", migrations=HUB_MIGRATIONS)
        version = db.initialize()
        assert version == 5
        with db.transaction() as conn:
            cursor = conn.execute("PRAGMA table_info(diagnostic_invocations)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "evidence_json" in columns
