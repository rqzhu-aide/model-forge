"""Project researcher-material shelf (ADR-019): informal, mutable state."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from model_forge.api.errors import CommandRejected
from model_forge.api.models import AttachResearcherMaterialRequest, CreateProjectRequest
from model_forge.api.ports import RawRequestBody
from model_forge.application.bootstrap import build_service
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.storage.repository import RepositoryNotFoundError


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def _service(tmp_path: Path) -> ModelForgeService:
    return build_service(
        ApplicationSettings(
            data_root=tmp_path / "data",
            architecture_root=ARCHITECTURE,
            executor_kind="fake",
            development_mode=True,
            frontend_dist=tmp_path / "missing-web",
        )
    )


async def _receipt(service: ModelForgeService, body: bytes, *, key: str, project_id):
    return await service.preserve_raw_request(
        RawRequestBody(
            body=body,
            byte_length=len(body),
            media_type="application/json",
            content_sha256=hashlib.sha256(body).hexdigest(),
            method="POST",
            path="/api/v1/projects",
            command_family=(
                "attach_researcher_material" if project_id else "create_project"
            ),
            project_id=project_id,
            idempotency_key=key,
        )
    )


async def _project(service: ModelForgeService) -> str:
    create = CreateProjectRequest(
        name="Material shelf test",
        research_question="Does the shelf keep copies and links distinctly?",
        domains=["statistics"],
        intended_use="Exercise the researcher-material shelf.",
    )
    body = json.dumps(create.model_dump(mode="json")).encode("utf-8")
    project = await service.create_project(
        create,
        raw_request=await _receipt(service, body, key="create-shelf", project_id=None),
    )
    return str(project.project_id)


async def _attach(service, project_id, request: AttachResearcherMaterialRequest, key: str):
    body = json.dumps(request.model_dump(mode="json")).encode("utf-8")
    return await service.attach_researcher_material(
        project_id,
        request,
        raw_request=await _receipt(service, body, key=key, project_id=project_id),
    )


def test_copy_material_stores_bytes_and_returns_exact_content(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        view = await _attach(
            service,
            project_id,
            AttachResearcherMaterialRequest(
                name="partial_fit.py",
                kind="copy",
                media_type="text/plain",
                content="def partial_fit(x):\n    return x\n",
            ),
            "shelf-copy",
        )
        assert view.kind == "copy"
        assert view.size_bytes == len("def partial_fit(x):\n    return x\n".encode())
        assert view.content_sha256 is not None

        listed = await service.list_researcher_materials(project_id)
        assert [item.material_id for item in listed] == [view.material_id]

        payload = await service.get_researcher_material_content(
            project_id, view.material_id
        )
        assert payload.content == "def partial_fit(x):\n    return x\n"
        assert payload.media_type == "text/plain"

    asyncio.run(scenario())


def test_link_material_seals_url_as_uri_list(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        view = await _attach(
            service,
            project_id,
            AttachResearcherMaterialRequest(
                name="simulation archive",
                kind="link",
                external_url="https://data.example.org/large-archive.tar",
            ),
            "shelf-link",
        )
        assert view.kind == "link"
        assert view.content_sha256 is None

        payload = await service.get_researcher_material_content(
            project_id, view.material_id
        )
        assert payload.content == "https://data.example.org/large-archive.tar"
        assert payload.media_type == "text/uri-list"

    asyncio.run(scenario())


def test_copy_over_one_megabyte_is_rejected_with_link_guidance(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        with pytest.raises(CommandRejected):
            await _attach(
                service,
                project_id,
                AttachResearcherMaterialRequest(
                    name="too-big.md",
                    kind="copy",
                    content="x" * 1_000_001,
                ),
                "shelf-big",
            )

    asyncio.run(scenario())


def test_delete_removes_shelf_entry_but_keeps_bytes(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        view = await _attach(
            service,
            project_id,
            AttachResearcherMaterialRequest(
                name="notes.md", kind="copy", content="# Notes\n"
            ),
            "shelf-delete",
        )
        sha = view.content_sha256
        await service.delete_researcher_material(project_id, view.material_id)
        assert await service.list_researcher_materials(project_id) == []
        with pytest.raises(RepositoryNotFoundError):
            await service.get_researcher_material_content(project_id, view.material_id)
        # The content-addressed bytes survive: runs may have sealed them.
        assert sha is not None
        assert service.artifacts.read_bytes(sha) == b"# Notes\n"

    asyncio.run(scenario())


def test_empty_copy_content_fails_model_validation() -> None:
    with pytest.raises(ValueError, match="non-empty content"):
        AttachResearcherMaterialRequest(name="empty.md", kind="copy", content="  ")


def test_link_requires_url() -> None:
    with pytest.raises(ValueError, match="external_url"):
        AttachResearcherMaterialRequest(name="link", kind="link")
