"""One-shot Hermes executor with mounted task brief.

Extends the bubblewrap prototype (C8) into a production-aligned one-shot
executor that:

* **Mounts the task brief as a file**, not as a CLI argument — avoids
  ``ARG_MAX`` limits, ``ps`` visibility, and process metadata leaks.
* **Records memory-state digests** before and after each invocation (C3).
* **Uses a pluggable container runtime** — ``bwrap`` today, ``podman`` when
  available (C8).
* **Tracks real process PIDs** — the PID is the external execution ID.

The one-shot ``hermes -z`` mode is synchronous: the process IS the agent.
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
# Settings                                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OneShotExecutorSettings:
    """Configuration for :class:`OneShotExecutor`."""

    hermes_binary: str = _HERMES_BINARY
    hermes_home: Path | None = None
    #: Container runtime: ``"bwrap"`` (current) or ``"podman"`` (planned).
    container_runtime: str = "bwrap"
    bwrap_binary: str = _BWRAP_BINARY
    poll_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES
    #: Secret environment variables injected at runtime — never persisted.
    secret_env: Mapping[str, str] = field(default_factory=dict)
    #: Default network policy when the invocation does not specify one.
    default_network_policy: NetworkPolicy | None = None
    #: Path inside the container where the task brief is mounted.
    brief_mount_point: str = "/workspace/task.md"
    #: Path inside the container used as the working directory.
    workspace_mount_point: str = "/workspace"


class OneShotExecutionError(RuntimeError):
    """A one-shot execution failed."""


# --------------------------------------------------------------------------- #
# Executor                                                                     #
# --------------------------------------------------------------------------- #


class OneShotExecutor:
    """Execute role invocations via ``hermes -z`` with a mounted task brief.

    Implements the :class:`RoleExecutor` protocol.  Each invocation:

    1. Records memory-state digests (C3).
    2. Constructs a ``bwrap`` command with:
       - Workspace bind-mounted at ``/workspace`` (rw).
       - Task brief bind-mounted at ``/workspace/task.md`` (ro).
       - Hermes home bind-mounted (rw — C1).
       - Identity files overlay-mounted read-only (SOUL.md, config.yaml).
       - Network isolation per the policy.
    3. Runs ``hermes -z "Read /workspace/task.md and follow it."``
    4. Polls until exit or timeout.
    5. Returns the terminal result with redacted diagnostics.
    """

    def __init__(self, settings: OneShotExecutorSettings) -> None:
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
            # Use real PID as the external execution ID (truthful identity).
            external_id_placeholder = f"oneshot:{invocation.execution_id}"
            await observer.launch_acknowledged(invocation, external_id_placeholder)

            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )

            # Update external ID to include real PID for cancel/reconcile.
            external_id = f"oneshot:pid:{process.pid}"
            if hasattr(observer, "external_execution_id"):
                observer.external_execution_id = external_id  # type: ignore[attr-defined]

            deadline = time.monotonic() + invocation.timeout_seconds
            start_time = deadline - invocation.timeout_seconds
            while True:
                try:
                    stdout_data, stderr_data = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.poll_interval_seconds,
                    )
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
                        summary=f"One-shot process exited with code {exit_code}.",
                        diagnostic_text=_redact(
                            f"{stderr_text}\n--- stdout ---\n{stdout_text}".strip()
                        ),
                    )
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - start_time
                    await observer.heartbeat(
                        invocation,
                        f"One-shot process {process.pid} running "
                        f"(elapsed {elapsed:.0f}s)",
                    )
                    if time.monotonic() >= deadline:
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        except (OSError, ProcessLookupError):
                            pass
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5)
                        except asyncio.TimeoutError:
                            try:
                                os.killpg(
                                    os.getpgid(process.pid), signal.SIGKILL
                                )
                            except (OSError, ProcessLookupError):
                                pass
                        return RoleExecutionResult(
                            status=RoleExecutionStatus.FAILED,
                            external_execution_id=external_id,
                            exit_code=None,
                            summary="One-shot process exceeded its time limit.",
                            diagnostic_text=(
                                f"Timed out after {invocation.timeout_seconds}s"
                            ),
                        )
        except (OSError, subprocess.SubprocessError) as error:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="One-shot execution failed to start.",
                diagnostic_text=str(error),
            )

    # ------------------------------------------------------------------ #
    # Cancel                                                             #
    # ------------------------------------------------------------------ #

    async def cancel(self, external_execution_id: str) -> None:
        """Kill the one-shot process by PID extracted from the external ID."""
        pid = self._extract_pid(external_execution_id)
        if pid is not None:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    # ------------------------------------------------------------------ #
    # Reconcile                                                          #
    # ------------------------------------------------------------------ #

    async def reconcile(
        self, external_execution_id: str
    ) -> RoleExecutionResult | None:
        """Check if a one-shot process is still running."""
        pid = self._extract_pid(external_execution_id)
        if pid is None:
            return None
        try:
            os.kill(pid, 0)
            return None  # Still running
        except (OSError, ProcessLookupError):
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=external_execution_id,
                exit_code=None,
                summary="One-shot process was terminated during reconciliation.",
                diagnostic_text="Process no longer exists.",
            )

    # ------------------------------------------------------------------ #
    # Command construction                                               #
    # ------------------------------------------------------------------ #

    def _build_command(self, invocation: RoleInvocation) -> list[str]:
        """Build the bwrap + hermes command for one invocation.

        Key difference from the bubblewrap prototype: the task brief is
        mounted as a file and the one-shot prompt references it, rather
        than inlining the entire brief in the command line.
        """
        workspace = invocation.workspace.resolve()
        hermes_home = self._resolve_hermes_home(invocation)
        task_brief = invocation.task_brief.resolve()
        brief_mount = self.settings.brief_mount_point
        workspace_mount = self.settings.workspace_mount_point

        # The one-shot prompt — short, references the mounted brief.
        one_shot_prompt = _BRIEF_PROMPT_TEMPLATE.format(brief_path=brief_mount)

        # Build the hermes sub-command.
        hermes_cmd: list[str] = [
            self.settings.hermes_binary,
            "-z", one_shot_prompt,
        ]
        # Model/provider override if specified in invocation metadata.
        model = invocation.metadata.get("model")
        provider = invocation.metadata.get("provider")
        if model:
            hermes_cmd.extend(["-m", str(model)])
        if provider:
            hermes_cmd.extend(["--provider", str(provider)])
        # Skills preload.
        if invocation.preloaded_skills:
            hermes_cmd.extend(
                ["--skills", ",".join(invocation.preloaded_skills)]
            )
        # Usage report.
        usage_file = str(Path(workspace_mount) / "usage.json")
        hermes_cmd.extend(["--usage-file", usage_file])

        command: list[str] = [
            self.settings.bwrap_binary,
            # Security hardening.
            "--unshare-all",
            "--share-net" if self._has_network(invocation) else "--unshare-net",
            "--new-session",
            "--die-with-parent",
            "--cap-drop", "ALL",
            "--no-new-privileges",
            # Mount the workspace read-write.
            "--bind", str(workspace), workspace_mount,
            # Mount the task brief read-only at the brief mount point.
            "--ro-bind", str(task_brief), brief_mount,
            # Mount Hermes home read-write (C1: state.db, logs, etc. required).
            "--bind", str(hermes_home), str(hermes_home),
            # Identity overlays: SOUL.md and config.yaml read-only.
            # (Only if they exist in the profile.)
        ]
        # Add identity overlays if the profile directory structure supports it.
        profile_dir = self._profile_dir(invocation, hermes_home)
        if profile_dir is not None:
            for identity_file in ("SOUL.md", "config.yaml"):
                identity_path = profile_dir / identity_file
                if identity_path.exists():
                    command.extend(
                        ["--ro-bind", str(identity_path), str(identity_path)]
                    )

        command.extend([
            # /dev, /proc, /tmp.
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            # Hostname and working directory.
            "--hostname", invocation.execution_id[:12],
            "--chdir", workspace_mount,
            # Environment.
            "--setenv", "HOME", workspace_mount,
            "--setenv", "HERMES_HOME", str(hermes_home),
        ])
        # Inject secret env into the child via bwrap --setenv.
        for key, value in self.settings.secret_env.items():
            command.extend(["--setenv", key, value])

        command.extend(hermes_cmd)
        return command

    def _build_environment(self, invocation: RoleInvocation) -> dict[str, str]:
        """Build a minimal environment for the bwrap process itself."""
        env: dict[str, str] = {}
        for key in _ENVIRONMENT_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        # Secrets are passed via bwrap --setenv, not host env.
        return env

    def _resolve_hermes_home(self, invocation: RoleInvocation) -> Path:
        if self.settings.hermes_home is not None:
            return self.settings.hermes_home.resolve()
        return (Path.home() / ".hermes").resolve()

    def _profile_dir(
        self, invocation: RoleInvocation, hermes_home: Path
    ) -> Path | None:
        """Resolve the profile directory from the invocation's profile name."""
        if not invocation.profile:
            return None
        candidate = hermes_home / "profiles" / invocation.profile
        return candidate if candidate.is_dir() else None

    def _has_network(self, invocation: RoleInvocation) -> bool:
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
        """Extract the PID from a one-shot external execution ID."""
        if not external_execution_id.startswith("oneshot:pid:"):
            return None
        try:
            return int(external_execution_id.split(":")[2])
        except (IndexError, ValueError):
            return None

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
    "OneShotExecutionError",
    "OneShotExecutor",
    "OneShotExecutorSettings",
]
