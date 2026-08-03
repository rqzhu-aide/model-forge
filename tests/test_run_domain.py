from __future__ import annotations

from datetime import datetime, timezone

import pytest

from method_hub.domain.identities import PhaseContractIdentity
from method_hub.domain.runs import (
    RunRequest,
    RunStatus,
    require_transition,
)
from method_hub.errors import DomainValidationError


def test_run_request_freezes_user_choices() -> None:
    source = {"p1.instructions": "Find the relevant literature."}
    request = RunRequest(
        project_id="project.demo",
        phase_contract=PhaseContractIdentity(
            "P1",
            "2.0.0",
            "a" * 64,
        ),
        mode="p1.literature_update",
        choice_values=source,
        context_policy="current_only",
        user_id="researcher.demo",
        idempotency_key="request-0001",
    )
    source["p1.instructions"] = "Changed after construction."
    assert request.choice_values["p1.instructions"] == "Find the relevant literature."
    with pytest.raises(TypeError):
        request.choice_values["new"] = "not allowed"  # type: ignore[index]


def test_run_lifecycle_allows_declared_path() -> None:
    path = (
        RunStatus.CREATED,
        RunStatus.PREPARING,
        RunStatus.PREPARED,
        RunStatus.RUNNING,
        RunStatus.SUBMITTED,
        RunStatus.VALIDATING,
        RunStatus.PROMOTING,
        RunStatus.PUBLISHED,
    )
    for current, target in zip(path, path[1:]):
        require_transition(current, target)


def test_run_lifecycle_rejects_automatic_phase_like_restart() -> None:
    with pytest.raises(DomainValidationError) as captured:
        require_transition(RunStatus.PUBLISHED, RunStatus.CREATED)
    assert captured.value.code == "run.invalid_transition"


def test_cancellation_is_not_legal_after_submission() -> None:
    with pytest.raises(DomainValidationError):
        require_transition(RunStatus.SUBMITTED, RunStatus.CANCELLATION_REQUESTED)


def test_datetime_fixture_is_timezone_aware() -> None:
    assert datetime(2026, 8, 2, tzinfo=timezone.utc).utcoffset() is not None
