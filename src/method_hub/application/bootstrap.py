"""Composition root for the greenfield Method Hub application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from ..api import create_app
from ..configuration.resources import RoleResourceCatalog
from ..executors import (
    HermesKanbanExecutor,
    HermesSettings,
    LocalHermesExecutor,
    LocalHermesExecutorSettings,
    SchemaExampleFakeExecutor,
    profile_exists,
)
from ..specification import SpecificationPackage
from ..storage.artifacts import ArtifactStore
from ..storage.paths import WorkspacePaths
from ..storage.repository import HubRepository
from .run_coordinator import RunCoordinator
from .service import MethodHubService
from .settings import ApplicationSettings
from .static_frontend import SPAStaticFiles


def _verify_hermes_profiles(settings: ApplicationSettings) -> None:
    """Fail fast if any role profile does not exist on disk."""

    role_profiles = {
        "research_lead": settings.research_lead_profile,
        "theorist": settings.theorist_profile,
        "data_analyst": settings.data_analyst_profile,
        "outside_reviewer": settings.outside_reviewer_profile,
    }
    missing = [
        f"{role} ({profile})"
        for role, profile in role_profiles.items()
        if not profile_exists(profile, hermes_root=settings.hermes_root)
    ]
    if missing:
        raise ValueError(
            "Hermes profiles not found on disk: " + ", ".join(missing)
            + ". Create them or configure the correct profile names."
        )


def build_service(settings: ApplicationSettings) -> MethodHubService:
    """Construct the durable service without starting external role work."""

    workspace = WorkspacePaths(settings.data_root, create=True)
    repository = HubRepository(workspace.root / "method-hub.sqlite3")
    repository.initialize()
    specification = SpecificationPackage.load(settings.resolved_architecture_root())
    resource_root = Path(__file__).resolve().parents[3] / "resources" / "team"
    resources = RoleResourceCatalog.load(resource_root)
    artifacts = ArtifactStore(workspace)
    coordinator = None
    if settings.executor_kind == "fake":
        executor = SchemaExampleFakeExecutor(settings.resolved_architecture_root())
        coordinator = RunCoordinator(
            settings=settings,
            specification=specification,
            repository=repository,
            artifacts=artifacts,
            role_resources=resources,
            executor=executor,
        )
    elif settings.executor_kind == "local_hermes":
        _verify_hermes_profiles(settings)
        executor = LocalHermesExecutor(
            LocalHermesExecutorSettings(
                hermes_binary=settings.hermes_executable,
                hermes_home=settings.resolved_hermes_root(),
            )
        )
        coordinator = RunCoordinator(
            settings=settings,
            specification=specification,
            repository=repository,
            artifacts=artifacts,
            role_resources=resources,
            executor=executor,
        )
    elif settings.executor_kind == "hermes_kanban":
        _verify_hermes_profiles(settings)
        executor = HermesKanbanExecutor(
            HermesSettings(
                executable=settings.hermes_executable,
                board_slug=settings.hermes_board,
                hermes_home=settings.hermes_root,
            )
        )
        coordinator = RunCoordinator(
            settings=settings,
            specification=specification,
            repository=repository,
            artifacts=artifacts,
            role_resources=resources,
            executor=executor,
        )
    return MethodHubService(
        settings=settings,
        specification=specification,
        repository=repository,
        artifacts=artifacts,
        role_resources=resources,
        run_launcher=coordinator.run if coordinator is not None else None,
        cancellation_notifier=(
            coordinator.notify_cancellation if coordinator is not None else None
        ),
        recovery_launcher=(
            coordinator.resume_incomplete if coordinator is not None else None
        ),
    )


def build_application(settings: ApplicationSettings | None = None) -> FastAPI:
    configured = settings or ApplicationSettings()
    app = create_app(build_service(configured))
    frontend = configured.resolved_frontend_dist()
    if frontend.is_dir():
        app.mount("/", SPAStaticFiles(directory=frontend, html=True), name="web")
    return app


__all__ = ["build_application", "build_service"]
