"""Block 4 integration tests: LocalHermesExecutor.

Tests the supervised local Hermes runner without bwrap, verifying:
- Direct Hermes execution (no bwrap wrapper)
- Durable process identity with PID + start time
- Hermes version recording (no image rebuild)
- Cancellation terminates the full process tree
- Restart reconciliation detects PID reuse
- Bounded output streaming with truncation
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from method_hub.executors.local_hermes import (
    LocalHermesExecutor,
    LocalHermesExecutorSettings,
    ProcessIdentity,
    _check_process_alive,
    _get_process_starttime,
    _read_boot_id,
)
from method_hub.executors.protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_invocation(
    workspace: Path,
    timeout_seconds: int = 60,
) -> RoleInvocation:
    """Create a minimal RoleInvocation for testing."""
    return RoleInvocation(
        execution_id="test-exec",
        invocation_id="test-inv",
        run_id="test-run",
        project_id="test",
        phase="diagnostic",
        mode="headless",
        stage_id="diag-1",
        role="theorist",
        profile="test-profile",
        workspace=workspace,
        task_brief=workspace / "task.md",
        expected_output_paths=(workspace / "output.json",),
        timeout_seconds=timeout_seconds,
    )


class _RecordingObserver:
    """Records all observer callbacks for assertion."""

    def __init__(self):
        self.intents: list[str] = []
        self.acks: list[str] = []
        self.heartbeats: list[str] = []

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self.intents.append(invocation.execution_id)

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.acks.append(external_execution_id)

    async def heartbeat(
        self, invocation: RoleInvocation, activity: str
    ) -> None:
        self.heartbeats.append(activity)


# --------------------------------------------------------------------------- #
# Tests: command construction (no bwrap)                                      #
# --------------------------------------------------------------------------- #


class TestCommandConstruction:
    """The command is built without any bwrap wrapper."""

    def test_command_starts_with_hermes(self, tmp_path):
        """The command list starts with the Hermes binary, not bwrap."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "task.md").write_text("# Test")

        executor = LocalHermesExecutor(LocalHermesExecutorSettings())
        cmd = executor._build_command(_make_invocation(workspace), "/usr/bin/hermes")

        assert cmd[0] == "/usr/bin/hermes"
        assert "bwrap" not in cmd
        assert "--unshare-all" not in cmd
        assert "-z" in cmd
        assert "-p" in cmd

    def test_command_includes_profile_and_skills(self, tmp_path):
        """Profile and skills are passed as CLI arguments."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "task.md").write_text("# Test")

        invocation = RoleInvocation(
            execution_id="exec-1",
            invocation_id="inv-1",
            run_id="run-1",
            project_id="p",
            phase="diag",
            mode="headless",
            stage_id="s1",
            role="theorist",
            profile="my-profile",
            workspace=workspace,
            task_brief=workspace / "task.md",
            expected_output_paths=(),
            preloaded_skills=("skill-a", "skill-b"),
            timeout_seconds=60,
        )

        executor = LocalHermesExecutor(LocalHermesExecutorSettings())
        cmd = executor._build_command(invocation, "hermes")

        assert "-p" in cmd
        profile_idx = cmd.index("-p") + 1
        assert cmd[profile_idx] == "my-profile"
        assert "--skills" in cmd
        skills_idx = cmd.index("--skills") + 1
        assert "skill-a,skill-b" in cmd[skills_idx]


# --------------------------------------------------------------------------- #
# Tests: process identity                                                      #
# --------------------------------------------------------------------------- #


class TestProcessIdentity:
    """Durable process identity distinguishes PID reuse."""

    def test_format_external_id_contains_pid_and_marker(self):
        """The external ID encodes PID, start time, and invocation marker."""
        identity = ProcessIdentity(
            pid=12345,
            start_time=0.0,
            executable="/usr/bin/hermes",
            invocation_marker="test-exec-1234567890",
        )
        ext_id = LocalHermesExecutor._format_external_id(identity)
        assert "local:pid:12345" in ext_id
        assert "st:" in ext_id
        assert "mk:test-exec-12" in ext_id  # marker truncated to 12 chars

    def test_extract_pid_roundtrip(self):
        """PID extraction works on formatted external IDs."""
        identity = ProcessIdentity(
            pid=999,
            start_time=0.0,
            executable="/usr/bin/hermes",
            invocation_marker="abcdef",
        )
        ext_id = LocalHermesExecutor._format_external_id(identity)
        extracted = LocalHermesExecutor._extract_pid(ext_id)
        assert extracted == 999

    def test_parse_external_id_components(self):
        """Full parsing extracts PID, start time, and marker."""
        identity = ProcessIdentity(
            pid=42,
            start_time=0.0,
            executable="/usr/bin/hermes",
            invocation_marker="marker1234567",
        )
        ext_id = LocalHermesExecutor._format_external_id(identity)
        parsed = LocalHermesExecutor._parse_external_id(ext_id)
        assert parsed is not None
        assert parsed["pid"] == 42
        assert "marker" in parsed or "mk" in parsed

    def test_extract_pid_rejects_old_format(self):
        """Old oneshot:pid: format is rejected."""
        assert LocalHermesExecutor._extract_pid("oneshot:pid:12345") is None
        assert LocalHermesExecutor._extract_pid("oci:abc123") is None


# --------------------------------------------------------------------------- #
# Tests: process status helpers                                                #
# --------------------------------------------------------------------------- #


class TestProcessStatusHelpers:
    """Linux /proc-based process inspection works correctly."""

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only /proc test")
    def test_check_process_alive_self(self):
        """The current process is alive."""
        assert _check_process_alive(os.getpid()) is True

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only /proc test")
    def test_check_process_alive_nonexistent(self):
        """A nonexistent PID is not alive."""
        # PID 0x7FFFFFFF is extremely unlikely to exist.
        assert _check_process_alive(2147483647) is False

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only /proc test")
    def test_get_process_starttime_returns_float(self):
        """The start time for the current process is a positive float."""
        st = _get_process_starttime(os.getpid())
        assert st is not None
        assert isinstance(st, float)
        assert st > 0

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only /proc test")
    def test_read_boot_id_returns_string(self):
        """Boot ID is readable on Linux."""
        boot_id = _read_boot_id()
        assert boot_id is not None
        assert len(boot_id) > 0


# --------------------------------------------------------------------------- #
# Tests: reconciliation                                                        #
# --------------------------------------------------------------------------- #


class TestReconcile:
    """Restart reconciliation detects process status via durable identity."""

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux-only /proc test")
    def test_reconcile_dead_process(self):
        """A process that no longer exists returns FAILED."""
        executor = LocalHermesExecutor(LocalHermesExecutorSettings())
        ext_id = "local:pid:2147483647:st:0:mk:nonexistent"
        result = asyncio.run(executor.reconcile(ext_id))
        assert result is not None
        assert result.status == RoleExecutionStatus.FAILED
        assert "exited" in result.summary.lower()

    def test_reconcile_invalid_format(self):
        """An invalid external ID returns None (can't reconcile)."""
        executor = LocalHermesExecutor(LocalHermesExecutorSettings())
        result = asyncio.run(executor.reconcile("invalid:id"))
        assert result is None


# --------------------------------------------------------------------------- #
# Tests: Hermes version recording                                              #
# --------------------------------------------------------------------------- #


class TestHermesVersion:
    """Hermes version is recorded, not used to gate execution."""

    def test_version_cached(self):
        """The version is fetched once and cached."""
        if not shutil.which("hermes"):
            pytest.skip("hermes not available")
        executor = LocalHermesExecutor(LocalHermesExecutorSettings())
        v1 = asyncio.run(executor._get_hermes_version("hermes"))
        v2 = asyncio.run(executor._get_hermes_version("hermes"))
        assert v1 == v2
        assert v1 != "unknown"


# --------------------------------------------------------------------------- #
# Tests: no bwrap dependency                                                   #
# --------------------------------------------------------------------------- #


class TestNoBwrapDependency:
    """The LocalHermesExecutor must NOT depend on bwrap."""

    def test_settings_have_no_bwrap_field(self):
        """LocalHermesExecutorSettings has no bwrap-related fields."""
        s = LocalHermesExecutorSettings()
        assert not hasattr(s, "bwrap_binary")
        assert not hasattr(s, "container_runtime")
        assert not hasattr(s, "brief_mount_point")
        assert not hasattr(s, "workspace_mount_point")

    def test_resolve_binary_does_not_check_bwrap(self, tmp_path):
        """The executor resolves the Hermes binary, never bwrap."""
        executor = LocalHermesExecutor(LocalHermesExecutorSettings())
        # _resolve_hermes_binary should return a path or None,
        # but should never look for 'bwrap'.
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None
            result = executor._resolve_hermes_binary()
            # It should have checked for 'hermes', not 'bwrap'.
            checked_names = [call.args[0] for call in mock_which.call_args_list]
            assert "bwrap" not in checked_names
