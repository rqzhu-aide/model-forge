"""Diagnostic composition root: constructs the local diagnostic lane.

This is the single entry point that builds the integrated diagnostic path:

    DiagnosticStore → DiagnosticService → LocalHermesExecutor → local Hermes

Under ADR-012 the OCI executor is removed. The lane runs the supervised
local Hermes executor (Block 4). Scientific execution cannot reach this
executor — scientific executor kinds are restricted by ``ApplicationSettings``
and the diagnostic composition is separately gated by ``diagnostic_enabled``.
"""

from __future__ import annotations

from pathlib import Path

from ..application.settings import ApplicationSettings
from ..configuration.profiles import resolve_hermes_root
from ..diagnostics.runtime_profiles import RuntimeProfileManager
from ..diagnostics.service import DiagnosticService
from ..diagnostics.store import DiagnosticStore
from ..executors.local_hermes import LocalHermesExecutor, LocalHermesExecutorSettings
from ..profiles.project_profiles import ProjectProfileManager
from ..storage.database import Database
from ..storage.paths import WorkspacePaths
from ..storage.migrations import HUB_MIGRATIONS


class DiagnosticNotEnabled(RuntimeError):
    """Raised when a new diagnostic start is attempted while the lane is disabled."""


def build_diagnostic_service(
    settings: ApplicationSettings,
    *,
    force_enabled: bool = False,
) -> DiagnosticService:
    """Construct the diagnostic service wired to the LocalHermesExecutor.

    Args:
        settings: Application settings (data_root, hermes_root, etc.)
        force_enabled: When True, skip the diagnostic_enabled check.
            Used by read-only commands (status, logs, reconcile) that must
            remain available even when the lane is disabled.

    Raises:
        DiagnosticNotEnabled: if ``diagnostic_enabled`` is False and
            ``force_enabled`` is not set.
    """
    if not settings.diagnostic_enabled and not force_enabled:
        raise DiagnosticNotEnabled(
            "The diagnostic lane is disabled. Set "
            "METHOD_HUB_DIAGNOSTIC_ENABLED=true to enable new starts. "
            "Status, logs, cancellation, reconciliation, and safe cleanup "
            "remain available for existing invocations."
        )

    hermes_root = settings.hermes_root or resolve_hermes_root()
    hermes_root = Path(hermes_root)

    workspace = WorkspacePaths(settings.data_root, create=True)
    db_path = workspace.root / "method-hub.sqlite3"
    db = Database(db_path, migrations=HUB_MIGRATIONS)
    db.initialize()

    store = DiagnosticStore(db)
    pm = ProjectProfileManager(hermes_root=hermes_root)
    rpm = RuntimeProfileManager(hermes_root)

    executor = LocalHermesExecutor(
        LocalHermesExecutorSettings(
            hermes_home=hermes_root,
            hermes_binary=settings.hermes_executable,
        )
    )

    return DiagnosticService(
        store=store,
        executor=executor,
        profile_manager=pm,
        runtime_profile_manager=rpm,
    )


def open_diagnostic_store(settings: ApplicationSettings) -> DiagnosticStore:
    """Open the diagnostic store for read-only or maintenance commands.

    This does NOT require diagnostic_enabled — status, logs, cancel,
    reconcile, and evidence inspection must remain available.
    """
    workspace = WorkspacePaths(settings.data_root, create=True)
    db_path = workspace.root / "method-hub.sqlite3"
    db = Database(db_path, migrations=HUB_MIGRATIONS)
    db.initialize()
    return DiagnosticStore(db)


__all__ = [
    "DiagnosticNotEnabled",
    "build_diagnostic_service",
    "open_diagnostic_store",
]
