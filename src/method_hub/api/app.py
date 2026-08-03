"""FastAPI application factory with explicit service injection."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .errors import install_error_handlers
from .ports import MethodHubApplicationService
from .router import create_api_router


def create_app(service: MethodHubApplicationService) -> FastAPI:
    """Create the HTTP transport around one application-service implementation."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recovery = getattr(service, "resume_incomplete", None)
        if callable(recovery):
            await recovery()
        yield

    app = FastAPI(title="Method Hub API", version="1.0.0", lifespan=lifespan)
    app.state.method_hub_service = service
    install_error_handlers(app)
    app.include_router(create_api_router())
    return app
