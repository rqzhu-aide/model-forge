"""Hermes Kanban adapter for one already-frozen role invocation.

This adapter submits one exact role task, polls its terminal Hermes state,
and reports that state to the harness.  It does not orchestrate research.

Track A (Phase 0) hardening:

* **Real status enum** — Hermes uses ``{triage, todo, scheduled, ready,
  running, blocked, review, done, archived}``; there is no ``failed`` or
  ``cancelled``.  Failure surfaces as ``blocked`` via the circuit breaker.
* **No-requeue guarantee** — tasks are created with ``--max-retries 1`` so
  the circuit breaker trips on the first non-success outcome and the task
  is never re-dispatched after a timeout or crash.
* **Archived-task hole** — because cancellation uses ``archive`` and
  idempotent create only deduplicates *non-archived* tasks, a cancelled
  invocation is terminal and never re-created during reconciliation.
* **Bounded output** — control-process stdout/stderr is streamed with an
  enforced byte cap rather than buffered and checked post-hoc.
* **Environment allowlist** — the child process receives only declared
  variables, not the full host environment.
* **Confirmed cancellation** — ``cancel`` polls until the task reaches
  ``archived`` (or a bounded timeout) instead of fire-and-forget.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Every status string Hermes kanban can produce (kanban_db.py:102).
_HERMES_STATUSES: frozenset[str] = frozenset(
    {"triage", "todo", "scheduled", "ready", "running",
     "blocked", "review", "done", "archived"}
)

#: Statuses that mean the task succeeded.
_SUCCESS_STATUSES: frozenset[str] = frozenset({"done"})

#: Statuses that mean the task failed (circuit-breaker trip).
_FAILURE_STATUSES: frozenset[str] = frozenset({"blocked"})

#: Status that means the task was cancelled.
_CANCELLED_STATUSES: frozenset[str] = frozenset({"archived"})

#: Terminal statuses — no further polling is productive.
_TERMINAL_STATUSES: frozenset[str] = (
    _SUCCESS_STATUSES | _FAILURE_STATUSES | _CANCELLED_STATUSES
)

#: Environment variables safe to pass to the Hermes child process.
#: Everything else is stripped to prevent credential and path leakage.
_ENVIRONMENT_ALLOWLIST: frozenset[str] = frozenset(
    {"PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
     "TERM", "TMPDIR", "HERMES_HOME"}
)

#: Maximum bytes to retain from each of stdout / stderr of a control
#: process.  The process is killed if it tries to emit more.
_DEFAULT_OUTPUT_LIMIT_BYTES = 1_048_576  # 1 MiB

#: How long to wait for confirmation that an archive/cancel took effect.
_CANCEL_CONFIRM_TIMEOUT_SECONDS = 30.0

#: Poll interval when confirming cancellation.
_CANCEL_CONFIRM_INTERVAL = 1.0

#: Compiled regex for redacting common secret patterns from captured output.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # API keys: sk-... (dashes/underscores allowed, e.g. sk-proj-...),
    # Bearer tokens, etc.  Character class aligned with local_hermes.py.
    re.compile(r"(sk-[a-zA-Z0-9_-]{20,})"),
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})"),
    # Generic hex/token assignments in env-like output
    re.compile(r"((?:api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?"
               r"[a-zA-Z0-9+/=]{16,}['\"]?)",
               re.IGNORECASE),
)


def _redact(text: str) -> str:
    """Replace likely-secret substrings with a placeholder."""

    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


@dataclass(frozen=True, slots=True)
class HermesSettings:
    """Configuration for :class:`HermesKanbanExecutor`."""

    executable: str = "hermes"
    board_slug: str = "model-forge"
    hermes_home: Path | None = None
    poll_interval_seconds: float = 5.0
    command_timeout_seconds: int = 30
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES
    cancel_confirm_timeout_seconds: float = _CANCEL_CONFIRM_TIMEOUT_SECONDS


class HermesExecutionError(RuntimeError):
    """A Hermes CLI invocation failed or returned unexpected data."""


# ---------------------------------------------------------------------------
# Bounded process supervisor (Domain 1 — control processes)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool


def _run_bounded(
    command: list[str],
    *,
    environment: Mapping[str, str],
    timeout: int,
    output_limit_bytes: int,
) -> _CommandResult:
    """Run *command* with streamed, capped output capture.

    stdout and stderr are consumed incrementally.  If either stream exceeds
    *output_limit_bytes* the process is killed and the output is truncated
    to the limit with a trailing marker.
    """

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(environment),
            start_new_session=True,  # own process group for clean kill
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HermesExecutionError(
            f"Failed to start command: {error}"
        ) from error

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_bytes = 0
    stderr_bytes = 0
    truncated = False
    timed_out = False

    assert process.stdout is not None
    assert process.stderr is not None

    start_time = time.monotonic()
    try:
        import select

        stdout, stderr = process.stdout, process.stderr
        while True:
            if process.poll() is not None:
                # Drain remaining buffered output.
                remaining_out, remaining_err = _drain_streams(stdout, stderr)
                if remaining_out:
                    stdout_chunks.append(remaining_out)
                    stdout_bytes += len(remaining_out.encode("utf-8"))
                if remaining_err:
                    stderr_chunks.append(remaining_err)
                    stderr_bytes += len(remaining_err.encode("utf-8"))
                break

            # Enforce the wall-clock timeout.
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                timed_out = True
                _kill_process_group(process)
                break

            # Poll streams without blocking indefinitely.
            readable, _, _ = select.select(
                [stdout, stderr], [], [], min(0.5, max(0.01, timeout - elapsed))
            )
            for stream in readable:
                chunk = stream.read(4096)
                if not chunk:
                    continue
                if stream is stdout:
                    if stdout_bytes < output_limit_bytes:
                        stdout_chunks.append(chunk)
                        stdout_bytes += len(chunk.encode("utf-8"))
                else:
                    if stderr_bytes < output_limit_bytes:
                        stderr_chunks.append(chunk)
                        stderr_bytes += len(chunk.encode("utf-8"))

            if (
                stdout_bytes >= output_limit_bytes
                or stderr_bytes >= output_limit_bytes
            ):
                truncated = True
                _kill_process_group(process)
                break

        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        returncode = process.wait(timeout=5)
    finally:
        if process.poll() is None:
            _kill_process_group(process)

    if timed_out:
        stderr_text_join = "".join(stderr_chunks)
        stderr_text_join += f"\n[process exceeded {timeout}s timeout]"
        stderr_chunks = [stderr_text_join]

    stdout_text = _redact("".join(stdout_chunks))
    stderr_text = _redact("".join(stderr_chunks))

    if truncated:
        stdout_text = stdout_text[:output_limit_bytes] + "\n[output truncated]"
        stderr_text = stderr_text[:output_limit_bytes] + "\n[output truncated]"

    return _CommandResult(returncode, stdout_text, stderr_text, truncated)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill the process and its entire group."""

    try:
        pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except (OSError, ProcessLookupError):
            pass


def _drain_streams(stdout: Any, stderr: Any) -> tuple[str, str]:
    """Read remaining buffered output from both streams."""

    remaining_out = ""
    remaining_err = ""
    try:
        remaining_out = stdout.read() or ""
    except (OSError, ValueError):
        pass
    try:
        remaining_err = stderr.read() or ""
    except (OSError, ValueError):
        pass
    return remaining_out, remaining_err


# ---------------------------------------------------------------------------
# Profile verification
# ---------------------------------------------------------------------------

def resolve_hermes_root(
    hermes_home: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the Hermes base directory.

    Priority:
    1. Explicit *hermes_home* argument.
    2. ``HERMES_HOME`` environment variable (may be base or profile dir).
    3. ``~/.hermes`` on POSIX.
    """

    if hermes_home is not None:
        return hermes_home.expanduser().resolve()

    env = os.environ if environ is None else environ
    configured = str(env.get("HERMES_HOME", "")).strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        # HERMES_HOME may point at <base>/profiles/<name>.
        if candidate.name and candidate.parent.name == "profiles":
            return candidate.parent.parent
        return candidate

    return (Path.home() / ".hermes").resolve()


def profile_home(
    profile_name: str,
    *,
    hermes_root: Path | None = None,
) -> Path:
    """Return the directory path for a named Hermes profile."""

    root = resolve_hermes_root(hermes_root)
    return root / "profiles" / profile_name


def profile_exists(
    profile_name: str,
    *,
    hermes_root: Path | None = None,
) -> bool:
    """Verify that a Hermes profile directory exists on disk."""

    if not profile_name or not isinstance(profile_name, str):
        return False
    home = profile_home(profile_name, hermes_root=hermes_root)
    return home.is_dir()


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------

class HermesKanbanExecutor:
    """Submit and monitor one Hermes kanban task per role invocation."""

    def __init__(self, settings: HermesSettings) -> None:
        self.settings = settings

    # -- environment ------------------------------------------------------

    def _environment(self) -> dict[str, str]:
        """Build a minimal environment for Hermes child processes."""

        env: dict[str, str] = {}
        for key in _ENVIRONMENT_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        if self.settings.hermes_home is not None:
            env["HERMES_HOME"] = str(self.settings.hermes_home.resolve())
        return env

    # -- CLI wrappers -----------------------------------------------------

    def _run(self, arguments: list[str]) -> _CommandResult:
        return _run_bounded(
            arguments,
            environment=self._environment(),
            timeout=self.settings.command_timeout_seconds,
            output_limit_bytes=self.settings.output_limit_bytes,
        )

    @staticmethod
    def _payload(value: Any) -> dict[str, Any]:
        if type(value) is dict and type(value.get("task")) is dict:
            return value["task"]
        if type(value) is dict and type(value.get("data")) is dict:
            return value["data"]
        if type(value) is dict:
            return value
        raise HermesExecutionError("Hermes returned a non-object task response.")

    @staticmethod
    def _status_from_payload(payload: dict[str, Any]) -> str:
        status = str(payload.get("status", "")).lower()
        return status

    # -- task lifecycle ---------------------------------------------------

    def _create(self, invocation: RoleInvocation) -> str:
        body = (
            f"Read the complete task brief at {invocation.task_brief}. "
            f"Work only on run {invocation.run_id}, stage {invocation.stage_id}, "
            f"and role {invocation.role}. Write only the declared output files "
            "inside this task workspace. Do not start another phase or role."
        )
        title = (
            f"{invocation.phase} {invocation.stage_id} {invocation.role} "
            f"[{invocation.run_id}]"
        )
        command = [
            self.settings.executable,
            "kanban",
            "--board",
            self.settings.board_slug,
            "create",
            title,
            "--assignee",
            invocation.profile,
            "--workspace",
            f"dir:{invocation.workspace.resolve()}",
            "--body",
            body,
            "--idempotency-key",
            f"model-forge:{invocation.invocation_id}",
            "--max-runtime",
            f"{invocation.timeout_seconds}s",
            # --max-retries 1: trip the circuit breaker on the FIRST
            # failure.  The task goes straight to ``blocked`` and is
            # never re-dispatched after a timeout or crash.
            "--max-retries",
            "1",
        ]
        for skill in invocation.preloaded_skills:
            command.extend(("--skill", skill))
        command.append("--json")
        completed = self._run(command)
        if completed.returncode != 0:
            raise HermesExecutionError(
                (completed.stderr or completed.stdout).strip()
                or "Hermes task creation failed."
            )
        try:
            payload = self._payload(json.loads(completed.stdout or "{}"))
        except json.JSONDecodeError as error:
            raise HermesExecutionError(
                "Hermes task creation returned invalid JSON."
            ) from error
        task_id = payload.get("id") or payload.get("task_id")
        if type(task_id) is not str or not task_id:
            raise HermesExecutionError(
                "Hermes task creation did not return a task ID."
            )
        return task_id

    def _show(self, task_id: str) -> dict[str, Any]:
        completed = self._run(
            [
                self.settings.executable,
                "kanban",
                "--board",
                self.settings.board_slug,
                "show",
                task_id,
                "--json",
            ]
        )
        if completed.returncode != 0:
            raise HermesExecutionError(
                (completed.stderr or completed.stdout).strip()
                or f"Could not inspect Hermes task {task_id}."
            )
        try:
            return self._payload(json.loads(completed.stdout or "{}"))
        except json.JSONDecodeError as error:
            raise HermesExecutionError(
                f"Hermes task {task_id} returned invalid JSON."
            ) from error

    def _capture_agent_log(self, task_id: str) -> str:
        """Read the bounded worker log (Domain 2) for a terminal task.

        Returns the last ``output_limit_bytes`` of the agent worker log,
        redacted.  Returns an empty string if the log is unavailable.
        """

        completed = self._run(
            [
                self.settings.executable,
                "kanban",
                "--board",
                self.settings.board_slug,
                "log",
                task_id,
                "--tail",
                str(self.settings.output_limit_bytes),
            ]
        )
        if completed.returncode != 0:
            return ""
        log_text = completed.stdout.strip()
        if not log_text or log_text.startswith("(no log"):
            return ""
        return _redact(log_text)

    def _map_status(self, status: str) -> RoleExecutionStatus | None:
        """Map a Hermes status string to a terminal RoleExecutionStatus.

        Returns ``None`` if *status* is not terminal.
        """

        if status in _SUCCESS_STATUSES:
            return RoleExecutionStatus.SUCCEEDED
        if status in _FAILURE_STATUSES:
            return RoleExecutionStatus.FAILED
        if status in _CANCELLED_STATUSES:
            return RoleExecutionStatus.CANCELLED
        return None

    # -- execute ----------------------------------------------------------

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult:
        await observer.launch_intent(invocation)
        try:
            task_id = await asyncio.to_thread(self._create, invocation)
            await observer.launch_acknowledged(invocation, task_id)
            deadline = time.monotonic() + invocation.timeout_seconds
            while True:
                payload = await asyncio.to_thread(self._show, task_id)
                status = self._status_from_payload(payload)
                await observer.heartbeat(
                    invocation,
                    f"Hermes task status: {status or 'unknown'}",
                )
                mapped = self._map_status(status)
                if mapped is not None:
                    agent_log = await asyncio.to_thread(
                        self._capture_agent_log, task_id
                    )
                    return self._result(
                        mapped, task_id, payload,
                        f"Hermes task ended with status {status}.",
                        agent_log=agent_log,
                    )
                if time.monotonic() >= deadline:
                    # Timeout — cancel and report failure.
                    await self.cancel(task_id)
                    return RoleExecutionResult(
                        RoleExecutionStatus.FAILED,
                        task_id,
                        None,
                        "Hermes task exceeded its frozen time limit.",
                    )
                await asyncio.sleep(self.settings.poll_interval_seconds)
        except (OSError, subprocess.SubprocessError, HermesExecutionError) as error:
            return RoleExecutionResult(
                RoleExecutionStatus.FAILED,
                None,
                None,
                "Hermes role execution failed.",
                str(error),
            )

    @staticmethod
    def _result(
        status: RoleExecutionStatus,
        task_id: str,
        payload: dict[str, Any],
        summary: str,
        *,
        agent_log: str = "",
    ) -> RoleExecutionResult:
        exit_code = 0 if status == RoleExecutionStatus.SUCCEEDED else 1
        detail = str(
            payload.get("reason")
            or payload.get("message")
            or payload.get("last_failure_error")
            or ""
        )
        if agent_log:
            detail = f"{detail}\n\n--- Agent worker log ---\n{agent_log}".strip()
        return RoleExecutionResult(status, task_id, exit_code, summary, detail)

    # -- cancellation -----------------------------------------------------

    async def cancel(self, external_execution_id: str) -> None:
        """Archive the task and wait for confirmed terminal state."""

        def _archive() -> None:
            self._run(
                [
                    self.settings.executable,
                    "kanban",
                    "--board",
                    self.settings.board_slug,
                    "archive",
                    external_execution_id,
                ]
            )

        await asyncio.to_thread(_archive)

        # Poll until the task reaches ``archived`` or the confirm timeout
        # expires.  An unconfirmed cancel is reported as an unresolved
        # condition by the caller, never as a silent success.
        deadline = time.monotonic() + self.settings.cancel_confirm_timeout_seconds
        while time.monotonic() < deadline:
            try:
                payload = await asyncio.to_thread(self._show, external_execution_id)
            except HermesExecutionError:
                break
            status = self._status_from_payload(payload)
            if status in _CANCELLED_STATUSES:
                return
            await asyncio.sleep(_CANCEL_CONFIRM_INTERVAL)

    # -- reconciliation ---------------------------------------------------

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult | None:
        """Inspect an existing Hermes task and return its terminal result.

        Returns ``None`` if the task is still running or its state is
        unknown.  A task in ``archived`` status is treated as CANCELLED —
        it is never revived or re-created.
        """

        try:
            payload = await asyncio.to_thread(self._show, external_execution_id)
        except (OSError, subprocess.SubprocessError, HermesExecutionError):
            return None
        status = self._status_from_payload(payload)
        mapped = self._map_status(status)
        if mapped is None:
            return None
        return self._result(
            mapped,
            external_execution_id,
            payload,
            f"Existing Hermes task ended with status {status}.",
        )


__all__ = [
    "HermesExecutionError",
    "HermesKanbanExecutor",
    "HermesSettings",
    "profile_exists",
    "profile_home",
    "resolve_hermes_root",
]
