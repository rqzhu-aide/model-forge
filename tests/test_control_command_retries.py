from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from method_hub.api.errors import CommandRejected
from method_hub.api.models import (
    CreateProjectRequest,
    ReasonedActionRequest,
    StartRunRequest,
)
from method_hub.api.ports import RawRequestBody
from method_hub.application.service import MethodHubService
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.specification import SpecificationPackage
from method_hub.storage.artifacts import ArtifactStore
from method_hub.storage.paths import WorkspacePaths
from method_hub.storage.repository import HubRepository


ROOT = Path(__file__).resolve().parents[1]


async def _do_nothing(_run_id: str) -> None:
    return None


def _service(tmp_path: Path) -> tuple[MethodHubService, HubRepository]:
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "hub.sqlite3")
    repository.initialize()
    service = MethodHubService(
        settings=ApplicationSettings(data_root=workspace.root),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(ROOT / "resources" / "team"),
        run_launcher=_do_nothing,
    )
    return service, repository


def _raw(
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str | None,
) -> RawRequestBody:
    return RawRequestBody(
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


async def _create_project(service: MethodHubService) -> str:
    command = CreateProjectRequest(
        name="Controlled retry test",
        research_question="Which estimator remains reliable under weak overlap?",
        domains=["statistics", "machine learning"],
        intended_use="Exercise explicit controlled operations.",
    )
    body = json.dumps(command.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    receipt = await service.preserve_raw_request(
        _raw(body, family="create_project", key="create-project", project_id=None)
    )
    return (await service.create_project(command, raw_request=receipt)).project_id


async def _start_command(
    service: MethodHubService, project_id: str
) -> tuple[StartRunRequest, bytes]:
    phase = await service.get_phase_view(
        project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    action = next(item for item in phase.actions if item.action_type == "start_run")
    command = StartRunRequest(
        action_descriptor_id=action.descriptor_id,
        phase="P1",
        mode="p1.literature_update",
        choice_values={
            "p1.scope": "focused_update",
            "p1.instructions": "Review the focused literature question.",
            "p1.selected_history": [],
        },
        context_policy="current_only",
        selected_context_option_ids=[
            item.option_id
            for item in phase.run_configuration.current_inputs
            if item.selected_by_default
        ],
    )
    body = json.dumps(command.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    return command, body


async def _submit_start(
    service: MethodHubService,
    project_id: str,
    command: StartRunRequest,
    body: bytes,
    *,
    key: str,
):
    receipt = await service.preserve_raw_request(
        _raw(body, family="start_run", key=key, project_id=project_id)
    )
    return await service.start_run(project_id, command, raw_request=receipt)


async def _submit_cancel(
    service: MethodHubService,
    project_id: str,
    run_id: str,
    command: ReasonedActionRequest,
    body: bytes,
    *,
    key: str,
):
    receipt = await service.preserve_raw_request(
        _raw(body, family="cancel_run", key=key, project_id=project_id)
    )
    return await service.cancel_run(
        project_id,
        run_id,
        command,
        raw_request=receipt,
    )


def _advance_run(
    repository: HubRepository,
    run_id: str,
    *,
    new_state: str,
) -> None:
    row = repository.get_run(run_id)
    event = {
        "event_type": "test.state_changed",
        "message": "Change the run state before retrying the command.",
        "occurred_at": "2026-08-02T00:00:00Z",
    }
    result = repository.compare_and_swap_run(
        run_id,
        str(row["status"]),
        int(row["head_sequence"]),
        new_state,
        json.loads(str(row["payload_json"])),
        f"event.test.{run_id}.{new_state}",
        hashlib.sha256(json.dumps(event, sort_keys=True).encode("utf-8")).hexdigest(),
        event,
    )
    assert result.applied


def test_start_run_retry_returns_original_run_without_revalidating_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        service, repository = _service(tmp_path)
        project_id = await _create_project(service)
        command, body = await _start_command(service, project_id)
        first = await _submit_start(
            service, project_id, command, body, key="start-controlled-run"
        )
        _advance_run(repository, first.run_id, new_state="running")

        async def unexpected_projection(*_args, **_kwargs):
            raise AssertionError("an accepted command retry must not revalidate the UI action")

        monkeypatch.setattr(service, "get_phase_view", unexpected_projection)
        repeated = await _submit_start(
            service, project_id, command, body, key="start-controlled-run"
        )

        assert repeated.run_id == first.run_id
        assert repeated.state == "running"

    asyncio.run(scenario())


def test_start_run_rejects_changed_body_under_the_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        service, _repository = _service(tmp_path)
        project_id = await _create_project(service)
        command, body = await _start_command(service, project_id)
        await _submit_start(
            service, project_id, command, body, key="start-body-bound"
        )
        changed_values = dict(command.choice_values)
        changed_values["p1.instructions"] = "Use a materially different literature scope."
        changed = command.model_copy(update={"choice_values": changed_values})
        changed_body = json.dumps(
            changed.model_dump(mode="json"), sort_keys=True
        ).encode("utf-8")

        async def unexpected_projection(*_args, **_kwargs):
            raise AssertionError("body identity must be checked before the UI action")

        monkeypatch.setattr(service, "get_phase_view", unexpected_projection)
        with pytest.raises(CommandRejected) as raised:
            await _submit_start(
                service,
                project_id,
                changed,
                changed_body,
                key="start-body-bound",
            )

        assert raised.value.error.code == "IDEMPOTENCY_KEY_REUSED"

    asyncio.run(scenario())


def test_cancel_run_retry_returns_current_terminal_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, repository = _service(tmp_path)
        project_id = await _create_project(service)
        start, start_body = await _start_command(service, project_id)
        run = await _submit_start(
            service, project_id, start, start_body, key="start-for-cancel"
        )
        cancel_action = next(
            item for item in run.actions if item.action_type == "cancel_run"
        )
        cancel = ReasonedActionRequest(
            action_descriptor_id=cancel_action.descriptor_id,
            reason="Stop this controlled run before any further work starts.",
        )
        cancel_body = json.dumps(
            cancel.model_dump(mode="json"), sort_keys=True
        ).encode("utf-8")
        first = await _submit_cancel(
            service,
            project_id,
            run.run_id,
            cancel,
            cancel_body,
            key="cancel-controlled-run",
        )
        assert first.state == "cancellation_requested"
        _advance_run(repository, run.run_id, new_state="cancelled")

        repeated = await _submit_cancel(
            service,
            project_id,
            run.run_id,
            cancel,
            cancel_body,
            key="cancel-controlled-run",
        )

        assert repeated.run_id == run.run_id
        assert repeated.state == "cancelled"

    asyncio.run(scenario())


def test_cancel_run_rejects_changed_body_under_the_same_key(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, _repository = _service(tmp_path)
        project_id = await _create_project(service)
        start, start_body = await _start_command(service, project_id)
        run = await _submit_start(
            service, project_id, start, start_body, key="start-cancel-body"
        )
        cancel_action = next(
            item for item in run.actions if item.action_type == "cancel_run"
        )
        cancel = ReasonedActionRequest(
            action_descriptor_id=cancel_action.descriptor_id,
            reason="Stop this run because its scope is no longer useful.",
        )
        cancel_body = json.dumps(
            cancel.model_dump(mode="json"), sort_keys=True
        ).encode("utf-8")
        await _submit_cancel(
            service,
            project_id,
            run.run_id,
            cancel,
            cancel_body,
            key="cancel-body-bound",
        )
        changed = cancel.model_copy(
            update={"reason": "Stop this run for a different stated reason."}
        )
        changed_body = json.dumps(
            changed.model_dump(mode="json"), sort_keys=True
        ).encode("utf-8")

        with pytest.raises(CommandRejected) as raised:
            await _submit_cancel(
                service,
                project_id,
                run.run_id,
                changed,
                changed_body,
                key="cancel-body-bound",
            )

        assert raised.value.error.code == "IDEMPOTENCY_KEY_REUSED"

    asyncio.run(scenario())
