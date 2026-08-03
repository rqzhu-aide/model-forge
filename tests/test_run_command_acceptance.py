from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from method_hub.api.errors import CommandRejected
from method_hub.api.models import CreateProjectRequest, StartRunRequest
from method_hub.api.ports import RawRequestBody
from method_hub.application.service import MethodHubService
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.specification import SpecificationPackage
from method_hub.storage.artifacts import ArtifactStore
from method_hub.storage.paths import WorkspacePaths
from method_hub.storage.repository import HubRepository


ROOT = Path(__file__).resolve().parents[1]


async def _no_role_work(_run_id: str) -> None:
    return None


def _service(tmp_path: Path) -> MethodHubService:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    return MethodHubService(
        settings=ApplicationSettings(data_root=workspace.root),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(ROOT / "resources" / "team"),
        run_launcher=_no_role_work,
    )


async def _receipt(
    service: MethodHubService,
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str | None,
):
    return await service.preserve_raw_request(
        RawRequestBody(
            body=body,
            byte_length=len(body),
            media_type="application/json",
            content_sha256=hashlib.sha256(body).hexdigest(),
            method="POST",
            path="/api/v1/projects",
            command_family=family,  # type: ignore[arg-type]
            project_id=project_id,
            idempotency_key=key,
        )
    )


def test_invalid_choices_and_current_context_are_rejected_before_run_creation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        create = CreateProjectRequest(
            name="Run acceptance test",
            research_question="Which estimator is stable under weak overlap?",
            domains=["statistics"],
            intended_use="Check command acceptance before role execution.",
        )
        create_body = json.dumps(create.model_dump(mode="json")).encode("utf-8")
        project = await service.create_project(
            create,
            raw_request=await _receipt(
                service,
                create_body,
                family="create_project",
                key="create-acceptance",
                project_id=None,
            ),
        )
        phase = await service.get_phase_view(
            project.project_id,
            "P1",
            mode="p1.literature_update",
            method_id=None,
        )
        action = next(item for item in phase.actions if item.action_type == "start_run")
        selected = [
            item.option_id for item in phase.run_configuration.current_inputs
        ]
        base = StartRunRequest(
            action_descriptor_id=action.descriptor_id,
            phase="P1",
            mode="p1.literature_update",
            choice_values={
                "p1.scope": "broad_update",
                "p1.instructions": "Update the literature basis.",
                "p1.selected_history": [],
            },
            context_policy="current_only",
            selected_context_option_ids=selected,
        )

        invalid_choice = base.model_copy(
            update={
                "choice_values": {
                    **base.choice_values,
                    "p1.scope": "unsupported_scope",
                }
            }
        )
        missing_required = base.model_copy(
            update={"selected_context_option_ids": []}
        )
        unknown_context = base.model_copy(
            update={"selected_context_option_ids": [*selected, "p1.unknown"]}
        )
        cases = (
            (invalid_choice, "invalid-choice", "COMMAND_SCHEMA_INVALID"),
            (
                missing_required,
                "missing-required-context",
                "DEPENDENCY_CLOSURE_INCOMPLETE",
            ),
            (unknown_context, "unknown-context", "COMMAND_SCHEMA_INVALID"),
        )
        for command, key, expected_code in cases:
            body = json.dumps(command.model_dump(mode="json")).encode("utf-8")
            with pytest.raises(CommandRejected) as raised:
                await service.start_run(
                    project.project_id,
                    command,
                    raw_request=await _receipt(
                        service,
                        body,
                        family="start_run",
                        key=key,
                        project_id=project.project_id,
                    ),
                )
            assert raised.value.error.code == expected_code

        assert service.queries.list_runs(project.project_id) == ()

    asyncio.run(scenario())


def test_start_run_request_rejects_duplicate_current_input_ids() -> None:
    with pytest.raises(ValidationError):
        StartRunRequest(
            action_descriptor_id="action.test",
            phase="P1",
            mode="p1.literature_update",
            choice_values={"p1.instructions": "Test."},
            context_policy="current_only",
            selected_context_option_ids=["p1.project_brief", "p1.project_brief"],
        )
