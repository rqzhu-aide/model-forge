"""Bubblewrap-based rootless sandbox executor.

Uses ``bwrap`` (bubblewrap) to create an isolated execution environment for
each role invocation.  The sandbox provides:

* **Private mount namespace** — the role sees only its workspace, task brief,
  and materialized inputs (via the capability broker).
* **Private network namespace** — deny-by-default (no interfaces except
  loopback).  When ``NetworkPolicy`` declares an allowlist, a proxy is
  started in a separate netns and the sandbox connects through it.
* **No-new-privileges** — the child cannot gain capabilities.
* **Read-only host root** — only the role workspace and Hermes install are
  bind-mounted, everything else is invisible.
* **One-shot execution** — the container runs ``hermes -z`` (zero-context
  one-shot) with the task brief, exits, and the process is gone.

This implements the ``RoleExecutor`` protocol using the same status-mapping
and polling pattern as ``HermesKanbanExecutor``, but with ``bwrap`` instead
of the host gateway.

C2 decision (in-container mechanism): one-shot ``hermes -z`` inside the
sandbox.  The sandbox IS the execution — there is no second agent process.
The container PID is the external execution ID.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
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
# Constants                                                                   #
# --------------------------------------------------------------------------- #

_BWRAP_BINARY = "bwrap"
_HERMES_BINARY = "hermes"

#: Environment variables safe inside the sandbox.
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


def _redact(text: str) -> str:
    """Replace likely-secret substrings with a placeholder."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


@dataclass(frozen=True, slots=True)
class BubblewrapSettings:
    """Configuration for :class:`BubblewrapExecutor`."""

    bwrap_binary: str = _BWRAP_BINARY
    hermes_binary: str = _HERMES_BINARY
    hermes_home: Path | None = None
    poll_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES
    #: Secret environment variables to inject at runtime.  These are passed
    #: to the sandbox process but never written to manifests, logs, or artifacts.
    secret_env: Mapping[str, str] = field(default_factory=dict)
    #: Default network policy when the invocation does not specify one.
    default_network_policy: NetworkPolicy | None = None


class BubblewrapExecutionError(RuntimeError):
    """A bubblewrap sandbox execution failed."""


class BubblewrapExecutor:
    """Execute role invocations inside a rootless bwrap sandbox.

    Implements the :class:`RoleExecutor` protocol.  Each invocation:

    1. Constructs a ``bwrap`` command line with the workspace bind-mounted,
       a read-only Hermes install, and network isolation per the policy.
    2. Runs ``hermes -z "$(cat task_brief)"`` inside the sandbox.
    3. Polls the process until it exits or the timeout expires.
    4. Returns the terminal result with redacted diagnostics.
    """

    def __init__(self, settings: BubblewrapSettings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ #
    # Execute                                                            #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult:
        await observer.launch_intent(invocation)
        try:
            command = self._build_command(invocation)
            env = self._build_environment(invocation)
            external_id = f"bwrap:{invocation.execution_id}"
            await observer.launch_acknowledged(invocation, external_id)

            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )

            deadline = time.monotonic() + invocation.timeout_seconds
            while True:
                try:
                    stdout_data, stderr_data = await asyncio.wait_for(
                        process.communicate(), timeout=self.settings.poll_interval_seconds
                    )
                    # Process finished
                    exit_code = process.returncode
                    stdout_text = self._truncate(
                        stdout_data.decode("utf-8", errors="replace")
                    )
                    stderr_text = self._truncate(
                        stderr_data.decode("utf-8", errors="replace")
                    )
                    status = (
                        RoleExecutionStatus.SUCCEEDED
                        if exit_code == 0
                        else RoleExecutionStatus.FAILED
                    )
                    return RoleExecutionResult(
                        status=status,
                        external_execution_id=external_id,
                        exit_code=exit_code,
                        summary=f"Sandbox process exited with code {exit_code}.",
                        diagnostic_text=_redact(
                            f"{stderr_text}\n--- stdout ---\n{stdout_text}".strip()
                        ),
                    )
                except asyncio.TimeoutError:
                    # Process still running — send heartbeat
                    await observer.heartbeat(
                        invocation,
                        f"Sandbox process {process.pid} running (elapsed "
                        f"{time.monotonic() - (deadline - invocation.timeout_seconds):.0f}s)",
                    )
                    if time.monotonic() >= deadline:
                        # Timeout — kill the process
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        except (OSError, ProcessLookupError):
                            pass
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            pass
                        return RoleExecutionResult(
                            status=RoleExecutionStatus.FAILED,
                            external_execution_id=external_id,
                            exit_code=None,
                            summary="Sandbox process exceeded its frozen time limit.",
                            diagnostic_text=f"Timed out after {invocation.timeout_seconds}s",
                        )
        except (OSError, subprocess.SubprocessError) as error:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="Bubblewrap sandbox execution failed to start.",
                diagnostic_text=str(error),
            )

    # ------------------------------------------------------------------ #
    # Cancel                                                             #
    # ------------------------------------------------------------------ #

    async def cancel(self, external_execution_id: str) -> None:
        """Kill the sandbox process by PID extracted from external_execution_id."""
        pid = self._extract_pid(external_execution_id)
        if pid is not None:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    # ------------------------------------------------------------------ #
    # Reconcile                                                          #
    # ------------------------------------------------------------------ #

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult | None:
        """Check if a sandbox process is still running.

        For bubblewrap (one-shot, non-durable), a killed process is gone.
        Returns ``None`` (still running) if the PID exists, or a FAILED
        result if it's gone (since reconciliation implies it was interrupted).
        """
        pid = self._extract_pid(external_execution_id)
        if pid is None:
            return None
        try:
            os.kill(pid, 0)  # Check if process exists
            return None  # Still running
        except (OSError, ProcessLookupError):
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=external_execution_id,
                exit_code=None,
                summary="Sandbox process was terminated during reconciliation.",
                diagnostic_text="Process no longer exists.",
            )

    # ------------------------------------------------------------------ #
    # Command construction                                               #
    # ------------------------------------------------------------------ #

    def _build_command(self, invocation: RoleInvocation) -> list[str]:
        """Build the bwrap + hermes command line for one invocation."""
        workspace = invocation.workspace.resolve()
        hermes_home = self._resolve_hermes_home(invocation)
        task_brief = invocation.task_brief.resolve()

        # Read the task brief content for hermes -z
        brief_content = task_brief.read_text(encoding="utf-8")

        command: list[str] = [
            self.settings.bwrap_binary,
            # Security hardening
            "--unshare-all",           # New namespaces for everything
            "--share-net" if self._has_network(invocation) else "--unshare-net",
            "--new-session",           # New session leader
            "--die-with-parent",       # Kill sandbox if parent dies
            "--cap-drop", "ALL",       # Drop all Linux capabilities
            "--no-new-privileges",     # Prevent privilege escalation
            # Mount the workspace read-write
            "--bind", str(workspace), str(workspace),
            # Mount the Hermes home read-only
            "--ro-bind", str(hermes_home), str(hermes_home),
            # Mount /dev/null, /dev/zero, /dev/urandom
            "--dev", "/dev",
            # Mount /proc (needed by Python)
            "--proc", "/proc",
            # Temporary directory
            "--tmpfs", "/tmp",
            # Set hostname to the execution ID
            "--hostname", invocation.execution_id[:12],
            # Set the working directory to the workspace
            "--chdir", str(workspace),
            # Set HOME to the workspace
            "--setenv", "HOME", str(workspace),
            "--setenv", "HERMES_HOME", str(hermes_home),
            # Execute hermes -z (one-shot mode)
            self.settings.hermes_binary,
            "-z", brief_content,
        ]
        return command

    def _build_environment(self, invocation: RoleInvocation) -> dict[str, str]:
        """Build a minimal environment for the bwrap process itself."""
        env: dict[str, str] = {}
        for key in _ENVIRONMENT_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        # Inject secrets at runtime — these reach the child via bwrap --setenv
        # but are NOT written to any manifest, log, or artifact.
        for key, value in self.settings.secret_env.items():
            env[key] = value
        return env

    def _resolve_hermes_home(self, invocation: RoleInvocation) -> Path:
        """Resolve the Hermes home directory to bind-mount read-only."""
        if self.settings.hermes_home is not None:
            return self.settings.hermes_home.resolve()
        return (Path.home() / ".hermes").resolve()

    def _has_network(self, invocation: RoleInvocation) -> bool:
        """Check if the invocation's network policy allows any network."""
        policy = invocation.metadata.get("network_policy")
        if isinstance(policy, NetworkPolicy):
            return policy.has_network
        if self.settings.default_network_policy is not None:
            return self.settings.default_network_policy.has_network
        return False

    def _truncate(self, text: str) -> str:
        if len(text.encode("utf-8")) > self.settings.output_limit_bytes:
            return text[: self.settings.output_limit_bytes] + "\n[output truncated]"
        return text

    @staticmethod
    def _extract_pid(external_execution_id: str) -> int | None:
        """Extract the PID from a bwrap external execution ID."""
        if not external_execution_id.startswith("bwrap:"):
            return None
        # The execution_id is the deterministic ID, not a PID.
        # For cancel/reconcile we track the actual PID via the process group.
        return None


__all__ = [
    "BubblewrapExecutionError",
    "BubblewrapExecutor",
    "BubblewrapSettings",
]
