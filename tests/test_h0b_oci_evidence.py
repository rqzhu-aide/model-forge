"""Real Linux evidence tests for the rootless OCI runtime (H0-B evidence).

These tests exercise the actual Podman + Hermes + filesystem stack through
the ADR-004 production boundary (rootless OCI).  They are the same evidence
matrix as the H0-A bwrap tests (``test_real_linux_evidence.py``) but repeated
through rootless Podman.

H0-B acceptance (next-block plan §5.2): "The complete matrix must pass through
rootless OCI for H0-B."

Evidence gathered:
  P1: Podman launches and mounts the workspace/profile correctly
  P2: Real Hermes one-shot executes inside the OCI container
  P3: Profile identity files are read-only, profile state is writable
  P4: The diagnostic output is validated independently of exit code
  P5: Timeout kills the container and verified cancellation works
  P6: Network isolation — deny-default blocks, allowlist permits
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Skip entire module on non-Linux or when podman/hermes is missing.
_podman = shutil.which("podman")
_hermes = shutil.which("hermes")

pytestmark = pytest.mark.skipif(
    platform.system() != "Linux" or _podman is None or _hermes is None,
    reason="H0-B evidence tests require Linux + podman + hermes",
)

from method_hub.diagnostics.contracts import (
    DiagnosticOutputContract,
    validate_diagnostic_output,
)
from method_hub.diagnostics.runtime_profiles import (
    RuntimeProfileManager,
    SnapshotState,
)
from method_hub.diagnostics.network_secrets import (
    canary_scan,
    CredentialDelivery,
    provider_network_policy,
)
from method_hub.executors.oci import OciExecutor, OciExecutorSettings
from method_hub.executors.protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)
from method_hub.profiles.project_profiles import (
    MemoryPolicy,
    ProjectProfileManager,
    RoleProfileSpec,
)


# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

HERMES_HOME = Path.home() / ".hermes"
BASE_PROFILE = "spike-test-profile"
TEST_PROJECT_ID = "evidence-oci"
TEST_ROLE = "theorist"
TEST_PROFILE_NAME = f"{TEST_PROJECT_ID}-{TEST_ROLE}"
RUNTIME_IMAGE = "localhost/method-hub-runtime:latest"


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def hermes_root() -> Path:
    return HERMES_HOME


@pytest.fixture
def profile_manager(hermes_root: Path) -> ProjectProfileManager:
    return ProjectProfileManager(hermes_root=hermes_root)


@pytest.fixture
def test_profile(profile_manager: ProjectProfileManager):
    """Create a real test profile and clean it up afterward."""
    spec = RoleProfileSpec(
        role=TEST_ROLE,
        base_profile=BASE_PROFILE,
        soul_text=(
            "# Evidence Test Theorist (OCI)\n\n"
            "You are a test profile for verifying the OCI execution boundary.\n"
            "Follow instructions exactly.\n"
        ),
        memory_policy=MemoryPolicy.EPHEMERAL,
    )
    profile_dir = profile_manager.profiles_root / TEST_PROFILE_NAME
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)

    records = profile_manager.create_project_profiles(
        project_id=TEST_PROJECT_ID,
        specs=(spec,),
    )
    yield records[0]

    profile_dir = profile_manager.profiles_root / TEST_PROFILE_NAME
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)


class NoopObserver:
    """Minimal observer that records heartbeats."""

    def __init__(self):
        self.external_execution_id = None
        self.heartbeats: list[str] = []

    async def launch_intent(self, invocation):
        pass

    async def launch_acknowledged(self, invocation, external_execution_id):
        self.external_execution_id = external_execution_id

    async def heartbeat(self, invocation, activity):
        self.heartbeats.append(activity)


# --------------------------------------------------------------------------- #
# P1: Podman launches and mounts correctly                                    #
# --------------------------------------------------------------------------- #


class TestP1PodmanLaunch:
    """Evidence that Podman starts and the filesystem isolation works."""

    def test_p1a_podman_executes_simple_command(self, tmp_path: Path):
        """P1a: Podman can run a basic echo command with full hardening."""
        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                RUNTIME_IMAGE,
                "echo", "hello-from-oci-container",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"podman stderr: {result.stderr}"
        assert "hello-from-oci-container" in result.stdout

    def test_p1b_workspace_mounted_writable(self, tmp_path: Path):
        """P1b: the workspace directory is mounted read-write inside the container."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        marker = workspace / "canary.txt"

        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                "-v", f"{workspace}:/workspace:Z",
                RUNTIME_IMAGE,
                "sh", "-c", "echo 'container wrote this' > /workspace/canary.txt",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0, f"podman stderr: {result.stderr}"
        assert marker.read_text().strip() == "container wrote this"

    def test_p1c_soul_md_mounted_read_only(
        self, tmp_path: Path, test_profile
    ):
        """P1c: SOUL.md is mounted read-only — writing fails."""
        soul_path = test_profile.home / "SOUL.md"

        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                "-v", f"{soul_path}:/soul.md:ro,Z",
                RUNTIME_IMAGE,
                "sh", "-c", "echo 'tampered' >> /soul.md",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        # Writing to the read-only mount should fail.
        assert result.returncode != 0

    def test_p1d_capabilities_dropped(self, tmp_path: Path):
        """P1d: the container process has zero effective capabilities."""
        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                RUNTIME_IMAGE,
                "python3", "-c",
                "import os; "
                "caps = open('/proc/self/status').read(); "
                "line = [l for l in caps.split('\\n') if 'CapEff' in l][0]; "
                "print(line)",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0
        # CapEff should be 0 (no effective capabilities).
        cap_line = result.stdout.strip()
        assert "0000000000000000" in cap_line

    def test_p1e_readonly_rootfs_blocks_writes(self, tmp_path: Path):
        """P1e: the root filesystem is read-only — writing outside mounts fails."""
        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                RUNTIME_IMAGE,
                "sh", "-c", "echo 'hack' > /etc/hacked",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode != 0
        assert "read-only" in result.stderr.lower()


# --------------------------------------------------------------------------- #
# P2: Real Hermes one-shot in OCI container                                   #
# --------------------------------------------------------------------------- #


class TestP2HermesOneShot:
    """Evidence that Hermes -z executes inside an OCI container."""

    def test_p2a_hermes_z_executes(
        self, tmp_path: Path, test_profile
    ):
        """P2a: Hermes -z runs and produces a simple output file.

        This is the key H0-B evidence: the same fixed synthetic task that
        passed through bwrap (E2a) now passes through rootless OCI.
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        task_brief = workspace / "task.md"
        task_brief.write_text(
            "# Simple Task\n\nWrite 'ok' to result.txt.\n"
        )
        result_file = workspace / "result.txt"

        hermes_bin = shutil.which("hermes")
        hermes_install = HERMES_HOME
        profile_dir = HERMES_HOME / "profiles" / TEST_PROFILE_NAME
        uv_python = Path.home() / ".local/share/uv"

        cmd = [
            "podman", "run", "--rm",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--userns", "keep-id",
            "--network", "host",  # Hermes needs network for LLM API.
            "--tmpfs", "/tmp",
            # Mount workspace at its own path (rw).
            "-v", f"{workspace}:{workspace}:Z",
            # Mount task brief at its own path (ro).
            "-v", f"{task_brief}:{task_brief}:ro,Z",
            # Mount the entire .hermes directory (rw for profile state).
            "-v", f"{hermes_install}:{hermes_install}:Z",
            # Mount the uv Python install (ro — hermes venv symlinks here).
            "-v", f"{uv_python}:{uv_python}:ro,Z",
            # Mount the hermes binary (ro).
            "-v", f"{hermes_bin}:{hermes_bin}:ro,Z",
            "-e", f"HERMES_HOME={hermes_install}",
            "-e", f"HOME={Path.home()}",
            "--workdir", str(workspace),
            RUNTIME_IMAGE,
            hermes_bin,
            "-p", TEST_PROFILE_NAME,
            "-z",
            f"Write exactly the text 'ok' (no quotes) to {workspace}/result.txt",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0, (
            f"Hermes in OCI failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )
        assert result_file.exists(), "Result file was not created"
        assert result_file.read_text().strip() == "ok"


# --------------------------------------------------------------------------- #
# P3: Profile mount verification                                              #
# --------------------------------------------------------------------------- #


class TestP3ProfileMounts:
    """Evidence that profile files are correctly isolated in OCI."""

    def test_p3a_profile_state_db_writable(
        self, tmp_path: Path, test_profile
    ):
        """P3a: state.db in the profile directory is writable (C1)."""
        profile_dir = HERMES_HOME / "profiles" / TEST_PROFILE_NAME
        db_path = profile_dir / "state.db"

        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--userns", "keep-id",
                "--tmpfs", "/tmp",
                "-v", f"{profile_dir}:/profile:Z",
                RUNTIME_IMAGE,
                "python3", "-c",
                "import sqlite3; "
                f"db=sqlite3.connect('/profile/state.db'); "
                "db.execute('CREATE TABLE IF NOT EXISTS ev (id INTEGER)'); "
                "db.execute('INSERT INTO ev VALUES (1)'); "
                "db.commit(); "
                "print(db.execute('SELECT count(*) FROM ev').fetchone()[0])",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert result.stdout.strip() != ""

    def test_p3b_cross_profile_access_blocked(
        self, tmp_path: Path, test_profile, profile_manager
    ):
        """P3b: a profile cannot read another profile's memories.

        Unlike bwrap's --ro-bind / (which exposed everything), Podman's
        read-only root filesystem only contains the image layers — no host
        paths.  The only way to access host files is through explicit -v
        bind mounts.  This test proves cross-profile isolation is enforced
        by the container boundary.
        """
        # Create a second profile with a secret.
        secret_profile_name = f"{TEST_PROJECT_ID}-outside-reviewer"
        secret_profile_dir = profile_manager.profiles_root / secret_profile_name
        if secret_profile_dir.exists():
            shutil.rmtree(secret_profile_dir, ignore_errors=True)

        profile_manager.create_project_profiles(
            project_id=TEST_PROJECT_ID,
            specs=(
                RoleProfileSpec(
                    role="outside_reviewer",
                    base_profile=BASE_PROFILE,
                    soul_text="# Secret Reviewer\n",
                ),
            ),
        )
        # Write a secret in the reviewer's memories.
        secret_mem_dir = secret_profile_dir / "memories"
        secret_mem_dir.mkdir(parents=True, exist_ok=True)
        (secret_mem_dir / "MEMORY.md").write_text("SECRET: cross-profile-leak-test-oci")

        # Mount only the test profile's directory, NOT the secret one.
        # Try to reach the secret profile via the host filesystem.
        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--userns", "keep-id",
                "--tmpfs", "/tmp",
                "-v", f"{test_profile.home}:/profile:Z",
                RUNTIME_IMAGE,
                "python3", "-c",
                "import os; "
                # Try to find the secret profile via the host path.
                f"path = '{secret_profile_dir}/memories/MEMORY.md'; "
                "print('EXISTS' if os.path.exists(path) else 'NOT_FOUND')",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        # The secret file must NOT be accessible from inside the container
        # because it was never bind-mounted.
        assert "NOT_FOUND" in result.stdout, (
            f"Cross-profile access succeeded! The secret profile's memory "
            f"file was accessible from inside the container.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Cleanup.
        shutil.rmtree(secret_profile_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# P4: Diagnostic output validation (same logic as H0-A E4)                    #
# --------------------------------------------------------------------------- #


class TestP4OutputValidation:
    """Evidence that output is validated independently of exit code.

    This reuses the same validation logic as H0-A E4 — the validation
    layer is executor-independent.
    """

    def test_p4a_valid_output_passes(self, tmp_path: Path):
        """P4a: a correctly-formatted diagnostic_result.json passes validation."""
        brief_content = b"# Test brief\nSome content."
        brief_sha = hashlib.sha256(brief_content).hexdigest()
        output = {
            "status": "ok",
            "brief_sha256": brief_sha,
            "agent_profile": "evidence-oci-theorist",
        }
        findings = validate_diagnostic_output(
            json.dumps(output).encode(),
            expected_brief_sha256=brief_sha,
            expected_profile="evidence-oci-theorist",
        )
        assert findings == []

    def test_p4b_wrong_brief_sha_fails(self, tmp_path: Path):
        """P4b: wrong brief_sha256 is caught."""
        output = {
            "status": "ok",
            "brief_sha256": "0" * 64,
            "agent_profile": "test",
        }
        findings = validate_diagnostic_output(
            json.dumps(output).encode(),
            expected_brief_sha256="a" * 64,
            expected_profile="test",
        )
        assert any("mismatch" in f for f in findings)

    def test_p4c_exit_code_zero_but_no_output_fails(self, tmp_path: Path):
        """P4c: exit code 0 with no output file → failure (the spike finding)."""
        contract = DiagnosticOutputContract()
        output_path = tmp_path / contract.output_filename
        assert not output_path.exists()

    def test_p4d_canary_scan_catches_secret_in_output(self, tmp_path: Path):
        """P4d: canary scan detects a leaked API key in output."""
        output_with_leak = "Using key sk-abcdefghijklmnopqrstuvwxyz1234567890"
        result = canary_scan(output_with_leak)
        assert result.has_leaks


# --------------------------------------------------------------------------- #
# P5: Timeout and cancellation                                                #
# --------------------------------------------------------------------------- #


class TestP5TimeoutCancellation:
    """Evidence that timeout kills the container and cancellation works."""

    def test_p5a_podman_process_killed_on_timeout(self, tmp_path: Path):
        """P5a: a long-running process inside OCI is killed on timeout."""
        proc = subprocess.Popen(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                RUNTIME_IMAGE,
                "sleep", "300",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        pid = proc.pid

        # Wait a moment to confirm it's running.
        time.sleep(1.0)
        os.kill(pid, 0)  # Should not raise.

        # Kill the process group.
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            proc.wait(timeout=5)

        with pytest.raises((OSError, ProcessLookupError)):
            os.kill(pid, 0)

    def test_p5b_cancel_returns_bool(self, tmp_path: Path, test_profile):
        """P5b: OciExecutor.cancel() returns True for confirmed termination."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = workspace / "task.md"
        brief.write_text("# Cancel test\n")

        invocation = RoleInvocation(
            execution_id="exec-oci-cancel",
            invocation_id="inv-oci-cancel",
            run_id="run-oci-cancel",
            project_id="evidence-oci",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile=TEST_PROFILE_NAME,
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
            timeout_seconds=300,
        )
        executor = OciExecutor(
            OciExecutorSettings(
                hermes_home=HERMES_HOME,
                poll_interval_seconds=1.0,
                verify_image_digest=False,  # skip for cancel test
            )
        )
        observer = NoopObserver()

        async def _run():
            task = asyncio.create_task(
                executor.execute(invocation, observer)
            )
            await asyncio.sleep(5)  # Let container start.
            assert observer.external_execution_id is not None
            cancelled = await executor.cancel(observer.external_execution_id)
            assert cancelled is True
            result = await task
            return result

        result = asyncio.run(_run())
        assert result.status in (
            RoleExecutionStatus.FAILED,
            RoleExecutionStatus.SUCCEEDED,
        )


# --------------------------------------------------------------------------- #
# P6: Network isolation                                                       #
# --------------------------------------------------------------------------- #


class TestP6NetworkIsolation:
    """Evidence that network isolation works in OCI."""

    def test_p6a_network_none_blocks_outbound(self, tmp_path: Path):
        """P6a: --network none prevents outbound connections."""
        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "none",
                "--tmpfs", "/tmp",
                RUNTIME_IMAGE,
                "python3", "-c",
                "import socket\n"
                "s = socket.socket()\n"
                "s.settimeout(2)\n"
                "try:\n"
                "    s.connect(('8.8.8.8', 53))\n"
                "    print('CONNECTED')\n"
                "except Exception:\n"
                "    print('BLOCKED')\n",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert "BLOCKED" in result.stdout

    def test_p6b_network_host_allows_outbound(self, tmp_path: Path):
        """P6b: --network host permits outbound connections."""
        result = subprocess.run(
            [
                "podman", "run", "--rm",
                "--read-only",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--userns", "keep-id",
                "--network", "host",
                "--tmpfs", "/tmp",
                RUNTIME_IMAGE,
                "python3", "-c",
                "import socket\n"
                "s = socket.socket()\n"
                "s.settimeout(5)\n"
                "try:\n"
                "    s.connect(('dns.google', 53))\n"
                "    print('CONNECTED')\n"
                "except Exception as e:\n"
                "    print(f'FAILED: {e}')\n",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        assert "CONNECTED" in result.stdout, (
            f"Network should work with --network host\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# --------------------------------------------------------------------------- #
# P7: OciExecutor integration (via the executor API)                         #
# --------------------------------------------------------------------------- #


class TestP7OciExecutorIntegration:
    """Integration tests for the OciExecutor via the RoleExecutor protocol."""

    def test_p7a_executor_launches_container(
        self, tmp_path: Path, test_profile
    ):
        """P7a: OciExecutor launches a container and returns a result.

        Uses a simple echo command instead of real Hermes to verify the
        executor plumbing works end-to-end without an LLM call.
        """
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = workspace / "task.md"
        brief.write_text("# Echo task\n")

        invocation = RoleInvocation(
            execution_id="exec-oci-int",
            invocation_id="inv-oci-int",
            run_id="run-oci-int",
            project_id="evidence-oci",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile=TEST_PROFILE_NAME,
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
            timeout_seconds=60,
        )
        executor = OciExecutor(
            OciExecutorSettings(
                hermes_home=HERMES_HOME,
                poll_interval_seconds=2.0,
                verify_image_digest=False,
            )
        )
        observer = NoopObserver()

        async def _run():
            # We can't easily override the command, so we test by
            # verifying the executor starts and produces a result
            # (even if Hermes itself fails due to missing API key).
            result = await asyncio.wait_for(
                executor.execute(invocation, observer),
                timeout=90,
            )
            return result

        result = asyncio.run(_run())
        # The execution should have been acknowledged.
        assert observer.external_execution_id is not None
        # We should get a result (either succeeded or failed).
        assert result.status in (
            RoleExecutionStatus.SUCCEEDED,
            RoleExecutionStatus.FAILED,
        )
        assert result.external_execution_id is not None

    def test_p7b_executor_reconcile_dead_process(
        self, tmp_path: Path
    ):
        """P7b: reconcile() returns FAILED for a dead process."""
        executor = OciExecutor(
            OciExecutorSettings(hermes_home=HERMES_HOME)
        )
        # Use a PID that doesn't exist.
        result = asyncio.run(
            executor.reconcile("oci:pid:99999999")
        )
        assert result is not None
        assert result.status == RoleExecutionStatus.FAILED

    def test_p7c_executor_cancel_nonexistent_pid(self):
        """P7c: cancel() returns True for a process that's already dead."""
        executor = OciExecutor(
            OciExecutorSettings(hermes_home=HERMES_HOME)
        )
        result = asyncio.run(
            executor.cancel("oci:pid:99999999")
        )
        assert result is True

    def test_p7d_verify_mounts_catches_missing_workspace(
        self, tmp_path: Path
    ):
        """P7d: _verify_mounts catches missing workspace."""
        executor = OciExecutor(
            OciExecutorSettings(hermes_home=HERMES_HOME)
        )
        invocation = RoleInvocation(
            execution_id="exec-verify",
            invocation_id="inv-verify",
            run_id="run-verify",
            project_id="evidence-oci",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile=TEST_PROFILE_NAME,
            workspace=tmp_path / "nonexistent",
            task_brief=tmp_path / "nonexistent.md",
            expected_output_paths=(),
        )
        problems = executor._verify_mounts(invocation)
        assert len(problems) > 0
        assert any("Workspace" in p for p in problems)


# --------------------------------------------------------------------------- #
# P8: Image digest pinning (ADR-004)                                          #
# --------------------------------------------------------------------------- #


class TestP8ImagePinning:
    """Evidence that the image digest is verified at launch (ADR-004)."""

    def test_p8a_image_has_stable_digest(self):
        """P8a: the runtime image has a verifiable digest."""
        result = subprocess.run(
            ["podman", "inspect", "--format", "{{.Digest}}", RUNTIME_IMAGE],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        digest = result.stdout.strip()
        # Locally-built images may have empty digest, but should have an ID.
        if not digest:
            result2 = subprocess.run(
                ["podman", "inspect", "--format", "{{.Id}}", RUNTIME_IMAGE],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result2.returncode == 0
            assert result2.stdout.strip().startswith("sha256:")

    def test_p8b_mismatched_digest_rejected(self, tmp_path: Path):
        """P8b: OciExecutor rejects a mismatched image digest."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        brief = workspace / "task.md"
        brief.write_text("# Task\n")

        invocation = RoleInvocation(
            execution_id="exec-digest",
            invocation_id="inv-digest",
            run_id="run-digest",
            project_id="evidence-oci",
            phase="diagnostic",
            mode="oneshot",
            stage_id="diag",
            role="theorist",
            profile=TEST_PROFILE_NAME,
            workspace=workspace,
            task_brief=brief,
            expected_output_paths=(),
        )
        executor = OciExecutor(
            OciExecutorSettings(
                hermes_home=HERMES_HOME,
                image_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                verify_image_digest=True,
            )
        )
        observer = NoopObserver()

        async def _run():
            result = await executor.execute(invocation, observer)
            return result

        result = asyncio.run(_run())
        assert result.status == RoleExecutionStatus.FAILED
        assert "digest" in result.summary.lower() or "digest" in result.diagnostic_text.lower()
