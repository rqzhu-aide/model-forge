from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from model_forge.api.models import (
    CreateProjectRequest,
    ReasonedActionRequest,
    StartRunRequest,
)
from model_forge.api.ports import RawRequestBody
from model_forge.application.bootstrap import build_service
from model_forge.application.settings import ApplicationSettings
from model_forge.executors import RoleExecutionResult, RoleExecutionStatus
from model_forge.executors.development import SchemaExampleFakeExecutor
from model_forge.storage.repository import HubRepository


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


class _RestartFakeExecutor(SchemaExampleFakeExecutor):
    """External process finishes its work but the harness pass is
    interrupted before close; reconcile stays non-terminal once, then
    returns the completed result."""

    def __init__(self, architecture_root: Path) -> None:
        super().__init__(architecture_root)
        self.completed: dict[str, RoleExecutionResult] = {}
        self.reconcile_suspended = True

    async def execute(self, invocation, observer):
        await observer.launch_intent(invocation)
        external_id = f"fake:{invocation.execution_id}"
        await observer.launch_acknowledged(invocation, external_id)
        for offset, output_path in enumerate(invocation.expected_output_paths, start=1):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(self._example_output(invocation, offset), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        result = RoleExecutionResult(
            RoleExecutionStatus.SUCCEEDED, external_id, 0,
            "Process completed; the harness pass was interrupted before close.",
        )
        self.completed[invocation.execution_id] = result
        await observer.heartbeat(invocation, "interrupted pass")
        return result

    async def reconcile(self, external_execution_id: str):
        if self.reconcile_suspended:
            return None
        return self.completed.get(external_execution_id.removeprefix("fake:"))

    async def cancel(self, external_execution_id: str) -> None:
        return None


def test_restart_with_in_flight_role_recovers(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        coordinator.executor = _RestartFakeExecutor(ARCHITECTURE)

        # One-shot harness-side failure: the FIRST heartbeat append raises;
        # later calls delegate to the original repository method. HubRepository
        # uses __slots__, so the wrap is applied at the class level.
        original_append = HubRepository.append_execution_heartbeat
        heartbeat_calls = 0

        def flaky_append_execution_heartbeat(self, *args, **kwargs):
            nonlocal heartbeat_calls
            heartbeat_calls += 1
            if heartbeat_calls == 1:
                raise sqlite3.OperationalError("database is locked")
            return original_append(self, *args, **kwargs)

        monkeypatch.setattr(
            HubRepository, "append_execution_heartbeat", flaky_append_execution_heartbeat
        )

        project = await _create_project(service, key="create-restart")
        started, _, _ = await _start_phase_one(
            service, project.project_id, key="start-restart"
        )
        assert started.state == "created"

        # Pass 1: the heartbeat raises inside the observer. The harness-side
        # bookkeeping failure must NOT be sealed into a durable FAILED
        # closure; the run stays running.
        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason
        completed_after_pass_one = len(coordinator.executor.completed)

        # Pass 2: the acknowledgement exists and reconcile is still
        # non-terminal, so the pass must leave the run running without
        # re-executing the role.
        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason
        assert len(coordinator.executor.completed) == completed_after_pass_one

        # Pass 3+: reconcile now returns the completed result and the run
        # drives to publication.
        coordinator.executor.reconcile_suspended = False
        for _ in range(10):
            await coordinator.run(started.run_id)
            detail = await service.get_run(project.project_id, started.run_id)
            if detail.state in TERMINAL_STATES:
                break
        assert detail.state == "published", detail.terminal_reason

    asyncio.run(scenario())


def test_pending_execution_watcher_reschedules_run(tmp_path: Path, monkeypatch) -> None:
    """F1 (audit 2026-09-02): a pending acknowledged execution must wake the
    coordinator in-process the moment the external process exits - without
    any further command acceptance, restart, or cancellation notification."""

    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        coordinator._pending_poll_seconds = 0.02
        coordinator.executor = _RestartFakeExecutor(ARCHITECTURE)

        # One-shot harness-side failure: the FIRST heartbeat append raises,
        # leaving an acknowledged in-flight execution with the run `running`.
        original_append = HubRepository.append_execution_heartbeat
        heartbeat_calls = 0

        def flaky_append_execution_heartbeat(self, *args, **kwargs):
            nonlocal heartbeat_calls
            heartbeat_calls += 1
            if heartbeat_calls == 1:
                raise sqlite3.OperationalError("database is locked")
            return original_append(self, *args, **kwargs)

        monkeypatch.setattr(
            HubRepository, "append_execution_heartbeat", flaky_append_execution_heartbeat
        )

        project = await _create_project(service, key="create-watcher")
        started, _, _ = await _start_phase_one(
            service, project.project_id, key="start-watcher"
        )

        # Pass 1: heartbeat failure -> run stays `running` with an
        # acknowledged execution.
        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason

        # Pass 2: reconcile is non-terminal -> RoleExecutionPending; the
        # pending watcher starts inside the coordinator.
        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason

        # The external process now exits. WITHOUT calling coordinator.run()
        # again, the watcher must re-schedule the run to a terminal state.
        coordinator.executor.reconcile_suspended = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        while True:
            detail = await service.get_run(project.project_id, started.run_id)
            if detail.state in TERMINAL_STATES:
                break
            assert loop.time() < deadline, (
                "Pending-execution watcher never re-scheduled the run; "
                f"state is still {detail.state!r}."
            )
            await asyncio.sleep(0.02)
        assert detail.state == "published", detail.terminal_reason

        closures = service.repository.list_role_closures_for_run(started.run_id)
        assert closures
        for closure in closures:
            payload = json.loads(closure["payload_json"])
            assert payload["status"] == "succeeded", payload

    asyncio.run(scenario())


class _NullIdentityVersionExecutor(SchemaExampleFakeExecutor):
    """Emit schema examples whose identity block carries a null version."""

    def _example_output(self, invocation, offset):
        document = super()._example_output(invocation, offset)
        if isinstance(document, dict):
            document["identity"] = {"version": None}
        elif isinstance(document, list):
            for item in document:
                if isinstance(item, dict):
                    item["identity"] = {"version": None}
        return document


def test_null_identity_version_is_coerced_during_repair(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        coordinator.executor = _NullIdentityVersionExecutor(ARCHITECTURE)

        project = await _create_project(service, key="create-null-version")
        started, _, _ = await _start_phase_one(
            service, project.project_id, key="start-null-version"
        )
        assert started.state == "created"

        detail = None
        for _ in range(10):
            await coordinator.run(started.run_id)
            detail = await service.get_run(project.project_id, started.run_id)
            if detail.state in TERMINAL_STATES:
                break
        assert detail.state == "published", detail.terminal_reason

    asyncio.run(scenario())
