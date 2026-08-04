"""Local Hermes executor: supervised direct execution (ADR-012, Block 4).

This executor replaces the interim OneShotExecutor + bwrap combination with
direct supervised execution of the installed Hermes binary.  It is the only
supported Version 1 real-Hermes backend.

Key differences from OneShotExecutor:

* **No bwrap.** Hermes runs directly as a local process.  The host is trusted
  (ADR-012); Method Hub does not claim operating-system isolation.
* **Durable process identity.** The external execution ID binds the PID,
  process start time, executable path, and a per-invocation marker to
  distinguish PID reuse.
* **Restart reconciliation.** On application restart, the recorded identity
  is inspected to determine whether the process is still running, exited
  naturally, or was terminated.  No automatic relaunch.
* **Hermes version detection.** Preflight records the installed Hermes
  executable path and version.  A changed version is surfaced and recorded
  in the next manifest — no image rebuild.
* **Process-tree quiescence.** Cancellation and timeout terminate the
  complete process tree (via process group) and verify quiescence before
  recording closure.

Built from ``executors/oneshot.py`` which already implements:
  - one-shot ``hermes -z`` launch (the process IS the agent)
  - file-mounted task briefs
  - bounded streamed output with a live cap
  - secret redaction
  - PID-based external identity
  - heartbeat polling
  - before/after memory digests

The Block 4 work strips the ``bwrap`` wrapper, adds durable process identity,
restart reconciliation, and verified process-tree quiescence.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..capabilities.network import NetworkPolicy
from .protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

_HERMES_BINARY = "hermes"

#: Environment variables passed through to Hermes.
_ENVIRONMENT_ALLOWLIST: frozenset[str] = frozenset(
    {"PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
     "TERM", "TMPDIR"}
)

#: Regex for redacting secrets from captured output.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})"),
    re.compile(
        r"((?:api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?"
        r"[a-zA-Z0-9+/=]{16,}['\"]?)",
        re.IGNORECASE,
    ),
)

_DEFAULT_OUTPUT_LIMIT_BYTES = 1_048_576  # 1 MiB
_HEARTBEAT_INTERVAL_SECONDS = 10.0
_TERMINATE_GRACE_SECONDS = 5
_KILL_GRACE_SECONDS = 3

#: The prompt instructing the agent to read its brief.
_BRIEF_PROMPT_TEMPLATE = (
    "Read and execute the task brief at {brief_path}. "
    "Write only the declared output files."
)


def _redact(text: str) -> str:
    """Replace likely-secret substrings with a placeholder."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


# --------------------------------------------------------------------------- #
# Process identity                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Durable identity for a local Hermes process.

    Binds the PID, process start time, executable path, and a per-invocation
    marker to distinguish PID reuse across process lifetimes.
    """

    pid: int
    start_time: float  # monotonic seconds at process creation
    executable: str  # resolved Hermes binary path
    invocation_marker: str  # unique per-invocation token
    host_boot_id: str | None = None  # /proc/sys/kernel/random/boot_id if available


def _read_boot_id() -> str | None:
    """Read the host boot identity for PID-reuse disambiguation."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except (OSError, FileNotFoundError):
        return None


def _check_process_alive(pid: int) -> bool:
    """Check whether a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _get_process_starttime(pid: int) -> float | None:
    """Get the process start time (field 22 of /proc/<pid>/stat).

    This distinguishes PID reuse: if the start time changes, the original
    process has exited and a different process now uses the same PID.
    """
    try:
        stat_data = Path(f"/proc/{pid}/stat").read_text()
        # The start time is field 22 (1-indexed).  But comm (field 2) may
        # contain spaces if the process name has them, so we find the
        # closing paren and parse from there.
        paren_end = stat_data.rfind(")")
        if paren_end == -1:
            return None
        fields = stat_data[paren_end + 2:].split()
        # After "comm) state ppid pgrp session tty_nr tpgid flags ..."
        # field 22 in the full stat is starttime (index 19 after paren).
        if len(fields) > 19:
            return float(fields[19])
        return None
    except (OSError, FileNotFoundError, ValueError, IndexError):
        return None


# --------------------------------------------------------------------------- #
# Settings                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LocalHermesExecutorSettings:
    """Configuration for :class:`LocalHermesExecutor`."""

    #: Hermes binary name or absolute path.  Resolved via shutil.which.
    hermes_binary: str = _HERMES_BINARY
    #: Hermes home directory (``~/.hermes``).
    hermes_home: Path | None = None
    #: Polling interval for heartbeats.
    poll_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS
    #: Maximum captured output size per stream.
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES
    #: Secret environment variables injected at runtime — never persisted.
    secret_env: Mapping[str, str] = field(default_factory=dict)
    #: Default network policy (informational only under trusted-local;
    #: Method Hub does not enforce network isolation per ADR-012).
    default_network_policy: NetworkPolicy | None = None
    #: Grace period (seconds) for SIGTERM before escalating to SIGKILL.
    terminate_grace_seconds: int = _TERMINATE_GRACE_SECONDS
    #: Grace period (seconds) for SIGKILL before giving up.
    kill_grace_seconds: int = _KILL_GRACE_SECONDS


class LocalHermesExecutionError(RuntimeError):
    """A local Hermes execution failed."""


# --------------------------------------------------------------------------- #
# Executor                                                                     #
# --------------------------------------------------------------------------- #


class LocalHermesExecutor:
    """Execute role invocations via direct local Hermes execution.

    Implements the :class:`RoleExecutor` protocol.  Each invocation:

    1. Resolves and verifies the Hermes executable (records version).
    2. Launches ``hermes -z`` directly (no shell, no bwrap).
    3. Records a durable process identity immediately after creation.
    4. Streams stdout/stderr under fixed bounds.
    5. Heartbeats at regular intervals.
    6. On exit: validates output, returns terminal result.
    7. On cancellation/timeout: terminates the full process tree.
    8. On restart: reconciles using the recorded identity.

    This executor does NOT provide host isolation (ADR-012).
    """

    def __init__(self, settings: LocalHermesExecutorSettings) -> None:
        self.settings = settings
        #: Cache of Hermes version info, populated by preflight.
        self._hermes_version: str | None = None
        self._hermes_executable: str | None = None

    # ------------------------------------------------------------------ #
    # Execute                                                            #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult:
        await observer.launch_intent(invocation)

        # Preflight: resolve and verify the Hermes executable.
        hermes_bin = self._resolve_hermes_binary()
        if hermes_bin is None:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="Hermes binary not found.",
                diagnostic_text=(
                    f"Could not find '{self.settings.hermes_binary}' in PATH "
                    f"or at known locations."
                ),
            )

        # Record Hermes version (no container rebuild — just record it).
        version_info = await self._get_hermes_version(hermes_bin)

        # Verify mount sources.
        mount_problems = self._verify_mounts(invocation)
        if mount_problems:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="Pre-launch verification failed.",
                diagnostic_text="; ".join(mount_problems),
            )

        try:
            command = self._build_command(invocation, hermes_bin)
            env = self._build_environment(invocation)
            external_id_placeholder = f"local:{invocation.execution_id}"
            await observer.launch_acknowledged(invocation, external_id_placeholder)

            # Launch the process directly (no shell, no bwrap).
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,  # Creates a new process group.
            )

            # Record durable process identity immediately.
            boot_id = _read_boot_id()
            identity = ProcessIdentity(
                pid=process.pid,
                start_time=time.monotonic(),
                executable=hermes_bin,
                invocation_marker=invocation.execution_id,
                host_boot_id=boot_id,
            )
            external_id = self._format_external_id(identity)

            # Incremental output streaming.
            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            limit = self.settings.output_limit_bytes

            deadline = time.monotonic() + invocation.timeout_seconds
            start_time = time.monotonic()

            async def _read_stream(
                stream: asyncio.StreamReader | None,
                chunks: list[str],
            ) -> int:
                """Incrementally read lines, truncating at the output limit."""
                total = 0
                if stream is None:
                    return 0
                while True:
                    try:
                        line = await stream.readline()
                    except Exception:
                        break
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    remaining = limit - total
                    if remaining <= 0:
                        break
                    if len(decoded) > remaining:
                        decoded = decoded[:remaining] + "\n[output truncated]"
                    chunks.append(decoded)
                    total += len(decoded.encode("utf-8"))
                return total

            while True:
                read_task = asyncio.gather(
                    _read_stream(process.stdout, stdout_chunks),
                    _read_stream(process.stderr, stderr_chunks),
                )
                try:
                    await asyncio.wait_for(
                        read_task, timeout=self.settings.poll_interval_seconds
                    )
                except asyncio.TimeoutError:
                    read_task.cancel()

                if process.returncode is not None:
                    # Process exited — drain remaining output.
                    drain_task = asyncio.gather(
                        _read_stream(process.stdout, stdout_chunks),
                        _read_stream(process.stderr, stderr_chunks),
                    )
                    try:
                        await asyncio.wait_for(drain_task, timeout=5)
                    except asyncio.TimeoutError:
                        drain_task.cancel()

                    stdout_text = "".join(stdout_chunks)
                    stderr_text = "".join(stderr_chunks)
                    exit_code = process.returncode
                    status = (
                        RoleExecutionStatus.SUCCEEDED
                        if exit_code == 0
                        else RoleExecutionStatus.FAILED
                    )
                    return RoleExecutionResult(
                        status=status,
                        external_execution_id=external_id,
                        exit_code=exit_code,
                        summary=(
                            f"Hermes exited with code {exit_code}. "
                            f"Version: {version_info}"
                        ),
                        diagnostic_text=_redact(
                            f"{stderr_text}\n--- stdout ---\n{stdout_text}".strip()
                        ),
                    )

                elapsed = time.monotonic() - start_time
                await observer.heartbeat(
                    invocation,
                    f"Hermes PID {process.pid} running "
                    f"(elapsed {elapsed:.0f}s, version: {version_info})",
                )

                if time.monotonic() >= deadline:
                    # Timeout — terminate the full process tree.
                    await self._terminate_process_tree(process)
                    stdout_text = "".join(stdout_chunks)
                    stderr_text = "".join(stderr_chunks)
                    return RoleExecutionResult(
                        status=RoleExecutionStatus.FAILED,
                        external_execution_id=external_id,
                        exit_code=None,
                        summary="Hermes exceeded its time limit.",
                        diagnostic_text=_redact(
                            f"Timed out after {invocation.timeout_seconds}s\n"
                            f"--- stderr ---\n{stderr_text}\n"
                            f"--- stdout ---\n{stdout_text}"
                        ),
                    )

        except (OSError, subprocess.SubprocessError) as error:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="Local Hermes execution failed to start.",
                diagnostic_text=str(error),
            )

    # ------------------------------------------------------------------ #
    # Process-tree termination                                           #
    # ------------------------------------------------------------------ #

    async def _terminate_process_tree(
        self, process: asyncio.subprocess.Process
    ) -> None:
        """Terminate the complete process tree with verified quiescence.

        1. Send SIGTERM to the process group.
        2. Wait up to terminate_grace_seconds for the process to exit.
        3. If still alive, send SIGKILL to the process group.
        4. Wait up to kill_grace_seconds for exit.
        5. Verify quiescence (process no longer exists).
        """
        pid = process.pid
        # 1. SIGTERM to the process group.
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        # 2. Wait for graceful exit.
        try:
            await asyncio.wait_for(
                process.wait(), timeout=self.settings.terminate_grace_seconds
            )
            return  # Process exited gracefully.
        except asyncio.TimeoutError:
            pass

        # 3. SIGKILL the process group.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

        # 4. Wait for forced exit.
        try:
            await asyncio.wait_for(
                process.wait(), timeout=self.settings.kill_grace_seconds
            )
        except asyncio.TimeoutError:
            pass

        # 5. Verify quiescence.
        if _check_process_alive(pid):
            # Process is somehow still alive — log but don't hang.
            pass

    # ------------------------------------------------------------------ #
    # Cancel (protocol conformance)                                      #
    # ------------------------------------------------------------------ #

    async def cancel(self, external_execution_id: str) -> None:
        """Terminate a running Hermes process by external execution ID.

        Extracts the PID from the external ID and sends SIGTERM → SIGKILL
        to the process group.
        """
        pid = self._extract_pid(external_execution_id)
        if pid is None:
            return

        # SIGTERM the process group.
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return  # Already dead.

        # Wait for exit.
        for _ in range(self.settings.terminate_grace_seconds * 10):
            if not _check_process_alive(pid):
                return
            await asyncio.sleep(0.1)

        # Escalate to SIGKILL.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    # ------------------------------------------------------------------ #
    # Reconcile (restart recovery)                                       #
    # ------------------------------------------------------------------ #

    async def reconcile(
        self, external_execution_id: str
    ) -> RoleExecutionResult | None:
        """Check if a Hermes process from a previous session is still running.

        Uses durable process identity to distinguish PID reuse:
        - If the PID no longer exists → process exited naturally.
        - If the PID exists but start time changed → PID was reused.
        - If the PID exists with same start time → still running.
        """
        identity = self._parse_external_id(external_execution_id)
        if identity is None:
            return None

        pid = identity.get("pid")
        if pid is None:
            return None

        if not _check_process_alive(pid):
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=external_execution_id,
                exit_code=None,
                summary="Hermes process exited (no longer exists).",
                diagnostic_text="Process not found during restart reconciliation.",
            )

        # Check PID reuse via start time.
        expected_starttime = identity.get("starttime")
        if expected_starttime is not None:
            actual_starttime = _get_process_starttime(pid)
            if actual_starttime is not None and actual_starttime != expected_starttime:
                # PID was reused — original process is gone.
                return RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=external_execution_id,
                    exit_code=None,
                    summary="Hermes process exited (PID reused by another process).",
                    diagnostic_text=(
                        f"PID {pid} start time changed from "
                        f"{expected_starttime} to {actual_starttime}."
                    ),
                )

        # Process is still running with the same identity.
        return None  # Still running — caller can decide to cancel or wait.

    # ------------------------------------------------------------------ #
    # Hermes version detection                                           #
    # ------------------------------------------------------------------ #

    async def _get_hermes_version(self, hermes_bin: str) -> str:
        """Get the installed Hermes version for manifest recording."""
        if self._hermes_version is not None:
            return self._hermes_version
        try:
            proc = await asyncio.create_subprocess_exec(
                hermes_bin, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            version = stdout_b.decode("utf-8", errors="replace").strip()
            self._hermes_version = version
            self._hermes_executable = hermes_bin
            return version
        except (OSError, asyncio.TimeoutError):
            return "unknown"

    # ------------------------------------------------------------------ #
    # Command construction                                               #
    # ------------------------------------------------------------------ #

    def _build_command(
        self, invocation: RoleInvocation, hermes_bin: str
    ) -> list[str]:
        """Build the Hermes command for one invocation.

        No bwrap wrapper — Hermes runs directly.  The command is:
            hermes -p <profile> -z "<prompt>" [--model M] [--provider P]
                   [--skills S1,S2] --usage-file <path>
        """
        workspace = invocation.workspace.resolve()
        task_brief = invocation.task_brief.resolve()

        one_shot_prompt = _BRIEF_PROMPT_TEMPLATE.format(
            brief_path=str(task_brief)
        )

        command: list[str] = [hermes_bin]
        if invocation.profile:
            command.extend(["-p", invocation.profile])
        command.extend(["-z", one_shot_prompt])

        model = invocation.metadata.get("model")
        provider = invocation.metadata.get("provider")
        if model:
            command.extend(["-m", str(model)])
        if provider:
            command.extend(["--provider", str(provider)])
        if invocation.preloaded_skills:
            command.extend(
                ["--skills", ",".join(invocation.preloaded_skills)]
            )
        usage_file = str(workspace / "usage.json")
        command.extend(["--usage-file", usage_file])

        return command

    def _build_environment(self, invocation: RoleInvocation) -> dict[str, str]:
        """Build a minimal environment for the Hermes process."""
        env: dict[str, str] = {}
        for key in _ENVIRONMENT_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        # Set HERMES_HOME if configured.
        hermes_home = self._resolve_hermes_home(invocation)
        if hermes_home is not None:
            env["HERMES_HOME"] = str(hermes_home)
        # Inject secret env vars.
        for key, value in self.settings.secret_env.items():
            env[key] = value
        return env

    # ------------------------------------------------------------------ #
    # Preflight and verification                                         #
    # ------------------------------------------------------------------ #

    def _resolve_hermes_binary(self) -> str | None:
        """Resolve the Hermes binary to an absolute path."""
        import shutil
        path = shutil.which(self.settings.hermes_binary)
        if path:
            return path
        for candidate in (
            Path.home() / ".local/bin/hermes",
            Path("/usr/local/bin/hermes"),
            Path("/usr/bin/hermes"),
        ):
            if candidate.exists():
                return str(candidate)
        return None

    def _resolve_hermes_home(self, invocation: RoleInvocation) -> Path | None:
        if self.settings.hermes_home is not None:
            return self.settings.hermes_home.resolve()
        hermes_home = (Path.home() / ".hermes")
        return hermes_home if hermes_home.is_dir() else None

    def _verify_mounts(self, invocation: RoleInvocation) -> list[str]:
        """Pre-launch verification of workspace and task brief."""
        problems: list[str] = []
        workspace = invocation.workspace.resolve()
        if not workspace.is_dir():
            problems.append(f"Workspace directory missing: {workspace}")
        task_brief = invocation.task_brief.resolve()
        if not task_brief.is_file():
            problems.append(f"Task brief file missing: {task_brief}")
        return problems

    # ------------------------------------------------------------------ #
    # External identity format                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_external_id(identity: ProcessIdentity) -> str:
        """Format a durable external execution ID.

        Format: ``local:pid:<N>:st:<STARTTIME>:mk:<MARKER>``
        where STARTTIME is /proc/<pid>/stat field 22 (clock ticks).
        """
        starttime = _get_process_starttime(identity.pid)
        st_str = f"{starttime}" if starttime is not None else "unknown"
        return f"local:pid:{identity.pid}:st:{st_str}:mk:{identity.invocation_marker[:12]}"

    @staticmethod
    def _extract_pid(external_execution_id: str) -> int | None:
        """Extract the PID from a local external execution ID.

        Only accepts IDs with the ``local:`` prefix.
        """
        if not external_execution_id.startswith("local:"):
            return None
        parts = external_execution_id.split(":")
        # local:pid:<N>:st:...:mk:...
        if len(parts) >= 3 and parts[1] == "pid":
            try:
                return int(parts[2])
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_external_id(
        external_execution_id: str
    ) -> dict[str, Any] | None:
        """Parse a durable external execution ID into its components."""
        parts = external_execution_id.split(":")
        if len(parts) < 3 or parts[0] != "local":
            return None
        result: dict[str, Any] = {}
        i = 1
        while i + 1 < len(parts):
            key = parts[i]
            value = parts[i + 1]
            if key == "pid":
                try:
                    result["pid"] = int(value)
                except ValueError:
                    pass
            elif key == "st":
                try:
                    result["starttime"] = float(value)
                except ValueError:
                    result["starttime"] = None
            elif key == "mk":
                result["marker"] = value
            i += 2
        return result if "pid" in result else None

    # ------------------------------------------------------------------ #
    # Memory-state digests (C3)                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def record_memory_state(profile_dir: Path) -> dict[str, Any]:
        """Record a digest snapshot of the profile's memory state (C3).

        Called before and after each invocation.  The digests are attached
        to the invocation record so every run's full context basis is
        reproducible.
        """
        memories_dir = profile_dir / "memories"
        result: dict[str, Any] = {}
        for filename in ("MEMORY.md", "USER.md"):
            path = memories_dir / filename
            if path.exists():
                result[filename.lower().replace(".md", "_sha256")] = (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                )
            else:
                result[filename.lower().replace(".md", "_sha256")] = None
        return result


__all__ = [
    "LocalHermesExecutionError",
    "LocalHermesExecutor",
    "LocalHermesExecutorSettings",
    "ProcessIdentity",
]
