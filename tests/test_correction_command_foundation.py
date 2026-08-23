"""K-1a5 foundation: correction error codes, API models, closure lookup,
and the attempt-aware submission read (HV-5 revision A1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from model_forge.api.errors import CommandError, new_command_error
from model_forge.api.models import CorrectionPreviewRequest, CorrectionRequest
from model_forge.harness.execution_records import document_sha256
from model_forge.harness.outputs import build_output_plan
from model_forge.harness.submission_validation import validate_submission
from model_forge.specification import SpecificationPackage
from model_forge.storage import ArtifactStore, WorkspacePaths
from model_forge.storage.repository import HubRepository

ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def _digest(character: str) -> str:
    return character * 64


# --------------------------------------------------------------------------- #
# Correction command error codes
# --------------------------------------------------------------------------- #

CORRECTION_POLICIES = [
    ("CORRECTION_NOT_APPLICABLE", "transition", 409, False, "MF-73"),
    ("CORRECTION_SCOPE_INVALID", "schema", 400, True, "MF-74"),
    ("CORRECTION_EXHAUSTED", "transition", 409, False, "MF-75"),
]


@pytest.mark.parametrize(
    ("code", "category", "http_status", "retryable", "rule_id"),
    CORRECTION_POLICIES,
)
def test_correction_error_codes_use_registered_mapping(
    code: str,
    category: str,
    http_status: int,
    retryable: bool,
    rule_id: str,
) -> None:
    error = new_command_error(
        code,  # type: ignore[arg-type]
        researcher_message="The correction command was refused.",
        smallest_correction="Resolve the run state and submit a new command.",
    )
    assert error.code == code
    assert error.category == category
    assert error.http_status == http_status
    assert error.retryable is retryable
    assert error.rule_id == rule_id


@pytest.mark.parametrize(
    ("code", "category", "http_status", "retryable", "rule_id"),
    CORRECTION_POLICIES,
)
def test_correction_error_codes_reject_wrong_mapping(
    code: str,
    category: str,
    http_status: int,
    retryable: bool,
    rule_id: str,
) -> None:
    with pytest.raises(ValidationError):
        CommandError(
            error_id="error.test",
            code=code,  # type: ignore[arg-type]
            category="digest" if category != "digest" else "schema",  # type: ignore[arg-type]
            http_status=418,
            retryable=not retryable,
            rule_id="MF-99",
            object_refs=[],
            researcher_message="The correction command was refused.",
            smallest_correction="Resolve the run state and submit a new command.",
            occurred_at="2026-08-17T00:00:00Z",
        )


# --------------------------------------------------------------------------- #
# Correction API models
# --------------------------------------------------------------------------- #


def test_correction_request_accepts_revalidate() -> None:
    request = CorrectionRequest(
        correction_type="revalidate",
        permitted_output_scope=["p1.source_changes"],
        action_descriptor_id="action.correct",
    )
    assert request.user_instruction is None
    assert request.transformation_codes == []


def test_correction_request_accepts_normalize_with_transformations() -> None:
    request = CorrectionRequest(
        correction_type="normalize",
        permitted_output_scope=["p1.source_changes"],
        action_descriptor_id="action.correct",
        transformation_codes=["strip_control_characters"],
    )
    assert request.transformation_codes == ["strip_control_characters"]


def test_correction_request_accepts_scientific_with_instruction() -> None:
    request = CorrectionRequest(
        correction_type="scientific",
        permitted_output_scope=["p1.source_changes"],
        action_descriptor_id="action.correct",
        user_instruction="Broaden the search window to ten years.",
    )
    assert request.user_instruction == "Broaden the search window to ten years."


def test_correction_request_accepts_packaging() -> None:
    request = CorrectionRequest(
        correction_type="packaging",
        permitted_output_scope=["p1.source_changes"],
        action_descriptor_id="action.correct",
    )
    assert request.correction_type == "packaging"


def test_correction_request_rejects_instruction_on_revalidate() -> None:
    with pytest.raises(ValidationError):
        CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=["p1.source_changes"],
            action_descriptor_id="action.correct",
            user_instruction="Not permitted here.",
        )


def test_correction_request_rejects_transformations_on_packaging() -> None:
    with pytest.raises(ValidationError):
        CorrectionRequest(
            correction_type="packaging",
            permitted_output_scope=["p1.source_changes"],
            action_descriptor_id="action.correct",
            transformation_codes=["strip_control_characters"],
        )


def test_correction_request_rejects_unknown_correction_type() -> None:
    with pytest.raises(ValidationError):
        CorrectionRequest(
            correction_type="regenerate",  # type: ignore[arg-type]
            permitted_output_scope=["p1.source_changes"],
            action_descriptor_id="action.correct",
        )


def test_correction_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=["p1.source_changes"],
            action_descriptor_id="action.correct",
            unexpected="field",  # type: ignore[call-arg]
        )


def test_correction_request_rejects_empty_scope() -> None:
    with pytest.raises(ValidationError):
        CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=[],
            action_descriptor_id="action.correct",
        )


def test_correction_preview_request_defaults_to_no_transformations() -> None:
    assert CorrectionPreviewRequest().transformation_codes == []
    request = CorrectionPreviewRequest(transformation_codes=["collapse_whitespace"])
    assert request.transformation_codes == ["collapse_whitespace"]


# --------------------------------------------------------------------------- #
# Repository fixture helpers (mirrors tests/test_hub_repository.py)
# --------------------------------------------------------------------------- #


@pytest.fixture
def repository(tmp_path: Path) -> HubRepository:
    result = HubRepository(tmp_path / "hub.sqlite3")
    assert result.initialize() == 13
    result.create_project("prj_correction", {"name": "Correction foundation"})
    return result


def _command(repository: HubRepository, suffix: str) -> str:
    request_id = f"req_{suffix}"
    command_id = f"cmd_{suffix}"
    repository.record_raw_command(
        request_id,
        "prj_correction",
        _digest("a"),
        {"request": suffix},
    )
    repository.seal_command(
        command_id,
        "prj_correction",
        request_id,
        f"key_{suffix}",
        _digest("b"),
        {"command": suffix},
    )
    return command_id


def _run(repository: HubRepository, suffix: str) -> str:
    command_id = _command(repository, suffix)
    run_id = f"run_{suffix}"
    repository.create_run(
        run_id,
        "prj_correction",
        command_id,
        "created",
        {"state": "created"},
        f"evt_{suffix}_created",
        _digest("c"),
        {"to": "created"},
    )
    return run_id


# --------------------------------------------------------------------------- #
# list_role_closures_for_run
# --------------------------------------------------------------------------- #


def test_list_role_closures_for_run_returns_closures_in_closed_at_order(
    repository: HubRepository,
) -> None:
    run_id = _run(repository, "closures")
    repository.get_or_create_execution(
        "exec_a", "inv_a", run_id, _digest("5"), {"role": "analyst"}
    )
    repository.get_or_create_execution(
        "exec_b", "inv_b", run_id, _digest("6"), {"role": "reviewer"}
    )
    repository.close_execution(
        "exec_a",
        "closure_a",
        _digest("7"),
        {"status": "succeeded"},
        closed_at="2026-08-17T00:00:02Z",
    )
    repository.close_execution(
        "exec_b",
        "closure_b",
        _digest("8"),
        {"status": "succeeded"},
        closed_at="2026-08-17T00:00:01Z",
    )

    rows = repository.list_role_closures_for_run(run_id)

    assert [row["closure_id"] for row in rows] == ["closure_b", "closure_a"]


def test_list_role_closures_for_run_returns_empty_for_unknown_run(
    repository: HubRepository,
) -> None:
    assert repository.list_role_closures_for_run("run.unknown") == []


# --------------------------------------------------------------------------- #
# Attempt-aware submission read
# --------------------------------------------------------------------------- #


class _PermissiveSchemas:
    """Schema catalog stand-in: structural schema findings are not the
    subject of these tests."""

    def validate(self, schema_ref: str, document: object) -> tuple:
        return ()


class _SubmissionFixture:
    def __init__(self, tmp_path: Path) -> None:
        specification = SpecificationPackage.load(ARCHITECTURE)
        identity = specification.phases.identity("P1")
        self.plan = specification.resolve_phase(
            identity,
            "p1.literature_update",
            {
                "p1.scope": "broad_update",
                "p1.instructions": "Update the literature basis.",
                "p1.selected_history": [],
            },
            "current_only",
        )
        self.output_plan = build_output_plan(self.plan)
        workspace = WorkspacePaths(tmp_path / "workspace", create=True)
        self.artifacts = ArtifactStore(workspace)
        self.repository = HubRepository(workspace.root / "hub.sqlite3")
        self.repository.initialize()
        self.repository.create_project("prj_correction", {"name": "Correction"})
        self.project_id = "prj_correction"


@pytest.fixture
def submission_fixture(tmp_path: Path) -> _SubmissionFixture:
    return _SubmissionFixture(tmp_path)


def _submission_payload(
    fixture: _SubmissionFixture, project_id: str
) -> tuple[dict, str]:
    payload = {
        "project_id": project_id,
        "phase": fixture.plan.identity.phase_id,
        "mode": fixture.plan.mode_id,
        "closure_chain": [],
        "submitted_artifacts": [],
    }
    digest = document_sha256(payload)
    payload["submission_sha256"] = digest
    return payload, digest


def _validate(fixture: _SubmissionFixture, run_id: str):
    return validate_submission(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        schemas=_PermissiveSchemas(),  # type: ignore[arg-type]
        project_id=fixture.project_id,
        run_id=run_id,
        plan=fixture.plan,
        output_plan=fixture.output_plan,
        selected_method=None,
    )


def test_validate_submission_prefers_latest_attempt(
    submission_fixture: _SubmissionFixture,
) -> None:
    fixture = submission_fixture
    run_id = _run(fixture.repository, "attempt_aware")
    # The base submission carries the WRONG project (fails project_mismatch);
    # the correction attempt carries the right one (passes that check).
    base_payload, base_sha = _submission_payload(fixture, "prj_other")
    sealed = fixture.repository.seal_submission(
        run_id,
        "submission_base",
        base_sha,
        "created",
        1,
        "submitted",
        base_payload,
        {"state": "submitted"},
        "evt_attempt_aware_submitted",
        _digest("9"),
        {"to": "submitted"},
    )
    assert sealed.applied is True
    attempt_payload, attempt_sha = _submission_payload(fixture, fixture.project_id)
    fixture.repository.insert_submission_attempt(
        run_id,
        "attempt_1",
        "submission_attempt_1",
        1,
        json.dumps(attempt_payload, sort_keys=True),
        attempt_sha,
        correction_command_id="cmd_correction",
        correction_type="revalidate",
    )

    result = _validate(fixture, run_id)

    codes = {finding.code for finding in result.findings}
    assert "submission.project_mismatch" not in codes
    assert result.submission.get("submission_sha256") == attempt_sha


def test_validate_submission_falls_back_to_base_submission(
    submission_fixture: _SubmissionFixture,
) -> None:
    fixture = submission_fixture
    run_id = _run(fixture.repository, "base_only")
    base_payload, base_sha = _submission_payload(fixture, "prj_other")
    sealed = fixture.repository.seal_submission(
        run_id,
        "submission_base",
        base_sha,
        "created",
        1,
        "submitted",
        base_payload,
        {"state": "submitted"},
        "evt_base_only_submitted",
        _digest("9"),
        {"to": "submitted"},
    )
    assert sealed.applied is True

    result = _validate(fixture, run_id)

    codes = {finding.code for finding in result.findings}
    assert "submission.project_mismatch" in codes
    assert result.submission.get("submission_sha256") == base_sha
