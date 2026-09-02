"""Audit-2026-09-02 Pkg C: cancellation integrity regressions (F5, F6).

F5: a ``compare_and_swap_failed`` from ``request_cancellation`` must raise
CONTROL_HEAD_STALE instead of silently dropping the cancellation behind an
already-sealed idempotency key.

F6: a durable launch intent with no acknowledgement (the crash window
between ``observer.launch_intent`` and the ack inside ``executor.execute``)
must settle to a sealed ``cancelled`` closure with a diagnostic, not wedge
the run in ``cancellation_requested`` forever.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from model_forge.api.errors import CommandRejected
from model_forge.api.models import ReasonedActionRequest
from model_forge.executors.development import SchemaExampleFakeExecutor
from model_forge.harness.execution_records import RoleExecutionPending
from model_forge.storage.repository import HubRepository, RunTransitionResult

from test_control_command_retries import (
    _create_project,
    _raw,
    _service as _command_service,
    _start_command,
    _submit_start,
)
from test_run_coordinator_recovery import (
    _create_project as _create_recovery_project,
    _service as _recovery_service,
    _start_phase_one,
)

ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


# --------------------------------------------------------------------------- #
# F5: cancel CAS race surfaces CONTROL_HEAD_STALE (no silent drop)
# --------------------------------------------------------------------------- #


def test_cancel_run_cas_race_surfaces_stale_head_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        service, repository = _command_service(tmp_path)
        project_id = await _create_project(service)
        start, start_body = await _start_command(service, project_id)
        run = await _submit_start(
            service, project_id, start, start_body, key="start-for-cancel-race"
        )
        detail = await service.get_run(project_id, run.run_id)
        cancel_action = next(
            item for item in detail.actions if item.action_type == "cancel_run"
        )
        cancel = ReasonedActionRequest(
            action_descriptor_id=cancel_action.descriptor_id,
            reason="Stop this run; the head moved while cancelling.",
        )
        cancel_body = json.dumps(
            cancel.model_dump(mode="json"), sort_keys=True
        ).encode("utf-8")

        # Force the race: a concurrent lifecycle event bumps the head between
        # the service's get_run and the repository CAS.
        def cas_lost(self, raced_run_id, *_args, **_kwargs):  # noqa: ANN001, ANN201, ANN202
            return RunTransitionResult(
                False, "compare_and_swap_failed", self.get_run(raced_run_id)
            )

        monkeypatch.setattr(HubRepository, "request_cancellation", cas_lost)

        receipt = await service.preserve_raw_request(
            _raw(
                cancel_body,
                family="cancel_run",
                key="cancel-cas-race",
                project_id=project_id,
            )
        )
        with pytest.raises(CommandRejected) as raised:
            await service.cancel_run(
                project_id, run.run_id, cancel, raw_request=receipt
            )

        error = raised.value.error
        assert error.code == "CONTROL_HEAD_STALE"
        assert error.researcher_message == (
            "The run changed while the cancellation was being requested."
        )
        assert error.smallest_correction == "Refresh the run and cancel again."
        assert error.object_refs[0] == run.run_id

        # The command row IS sealed (raw preservation by design) and the
        # error carries the sealed command's identity; the cancellation
        # itself was NOT recorded.
        command_row = repository.get_command_by_idempotency(
            project_id, receipt.request_artifact_id
        )
        assert command_row is not None
        assert str(command_row["command_id"]) in error.object_refs
        assert repository.get_run(run.run_id)["status"] == "created"

        # A fresh retry with a NEW idempotency key applies cleanly.
        monkeypatch.undo()
        fresh_receipt = await service.preserve_raw_request(
            _raw(
                cancel_body,
                family="cancel_run",
                key="cancel-cas-race-fresh",
                project_id=project_id,
            )
        )
        retried = await service.cancel_run(
            project_id, run.run_id, cancel, raw_request=fresh_receipt
        )
        assert retried.state == "cancellation_requested"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# F6: intent without acknowledgement settles cancelled, no wedge
# --------------------------------------------------------------------------- #


class _CrashAfterIntentExecutor(SchemaExampleFakeExecutor):
    """Record the durable launch intent, then the harness 'crashes' before
    the acknowledgement inside ``execute`` - the F6 crash window."""

    async def execute(self, invocation, observer):  # noqa: ANN001, ANN201, ANN202
        await observer.launch_intent(invocation)
        raise RoleExecutionPending(
            "Simulated harness crash after the launch intent for "
            f"{invocation.execution_id}; no acknowledgement was recorded."
        )


def test_intent_without_acknowledgement_settles_cancelled(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = _recovery_service(tmp_path)
        coordinator = service.run_launcher.__self__
        service.run_launcher = None
        service.cancellation_notifier = None
        coordinator.executor = _CrashAfterIntentExecutor(ARCHITECTURE)

        project = await _create_recovery_project(service, key="create-f6")
        started, _, _ = await _start_phase_one(
            service, project.project_id, key="start-f6"
        )

        # Pass 1: every p1.discovery role records its launch intent, then the
        # harness 'crash' raises before any acknowledgement; the coordinator
        # leaves the run `running` (pending semantics).
        await coordinator.run(started.run_id)
        detail = await service.get_run(project.project_id, started.run_id)
        assert detail.state == "running", detail.terminal_reason
        with service.repository.database.connect() as connection:
            intents = connection.execute(
                "SELECT execution_id FROM role_execution_intents "
                "WHERE run_id = ?",
                (started.run_id,),
            ).fetchall()
            acknowledgements = connection.execute(
                "SELECT execution_id FROM role_execution_acknowledgements "
                "WHERE execution_id IN (SELECT execution_id FROM "
                "role_execution_intents WHERE run_id = ?)",
                (started.run_id,),
            ).fetchall()
        assert len(intents) == 3
        assert acknowledgements == []

        # The researcher cancels the wedged-shape run.
        cancel_action = next(
            item for item in detail.actions if item.action_type == "cancel_run"
        )
        cancel = ReasonedActionRequest(
            action_descriptor_id=cancel_action.descriptor_id,
            reason="Stop the run whose launch never acknowledged.",
        )
        cancel_body = json.dumps(cancel.model_dump(mode="json")).encode("utf-8")
        cancelling = await service.cancel_run(
            project.project_id,
            started.run_id,
            cancel,
            raw_request=await service.preserve_raw_request(
                _raw(
                    cancel_body,
                    family="cancel_run",
                    key="cancel-f6",
                    project_id=project.project_id,
                )
            ),
        )
        assert cancelling.state == "cancellation_requested"

        # Pass 2: settlement seals each intent-only execution cancelled with
        # a diagnostic and the run reaches its cancelled terminal state.
        await coordinator.run(started.run_id)
        settled = await service.get_run(project.project_id, started.run_id)
        assert settled.state == "cancelled", settled.terminal_reason
        assert settled.terminal_reason is not None
        assert settled.terminal_reason.code == "run.cancelled_by_user"

        closures = service.repository.list_role_closures_for_run(started.run_id)
        assert len(closures) == 3
        for row in closures:
            payload = json.loads(str(row["payload_json"]))
            assert payload["status"] == "cancelled", payload
            assert payload["external_execution_id"] is None
            assert payload["exit_code"] is None
            assert payload["summary"] == (
                "Cancelled before the execution was acknowledged; "
                "no external process was launched."
            )
            assert "launch intent" in str(payload["diagnostic_text"])

        # Pass 3 (restart replay): the settle pass converges with no raise,
        # no new closures, and the run stays cancelled.
        await coordinator.run(started.run_id)
        replayed = await service.get_run(project.project_id, started.run_id)
        assert replayed.state == "cancelled"
        assert (
            len(service.repository.list_role_closures_for_run(started.run_id)) == 3
        )

    asyncio.run(scenario())
