"""Service-level end-to-end coverage for the ADR-019 seed channel."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from model_forge.api.models import CreateProjectRequest, StartRunRequest
from model_forge.api.ports import RawRequestBody
from model_forge.application.bootstrap import build_service
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings


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
            command_family="start_run" if project_id else "create_project",
            project_id=project_id,
            idempotency_key=key,
        )
    )


async def _project(service: ModelForgeService) -> str:
    create = CreateProjectRequest(
        name="Seed channel e2e",
        research_question="Does supplementary material freeze additively?",
        domains=["statistics"],
        intended_use="Exercise the ADR-019 seed channel end to end.",
    )
    body = json.dumps(create.model_dump(mode="json")).encode("utf-8")
    project = await service.create_project(
        create,
        raw_request=await _receipt(service, body, key="create-seed-e2e", project_id=None),
    )
    return str(project.project_id)


async def _start(service: ModelForgeService, project_id: str, request: StartRunRequest, key: str):
    body = json.dumps(request.model_dump(mode="json")).encode("utf-8")
    return await service.start_run(
        project_id,
        request,
        raw_request=await _receipt(service, body, key=key, project_id=project_id),
    )



async def _settled_detail(service: ModelForgeService, project_id: str, run_id: str):
    # Runs prepare and execute detached; poll until the run settles.
    for _ in range(200):
        detail = await service.get_run(project_id, run_id)
        if detail.state in {"published", "failed", "rejected", "conflicted", "cancelled"}:
            return detail
        await asyncio.sleep(0.025)
    raise AssertionError("run did not settle")

def _base_request(action_descriptor_id: str, selected: list[str], **overrides) -> StartRunRequest:
    return StartRunRequest(
        action_descriptor_id=action_descriptor_id,
        phase="P1",
        mode="p1.literature_update",
        choice_values={
            "p1.scope": "broad_update",
            "p1.instructions": "Update the literature basis.",
            "p1.selected_history": [],
        },
        context_policy="current_only",
        selected_context_option_ids=selected,
        **overrides,
    )


def test_seeded_supplementary_material_freezes_with_provenance(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        phase = await service.get_phase_view(
            project_id, "P1", mode="p1.literature_update", method_id=None
        )
        action = next(item for item in phase.actions if item.action_type == "start_run")
        selected = [item.option_id for item in phase.run_configuration.current_inputs]
        request = _base_request(
            action.descriptor_id,
            selected,
            seed_inputs={
                "p1.researcher_material": {
                    "content": "# Our earlier draft\n\nPartial notes on overlap weighting.",
                    "media_type": "text/markdown",
                }
            },
        )
        run = await _start(service, project_id, request, "seed-e2e-positive")

        detail = await _settled_detail(service, project_id, str(run.run_id))
        seeded = [item for item in detail.frozen_basis if item.origin == "researcher_seed"]
        assert len(seeded) == 1
        assert seeded[0].label == "Researcher Material"
        assert seeded[0].identity == "seed"
        assert all(
            item.origin == "current_record"
            for item in detail.frozen_basis
            if item.label != "Researcher Material"
        )

    asyncio.run(scenario())


def test_external_link_seed_uses_uri_list_media_type(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        phase = await service.get_phase_view(
            project_id, "P1", mode="p1.literature_update", method_id=None
        )
        action = next(item for item in phase.actions if item.action_type == "start_run")
        selected = [item.option_id for item in phase.run_configuration.current_inputs]
        request = _base_request(
            action.descriptor_id,
            selected,
            seed_inputs={
                "p1.researcher_material": {
                    "content": "https://data.example.org/large-archive.tar",
                    "media_type": "text/uri-list",
                }
            },
        )
        run = await _start(service, project_id, request, "seed-e2e-link")
        detail = await _settled_detail(service, project_id, str(run.run_id))
        assert any(item.origin == "researcher_seed" for item in detail.frozen_basis)

    asyncio.run(scenario())


def test_seed_targeting_required_input_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        project_id = await _project(service)
        phase = await service.get_phase_view(
            project_id, "P1", mode="p1.literature_update", method_id=None
        )
        action = next(item for item in phase.actions if item.action_type == "start_run")
        selected = [item.option_id for item in phase.run_configuration.current_inputs]
        request = _base_request(
            action.descriptor_id,
            selected,
            seed_inputs={
                "p1.project_brief": {
                    "content": "# A foreign brief",
                    "media_type": "text/markdown",
                }
            },
        )
        # Preparation is detached: the run must stop safely in a terminal
        # state with the precise rejection as its recorded reason.
        run = await _start(service, project_id, request, "seed-e2e-negative")
        detail = await _settled_detail(service, project_id, str(run.run_id))
        assert detail.state == "failed"
        assert detail.terminal_reason is not None
        assert "Seeds may only supply declared supplementary material" in (
            detail.terminal_reason.message
        )
        assert "p1.project_brief" in detail.terminal_reason.message

    asyncio.run(scenario())
