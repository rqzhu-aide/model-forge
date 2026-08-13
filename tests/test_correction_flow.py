"""Tests for HV-5 bounded user-controlled recovery.

Exercises:
1. Correction state transitions (failed/rejected → correction_authorized → correcting → submitted/exhausted)
2. OutputCorrectionCommand scope validation
3. ValidationAttempt chain
4. Revalidation (Action 1)
5. Normalization (Action 2) with allowlisted codes
6. Correction instruction builder (Action 3)
7. Attempt bounds (HV-5.6)
8. Restart reconciliation (HV-5.8)
9. Lifecycle projection for correction states
"""

from __future__ import annotations

import pytest

from method_hub.application.correction import (
    ALLOWED_NORMALIZE_CODES,
    MAX_PACKAGING_ATTEMPTS,
    MAX_SCIENTIFIC_ATTEMPTS,
    OutputCorrectionCommand,
    ValidationAttempt,
    build_correction_instruction,
    check_correction_bounds,
    is_correction_exhausted,
    normalize,
    revalidate,
)
from method_hub.domain.runs import RunStatus, TERMINAL_RUN_STATUSES
from method_hub.domain.runs import require_transition
from method_hub.domain.validation import (
    FindingClass,
    OutputTransformationRecord,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    make_finding,
)
from method_hub.application.run_views import _compute_projection


# --------------------------------------------------------------------------- #
# HV-5.1: State transitions                                                   #
# --------------------------------------------------------------------------- #


class TestCorrectionStateTransitions:
    """Verify the correction state machine edges."""

    def test_failed_can_transition_to_correction_authorized(self) -> None:
        """FAILED → CORRECTION_AUTHORIZED must be a valid transition."""
        require_transition(RunStatus.FAILED, RunStatus.CORRECTION_AUTHORIZED)

    def test_rejected_can_transition_to_correction_authorized(self) -> None:
        """REJECTED → CORRECTION_AUTHORIZED must be a valid transition."""
        require_transition(RunStatus.REJECTED, RunStatus.CORRECTION_AUTHORIZED)

    def test_correction_authorized_to_correcting(self) -> None:
        require_transition(
            RunStatus.CORRECTION_AUTHORIZED, RunStatus.CORRECTING
        )

    def test_correction_authorized_to_exhausted(self) -> None:
        require_transition(
            RunStatus.CORRECTION_AUTHORIZED, RunStatus.CORRECTION_EXHAUSTED
        )

    def test_correcting_to_submitted(self) -> None:
        require_transition(RunStatus.CORRECTING, RunStatus.SUBMITTED)

    def test_correcting_to_exhausted(self) -> None:
        require_transition(
            RunStatus.CORRECTING, RunStatus.CORRECTION_EXHAUSTED
        )

    def test_correction_exhausted_is_terminal(self) -> None:
        assert RunStatus.CORRECTION_EXHAUSTED in TERMINAL_RUN_STATUSES

    def test_correction_exhausted_has_no_outgoing(self) -> None:
        """CORRECTION_EXHAUSTED must be terminal with no outgoing edges."""
        from method_hub.domain.runs import _TRANSITIONS
        assert _TRANSITIONS[RunStatus.CORRECTION_EXHAUSTED] == frozenset()

    def test_failed_still_has_correction_outgoing(self) -> None:
        """FAILED is no longer truly terminal — it has a correction path."""
        from method_hub.domain.runs import _TRANSITIONS
        assert RunStatus.CORRECTION_AUTHORIZED in _TRANSITIONS[RunStatus.FAILED]

    def test_rejected_still_has_correction_outgoing(self) -> None:
        """REJECTED is no longer truly terminal — it has a correction path."""
        from method_hub.domain.runs import _TRANSITIONS
        assert RunStatus.CORRECTION_AUTHORIZED in _TRANSITIONS[RunStatus.REJECTED]


# --------------------------------------------------------------------------- #
# HV-5.2: OutputCorrectionCommand                                            #
# --------------------------------------------------------------------------- #


class TestOutputCorrectionCommand:

    def test_command_id_is_deterministic(self) -> None:
        """Same inputs → same command ID."""
        cmd1 = OutputCorrectionCommand(
            run_id="run-001",
            correction_type="packaging",
            permitted_output_scope=("output.1",),
            expected_lifecycle_head="abc",
        )
        cmd2 = OutputCorrectionCommand(
            run_id="run-001",
            correction_type="packaging",
            permitted_output_scope=("output.1",),
            expected_lifecycle_head="abc",
        )
        assert cmd1.correction_command_id == cmd2.correction_command_id

    def test_command_id_differs_by_type(self) -> None:
        cmd1 = OutputCorrectionCommand(
            run_id="run-001",
            correction_type="packaging",
            permitted_output_scope=("output.1",),
            expected_lifecycle_head="abc",
        )
        cmd2 = OutputCorrectionCommand(
            run_id="run-001",
            correction_type="scientific",
            permitted_output_scope=("output.1",),
            expected_lifecycle_head="abc",
        )
        assert cmd1.correction_command_id != cmd2.correction_command_id

    def test_scope_validation_passes(self) -> None:
        cmd = OutputCorrectionCommand(
            run_id="run-001",
            correction_type="packaging",
            permitted_output_scope=("output.1", "output.2"),
            expected_lifecycle_head="abc",
        )
        cmd.validate_scope(("output.1",))

    def test_scope_validation_rejects_out_of_scope(self) -> None:
        cmd = OutputCorrectionCommand(
            run_id="run-001",
            correction_type="packaging",
            permitted_output_scope=("output.1",),
            expected_lifecycle_head="abc",
        )
        with pytest.raises(ValueError, match="outside the permitted scope"):
            cmd.validate_scope(("output.99",))


# --------------------------------------------------------------------------- #
# HV-5.2: ValidationAttempt                                                  #
# --------------------------------------------------------------------------- #


class TestValidationAttempt:

    def test_attempt_has_id_and_timestamp(self) -> None:
        report = ValidationReport.from_findings("r1", "run-001", "test", [])
        attempt = ValidationAttempt(
            attempt_id="attempt.run-001.1",
            run_id="run-001",
            policy_version="1.0.0",
            report=report,
            source_sha256="a" * 64,
        )
        assert attempt.attempt_id == "attempt.run-001.1"
        assert len(attempt.attempted_at) > 0
        assert not attempt.is_correction

    def test_correction_attempt_is_marked(self) -> None:
        report = ValidationReport.from_findings("r1", "run-001", "test", [])
        attempt = ValidationAttempt(
            attempt_id="attempt.run-001.2",
            run_id="run-001",
            policy_version="1.0.0",
            report=report,
            source_sha256="a" * 64,
            correction_type="revalidate",
            prior_attempt_id="attempt.run-001.1",
        )
        assert attempt.is_correction
        assert attempt.prior_attempt_id == "attempt.run-001.1"

    def test_attempt_passed_reflects_report(self) -> None:
        finding = make_finding("submission.digest_mismatch", "bad", "obj")
        report = ValidationReport.from_findings("r1", "run-001", "test", [finding])
        attempt = ValidationAttempt(
            attempt_id="attempt.run-001.1",
            run_id="run-001",
            policy_version="1.0.0",
            report=report,
            source_sha256="a" * 64,
        )
        assert not attempt.passed


# --------------------------------------------------------------------------- #
# HV-5.3: Revalidation (Action 1)                                            #
# --------------------------------------------------------------------------- #


class TestRevalidation:

    def test_revalidate_creates_attempt(self) -> None:
        """Revalidation produces a new attempt with the same report."""
        report = ValidationReport.from_findings("r1", "run-001", "test", [])
        result = revalidate(
            run_id="run-001",
            sealed_output_sha256="a" * 64,
            validation_report=report,
            policy_version="1.0.0",
            prior_attempt_id="attempt.run-001.1",
            attempt_ordinal=2,
        )
        assert result.attempt.correction_type == "revalidate"
        assert result.attempt.prior_attempt_id == "attempt.run-001.1"
        assert result.attempt.passed
        assert result.attempt.source_sha256 == "a" * 64

    def test_revalidate_preserves_unchanged_digest(self) -> None:
        """The source digest must be unchanged — no transformation applied."""
        report = ValidationReport.from_findings("r1", "run-001", "test", [])
        result = revalidate(
            run_id="run-001",
            sealed_output_sha256="b" * 64,
            validation_report=report,
            policy_version="1.0.0",
        )
        assert result.attempt.source_sha256 == "b" * 64


# --------------------------------------------------------------------------- #
# HV-5.4: Normalization (Action 2)                                           #
# --------------------------------------------------------------------------- #


class TestNormalization:

    def _transform_record(self) -> OutputTransformationRecord:
        return OutputTransformationRecord(
            contract_output_id="output.1",
            source_sha256="a" * 64,
            result_sha256="b" * 64,
        )

    def test_normalize_with_allowlisted_codes(self) -> None:
        report = ValidationReport.from_findings("r1", "run-001", "test", [])
        result = normalize(
            run_id="run-001",
            transformation_codes=("timestamp_injection", "hash_recomputation"),
            transformation_record=self._transform_record(),
            validation_report=report,
            policy_version="1.0.0",
            attempt_ordinal=2,
        )
        assert result.attempt.correction_type == "normalize"
        assert result.transformation_record is not None

    def test_normalize_rejects_disallowed_codes(self) -> None:
        """Non-allowlisted transformation codes must be rejected."""
        report = ValidationReport.from_findings("r1", "run-001", "test", [])
        result = normalize(
            run_id="run-001",
            transformation_codes=("semantic_rewrite",),  # not allowlisted
            transformation_record=self._transform_record(),
            validation_report=report,
            policy_version="1.0.0",
            attempt_ordinal=2,
        )
        assert len(result.findings) == 1
        assert result.findings[0].blocks_publication

    def test_allowed_normalize_codes_are_mechanical(self) -> None:
        """All allowlisted codes must be mechanical, not scientific."""
        assert "timestamp_injection" in ALLOWED_NORMALIZE_CODES
        assert "id_sanitization" in ALLOWED_NORMALIZE_CODES
        assert "hash_recomputation" in ALLOWED_NORMALIZE_CODES
        assert "additional_properties_strip" in ALLOWED_NORMALIZE_CODES
        # No scientific codes allowed
        assert "claim_revision" not in ALLOWED_NORMALIZE_CODES
        assert "evidence_addition" not in ALLOWED_NORMALIZE_CODES


# --------------------------------------------------------------------------- #
# HV-5.5: Correction instruction builder (Action 3)                         #
# --------------------------------------------------------------------------- #


class TestCorrectionInstruction:

    def test_packaging_instruction_is_clear(self) -> None:
        findings = (
            make_finding("output.required_missing", "Missing field", "obj"),
        )
        instruction = build_correction_instruction(
            correction_type="packaging",
            findings=findings,
            output_scope=("output.1",),
        )
        assert "packaging" in instruction.lower()
        assert "output.1" in instruction
        assert "output.required_missing" in instruction

    def test_scientific_instruction_is_clear(self) -> None:
        findings = (
            make_finding("p5.claim_without_evidence", "Claim lacks evidence", "c1"),
        )
        instruction = build_correction_instruction(
            correction_type="scientific",
            findings=findings,
            output_scope=("output.2",),
        )
        assert "scientific" in instruction.lower()
        assert "output.2" in instruction
        assert "p5.claim_without_evidence" in instruction

    def test_instruction_includes_user_guidance(self) -> None:
        findings = (make_finding("output.required_missing", "Missing", "obj"),)
        instruction = build_correction_instruction(
            correction_type="packaging",
            findings=findings,
            output_scope=("output.1",),
            user_instruction="Fix the timestamp format",
        )
        assert "Fix the timestamp format" in instruction


# --------------------------------------------------------------------------- #
# HV-5.6: Attempt bounds                                                     #
# --------------------------------------------------------------------------- #


class TestAttemptBounds:

    def test_first_packaging_attempt_allowed(self) -> None:
        assert check_correction_bounds(
            correction_type="packaging",
            prior_packaging_attempts=0,
            prior_scientific_attempts=0,
        )

    def test_second_packaging_attempt_rejected(self) -> None:
        assert not check_correction_bounds(
            correction_type="packaging",
            prior_packaging_attempts=MAX_PACKAGING_ATTEMPTS,
            prior_scientific_attempts=0,
        )

    def test_first_scientific_attempt_allowed(self) -> None:
        assert check_correction_bounds(
            correction_type="scientific",
            prior_packaging_attempts=1,
            prior_scientific_attempts=0,
        )

    def test_second_scientific_attempt_rejected(self) -> None:
        assert not check_correction_bounds(
            correction_type="scientific",
            prior_packaging_attempts=1,
            prior_scientific_attempts=MAX_SCIENTIFIC_ATTEMPTS,
        )

    def test_revalidate_has_no_bounds(self) -> None:
        """Revalidation is always allowed regardless of prior attempts."""
        assert check_correction_bounds(
            correction_type="revalidate",
            prior_packaging_attempts=10,
            prior_scientific_attempts=10,
        )

    def test_normalize_has_no_bounds(self) -> None:
        assert check_correction_bounds(
            correction_type="normalize",
            prior_packaging_attempts=10,
            prior_scientific_attempts=10,
        )

    def test_exhaustion_detection(self) -> None:
        """Both packaging and scientific exhausted → correction_exhausted."""
        assert is_correction_exhausted(
            prior_packaging_attempts=MAX_PACKAGING_ATTEMPTS,
            prior_scientific_attempts=MAX_SCIENTIFIC_ATTEMPTS,
        )

    def test_not_exhausted_if_one_remaining(self) -> None:
        assert not is_correction_exhausted(
            prior_packaging_attempts=0,
            prior_scientific_attempts=MAX_SCIENTIFIC_ATTEMPTS,
        )


# --------------------------------------------------------------------------- #
# HV-5.8: Restart reconciliation                                             #
# --------------------------------------------------------------------------- #


class TestRestartReconciliation:

    def test_correction_exhausted_listed_as_terminal(self) -> None:
        """correction_exhausted runs must NOT be listed as incomplete."""
        from method_hub.storage.repository import HubRepository
        import inspect
        source = inspect.getsource(HubRepository.list_incomplete_runs)
        assert "correction_exhausted" in source

    def test_correction_states_not_auto_relaunched(self) -> None:
        """The coordinator run loop must return on correction states."""
        from method_hub.application.run_coordinator import RunCoordinator
        import inspect
        source = inspect.getsource(RunCoordinator.run)
        assert "correction_authorized" in source
        assert "correcting" in source


# --------------------------------------------------------------------------- #
# HV-5.7: Lifecycle projection for correction states                         #
# --------------------------------------------------------------------------- #


class TestProjectionForCorrectionStates:

    def test_correction_authorized_is_in_progress(self) -> None:
        proj = _compute_projection("correction_authorized", {})
        assert proj.recovery_summary == "in_progress"

    def test_correcting_is_in_progress(self) -> None:
        proj = _compute_projection("correcting", {})
        assert proj.recovery_summary == "in_progress"

    def test_correction_exhausted_projection(self) -> None:
        proj = _compute_projection("correction_exhausted", {})
        assert proj.recovery_summary == "correction_exhausted"
        assert proj.execution_state == "completed"
        assert proj.conformance_state == "correction_required"
        assert proj.publication_state == "withheld"

    def test_recovery_controls_empty_until_endpoints_land(self) -> None:
        """available_recovery_controls must be empty until HV-5 endpoints exist."""
        proj = _compute_projection(
            "failed",
            {
                "terminal_reason": {"code": "output.structural_validation_failed"},
                "closure_findings": [
                    {
                        "code": "output.required_missing",
                        "finding_class": "correctable_contract_error",
                        "blocks_publication": True,
                    }
                ],
            },
        )
        assert proj.recovery_summary == "needs_output_correction"
        assert proj.available_recovery_controls == []

    def test_recovery_controls_empty_for_executor_failure(self) -> None:
        proj = _compute_projection(
            "failed",
            {"terminal_reason": {"code": "executor.timeout"}},
        )
        assert proj.recovery_summary == "failed"
        assert proj.available_recovery_controls == []

    def test_recovery_controls_empty_for_in_progress(self) -> None:
        proj = _compute_projection("running", {})
        assert proj.available_recovery_controls == []
