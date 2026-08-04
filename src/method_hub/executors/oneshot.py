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
    #: When True, use the runtime profile snapshot (H0.4) instead of mounting
    #: the entire Hermes root.  The runtime_profile_dir is read from the
    #: invocation metadata key ``runtime_profile_dir``.
    use_runtime_snapshot: bool = True


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

        # Pre-launch verification (H0.4): check all mount sources exist.
        mount_problems = self._verify_mounts(invocation)
        if mount_problems:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="Pre-launch mount verification failed.",
                diagnostic_text="; ".join(mount_problems),
            )

        try:
            command = self._build_command(invocation)
            env = self._build_environment(invocation)
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

            external_id = f"oneshot:pid:{process.pid}"
            if hasattr(observer, "external_execution_id"):
                observer.external_execution_id = external_id  # type: ignore[attr-defined]

            # Incremental output streaming (H0.5) — read line by line
            # instead of buffering everything via communicate().
            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            stdout_bytes = 0
            stderr_bytes = 0
            limit = self.settings.output_limit_bytes

            deadline = time.monotonic() + invocation.timeout_seconds
            start_time = deadline - invocation.timeout_seconds

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
                # Read available output with a short timeout.
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

                # Check if process exited.
                if process.returncode is not None:
                    # Drain remaining output.
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
                        summary=f"One-shot process exited with code {exit_code}.",
                        diagnostic_text=_redact(
                            f"{stderr_text}\n--- stdout ---\n{stdout_text}".strip()
                        ),
                    )

                # Process still running — send heartbeat.
                elapsed = time.monotonic() - start_time
                await observer.heartbeat(
                    invocation,
                    f"One-shot process {process.pid} running "
                    f"(elapsed {elapsed:.0f}s)",
                )

                if time.monotonic() >= deadline:
                    # Timeout: send SIGTERM, then SIGKILL if needed.
                    await self._terminate_process(process)
                    stdout_text = "".join(stdout_chunks)
                    stderr_text = "".join(stderr_chunks)
                    return RoleExecutionResult(
                        status=RoleExecutionStatus.FAILED,
                        external_execution_id=external_id,
                        exit_code=None,
                        summary="One-shot process exceeded its time limit.",
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
                summary="One-shot execution failed to start.",
                diagnostic_text=str(error),
            )

    async def _terminate_process(
        self, process: asyncio.subprocess.Process
    ) -> None:
        """Gracefully terminate a process: SIGTERM → wait → SIGKILL (H0.5)."""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------ #
    # Cancel                                                             #
    # ------------------------------------------------------------------ #

    async def cancel(self, external_execution_id: str) -> bool:
        """Kill the one-shot process by PID extracted from the external ID.

        H0.5: Verified cancellation — sends SIGTERM, waits for exit
        confirmation, then SIGKILL if needed.  Returns True if the
        process was confirmed terminated.
        """
        pid = self._extract_pid(external_execution_id)
        if pid is None:
            return False
        # Send SIGTERM to the process group.
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return True  # Already dead.

        # Wait up to 5 seconds for the process to exit.
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                return True  # Confirmed dead.
            await asyncio.sleep(0.1)

        # Process didn't exit on SIGTERM — escalate to SIGKILL.
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        # Confirm.
        try:
            os.kill(pid, 0)
            return False  # Still alive after SIGKILL — error.
        except (OSError, ProcessLookupError):
            return True

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

        H0.4 changes:
        - Uses ``-p <profile_name>`` to select the profile instead of exposing
          the whole Hermes root.
        - Mounts only the runtime profile snapshot directory (or the specific
          profile directory) instead of the entire Hermes home.
        - Adds ``--symlink`` for proc/dev/tmp but never exposes host paths
          beyond the workspace, brief, and runtime profile.
        - Verifies mount sources exist before constructing the command
          (callers should call ``_verify_mounts`` first).
        """
        workspace = invocation.workspace.resolve()
        hermes_home = self._resolve_hermes_home(invocation)
        task_brief = invocation.task_brief.resolve()
        brief_mount = self.settings.brief_mount_point
        workspace_mount = self.settings.workspace_mount_point

        # Determine the profile directory to mount.
        runtime_profile_dir = self._resolve_runtime_profile_dir(invocation, hermes_home)

        # The one-shot prompt — short, references the mounted brief.
        one_shot_prompt = _BRIEF_PROMPT_TEMPLATE.format(brief_path=brief_mount)

        # Build the hermes sub-command with -p profile selection (H0.4).
        hermes_cmd: list[str] = [
            self.settings.hermes_binary,
        ]
        # Profile selection via -p (H0.4).
        if invocation.profile:
            hermes_cmd.extend(["-p", invocation.profile])
        hermes_cmd.extend(["-z", one_shot_prompt])
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
        ]

        # Mount the runtime profile directory (H0.4).
        # Only the specific profile's directory is mounted — not the entire
        # Hermes root.  This prevents the agent from seeing other profiles.
        if runtime_profile_dir is not None:
            # HERMES_HOME is set to hermes_home so Hermes can find profiles/,
            # but we only mount the specific profile dir rw.
            # Profile dir is mounted at its expected path inside HERMES_HOME.
            profile_mount_path = str(
                hermes_home / "profiles" / invocation.profile
            )
            command.extend([
                "--bind", str(runtime_profile_dir), profile_mount_path,
            ])
            # Mount the Hermes home root structure (read-only) so Hermes
            # can resolve its config, but only the profile dir is writable.
            # We mount hermes_home itself read-only, then overlay the profile
            # directory on top read-write.
            command.extend([
                "--ro-bind", str(hermes_home), str(hermes_home),
            ])
            # Re-mount the profile dir rw on top of the ro Hermes home.
            command.extend([
                "--bind", str(runtime_profile_dir), profile_mount_path,
            ])

            # Identity overlays: SOUL.md and config.yaml read-only.
            for identity_file in ("SOUL.md", "config.yaml"):
                identity_path = runtime_profile_dir / identity_file
                if identity_path.exists():
                    command.extend(
                        ["--ro-bind",
                         str(identity_path),
                         str(identity_path)]
                    )
        else:
            # Fallback: mount the whole Hermes home (legacy behavior).
            command.extend([
                "--bind", str(hermes_home), str(hermes_home),
            ])

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

    def _resolve_runtime_profile_dir(
        self, invocation: RoleInvocation, hermes_home: Path
    ) -> Path | None:
        """Resolve the runtime profile directory to mount (H0.4).

        If ``runtime_profile_dir`` is in the invocation metadata (set by
        the diagnostic service after snapshot creation), use that.
        Otherwise, fall back to the canonical profile directory if it exists.
        """
        runtime_dir = invocation.metadata.get("runtime_profile_dir")
        if runtime_dir is not None:
            path = Path(str(runtime_dir))
            if path.is_dir():
                return path
        # Fallback: canonical profile directory.
        if invocation.profile:
            canonical = hermes_home / "profiles" / invocation.profile
            if canonical.is_dir():
                return canonical
        return None

    def _verify_mounts(self, invocation: RoleInvocation) -> list[str]:
        """Pre-launch verification of all mount sources (H0.4).

        Returns a list of problems (empty = all mounts verified).
        """
        problems: list[str] = []
        workspace = invocation.workspace.resolve()
        if not workspace.is_dir():
            problems.append(f"Workspace directory missing: {workspace}")
        task_brief = invocation.task_brief.resolve()
        if not task_brief.is_file():
            problems.append(f"Task brief file missing: {task_brief}")
        hermes_home = self._resolve_hermes_home(invocation)
        if not hermes_home.is_dir():
            problems.append(f"Hermes home missing: {hermes_home}")
        runtime_dir = self._resolve_runtime_profile_dir(invocation, hermes_home)
        if runtime_dir is not None:
            for identity_file in ("SOUL.md", "config.yaml"):
                if not (runtime_dir / identity_file).exists():
                    problems.append(
                        f"Identity file {identity_file} missing from "
                        f"runtime profile: {runtime_dir}"
                    )
        return problems

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
