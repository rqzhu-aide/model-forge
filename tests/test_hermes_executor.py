"""Tests for the Hermes Kanban executor (Track A hardening).

These tests verify the behavioral fixes documented in the Phase 0 spike
findings:

- Status enum mapping (no ``failed``/``cancelled`` in Hermes)
- ``--max-retries 1`` in the create command (prevents requeue)
- Archived-task hole (cancelled invocations are never re-created)
- Bounded streaming output capture
- Environment allowlist
- Profile existence verification
- Confirmed cancellation polling

The tests mock the subprocess layer — they do not require a real Hermes
installation.  Integration with a live Hermes is verified separately.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from method_hub.executors.hermes import (
    HermesExecutionError,
    HermesKanbanExecutor,
    HermesSettings,
    _ENVIRONMENT_ALLOWLIST,
    _redact,
    _run_bounded,
    profile_exists,
    profile_home,
    resolve_hermes_root,
)
from method_hub.executors.protocol import (
    RoleExecutionStatus,
    RoleInvocation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class RecordingObserver:
    """Capture all observer callbacks for assertions."""

    def __init__(self) -> None:
        self.intents: list[RoleInvocation] = []
        self.acks: list[tuple[RoleInvocation, str]] = []
        self.heartbeats: list[tuple[RoleInvocation, str]] = []

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self.intents.append(invocation)

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.acks.append((invocation, external_execution_id))

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        self.heartbeats.append((invocation, activity))


def make_invocation(tmp_path: Path, **overrides: Any) -> RoleInvocation:
    defaults: dict[str, Any] = dict(
        execution_id="execution.test",
        invocation_id="invocation.test",
        run_id="run.test",
        project_id="project.test",
        phase="P3",
        mode="p3.theory",
        stage_id="p3.theorist",
        role="theorist",
        profile="theorist",
        workspace=tmp_path / "workspace",
        task_brief=tmp_path / "task.md",
        expected_output_paths=(tmp_path / "output.json",),
        timeout_seconds=60,
    )
    defaults.update(overrides)
    defaults["workspace"] = Path(defaults["workspace"])
    defaults["task_brief"] = Path(defaults["task_brief"])
    return RoleInvocation(**defaults)


def make_executor(**overrides: Any) -> HermesKanbanExecutor:
    settings_defaults: dict[str, Any] = dict(
        executable="hermes",
        board_slug="test-board",
        poll_interval_seconds=0.01,  # fast for tests
        command_timeout_seconds=5,
        output_limit_bytes=4096,
        cancel_confirm_timeout_seconds=0.5,
    )
    settings_defaults.update(overrides)
    return HermesKanbanExecutor(HermesSettings(**settings_defaults))


# ---------------------------------------------------------------------------
# Status mapping (A5)
# ---------------------------------------------------------------------------

class TestStatusMapping:
    """Hermes has no ``failed`` or ``cancelled`` — verify the real enum."""

    @pytest.mark.parametrize(
        "hermes_status, expected",
        [
            ("done", RoleExecutionStatus.SUCCEEDED),
            ("blocked", RoleExecutionStatus.FAILED),
            ("archived", RoleExecutionStatus.CANCELLED),
        ],
    )
    def test_terminal_statuses_mapped(
        self, hermes_status: str, expected: RoleExecutionStatus
    ) -> None:
        executor = make_executor()
        assert executor._map_status(hermes_status) == expected

    @pytest.mark.parametrize(
        "hermes_status",
        ["triage", "todo", "scheduled", "ready", "running", "review"],
    )
    def test_non_terminal_statuses_return_none(self, hermes_status: str) -> None:
        executor = make_executor()
        assert executor._map_status(hermes_status) is None

    def test_nonexistent_statuses_are_not_mapped(self) -> None:
        """The old adapter mapped 'failed' and 'cancelled' — these do not exist."""
        executor = make_executor()
        assert executor._map_status("failed") is None
        assert executor._map_status("cancelled") is None


# ---------------------------------------------------------------------------
# Create command — --max-retries 1 (A4)
# ---------------------------------------------------------------------------

class TestMaxRetries:
    """The create command must use ``--max-retries 1`` to prevent requeue."""

    def test_create_uses_max_retries_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_command: list[str] = []

        def fake_run_bounded(command, **kwargs):
            captured_command.extend(command)
            from method_hub.executors.hermes import _CommandResult
            return _CommandResult(
                returncode=0,
                stdout=json.dumps({"id": "t_test123", "status": "ready"}),
                stderr="",
                truncated=False,
            )

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor()
        invocation = make_invocation(tmp_path)
        task_id = executor._create(invocation)

        assert task_id == "t_test123"
        # Verify --max-retries 1 is in the command
        assert "--max-retries" in captured_command
        idx = captured_command.index("--max-retries")
        assert captured_command[idx + 1] == "1"


# ---------------------------------------------------------------------------
# Reconciliation — archived-task hole (A3)
# ---------------------------------------------------------------------------

class TestArchivedTaskHole:
    """A cancelled (archived) invocation must never be revived."""

    def test_reconcile_archived_returns_cancelled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_show_response(*args, **kwargs):
            return _CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {"task": {"id": "t_archived", "status": "archived"}}
                ),
                stderr="",
                truncated=False,
            )

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_show_response
        )

        executor = make_executor()
        result = asyncio.run(executor.reconcile("t_archived"))

        assert result is not None
        assert result.status == RoleExecutionStatus.CANCELLED

    def test_reconcile_running_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_show_response(*args, **kwargs):
            return _CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {"task": {"id": "t_running", "status": "running"}}
                ),
                stderr="",
                truncated=False,
            )

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_show_response
        )

        executor = make_executor()
        result = asyncio.run(executor.reconcile("t_running"))
        assert result is None  # still running, not terminal


# ---------------------------------------------------------------------------
# Bounded output capture (Domain 1)
# ---------------------------------------------------------------------------

class TestBoundedOutput:
    """Control-process output must be streamed and capped, not buffered."""

    def test_normal_output_is_captured(self) -> None:
        result = _run_bounded(
            ["echo", "hello world"],
            environment={"PATH": os.environ.get("PATH", "")},
            timeout=5,
            output_limit_bytes=4096,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout
        assert not result.truncated

    def test_oversized_output_is_truncated(self) -> None:
        # Generate ~100KB of output, cap at 4KB.
        result = _run_bounded(
            ["python3", "-c", "import sys; sys.stdout.write('x' * 100000)"],
            environment={"PATH": os.environ.get("PATH", "")},
            timeout=10,
            output_limit_bytes=4096,
        )
        assert result.truncated
        assert len(result.stdout) <= 4096 + len("\n[output truncated]")

    def test_hung_process_is_killed(self) -> None:
        start = time.monotonic()
        result = _run_bounded(
            ["python3", "-c", "import time; time.sleep(30)"],
            environment={"PATH": os.environ.get("PATH", "")},
            timeout=2,
            output_limit_bytes=4096,
        )
        elapsed = time.monotonic() - start
        # Should be killed well before the 30s sleep
        assert elapsed < 15


# ---------------------------------------------------------------------------
# Environment allowlist
# ---------------------------------------------------------------------------

class TestEnvironmentAllowlist:
    """Child processes must not inherit the full host environment."""

    def test_only_allowlisted_vars_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Inject a secret into the host environment.
        monkeypatch.setenv("SECRET_API_KEY", "sk-very-secret-1234567890")
        monkeypatch.setenv("DATABASE_PASSWORD", "super-secret-password")

        executor = make_executor()
        env = executor._environment()

        # Secrets must not be present
        assert "SECRET_API_KEY" not in env
        assert "DATABASE_PASSWORD" not in env

        # Allowlisted vars should be present if they exist in host env
        for key in ("PATH", "HOME", "USER"):
            if key in os.environ:
                assert key in env

    def test_hermes_home_injected_when_configured(
        self, tmp_path: Path
    ) -> None:
        settings = HermesSettings(hermes_home=tmp_path / "custom-hermes")
        executor = HermesKanbanExecutor(settings)
        env = executor._environment()
        assert env["HERMES_HOME"] == str((tmp_path / "custom-hermes").resolve())

    def test_secret_redaction_in_output(self) -> None:
        text = "Config: api_key=" + "sk-" + "abcdefghijklmnopqrstuvwxyz1234567890"
        redacted = _redact(text)
        assert "sk-" + "abcdefghij" not in redacted
        assert "[REDACTED]" in redacted

    def test_secret_redaction_covers_dashed_underscored_keys(self) -> None:
        """K-3: sk- keys with dashes/underscores (e.g. sk-proj-...) redact."""
        text = "key is sk-proj-abcDEF_123-xyzQWERTY987 here"
        redacted = _redact(text)
        assert "sk-proj" not in redacted
        assert "[REDACTED]" in redacted


# ---------------------------------------------------------------------------
# Profile verification
# ---------------------------------------------------------------------------

class TestProfileVerification:
    """Profile existence must be verified on disk, not just by name."""

    def test_profile_exists_for_real_profile(
        self, tmp_path: Path
    ) -> None:
        # Create a fake profile structure
        root = tmp_path / "hermes-root"
        profile_dir = root / "profiles" / "test_profile"
        profile_dir.mkdir(parents=True)

        assert profile_exists("test_profile", hermes_root=root)

    def test_profile_does_not_exist(self, tmp_path: Path) -> None:
        root = tmp_path / "hermes-root"
        root.mkdir()
        assert not profile_exists("nonexistent", hermes_root=root)

    def test_profile_exists_rejects_empty_name(self) -> None:
        assert not profile_exists("")

    def test_profile_home_path_construction(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "hermes-root"
        home = profile_home("my_profile", hermes_root=root)
        assert home == root / "profiles" / "my_profile"

    def test_resolve_hermes_root_from_profile_path(
        self, tmp_path: Path
    ) -> None:
        """HERMES_HOME may point at a profile dir — root must be the parent."""
        root = tmp_path / ".hermes"
        profile = root / "profiles" / "developer"
        profile.mkdir(parents=True)

        resolved = resolve_hermes_root(environ={"HERMES_HOME": str(profile)})
        assert resolved == root.resolve()


# ---------------------------------------------------------------------------
# Confirmed cancellation
# ---------------------------------------------------------------------------

class TestConfirmedCancellation:
    """Cancellation must poll for ``archived`` status, not fire-and-forget."""

    def test_cancel_polls_until_archived(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        call_count = {"show": 0}

        def fake_run_bounded(command, **kwargs):
            if "archive" in command:
                return _CommandResult(0, "Archived", "", False)
            if "show" in command:
                call_count["show"] += 1
                # First show: still running. Second show: archived.
                status = "running" if call_count["show"] < 2 else "archived"
                return _CommandResult(
                    0,
                    json.dumps({"task": {"id": "t_123", "status": status}}),
                    "",
                    False,
                )
            return _CommandResult(0, "", "", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor(cancel_confirm_timeout_seconds=5.0)
        # Should complete without hanging
        asyncio.run(asyncio.wait_for(executor.cancel("t_123"), timeout=10))
        assert call_count["show"] >= 2  # polled at least twice

    def test_cancel_times_out_gracefully(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_run_bounded(command, **kwargs):
            if "archive" in command:
                return _CommandResult(0, "Archived", "", False)
            if "show" in command:
                # Never reaches archived
                return _CommandResult(
                    0,
                    json.dumps({"task": {"id": "t_456", "status": "running"}}),
                    "",
                    False,
                )
            return _CommandResult(0, "", "", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor(
            cancel_confirm_timeout_seconds=0.2,
        )
        # Should return (not raise) after the timeout
        asyncio.run(asyncio.wait_for(executor.cancel("t_456"), timeout=5))


# ---------------------------------------------------------------------------
# Execute — end-to-end with mocked subprocess
# ---------------------------------------------------------------------------

class TestAgentLogCapture:
    """After terminal state, the agent worker log (Domain 2) is captured."""

    def test_successful_execution_includes_agent_log(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_run_bounded(command, **kwargs):
            if "create" in command:
                return _CommandResult(
                    0,
                    json.dumps({"id": "t_with_log", "status": "ready"}),
                    "",
                    False,
                )
            if "show" in command:
                return _CommandResult(
                    0,
                    json.dumps({"task": {"id": "t_with_log", "status": "done"}}),
                    "",
                    False,
                )
            if "log" in command:
                return _CommandResult(
                    0,
                    "Worker started\nProcessing task\nTask complete",
                    "",
                    False,
                )
            return _CommandResult(0, "", "", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor()
        observer = RecordingObserver()
        invocation = make_invocation(tmp_path)

        result = asyncio.run(executor.execute(invocation, observer))

        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert "Agent worker log" in result.diagnostic_text
        assert "Worker started" in result.diagnostic_text

    def test_agent_log_empty_when_no_log_available(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_run_bounded(command, **kwargs):
            if "create" in command:
                return _CommandResult(
                    0,
                    json.dumps({"id": "t_no_log", "status": "ready"}),
                    "",
                    False,
                )
            if "show" in command:
                return _CommandResult(
                    0,
                    json.dumps({"task": {"id": "t_no_log", "status": "done"}}),
                    "",
                    False,
                )
            if "log" in command:
                return _CommandResult(0, "(no log for t_no_log)", "", False)
            return _CommandResult(0, "", "", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor()
        observer = RecordingObserver()
        invocation = make_invocation(tmp_path)

        result = asyncio.run(executor.execute(invocation, observer))

        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert "Agent worker log" not in result.diagnostic_text


class TestExecuteFlow:
    """Full execute flow with mocked Hermes CLI responses."""

    def test_successful_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_run_bounded(command, **kwargs):
            if "create" in command:
                return _CommandResult(
                    0,
                    json.dumps({"id": "t_success", "status": "ready"}),
                    "",
                    False,
                )
            if "show" in command:
                return _CommandResult(
                    0,
                    json.dumps({"task": {"id": "t_success", "status": "done"}}),
                    "",
                    False,
                )
            return _CommandResult(0, "", "", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor()
        observer = RecordingObserver()
        invocation = make_invocation(tmp_path)

        result = asyncio.run(executor.execute(invocation, observer))

        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert result.external_execution_id == "t_success"
        assert result.exit_code == 0
        assert len(observer.intents) == 1
        assert len(observer.acks) == 1
        assert len(observer.heartbeats) >= 1

    def test_failed_execution_blocked_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the circuit breaker trips, status becomes 'blocked'."""
        from method_hub.executors.hermes import _CommandResult

        def fake_run_bounded(command, **kwargs):
            if "create" in command:
                return _CommandResult(
                    0,
                    json.dumps({"id": "t_blocked", "status": "ready"}),
                    "",
                    False,
                )
            if "show" in command:
                return _CommandResult(
                    0,
                    json.dumps(
                        {
                            "task": {
                                "id": "t_blocked",
                                "status": "blocked",
                                "last_failure_error": "circuit breaker tripped",
                            }
                        }
                    ),
                    "",
                    False,
                )
            return _CommandResult(0, "", "", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor()
        observer = RecordingObserver()
        invocation = make_invocation(tmp_path)

        result = asyncio.run(executor.execute(invocation, observer))

        assert result.status == RoleExecutionStatus.FAILED
        assert "circuit breaker tripped" in result.diagnostic_text

    def test_execution_failure_on_cli_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from method_hub.executors.hermes import _CommandResult

        def fake_run_bounded(command, **kwargs):
            return _CommandResult(1, "", "hermes: command not found", False)

        monkeypatch.setattr(
            "method_hub.executors.hermes._run_bounded", fake_run_bounded
        )

        executor = make_executor()
        observer = RecordingObserver()
        invocation = make_invocation(tmp_path)

        result = asyncio.run(executor.execute(invocation, observer))

        assert result.status == RoleExecutionStatus.FAILED
        assert "execution failed" in result.summary.lower()
