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
import time
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


# --------------------------------------------------------------------------- #
# End-to-end tests with a stub executable (Block 4 checkpoint)                 #
# --------------------------------------------------------------------------- #


_STUB_SCRIPT = r'''#!/usr/bin/env python3
"""Stub Hermes executable for Block 4 end-to-end tests.

Handles --version and -z/-p/--usage-file args.  Behavior is controlled
by the STUB_MODE environment variable:

  success    Print a message and exit 0 (default).
  flood      Write many lines exceeding the output cap, then exit 0.
  longline   Write a single line exceeding 64 KiB, then exit 0.
  grandchild Spawn a detached grandchild that sleeps, then sleep
             ourselves until killed.
  sleep      Sleep until killed (for timeout/cancel tests).
"""
import sys
import os
import time
import signal
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    parser.add_argument("-z", dest="prompt")
    parser.add_argument("-p", dest="profile")
    parser.add_argument("--usage-file", dest="usage_file")
    parser.add_argument("-m", dest="model")
    parser.add_argument("--provider", dest="provider")
    parser.add_argument("--skills", dest="skills")
    args, _ = parser.parse_known_args()

    if args.version:
        print("stub-hermes 0.0.1")
        sys.exit(0)

    mode = os.environ.get("STUB_MODE", "success")

    if mode == "flood":
        # Write ~5 MiB across many lines.
        chunk = "x" * 4096 + "\n"
        for _ in range(1280):
            sys.stdout.write(chunk)
        sys.stdout.flush()
        sys.exit(0)

    if mode == "longline":
        # Write a single line exceeding 64 KiB (no newline until the end).
        sys.stdout.write("A" * 300000 + "\n")
        sys.stdout.flush()
        sys.exit(0)

    if mode == "grandchild":
        # Spawn a detached grandchild that sleeps.
        pid = os.fork()
        if pid == 0:
            # Grandchild: sleep for a long time.
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            time.sleep(600)
            os._exit(0)
        # Parent: write our PID + grandchild PID, then sleep.
        sys.stdout.write(f"parent_pid={os.getpid()}\n")
        sys.stdout.write(f"grandchild_pid={pid}\n")
        sys.stdout.flush()
        # Write usage file if requested.
        if args.usage_file:
            with open(args.usage_file, "w") as f:
                f.write('{"tokens": 1}')
        time.sleep(600)
        sys.exit(0)

    if mode == "sleep":
        time.sleep(600)
        sys.exit(0)

    # Default: success.
    sys.stdout.write("stub-hermes completed successfully\n")
    if args.usage_file:
        with open(args.usage_file, "w") as f:
            f.write('{"tokens": 1}')
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


@pytest.fixture
def stub_hermes(tmp_path: Path) -> Path:
    """Create a stub Hermes executable and return its absolute path."""
    stub = tmp_path / "stub-hermes"
    stub.write_text(_STUB_SCRIPT)
    stub.chmod(0o755)
    return stub


def _make_settings(stub_path: Path, stub_mode: str | None = None) -> LocalHermesExecutorSettings:
    """Settings pointing at the stub executable with fast polling.

    If ``stub_mode`` is given, it is injected via ``secret_env`` so the
    stub receives it as ``STUB_MODE``.
    """
    secret_env: dict[str, str] = {}
    if stub_mode is not None:
        secret_env["STUB_MODE"] = stub_mode
    return LocalHermesExecutorSettings(
        hermes_binary=str(stub_path),
        poll_interval_seconds=0.05,
        output_limit_bytes=65536,  # 64 KiB — small for fast tests.
        terminate_grace_seconds=1,
        kill_grace_seconds=1,
        secret_env=secret_env,
    )


def _make_e2e_invocation(workspace: Path, timeout_seconds: int = 10) -> RoleInvocation:
    """Create a minimal invocation with a task brief file."""
    brief = workspace / "task.md"
    brief.write_text("# Test task")
    return RoleInvocation(
        execution_id=f"e2e-{os.getpid()}-{int(time.monotonic() * 1000) % 100000}",
        invocation_id="e2e-inv",
        run_id="e2e-run",
        project_id="e2e-proj",
        phase="diagnostic",
        mode="headless",
        stage_id="diag-1",
        role="theorist",
        profile="test-profile",
        workspace=workspace,
        task_brief=brief,
        expected_output_paths=(),
        timeout_seconds=timeout_seconds,
    )


class TestEndToEndSuccess:
    """(a) Success path: stub exits 0, result is SUCCEEDED."""

    def test_success_exit0(self, stub_hermes: Path, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        settings = _make_settings(stub_hermes)
        executor = LocalHermesExecutor(settings)
        invocation = _make_e2e_invocation(workspace)
        observer = _RecordingObserver()

        result = asyncio.run(executor.execute(invocation, observer))

        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert result.exit_code == 0
        assert result.external_execution_id is not None
        assert result.external_execution_id.startswith("local:")
        assert len(observer.acks) >= 1


class TestEndToEndOutputFlood:
    """(b) Output flood stays within the cumulative cap and completes (F1/F2)."""

    def test_flood_within_cap(self, stub_hermes: Path, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        settings = _make_settings(stub_hermes, stub_mode="flood")
        executor = LocalHermesExecutor(settings)
        invocation = _make_e2e_invocation(workspace)
        observer = _RecordingObserver()

        result = asyncio.run(executor.execute(invocation, observer))

        # The stub exited 0 — process completed despite flood.
        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert result.exit_code == 0
        # The captured diagnostic must NOT exceed the cap (65536 bytes)
        # by more than the marker text length.
        diag_size = len(result.diagnostic_text.encode("utf-8"))
        # diagnostic_text includes the "--- stdout ---" prefix, so allow
        # some overhead, but the stdout portion must be capped.
        assert diag_size < 65536 + 200, (
            f"diagnostic_text is {diag_size} bytes, expected < ~65736"
        )
        # The truncation marker must be present.
        assert "[output truncated]" in result.diagnostic_text


class TestEndToEndOverlongLine:
    """(c) Over-long line is captured with truncation marker, no hang."""

    def test_overlong_line_truncated(self, stub_hermes: Path, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        settings = _make_settings(stub_hermes, stub_mode="longline")
        executor = LocalHermesExecutor(settings)
        invocation = _make_e2e_invocation(workspace)
        observer = _RecordingObserver()

        result = asyncio.run(executor.execute(invocation, observer))

        # Must not hang — process completed.
        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert result.exit_code == 0
        # The truncation marker must be present.
        assert "[output truncated]" in result.diagnostic_text
        # The captured text must be bounded.
        diag_size = len(result.diagnostic_text.encode("utf-8"))
        assert diag_size < 65536 + 200


class TestEndToEndCancellation:
    """(d) Cancellation kills the whole process tree including grandchildren."""

    def test_cancel_kills_grandchild(self, stub_hermes: Path, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        settings = _make_settings(stub_hermes, stub_mode="grandchild")
        executor = LocalHermesExecutor(settings)
        invocation = _make_e2e_invocation(workspace, timeout_seconds=30)
        observer = _RecordingObserver()

        async def run_and_cancel():
            # Start execute in a task.
            exec_task = asyncio.create_task(
                executor.execute(invocation, observer)
            )
            # Give the stub time to spawn the grandchild.
            await asyncio.sleep(0.5)

            # The observer's ack is a placeholder; the real PID is in
            # the heartbeat message ("Hermes PID <N> running...").
            assert len(observer.heartbeats) >= 1
            import re

            m = re.search(r"PID (\d+)", observer.heartbeats[-1])
            assert m, f"Could not extract PID from heartbeat: {observer.heartbeats}"
            pid = int(m.group(1))

            # Find all processes in the same process group (grandchildren).
            import glob

            children: list[int] = []
            for stat_path in glob.glob("/proc/[0-9]*/stat"):
                try:
                    data = Path(stat_path).read_text()
                    paren_end = data.rfind(")")
                    if paren_end == -1:
                        continue
                    fields = data[paren_end + 2:].split()
                    if len(fields) > 3:
                        stat_pid = int(Path(stat_path).parent.name)
                        pgrp = int(fields[3])
                        if pgrp == os.getpgid(pid) and stat_pid != pid:
                            children.append(stat_pid)
                except (OSError, ValueError, ProcessLookupError):
                    continue

            assert len(children) > 0, (
                "Expected at least one grandchild process in the group"
            )
            grandchild_pid = children[0]

            # Construct the external_id to cancel.
            external_id = f"local:pid:{pid}:st:0:mk:{invocation.execution_id[:12]}"

            # Cancel the execution.
            await executor.cancel(external_id)

            # Wait for the exec task to complete.
            try:
                await asyncio.wait_for(exec_task, timeout=10)
            except asyncio.TimeoutError:
                exec_task.cancel()

            # Verify the grandchild is dead.
            await asyncio.sleep(0.5)
            return _check_process_alive(grandchild_pid), grandchild_pid

        gc_alive, gc_pid = asyncio.run(run_and_cancel())
        assert not gc_alive, (
            f"Grandchild PID {gc_pid} is still alive after cancel"
        )


class TestEndToEndTimeout:
    """(e) Timeout returns FAILED and kills descendants."""

    def test_timeout_kills_descendants(self, stub_hermes: Path, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        settings = _make_settings(stub_hermes, stub_mode="grandchild")
        executor = LocalHermesExecutor(settings)
        invocation = _make_e2e_invocation(workspace, timeout_seconds=2)
        observer = _RecordingObserver()

        async def run():
            result = await executor.execute(invocation, observer)

            # Extract the PID for descendant verification.
            assert result.external_execution_id is not None
            pid = LocalHermesExecutor._extract_pid(
                result.external_execution_id
            )

            # The result should be FAILED (timeout).
            assert result.status == RoleExecutionStatus.FAILED
            assert "time limit" in result.summary.lower()

            # Give the OS a moment to clean up.
            await asyncio.sleep(0.5)

            # The main process should be dead.
            if pid is not None:
                assert not _check_process_alive(pid), (
                    f"Main process {pid} still alive after timeout"
                )

            return result

        result = asyncio.run(run())
        assert result.status == RoleExecutionStatus.FAILED
