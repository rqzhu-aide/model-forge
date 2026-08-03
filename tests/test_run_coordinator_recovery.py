from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from method_hub.api.models import (
    CreateProjectRequest,
    ReasonedActionRequest,
    StartRunRequest,
)
from method_hub.api.ports import RawRequestBody
from method_hub.application.bootstrap import build_service
from method_hub.application.settings import ApplicationSettings


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
TERMINAL_STATES = {
    "published",
    "failed",
    "rejected",
    "conflicted",
    "cancelled",
}


def _raw(
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str | None = None,
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


async def _create_project(service, *, key: str):
    command = CreateProjectRequest(
        name="Coordinator durability test",
        research_question="Which method remains reliable under weak overlap?",
        domains=["statistics", "machine learning"],
        intended_use="Exercise a durable manually authorized research run.",
    )
    body = json.dumps(command.model_dump()).encode("utf-8")
    return await service.create_project(
        command,
        raw_request=await service.preserve_raw_request(
            _raw(body, family="create_project", key=key)
        ),
    )


async def _start_phase_one(service, project_id: str, *, key: str):
    phase = await service.get_phase_view(
        project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    action = next(item for item in phase.actions if item.action_type == "start_run")
    selected = [item.option_id for item in phase.run_configuration.current_inputs]
    command = StartRunRequest(
        action_descriptor_id=action.descriptor_id,
        phase="P1",
        mode="p1.literature_update",
        choice_values={
            "p1.scope": "focused_update",
            "p1.instructions": "Check the focused literature question and its limits.",
            "p1.selected_history": [],
        },
        context_policy="current_only",
        selected_context_option_ids=selected,
    )
    body = json.dumps(command.model_dump()).encode("utf-8")
    started = await service.start_run(
        project_id,
        command,
        raw_request=await service.preserve_raw_request(
            _raw(
                body,
                family="start_run",
                key=key,
                project_id=project_id,
            )
        ),
    )
    return started, command, selected


async def _wait_for_terminal(service, project_id: str, run_id: str):
    for _ in range(200):
        detail = await service.get_run(project_id, run_id)
        if detail.state in TERMINAL_STATES:
            return detail
        await asyncio.sleep(0.025)
    return await service.get_run(project_id, run_id)


def _service(tmp_path: Path):
    return build_service(
        ApplicationSettings(
            data_root=tmp_path / "data",
            architecture_root=ARCHITECTURE,
            executor_kind="fake",
            development_mode=True,
            frontend_dist=tmp_path / "missing-web",
        )
    )


def test_startup_recovery_preserves_request_and_terminal_resume_is_a_noop(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        project = await _create_project(service, key="create-recovery")
        started, command, selected = await _start_phase_one(
            service, project.project_id, key="start-recovery"
        )
        assert started.state == "created"

        await service.resume_incomplete()
        detail = await _wait_for_terminal(service, project.project_id, started.run_id)
        assert detail.state == "published", detail.terminal_reason
        assert detail.publication_receipt is not None

        run_payload = json.loads(
            service.repository.get_run(started.run_id)["payload_json"]
        )
        assert run_payload["phase"] == "P1"
        assert run_payload["mode"] == "p1.literature_update"
        assert run_payload["requested_by"] == "researcher.local"
        assert run_payload["choice_values"] == command.choice_values
        assert run_payload["selected_current_input_ids"] == selected
        assert run_payload["submission_id"]
        assert run_payload["submission_sha256"]

        receipt_id = detail.publication_receipt.publication_id
        event_count = len(service.repository.list_run_events(started.run_id))
        current_records = [
            (row["logical_slot"], row["generation_id"])
            for row in service.repository.list_current_records(project.project_id)
        ]
        invocation_count = len(coordinator.executor.invocations)

        await coordinator.run(started.run_id)
        await coordinator.run(started.run_id)

        resumed = await service.get_run(project.project_id, started.run_id)
        assert resumed.state == "published"
        assert resumed.publication_receipt is not None
        assert resumed.publication_receipt.publication_id == receipt_id
        assert len(service.repository.list_run_events(started.run_id)) == event_count
        assert len(coordinator.executor.invocations) == invocation_count
        assert [
            (row["logical_slot"], row["generation_id"])
            for row in service.repository.list_current_records(project.project_id)
        ] == current_records

    asyncio.run(scenario())


def test_cancellation_before_preparation_starts_no_role_or_publication(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        service.cancellation_notifier = None
        project = await _create_project(service, key="create-cancel")
        before = [
            (row["logical_slot"], row["generation_id"])
            for row in service.repository.list_current_records(project.project_id)
        ]
        started, _, _ = await _start_phase_one(
            service, project.project_id, key="start-cancel"
        )
        cancel_action = next(
            item for item in started.actions if item.action_type == "cancel_run"
        )
        cancel = ReasonedActionRequest(
            action_descriptor_id=cancel_action.descriptor_id,
            reason="The researcher withdrew this run before work started.",
        )
        cancel_body = json.dumps(cancel.model_dump()).encode("utf-8")
        cancelling = await service.cancel_run(
            project.project_id,
            started.run_id,
            cancel,
            raw_request=await service.preserve_raw_request(
                _raw(
                    cancel_body,
                    family="cancel_run",
                    key="cancel-before-start",
                    project_id=project.project_id,
                )
            ),
        )
        assert cancelling.state == "cancellation_requested"

        await coordinator.run(started.run_id)

        cancelled = await service.get_run(project.project_id, started.run_id)
        assert cancelled.state == "cancelled"
        assert cancelled.terminal_reason is not None
        assert cancelled.terminal_reason.code == "run.cancelled_by_user"
        assert coordinator.executor.invocations == []
        assert [
            (row["logical_slot"], row["generation_id"])
            for row in service.repository.list_current_records(project.project_id)
        ] == before
        assert (
            service.repository.get_publication_receipt_for_run(started.run_id) is None
        )

    asyncio.run(scenario())
