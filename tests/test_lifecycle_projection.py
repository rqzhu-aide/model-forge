"""Tests for the HV-3 lifecycle projection.

Exercises every one of the 13 RunStatus values through the projection
computation and asserts the correct recovery_summary, execution_state,
conformance_state, and publication_state.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from method_hub.application.run_views import _compute_projection


def _payload(
    *,
    code: str = "",
    message: str = "test",
    closure_findings: list[dict[str, Any]] | None = None,
    scientific_outcome: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if code:
        payload["terminal_reason"] = {"code": code, "message": message}
    if closure_findings is not None:
        payload["closure_findings"] = closure_findings
    if scientific_outcome is not None:
        payload["scientific_outcome"] = scientific_outcome
    return payload


# --------------------------------------------------------------------------- #
# recovery_summary must cover all 13 states                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("status", "code", "expected_recovery"),
    [
        # Non-terminal → in_progress
        ("created", "", "in_progress"),
        ("preparing", "", "in_progress"),
        ("prepared", "", "in_progress"),
        ("running", "", "in_progress"),
        ("cancellation_requested", "", "in_progress"),
        ("submitted", "", "in_progress"),
        ("validating", "", "in_progress"),
        ("promoting", "", "in_progress"),
        # Terminal success
        ("published", "", "ok"),
        # Terminal cancelled
        ("cancelled", "run.cancelled_by_user", "cancelled"),
        # Terminal conflicted
        ("conflicted", "publication.basis_changed", "conflicted"),
    ],
)
def test_recovery_summary_for_non_failed_states(
    status: str, code: str, expected_recovery: str
) -> None:
    """Non-failed/non-rejected states must map to the right recovery_summary."""
    proj = _compute_projection(status, _payload(code=code))
    assert proj.recovery_summary == expected_recovery, (
        f"status={status}: expected {expected_recovery}, got {proj.recovery_summary}"
    )


def test_recovery_summary_failed_executor() -> None:
    """Executor failure → recovery_summary=failed."""
    proj = _compute_projection(
        "failed", _payload(code="executor.unrequested_cancellation")
    )
    assert proj.recovery_summary == "failed"
    assert proj.execution_state == "failed"


def test_recovery_summary_failed_orchestration() -> None:
    """Orchestration failure → recovery_summary=failed."""
    proj = _compute_projection(
        "failed", _payload(code="orchestration.failed")
    )
    assert proj.recovery_summary == "failed"


def test_recovery_summary_failed_output_correction() -> None:
    """Output validation failure → recovery_summary=needs_output_correction."""
    proj = _compute_projection(
        "failed",
        _payload(
            code="output.structural_validation_failed",
            closure_findings=[
                {
                    "code": "submission.required_output_missing",
                    "finding_class": "correctable_contract_error",
                    "blocks_publication": True,
                },
            ],
        ),
    )
    assert proj.recovery_summary == "needs_output_correction"
    assert proj.execution_state == "completed"
    assert proj.conformance_state == "correction_required"


def test_recovery_summary_rejected_correction() -> None:
    """Submission rejection with correctable findings → needs_output_correction."""
    proj = _compute_projection(
        "rejected",
        _payload(
            code="submission.validation_failed",
            closure_findings=[
                {
                    "code": "submission.invalid_output_entry",
                    "finding_class": "correctable_contract_error",
                    "blocks_publication": True,
                },
            ],
        ),
    )
    assert proj.recovery_summary == "needs_output_correction"
    assert proj.conformance_state == "correction_required"


def test_recovery_summary_rejected_integrity() -> None:
    """Submission rejection with integrity blocker → rejected."""
    proj = _compute_projection(
        "rejected",
        _payload(
            code="submission.validation_failed",
            closure_findings=[
                {
                    "code": "submission.digest_mismatch",
                    "finding_class": "integrity_blocker",
                    "blocks_publication": True,
                },
            ],
        ),
    )
    assert proj.recovery_summary == "rejected"
    assert proj.conformance_state == "integrity_rejected"


# --------------------------------------------------------------------------- #
# execution_state                                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("status", "code", "expected_exec"),
    [
        ("created", "", "not_started"),
        ("preparing", "", "not_started"),
        ("prepared", "", "not_started"),
        ("running", "", "running"),
        ("submitted", "", "running"),
        ("validating", "", "running"),
        ("promoting", "", "running"),
        ("published", "", "completed"),
        ("cancelled", "run.cancelled_by_user", "cancelled"),
        ("conflicted", "publication.basis_changed", "completed"),
        # failed depends on failure_code
        ("failed", "executor.timeout", "failed"),
        ("failed", "output.structural_validation_failed", "completed"),
        ("rejected", "submission.validation_failed", "completed"),
    ],
)
def test_execution_state(
    status: str, code: str, expected_exec: str
) -> None:
    proj = _compute_projection(status, _payload(code=code))
    assert proj.execution_state == expected_exec


# --------------------------------------------------------------------------- #
# conformance_state                                                           #
# --------------------------------------------------------------------------- #

def test_conformance_passed_for_published() -> None:
    proj = _compute_projection("published", _payload())
    assert proj.conformance_state == "passed"


def test_conformance_not_checked_for_validating() -> None:
    proj = _compute_projection("validating", _payload())
    assert proj.conformance_state == "not_checked"


def test_conformance_correction_required_for_correctable_failed() -> None:
    proj = _compute_projection(
        "failed",
        _payload(
            code="output.structural_validation_failed",
            closure_findings=[
                {
                    "code": "output.required_missing",
                    "finding_class": "correctable_contract_error",
                    "blocks_publication": True,
                },
            ],
        ),
    )
    assert proj.conformance_state == "correction_required"


def test_conformance_integrity_rejected_for_digest_mismatch() -> None:
    proj = _compute_projection(
        "rejected",
        _payload(
            code="submission.validation_failed",
            closure_findings=[
                {
                    "code": "submission.digest_mismatch",
                    "finding_class": "integrity_blocker",
                    "blocks_publication": True,
                },
            ],
        ),
    )
    assert proj.conformance_state == "integrity_rejected"


# --------------------------------------------------------------------------- #
# publication_state                                                           #
# --------------------------------------------------------------------------- #

def test_publication_state_published_with_receipt() -> None:
    proj = _compute_projection(
        "published", _payload(), has_publication=True
    )
    assert proj.publication_state == "published"


def test_publication_state_withheld_for_failed() -> None:
    proj = _compute_projection(
        "failed", _payload(code="executor.timeout")
    )
    assert proj.publication_state == "withheld"


def test_publication_state_conflicted() -> None:
    proj = _compute_projection(
        "conflicted", _payload(code="publication.basis_changed")
    )
    assert proj.publication_state == "conflicted"


def test_publication_state_not_attempted_for_running() -> None:
    proj = _compute_projection("running", _payload())
    assert proj.publication_state == "not_attempted"


# --------------------------------------------------------------------------- #
# Finding classification and counting                                          #
# --------------------------------------------------------------------------- #

def test_finding_counts() -> None:
    """blocking_finding_count and correctable_finding_count are computed correctly."""
    proj = _compute_projection(
        "rejected",
        _payload(
            code="submission.validation_failed",
            closure_findings=[
                {"code": "output.required_missing",
                 "finding_class": "correctable_contract_error",
                 "blocks_publication": True},
                {"code": "submission.invalid_output_entry",
                 "finding_class": "correctable_contract_error",
                 "blocks_publication": True},
                {"code": "submission.digest_mismatch",
                 "finding_class": "integrity_blocker",
                 "blocks_publication": True},
                {"code": "p3.informational",
                 "finding_class": "information",
                 "blocks_publication": False},
            ],
        ),
    )
    assert proj.blocking_finding_count == 3
    assert proj.correctable_finding_count == 2


def test_finding_groups() -> None:
    """Finding groups are computed correctly."""
    proj = _compute_projection(
        "rejected",
        _payload(
            code="submission.validation_failed",
            closure_findings=[
                {"code": "output.required_missing",
                 "finding_class": "correctable_contract_error",
                 "blocks_publication": True},
                {"code": "submission.digest_mismatch",
                 "finding_class": "integrity_blocker",
                 "blocks_publication": True},
            ],
        ),
    )
    assert len(proj.finding_groups) == 2
    classes = {g.finding_class for g in proj.finding_groups}
    assert "correctable_contract_error" in classes
    assert "integrity_blocker" in classes


def test_zero_findings() -> None:
    """No findings → all counts zero, groups empty."""
    proj = _compute_projection("failed", _payload(code="executor.timeout"))
    assert proj.blocking_finding_count == 0
    assert proj.correctable_finding_count == 0
    assert proj.finding_groups == []


# --------------------------------------------------------------------------- #
# Recovery controls (empty until HV-5)                                        #
# --------------------------------------------------------------------------- #

def test_recovery_controls_empty() -> None:
    """available_recovery_controls must be empty until HV-5 lands."""
    for status in ("failed", "rejected", "published", "running"):
        proj = _compute_projection(status, _payload())
        assert proj.available_recovery_controls == []


# --------------------------------------------------------------------------- #
# has_publication affects publication_state                                    #
# --------------------------------------------------------------------------- #

def test_has_publication_overrides_publication_state() -> None:
    """Even for non-published status, a receipt means published."""
    proj = _compute_projection(
        "promoting", _payload(), has_publication=True
    )
    assert proj.publication_state == "published"


# --------------------------------------------------------------------------- #
# Scientific outcome passthrough                                              #
# --------------------------------------------------------------------------- #

def test_scientific_outcome_passthrough() -> None:
    """scientific_outcome from payload is passed through."""
    proj = _compute_projection(
        "published",
        _payload(scientific_outcome="supported"),
    )
    assert proj.scientific_outcome == "supported"


def test_scientific_outcome_none_by_default() -> None:
    proj = _compute_projection("published", _payload())
    assert proj.scientific_outcome is None


def test_failed_harness_fault_findings_route_to_plain_failed() -> None:
    """K5-2/ADR-015: findings recorded but none correctable (harness faults)
    -> plain failed recovery, not a correction promise."""
    proj = _compute_projection(
        "failed",
        _payload(
            code="output.structural_validation_failed",
            closure_findings=[
                {
                    "code": "schema.required",
                    "finding_class": "operational_failure",
                    "blocks_publication": True,
                    "message": "The harness could not satisfy its own field 'to_role'.",
                },
            ],
        ),
    )
    assert proj.recovery_summary == "failed"
    assert proj.conformance_state == "integrity_rejected"
    assert proj.correctable_finding_count == 0


def test_failed_output_failure_without_findings_keeps_legacy_routing() -> None:
    """Pre-K5-2 rows carry no closure_findings; the fallback branch still
    marks them correction_required (display heuristic only)."""
    proj = _compute_projection(
        "failed",
        _payload(code="output.structural_validation_failed"),
    )
    assert proj.recovery_summary == "needs_output_correction"
    assert proj.conformance_state == "correction_required"
    assert proj.correctable_finding_count == 0
