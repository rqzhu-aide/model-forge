"""Diagnostic composition root tests (trusted-local topology, ADR-012).

Proves that:
- The diagnostic lane wires DiagnosticService → LocalHermesExecutor (local).
- A disabled diagnostic lane rejects new starts but allows read-only access.
- The composition root no longer requires bwrap.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from model_forge.application.settings import ApplicationSettings
from model_forge.diagnostics.composition import (
    DiagnosticNotEnabled,
    build_diagnostic_service,
    open_diagnostic_store,
)
from model_forge.diagnostics.store import DiagnosticStore
from model_forge.executors.local_hermes import LocalHermesExecutor


@pytest.fixture
def test_settings(tmp_path: Path) -> ApplicationSettings:
    """Settings with diagnostic_enabled=True and a temp data root."""
    return ApplicationSettings(
        data_root=tmp_path / "model-forge-data",
        diagnostic_enabled=True,
        development_mode=True,
    )


@pytest.fixture
def disabled_settings(tmp_path: Path) -> ApplicationSettings:
    """Settings with diagnostic_enabled=False."""
    return ApplicationSettings(
        data_root=tmp_path / "model-forge-data",
        diagnostic_enabled=False,
        development_mode=True,
    )


class TestCompositionRoot:
    def test_build_service_returns_local_hermes_executor(
        self, test_settings: ApplicationSettings
    ) -> None:
        """The diagnostic lane wires the local LocalHermesExecutor, not bwrap."""
        if not shutil.which("hermes"):
            pytest.skip("hermes not available")
        service = build_diagnostic_service(test_settings)
        assert isinstance(service._executor, LocalHermesExecutor)

    def test_disabled_lane_rejects_new_start(
        self, disabled_settings: ApplicationSettings
    ) -> None:
        with pytest.raises(DiagnosticNotEnabled):
            build_diagnostic_service(disabled_settings)

    def test_disabled_lane_allows_read_only_access(
        self, disabled_settings: ApplicationSettings
    ) -> None:
        service = build_diagnostic_service(disabled_settings, force_enabled=True)
        assert service is not None
        store = open_diagnostic_store(disabled_settings)
        assert isinstance(store, DiagnosticStore)

    def test_no_bwrap_required(
        self, test_settings: ApplicationSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The composition root must NOT require bwrap (Block 4 removes it)."""
        # Even if bwrap is missing, the composition should succeed.
        original_which = shutil.which

        def mock_which(name: str) -> str | None:
            if name == "bwrap":
                return None  # bwrap is not needed anymore
            return original_which(name)

        monkeypatch.setattr(shutil, "which", mock_which)
        if not original_which("hermes"):
            pytest.skip("hermes not available")
        service = build_diagnostic_service(test_settings)
        assert isinstance(service._executor, LocalHermesExecutor)
