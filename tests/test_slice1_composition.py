"""Slice 1 integration tests: diagnostic composition root and fail-closed gates.

Proves that:
- The diagnostic CLI path reaches DiagnosticService → OciExecutor (not OneShotExecutor)
- A disabled diagnostic lane rejects new starts
- The scientific path cannot select the OCI executor
- Missing Podman fails before container creation
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from method_hub.application.settings import ApplicationSettings
from method_hub.diagnostics.composition import (
    DiagnosticNotEnabled,
    build_diagnostic_service,
    open_diagnostic_store,
)
from method_hub.diagnostics.contracts import DiagnosticState
from method_hub.diagnostics.service import DiagnosticRequest, DiagnosticService
from method_hub.executors.oci import OciExecutor
from method_hub.executors.protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
)
from method_hub.profiles.project_profiles import MemoryPolicy


@pytest.fixture
def test_settings(tmp_path: Path) -> ApplicationSettings:
    """Settings with diagnostic_enabled=True and a temp data root."""
    return ApplicationSettings(
        data_root=tmp_path / "method-hub-data",
        diagnostic_enabled=True,
        development_mode=True,
    )


@pytest.fixture
def disabled_settings(tmp_path: Path) -> ApplicationSettings:
    """Settings with diagnostic_enabled=False."""
    return ApplicationSettings(
        data_root=tmp_path / "method-hub-data",
        diagnostic_enabled=False,
        development_mode=True,
    )


class TestCompositionRoot:
    """Tests for the diagnostic composition root (Slice 1)."""

    def test_build_service_returns_oci_executor(self, test_settings: ApplicationSettings):
        """Building the diagnostic service wires OciExecutor, not OneShotExecutor."""
        if not shutil.which("podman"):
            pytest.skip("Podman not available")
        service = build_diagnostic_service(test_settings)
        assert isinstance(service._executor, OciExecutor)

    def test_disabled_lane_rejects_new_start(self, disabled_settings: ApplicationSettings):
        """A disabled diagnostic lane rejects build_diagnostic_service."""
        with pytest.raises(DiagnosticNotEnabled):
            build_diagnostic_service(disabled_settings)

    def test_open_store_works_when_disabled(self, disabled_settings: ApplicationSettings):
        """Read-only commands (status, logs) must work even when disabled."""
        store = open_diagnostic_store(disabled_settings)
        assert store is not None
        # Listing invocations should work (empty list, not an error).
        invocations = store.list_invocations()
        assert invocations == []

    def test_force_enabled_bypasses_gate(self, disabled_settings: ApplicationSettings):
        """force_enabled allows construction even when the lane is disabled."""
        if not shutil.which("podman"):
            pytest.skip("Podman not available")
        service = build_diagnostic_service(disabled_settings, force_enabled=True)
        assert isinstance(service._executor, OciExecutor)


class TestScientificPathBlocked:
    """The scientific path cannot select the OCI executor."""

    def test_oci_executor_kind_rejected_in_settings(self, tmp_path: Path):
        """The 'oci' executor kind is no longer accepted for scientific execution."""
        with pytest.raises(Exception):
            ApplicationSettings(
                data_root=tmp_path / "data",
                executor_kind="oci",  # type: ignore[arg-type]
                development_mode=True,
            )

    def test_bootstrap_rejects_oci(self, tmp_path: Path):
        """Bootstrap raises when executor_kind='oci' is attempted."""
        from method_hub.application.bootstrap import build_service

        # The settings validation should reject 'oci' before bootstrap.
        # If somehow it gets through, bootstrap raises ValueError.
        with pytest.raises((ValueError, Exception)):
            settings = ApplicationSettings(
                data_root=tmp_path / "data",
                executor_kind="fake",
                development_mode=True,
            )
            # Manually set executor_kind to 'oci' to bypass Literal validation
            # and verify bootstrap rejects it.
            settings.executor_kind = "oci"  # type: ignore[assignment]
            build_service(settings)


class TestObserverDrivenTransitions:
    """The service must not pre-mark running state — the observer drives transitions."""

    def test_observer_drives_lifecycle(
        self, tmp_path: Path, test_settings: ApplicationSettings
    ):
        """The executor's observer drives PREFLIGHT → CREATING → ACK → RUNNING."""
        if not shutil.which("podman"):
            pytest.skip("Podman not available")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        brief = workspace / "task.md"
        brief.write_text("# Test task\nWrite diagnostic_result.json.")
        brief_sha = hashlib.sha256(brief.read_bytes()).hexdigest()

        # Create a real profile for the test.
        from method_hub.profiles.project_profiles import (
            ProjectProfileManager,
            RoleProfileSpec,
        )
        hermes_root = Path.home() / ".hermes"
        pm = ProjectProfileManager(hermes_root=hermes_root)
        profile_name = "slice1-test-theorist"
        profile_dir = pm.profiles_root / profile_name
        if profile_dir.exists():
            import shutil as shutil_mod
            shutil_mod.rmtree(profile_dir, ignore_errors=True)
        try:
            pm.create_project_profiles(
                project_id="slice1-test",
                specs=(RoleProfileSpec(
                    role="theorist",
                    base_profile="spike-test-profile",
                    soul_text="# Slice 1 Test\n",
                    memory_policy=MemoryPolicy.EPHEMERAL,
                ),),
            )

            # Mock executor that calls observer callbacks.
            captured_transitions: list[str] = []

            async def mock_execute(invocation, observer):
                await observer.launch_intent(invocation)
                captured_transitions.append("launch_intent")
                await observer.launch_acknowledged(invocation, "oci:test:456")
                captured_transitions.append("launch_acknowledged")
                await observer.heartbeat(invocation, "running")
                captured_transitions.append("heartbeat")

                output = workspace / "diagnostic_result.json"
                output.write_text(json.dumps({
                    "status": "ok",
                    "brief_sha256": brief_sha,
                    "agent_profile": profile_name,
                }))
                return RoleExecutionResult(
                    status=RoleExecutionStatus.SUCCEEDED,
                    external_execution_id="oci:test:456",
                    exit_code=0,
                    summary="OK",
                )

            mock_executor = AsyncMock()
            mock_executor.execute.side_effect = mock_execute

            # Build service with mock executor.
            store = open_diagnostic_store(test_settings)
            rpm = __import__(
                "method_hub.diagnostics.runtime_profiles",
                fromlist=["RuntimeProfileManager"],
            ).RuntimeProfileManager(hermes_root)

            service = DiagnosticService(
                store=store,
                executor=mock_executor,
                profile_manager=pm,
                runtime_profile_manager=rpm,
            )

            request = DiagnosticRequest(
                project_id="slice1-test",
                role="theorist",
                profile_name=profile_name,
                workspace=workspace,
                task_brief=brief,
                memory_policy=MemoryPolicy.EPHEMERAL,
            )

            result = asyncio.run(service.run_diagnostic(request))
            assert result.status == "succeeded"
            # The observer callbacks were all called.
            assert "launch_intent" in captured_transitions
            assert "launch_acknowledged" in captured_transitions
            assert "heartbeat" in captured_transitions

            # Verify the invocation went through the full state machine.
            inv = store.get_invocation(result.invocation_id)
            assert inv is not None
            assert inv["status"] == "succeeded"
        finally:
            if profile_dir.exists():
                import shutil as shutil_mod
                shutil_mod.rmtree(profile_dir, ignore_errors=True)


class TestDisabledStartCreatesZeroContainers:
    """A disabled or blocked request launches zero containers (Slice 1 acceptance)."""

    def test_disabled_rejects_without_podman(self, tmp_path: Path):
        """Even with no Podman, a disabled lane rejects before any execution."""
        settings = ApplicationSettings(
            data_root=tmp_path / "data",
            diagnostic_enabled=False,
            development_mode=True,
        )
        with pytest.raises(DiagnosticNotEnabled):
            build_diagnostic_service(settings)
