"""F1 (audit 2026-09-02): post-restart success detection from on-disk outputs.

A reconcile that reports FAILED with no exit code means the external process
merely vanished while the server was down. When every declared expected
output exists in the workspace, the closure must seal succeeded and let
output validation judge the bytes; a missing output keeps the honest
failure.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from model_forge.api.models import (
    CreateProjectRequest,
    StartRunRequest,
)
from model_forge.api.ports import RawRequestBody
from model_forge.application.bootstrap import build_service
from model_forge.application.settings import ApplicationSettings
from model_forge.executors import (
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)
from model_forge.executors.development import SchemaExampleFakeExecutor
from model_forge.harness.role_execution import RoleLifecycleService
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
        name="Restart output recovery test",
        research_question="Which method remains reliable under weak overlap?",
        domains=["statistics", "machine learning"],
        intended_use="Exercise post-restart success detection.",
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
    return await service.start_run(
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


class _VanishedProcessExecutor(SchemaExampleFakeExecutor):
    """Execute writes every declared output and acknowledges; reconcile then
    reports the process merely vanished (FAILED with no exit code), exactly
    as local_hermes maps a gone PID after a restart."""

    def __init__(self, architecture_root: Path) -> None:
        super().__init__(architecture_root)
        self.invocations_seen: list[RoleInvocation] = []

    async def execute(self, invocation, observer):
        await observer.launch_intent(invocation)
        external_id = f"fake:{invocation.execution_id}"
        await observer.launch_acknowledged(invocation, external_id)
        self.invocations_seen.append(invocation)
        for offset, output_path in enumerate(invocation.expected_output_paths, start=1):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(self._example_output(invocation, offset), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        await observer.heartbeat(invocation, "outputs written")
        return RoleExecutionResult(
            RoleExecutionStatus.SUCCEEDED, external_id, 0,
            "Process completed; the harness pass was interrupted before close.",
        )

    async def reconcile(self, external_execution_id: str):
        return RoleExecutionResult(
            status=RoleExecutionStatus.FAILED,
            external_execution_id=external_execution_id,
            exit_code=None,
            summary="Hermes process exited (no longer exists).",
            diagnostic_text="Process not found during restart reconciliation.",
        )

    async def cancel(self, external_execution_id: str) -> None:
        return None


def _flaky_first_heartbeat(monkeypatch) -> None:
    """One-shot harness-side failure leaving an acknowledged execution with
    the run `running` (simulating the restart mid-pass)."""
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


async def _drive_to_terminal(service, coordinator, project_id: str, run_id: str):
    detail = None
    for _ in range(10):
        await coordinator.run(run_id)
        detail = await service.get_run(project_id, run_id)
        if detail.state in TERMINAL_STATES:
            break
    return detail


def test_vanished_process_with_all_outputs_recovers_success(
    tmp_path: Path, monkeypatch
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        coordinator._pending_poll_seconds = 0.02
        coordinator.executor = _VanishedProcessExecutor(ARCHITECTURE)
        _flaky_first_heartbeat(monkeypatch)

        project = await _create_project(service, key="create-recover-success")
        started = await _start_phase_one(
            service, project.project_id, key="start-recover-success"
        )

        # Pass 1: heartbeat failure leaves an acknowledged execution whose
        # outputs are all on disk; the run stays `running`.
        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason

        # Pass 2+: reconcile reports a vanished process (FAILED, exit_code
        # None) but every declared output exists, so the closure seals
        # succeeded and validation judges the real bytes.
        detail = await _drive_to_terminal(
            service, coordinator, project.project_id, started.run_id
        )
        assert detail.state == "published", detail.terminal_reason

        closures = service.repository.list_role_closures_for_run(started.run_id)
        assert closures
        recovered = [
            json.loads(closure["payload_json"]) for closure in closures
        ]
        assert all(payload["status"] == "succeeded" for payload in recovered), recovered
        assert any(
            "Recovered post-restart from on-disk outputs"
            in payload["diagnostic_text"]
            for payload in recovered
        ), recovered

    asyncio.run(scenario())


def test_vanished_process_with_missing_output_keeps_honest_failure(
    tmp_path: Path, monkeypatch
) -> None:
    async def scenario() -> None:
        service = _service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        coordinator._pending_poll_seconds = 0.02
        coordinator.executor = _VanishedProcessExecutor(ARCHITECTURE)
        _flaky_first_heartbeat(monkeypatch)

        project = await _create_project(service, key="create-recover-failure")
        started = await _start_phase_one(
            service, project.project_id, key="start-recover-failure"
        )

        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason

        # One declared output of the first interrupted role never landed.
        first_invocation = coordinator.executor.invocations_seen[0]
        missing = first_invocation.expected_output_paths[0]
        missing.unlink()
        assert not missing.exists()

        detail = await _drive_to_terminal(
            service, coordinator, project.project_id, started.run_id
        )
        assert detail.state == "failed", detail.terminal_reason

        closures = service.repository.list_role_closures_for_run(started.run_id)
        assert closures
        payloads = [json.loads(closure["payload_json"]) for closure in closures]
        assert any(payload["status"] == "failed" for payload in payloads), payloads

    asyncio.run(scenario())


def _failed_vanished_result() -> RoleExecutionResult:
    return RoleExecutionResult(
        status=RoleExecutionStatus.FAILED,
        external_execution_id="external.test",
        exit_code=None,
        summary="Hermes process exited (no longer exists).",
        diagnostic_text="Process not found during restart reconciliation.",
        captured_stdout="partial stdout",
        captured_stderr="partial stderr",
    )


def _invocation(paths: tuple[Path, ...]) -> RoleInvocation:
    return RoleInvocation(
        execution_id="execution.test",
        invocation_id="invocation.test",
        run_id="run.test",
        project_id="project.test",
        phase="P1",
        mode="p1.literature_update",
        stage_id="stage.test",
        role="role.test",
        profile="profile.test",
        workspace=Path("."),
        task_brief=Path("brief.md"),
        expected_output_paths=paths,
    )


def test_recover_completed_execution_no_expected_paths_returns_none() -> None:
    service = object.__new__(RoleLifecycleService)
    result = service._recover_completed_execution(
        _invocation(()), _failed_vanished_result()
    )
    assert result is None


def test_recover_completed_execution_missing_output_returns_none(
    tmp_path: Path,
) -> None:
    service = object.__new__(RoleLifecycleService)
    missing = tmp_path / "never-written.json"
    result = service._recover_completed_execution(
        _invocation((missing,)), _failed_vanished_result()
    )
    assert result is None


def test_recover_completed_execution_empty_output_returns_none(
    tmp_path: Path,
) -> None:
    service = object.__new__(RoleLifecycleService)
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    result = service._recover_completed_execution(
        _invocation((empty,)), _failed_vanished_result()
    )
    assert result is None


def test_recover_completed_execution_all_outputs_present_succeeds(
    tmp_path: Path,
) -> None:
    service = object.__new__(RoleLifecycleService)
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    first.write_text('{"ok": 1}\n', encoding="utf-8")
    second.write_text('{"ok": 2}\n', encoding="utf-8")

    failed = _failed_vanished_result()
    result = service._recover_completed_execution(
        _invocation((first, second)), failed
    )
    assert result is not None
    assert result.status is RoleExecutionStatus.SUCCEEDED
    assert result.external_execution_id == "external.test"
    assert result.exit_code is None
    assert "declared outputs are present" in result.summary
    assert "Recovered post-restart from on-disk outputs" in result.diagnostic_text
    assert failed.summary in result.diagnostic_text
    assert result.captured_stdout == "partial stdout"
    assert result.captured_stderr == "partial stderr"
