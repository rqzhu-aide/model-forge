"""F4 (audit 2026-09-02): correction close-path infrastructure containment.

A transient repository failure while the correction close path records the
bounded validation attempt must surface as ``RoleExecutionInfrastructureError``
(non-sealing, retryable) - never as a run-fatal generic error.  The
correction closure is NOT sealed and no attempt row is written.

The drive mirrors tests/test_correction_lane_b.py's packaging-correction
flow: a failed base closure is sealed with schema-conforming bytes, then a
Lane B correction re-invocation runs under the correction identity.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from pathlib import Path

import pytest

from model_forge.application.correction_execution import execute_targeted_correction
from model_forge.executors import DeterministicFakeExecutor
from model_forge.harness.execution_records import (
    RoleExecutionInfrastructureError,
    correction_role_identity,
)
from model_forge.harness.stage_execution import HarnessExecutionServices
from model_forge.storage.repository import HubRepository

from test_correction_command_path import (
    RUN,
    _scope,
    _seal_failed_closure_bytes,
)
from test_correction_execution import _Fixture, _PermissiveSchemas
from test_correction_normalize import _fixable_defect_bytes
from test_correction_submission import _golden_output


def test_correction_attempt_record_failure_is_infrastructure_error(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )

    context = dataclasses.replace(
        fixture.context,
        submission_from_status="correcting",
        correction_command_id="cmd_infra",
        correction_type="packaging",
    )
    services = HarnessExecutionServices(
        context=context,
        repository=fixture.repository,
        executor=fixture.executor,
        schemas=_PermissiveSchemas(),
        artifacts=fixture.artifacts,
        workspace=fixture.workspace,
    )

    def flaky_record_validation_attempt(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        HubRepository, "record_validation_attempt", flaky_record_validation_attempt
    )

    with pytest.raises(RoleExecutionInfrastructureError):
        asyncio.run(
            execute_targeted_correction(
                services=services,
                repository=fixture.repository,
                specification=fixture.specification,
                artifacts=fixture.artifacts,
                run_id=RUN,
                role_closure_id=base_closure_id,
                correction_command_id="cmd_infra",
                correction_type="packaging",
                permitted_output_scope=(_scope(fixture),),
                user_instruction=None,
            )
        )

    # Not sealed, not run-fatal: no correction closure, no attempt row, and
    # the run row keeps its pre-correction status.
    c_closure_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", "cmd_infra"
    )[2]
    assert fixture.repository.get_role_closure(c_closure_id) is None
    assert fixture.repository.list_validation_attempts(RUN) == []
    assert fixture.repository.get_run(RUN)["status"] == "running"
