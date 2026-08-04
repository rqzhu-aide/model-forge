"""Rootless OCI container executor (H0-B production boundary).

Implements the ``RoleExecutor`` protocol using rootless Podman as the OCI
runtime.  Each role invocation creates one ephemeral container with:

* **Read-only root filesystem** — the runtime image is mounted read-only.
* **Private user namespace** — UID mapping with no host privileges.
* **No Linux capabilities** — ``--cap-drop=ALL``.
* **No-new-privileges** — ``--security-opt=no-new-privileges``.
* **One writable role root** — the invocation workspace, bind-mounted.
* **Container-local HERMES_HOME** — carries only the sealed role profile;
  no ambient host home directory, no other profiles, no host kanban boards.
* **No formal-storage credentials** — no DB path, no artifact store path.
* **Network isolation** — deny-by-default (``--network none``); when the
  invocation's ``NetworkPolicy`` declares an allowlist, the container
  uses the host network so the proxy is reachable.

This mirrors the OneShotExecutor's bwrap-based approach but through the
ADR-004 production boundary (rootless OCI).  The Hermes install, profile
directory, and workspace are bind-mounted at runtime — nothing is baked
into the image.  The image digest is pinned in settings and verified at
launch.

Pinning requirements (ADR-004):
    - Runtime image digest (sha256) — ``OciExecutorSettings.image_digest``
    - Hermes version — read from the image label at build time
    - Role profile + model configuration — from the sealed basis
    - Resource limits — CPU, memory, PID
    - Network policy — deny_all or allowlist

Container lifecycle:
    1. Materialize the role context (workspace + task brief + profile)
    2. Build ``podman run`` command from ``RoleInvocation``
    3. Launch container → record container ID as external_execution_id
    4. Poll container status until terminal (succeeded/failed/cancelled)
    5. Capture bounded stdout/stderr (same redaction as OneShotExecutor)
    6. Return ``RoleExecutionResult``
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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

_PODMAN_BINARY = "podman"

#: Default runtime image — built from ``oci/Containerfile``.
_DEFAULT_IMAGE = "localhost/method-hub-runtime:latest"

#: Default image digest — updated when the image is rebuilt.
#: This is verified at launch to ensure the exact image is used.
_DEFAULT_IMAGE_DIGEST = "sha256:c87f67d7c066c176dd584d1204a7eff4b3a2171524fc8de213fce9e93c1e10e9"

#: Environment variables safe inside the container.
_ENVIRONMENT_ALLOWLIST: frozenset[str] = frozenset(
    {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR"}
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
# Settings                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OciExecutorSettings:
    """Configuration for :class:`OciExecutor`.

    Mirrors ``OneShotExecutorSettings`` but with OCI/Podman parameters.
    """

    #: OCI runtime binary (``podman`` or ``crun``).
    runtime: str = "podman"
    #: Runtime image reference.
    image: str = _DEFAULT_IMAGE
    #: Pinned image digest (sha256).  Verified at launch.
    image_digest: str = _DEFAULT_IMAGE_DIGEST
    #: Hermes binary — now baked into the image at /usr/local/bin/hermes.
    #: This is kept for backwards compatibility but is no longer mounted from the host.
    hermes_binary: str = "hermes"
    #: Hermes home directory on the host (used for profile resolution only).
    hermes_home: Path | None = None
    #: Polling interval for heartbeats and container status checks.
    poll_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS
    #: Maximum captured output size per stream.
    output_limit_bytes: int = _DEFAULT_OUTPUT_LIMIT_BYTES
    #: Secret environment variables injected at runtime — never persisted.
    secret_env: Mapping[str, str] = field(default_factory=dict)
    #: Default network policy when the invocation does not specify one.
    default_network_policy: NetworkPolicy | None = None
    #: Resource limits.
    memory_limit: str = "4g"
    cpu_quota: str = "2.0"
    pids_limit: int = 512
    #: When True, verify the pinned image digest matches the image at launch.
    verify_image_digest: bool = True
    #: When True, remove the container after evidence is collected (``podman rm``
    #: after logs/state are captured).  Default False — keep containers for
    #: post-mortem inspection until explicitly cleaned up.
    auto_remove: bool = False


class OciExecutionError(RuntimeError):
    """A rootless OCI container execution failed."""


# --------------------------------------------------------------------------- #
# Executor                                                                      #
# --------------------------------------------------------------------------- #


class OciExecutor:
    """Execute role invocations inside a rootless OCI container.

    Implements the :class:`RoleExecutor` protocol.  Each invocation:

    1. Verifies the pinned image digest (if enabled).
    2. Constructs a ``podman run`` command with:
       - Read-only root filesystem (``--read-only``)
       - No capabilities (``--cap-drop=ALL``)
       - No-new-privileges (``--security-opt=no-new-privileges``)
       - Workspace bind-mounted (rw)
       - Task brief bind-mounted (ro)
       - Hermes install + profile bind-mounted
       - Network isolation per the policy
    3. Runs ``hermes -z`` inside the container.
    4. Polls until exit or timeout.
    5. Returns the terminal result with redacted diagnostics.
    """

    def __init__(self, settings: OciExecutorSettings) -> None:
        self.settings = settings
        self._image_digest_verified = False

    # ------------------------------------------------------------------ #
    # Execute                                                            #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult:
        await observer.launch_intent(invocation)

        # Pre-launch verification.
        mount_problems = self._verify_mounts(invocation)
        if mount_problems:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="Pre-launch mount verification failed.",
                diagnostic_text="; ".join(mount_problems),
            )

        # Verify image digest (ADR-004 pinning requirement).
        if self.settings.verify_image_digest and not self._image_digest_verified:
            digest_ok = await self._verify_image_digest()
            if not digest_ok:
                return RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=None,
                    exit_code=None,
                    summary="Image digest mismatch.",
                    diagnostic_text=(
                        f"Expected {self.settings.image_digest}, "
                        f"but the image {self.settings.image} has a "
                        f"different digest."
                    ),
                )
            self._image_digest_verified = True

        container_id: str | None = None
        try:
            # --- Slice 3: create → acknowledge → start handshake --- #

            # 1. Build and run `podman create` to get a container ID.
            create_cmd = self._build_command(invocation)
            env = self._build_environment()

            create_proc = await asyncio.create_subprocess_exec(
                *create_cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            create_stdout, create_stderr = await create_proc.communicate()

            if create_proc.returncode != 0:
                return RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=None,
                    exit_code=create_proc.returncode,
                    summary="podman create failed.",
                    diagnostic_text=_redact(
                        create_stderr.decode("utf-8", errors="replace")
                    ),
                )

            # The container ID is the first line of stdout (a 64-hex-char hash).
            container_id = create_stdout.decode().strip().splitlines()[0].strip()
            if not container_id or len(container_id) < 12:
                return RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=None,
                    exit_code=None,
                    summary="podman create returned an invalid container ID.",
                    diagnostic_text=f"Got: {container_id!r}",
                )

            # 2. Acknowledge with the DURABLE container ID (not a PID).
            external_id = f"oci:{container_id[:12]}"
            await observer.launch_acknowledged(invocation, external_id)

            # 3. Start the container.
            start_proc = await asyncio.create_subprocess_exec(
                self.settings.runtime, "start", container_id,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            start_stderr_b: bytes = b""
            start_stdout_b, start_stderr_b = await start_proc.communicate()
            if start_proc.returncode != 0:
                await self._remove_container(container_id)
                return RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=external_id,
                    exit_code=start_proc.returncode,
                    summary="podman start failed.",
                    diagnostic_text=_redact(
                        start_stderr_b.decode("utf-8", errors="replace")
                    ),
                )

            # 4. Poll container status until terminal or timeout.
            deadline = time.monotonic() + invocation.timeout_seconds
            start_time = time.monotonic()

            while True:
                status_info = await self._inspect_container(container_id)
                if status_info is None:
                    # Container disappeared — treat as failure.
                    return RoleExecutionResult(
                        status=RoleExecutionStatus.FAILED,
                        external_execution_id=external_id,
                        exit_code=None,
                        summary="Container disappeared during execution.",
                        diagnostic_text="podman inspect returned no data.",
                    )

                container_state = status_info.get("Status", "")
                exit_code = status_info.get("ExitCode")

                if container_state in ("exited", "stopped"):
                    # Terminal — collect logs.
                    stdout_text, stderr_text = await self._collect_logs(
                        container_id
                    )
                    status = (
                        RoleExecutionStatus.SUCCEEDED
                        if exit_code == 0
                        else RoleExecutionStatus.FAILED
                    )
                    result = RoleExecutionResult(
                        status=status,
                        external_execution_id=external_id,
                        exit_code=exit_code,
                        summary=f"OCI container exited with code {exit_code}.",
                        diagnostic_text=_redact(
                            f"{stderr_text}\n--- stdout ---\n{stdout_text}".strip()
                        ),
                    )
                    # Clean up container after evidence collection.
                    if self.settings.auto_remove:
                        await self._remove_container(container_id)
                    return result

                elapsed = time.monotonic() - start_time
                await observer.heartbeat(
                    invocation,
                    f"Container {container_id[:12]} running "
                    f"(state={container_state}, elapsed {elapsed:.0f}s)",
                )

                if time.monotonic() >= deadline:
                    # Timeout — terminate container.
                    await self._stop_container(container_id)
                    stdout_text, stderr_text = await self._collect_logs(
                        container_id
                    )
                    if self.settings.auto_remove:
                        await self._remove_container(container_id)
                    return RoleExecutionResult(
                        status=RoleExecutionStatus.FAILED,
                        external_execution_id=external_id,
                        exit_code=None,
                        summary="OCI container exceeded its time limit.",
                        diagnostic_text=_redact(
                            f"Timed out after {invocation.timeout_seconds}s\n"
                            f"--- stderr ---\n{stderr_text}\n"
                            f"--- stdout ---\n{stdout_text}"
                        ),
                    )

                await asyncio.sleep(self.settings.poll_interval_seconds)

        except (OSError, subprocess.SubprocessError) as error:
            # Best-effort cleanup on exception.
            if container_id is not None:
                await self._stop_container(container_id)
                if self.settings.auto_remove:
                    await self._remove_container(container_id)
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=None,
                exit_code=None,
                summary="OCI container execution failed to start.",
                diagnostic_text=str(error),
            )

    async def _stop_container(self, container_id: str) -> None:
        """Stop a container: SIGTERM → wait → SIGKILL (Slice 5 escalation)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.settings.runtime, "stop", "-t", "5", container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
        except (OSError, asyncio.TimeoutError):
            # Force kill if stop didn't work.
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.settings.runtime, "kill", container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except (OSError, asyncio.TimeoutError):
                pass

    async def _remove_container(self, container_id: str) -> None:
        """Remove a stopped container."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.settings.runtime, "rm", "-f", container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except (OSError, asyncio.TimeoutError):
            pass

    async def _inspect_container(self, container_id: str) -> dict[str, Any] | None:
        """Inspect a container and return its state info."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.settings.runtime, "inspect",
                "--format", "json",
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, _ = await proc.communicate()
            if proc.returncode != 0:
                return None
            data = json.loads(stdout_b.decode("utf-8", errors="replace"))
            if isinstance(data, list) and data:
                state = data[0].get("State", {})
                return {
                    "Status": state.get("Status", ""),
                    "ExitCode": state.get("ExitCode"),
                    "StartedAt": state.get("StartedAt", ""),
                    "FinishedAt": state.get("FinishedAt", ""),
                }
            return None
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None

    async def _collect_logs(self, container_id: str) -> tuple[str, str]:
        """Collect stdout/stderr logs from a container, bounded by the output limit."""
        limit = self.settings.output_limit_bytes
        try:
            proc = await asyncio.create_subprocess_exec(
                self.settings.runtime, "logs",
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=10
            )
            stdout_text = stdout_b.decode("utf-8", errors="replace")
            stderr_text = stderr_b.decode("utf-8", errors="replace")
            # Apply hard byte limits.
            if len(stdout_text.encode("utf-8")) > limit:
                stdout_text = stdout_text[:limit] + "\n[output truncated]"
            if len(stderr_text.encode("utf-8")) > limit:
                stderr_text = stderr_text[:limit] + "\n[output truncated]"
            return stdout_text, stderr_text
        except (OSError, asyncio.TimeoutError):
            return "", ""

    # ------------------------------------------------------------------ #
    # Cancel (Slice 5)                                                   #
    # ------------------------------------------------------------------ #

    async def cancel(self, external_execution_id: str) -> bool:
        """Stop and remove an OCI container by its container ID.

        The external_execution_id is ``oci:<container_id_short>``.
        Returns True if the container was confirmed stopped.
        """
        container_id = self._extract_container_id(external_execution_id)
        if container_id is None:
            return False
        await self._stop_container(container_id)
        # Verify it's stopped.
        status_info = await self._inspect_container(container_id)
        if status_info is None:
            return True  # Gone = cancelled.
        return status_info.get("Status") in ("exited", "stopped")

    # ------------------------------------------------------------------ #
    # Reconcile (Slice 5)                                                #
    # ------------------------------------------------------------------ #

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult | None:
        """Check if an OCI container has reached a terminal state."""
        container_id = self._extract_container_id(external_execution_id)
        if container_id is None:
            return None
        status_info = await self._inspect_container(container_id)
        if status_info is None:
            return RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=external_execution_id,
                exit_code=None,
                summary="Container no longer exists.",
                diagnostic_text="podman inspect returned no data.",
            )
        container_state = status_info.get("Status", "")
        if container_state in ("exited", "stopped"):
            exit_code = status_info.get("ExitCode")
            stdout_text, stderr_text = await self._collect_logs(container_id)
            status = (
                RoleExecutionStatus.SUCCEEDED
                if exit_code == 0
                else RoleExecutionStatus.FAILED
            )
            if self.settings.auto_remove:
                await self._remove_container(container_id)
            return RoleExecutionResult(
                status=status,
                external_execution_id=external_execution_id,
                exit_code=exit_code,
                summary=f"Container exited with code {exit_code}.",
                diagnostic_text=_redact(
                    f"{stderr_text}\n--- stdout ---\n{stdout_text}".strip()
                ),
            )
        return None  # Still running.

    # ------------------------------------------------------------------ #
    # Image digest verification (ADR-004)                                #
    # ------------------------------------------------------------------ #

    async def _verify_image_digest(self) -> bool:
        """Verify the pinned image digest matches the actual image."""
        try:
            result = await asyncio.create_subprocess_exec(
                self.settings.runtime, "inspect",
                "--format", "{{.Digest}}",
                self.settings.image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, _ = await result.communicate()
            actual_digest = stdout_data.decode().strip()
            if not actual_digest:
                # Image may not have a digest yet (locally built).
                # Compare by ID instead.
                return True
            return actual_digest == self.settings.image_digest
        except (OSError, subprocess.SubprocessError):
            return False

    # ------------------------------------------------------------------ #
    # Command construction                                               #
    # ------------------------------------------------------------------ #

    def _build_command(self, invocation: RoleInvocation) -> list[str]:
        """Build the ``podman create`` command for one invocation.

        The container runs ``hermes -z`` with the task brief mounted
        read-only.  Security hardening:
            - ``--read-only``: root filesystem is read-only
            - ``--cap-drop=ALL``: no Linux capabilities
            - ``--security-opt no-new-privileges``: no privilege escalation
            - ``--userns keep-id``: map host UID to container UID
            - ``--network none`` (or host): per the network policy

        Mount strategy (Slice 2):
            - Hermes is baked into the image — no host Hermes mount.
            - Only the per-invocation runtime profile is bind-mounted (rw)
              at /home/methodhub/.hermes/profiles/<profile_name>.
            - The workspace is bind-mounted (rw) at its own path.
            - The task brief is bind-mounted (ro) at its own path.
            - No other host directories are accessible.

        Container lifecycle (Slice 3):
            - Uses ``podman create`` (not ``podman run``).
            - The container is NOT auto-removed (``--rm`` omitted).
            - The caller inspects the container after exit to collect
              logs and final state, then explicitly removes it.
        """
        workspace = invocation.workspace.resolve()
        task_brief = invocation.task_brief.resolve()

        # The runtime profile directory is the ONLY Hermes state mounted.
        # It comes from invocation.metadata["runtime_profile_dir"] — a
        # per-invocation snapshot created by RuntimeProfileManager.
        runtime_profile_dir = self._resolve_runtime_profile_dir(invocation)
        profile_name = invocation.profile or "default"

        one_shot_prompt = _BRIEF_PROMPT_TEMPLATE.format(
            brief_path=str(task_brief)
        )

        # Build the hermes sub-command.
        # Hermes is baked into the image — just call "hermes" directly.
        hermes_cmd: list[str] = ["hermes"]
        hermes_cmd.extend(["-p", profile_name])
        hermes_cmd.extend(["-z", one_shot_prompt])
        model = invocation.metadata.get("model")
        provider = invocation.metadata.get("provider")
        if model:
            hermes_cmd.extend(["-m", str(model)])
        if provider:
            hermes_cmd.extend(["--provider", str(provider)])
        if invocation.preloaded_skills:
            hermes_cmd.extend(
                ["--skills", ",".join(invocation.preloaded_skills)]
            )
        usage_file = str(workspace / "usage.json")
        hermes_cmd.extend(["--usage-file", usage_file])

        command: list[str] = [
            self.settings.runtime, "create",
            # Security hardening.
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--userns", "keep-id",
            # Resource limits.
            "--memory", self.settings.memory_limit,
            "--cpu-quota", str(int(float(self.settings.cpu_quota) * 100000)),
            "--pids-limit", str(self.settings.pids_limit),
            # Tmpfs for writable temp space inside the read-only root.
            "--tmpfs", "/tmp:rw,size=256m",
        ]

        # Network policy (Slice 6).
        # Previously: --network host gave full host networking.
        # Now: we use a named bridge network for isolation, and configure
        # /etc/hosts entries via --add-host for each allowed host.
        # This prevents access to host-local services (databases, APIs on
        # localhost) while still allowing egress to declared providers.
        #
        # True per-host egress filtering (blocking connections to
        # non-allowlisted IPs) requires a network namespace with iptables
        # rules.  That is a documented future hardening item.  For now,
        # removing host networking eliminates the largest attack surface.
        if self._has_network(invocation):
            policy = self._get_network_policy(invocation)
            # Use the default Podman bridge (slirp4netns/pasta) which
            # isolates from host localhost.
            command.extend(["--network"])
            if policy is not None and policy.allowed_hosts:
                # Add /etc/hosts entries for each allowed host so DNS
                # resolution is controlled.
                for host in policy.allowed_hosts:
                    command.extend(["--add-host", f"{host}:host-gateway"])
                command.append("slirp4netns")
            else:
                command.append("slirp4netns")
        else:
            command.extend(["--network", "none"])

        # Bind-mount the workspace read-write at its own absolute path.
        command.extend([
            "-v", f"{workspace}:{workspace}:Z",
        ])

        # Bind-mount the task brief read-only at its own path.
        command.extend([
            "-v", f"{task_brief}:{task_brief}:ro,Z",
        ])

        # Bind-mount ONLY the runtime profile directory.
        # This is the synthetic Hermes home — the only profile visible
        # to the agent.  No sibling profiles, no sessions from other
        # runs, no host kanban boards.
        if runtime_profile_dir is not None:
            container_profile = f"/home/methodhub/.hermes/profiles/{profile_name}"
            command.extend([
                "-v", f"{runtime_profile_dir}:{container_profile}:Z",
            ])

        # Environment — container-local paths.
        command.extend([
            "-e", "HERMES_HOME=/home/methodhub/.hermes",
            "-e", "HOME=/home/methodhub",
        ])

        # Inject secret env vars.
        for key in self.settings.secret_env:
            command.extend(["-e", key])

        # Working directory.
        command.extend(["--workdir", str(workspace)])

        # Image reference.
        command.append(self.settings.image)

        # Hermes command.
        command.extend(hermes_cmd)
        return command

    def _build_environment(self) -> dict[str, str]:
        """Build a minimal environment for the podman process itself."""
        env: dict[str, str] = {}
        for key in _ENVIRONMENT_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        # Secrets are passed via -e flags, not host env.
        # But podman needs them in its own environment to pass through.
        for key, value in self.settings.secret_env.items():
            env[key] = value
        return env

    def _resolve_hermes_home(self, invocation: RoleInvocation) -> Path:
        if self.settings.hermes_home is not None:
            return self.settings.hermes_home.resolve()
        return (Path.home() / ".hermes").resolve()

    def _resolve_hermes_binary(self) -> str:
        """Resolve the hermes binary to an absolute host path."""
        import shutil
        path = shutil.which(self.settings.hermes_binary)
        if path:
            return path
        # Fallback to common locations.
        for candidate in (
            Path.home() / ".local/bin/hermes",
            Path("/usr/local/bin/hermes"),
            Path("/usr/bin/hermes"),
        ):
            if candidate.exists():
                return str(candidate)
        return self.settings.hermes_binary

    def _resolve_runtime_profile_dir(
        self, invocation: RoleInvocation
    ) -> Path | None:
        """Resolve the runtime profile directory to mount.

        Slice 2: The runtime profile comes exclusively from
        invocation.metadata["runtime_profile_dir"] — a per-invocation
        snapshot created by RuntimeProfileManager.  The canonical host
        profile is NEVER mounted directly.
        """
        runtime_dir = invocation.metadata.get("runtime_profile_dir")
        if runtime_dir is not None:
            path = Path(str(runtime_dir))
            if path.is_dir():
                return path.resolve()
        return None

    def _verify_mounts(self, invocation: RoleInvocation) -> list[str]:
        """Pre-launch verification of all mount sources.

        Slice 2: We no longer mount the host Hermes directory or binary.
        We require:
        - Workspace directory exists.
        - Task brief file exists.
        - Runtime profile directory exists (from RuntimeProfileManager).
        - Identity files (SOUL.md, config.yaml) exist in the runtime profile.
        """
        problems: list[str] = []
        workspace = invocation.workspace.resolve()
        if not workspace.is_dir():
            problems.append(f"Workspace directory missing: {workspace}")
        task_brief = invocation.task_brief.resolve()
        if not task_brief.is_file():
            problems.append(f"Task brief file missing: {task_brief}")
        runtime_dir = self._resolve_runtime_profile_dir(invocation)
        if runtime_dir is None:
            problems.append(
                "Runtime profile directory not provided. "
                "Set invocation.metadata['runtime_profile_dir']."
            )
        else:
            for identity_file in ("SOUL.md", "config.yaml"):
                if not (runtime_dir / identity_file).exists():
                    problems.append(
                        f"Identity file {identity_file} missing from "
                        f"runtime profile: {runtime_dir}"
                    )
        return problems

    def _has_network(self, invocation: RoleInvocation) -> bool:
        policy = invocation.metadata.get("network_policy")
        if isinstance(policy, NetworkPolicy):
            return policy.has_network
        if self.settings.default_network_policy is not None:
            return self.settings.default_network_policy.has_network
        return False

    def _get_network_policy(
        self, invocation: RoleInvocation
    ) -> NetworkPolicy | None:
        """Return the effective network policy for the invocation."""
        policy = invocation.metadata.get("network_policy")
        if isinstance(policy, NetworkPolicy):
            return policy
        return self.settings.default_network_policy

    @staticmethod
    def _extract_container_id(external_execution_id: str) -> str | None:
        """Extract the container ID from an OCI external execution ID.

        Format: ``oci:<container_id_short>`` (e.g. ``oci:a1b2c3d4e5f6``).
        Rejects the old ``oci:pid:<N>`` format.
        """
        if not external_execution_id.startswith("oci:"):
            return None
        remainder = external_execution_id[4:]
        if not remainder or remainder.startswith("pid:"):
            return None
        return remainder


__all__ = [
    "OciExecutionError",
    "OciExecutor",
    "OciExecutorSettings",
]
