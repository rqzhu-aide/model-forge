"""Bounded, user-controlled output recovery (HV-5).

Three recovery actions, each with clear authority boundaries:
1. Revalidate — re-check unchanged bytes with current policy (no model call)
2. Normalize — apply allowlisted mechanical transformations (no model call)
3. Targeted correction — re-run a role with the validation report (model call)

All correction attempts are bounded, immutable, and linked to the original
closure via ``OutputCorrectionCommand``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..domain.validation import (
    OutputTransformationRecord,
    ValidationFinding,
    ValidationReport,
    make_finding,
)


# --------------------------------------------------------------------------- #
# Correction types                                                            #
# --------------------------------------------------------------------------- #

CorrectionType = Literal["revalidate", "normalize", "packaging", "scientific"]

# Default attempt bounds (HV-5.6)
MAX_PACKAGING_ATTEMPTS = 1
MAX_SCIENTIFIC_ATTEMPTS = 1


# --------------------------------------------------------------------------- #
# OutputCorrectionCommand (HV-5.2)                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class OutputCorrectionCommand:
    """A user-authorized correction action for a specific run.

    The command must not authorize a different method, phase scope, or
    context basis. A change to those items remains a new phase run.
    """

    run_id: str
    correction_type: CorrectionType
    permitted_output_scope: tuple[str, ...]
    expected_lifecycle_head: str  # for optimistic concurrency
    schema_version: str = "1.0.0"  # output-correction-command.schema.json
    role_closure_id: str = ""  # closure whose output is being corrected
    validation_attempt_id: str = ""  # attempt whose report drives the correction
    user_instruction: str | None = None
    transformation_codes: tuple[str, ...] = ()  # for normalize
    issued_by: str = ""
    issued_at: str = ""
    correction_command_id: str = ""

    def __post_init__(self) -> None:
        if not self.issued_at:
            object.__setattr__(
                self, "issued_at", datetime.now(timezone.utc).isoformat()
            )
        if not self.correction_command_id:
            object.__setattr__(
                self,
                "correction_command_id",
                _derive_command_id(
                    self.run_id, self.correction_type, self.expected_lifecycle_head
                ),
            )

    def validate_scope(self, requested_outputs: tuple[str, ...]) -> None:
        """Ensure requested outputs are within the permitted scope."""
        scope_set = set(self.permitted_output_scope)
        requested_set = set(requested_outputs)
        out_of_scope = requested_set - scope_set
        if out_of_scope:
            raise ValueError(
                f"Outputs {sorted(out_of_scope)} are outside the permitted scope."
            )


# --------------------------------------------------------------------------- #
# ValidationAttempt (HV-5.2)                                                  #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ValidationAttempt:
    """One validation pass against a run's output, with policy version.

    Each correction produces a new attempt linked to the prior one.
    """

    attempt_id: str
    run_id: str
    policy_version: str
    report: ValidationReport
    source_sha256: str  # digest of the validated bytes
    correction_type: CorrectionType | None = None  # None for initial validation
    prior_attempt_id: str | None = None  # links correction chain
    correction_command_id: str | None = None
    attempted_at: str = ""

    def __post_init__(self) -> None:
        if not self.attempted_at:
            object.__setattr__(
                self, "attempted_at", datetime.now(timezone.utc).isoformat()
            )

    @property
    def is_correction(self) -> bool:
        return self.correction_type is not None

    @property
    def passed(self) -> bool:
        return self.report.passed


# --------------------------------------------------------------------------- #
# CorrectionResult — what the coordinator gets back                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    """Outcome of a correction action."""

    attempt: ValidationAttempt
    transformation_record: OutputTransformationRecord | None = None
    correction_exhausted: bool = False
    findings: tuple[ValidationFinding, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Recovery action implementations                                             #
# --------------------------------------------------------------------------- #


def _derive_command_id(
    run_id: str, correction_type: str, expected_head: str
) -> str:
    """Deterministic ID for a correction command."""
    raw = f"{run_id}\x1f{correction_type}\x1f{expected_head}"
    return "correction." + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _derive_attempt_id(run_id: str, ordinal: int) -> str:
    """Deterministic ID for a validation attempt."""
    return f"attempt.{run_id}.{ordinal}"


def attempt_ordinal_from_id(attempt_id: str) -> int:
    """Extract the ordinal from an attempt ID."""
    parts = attempt_id.rsplit(".", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


# --------------------------------------------------------------------------- #
# Action 1: Revalidate                                                        #
# --------------------------------------------------------------------------- #


def revalidate(
    *,
    run_id: str,
    sealed_output_sha256: str,
    validation_report: ValidationReport,
    policy_version: str,
    prior_attempt_id: str | None = None,
    attempt_ordinal: int = 1,
) -> CorrectionResult:
    """Re-run validation against unchanged bytes with the current policy.

    No model call. No transformation. Just re-checks the report with new
    policy.  Since the report is already computed, revalidation simply
    creates a new ``ValidationAttempt`` with the current policy version.

    Authority: explicit user click. No new scientific authority needed.
    """
    attempt = ValidationAttempt(
        attempt_id=_derive_attempt_id(run_id, attempt_ordinal),
        run_id=run_id,
        policy_version=policy_version,
        report=validation_report,
        source_sha256=sealed_output_sha256,
        correction_type="revalidate",
        prior_attempt_id=prior_attempt_id,
    )
    return CorrectionResult(attempt=attempt)


# --------------------------------------------------------------------------- #
# Action 2: Normalize                                                         #
# --------------------------------------------------------------------------- #

# Allowlisted transformation codes for normalization
ALLOWED_NORMALIZE_CODES = frozenset({
    "timestamp_injection",
    "id_sanitization",
    "hash_recomputation",
    "additional_properties_strip",
    "schema_version_injection",
    "null_strip",
    "empty_string_strip",
})


def normalize(
    *,
    run_id: str,
    transformation_codes: tuple[str, ...],
    transformation_record: OutputTransformationRecord,
    validation_report: ValidationReport,
    policy_version: str,
    prior_attempt_id: str | None = None,
    attempt_ordinal: int = 1,
    correction_command_id: str | None = None,
) -> CorrectionResult:
    """Apply allowlisted mechanical transformations to produce a new candidate.

    No model call. Runs as part of the original launch authority.
    Must never alter a primary research artifact or semantic claim.

    Authority: covered by the original launch authority (mechanical, not
    scientific). Must be fully disclosed and cannot alter scientific meaning.
    """
    # Verify all requested codes are allowlisted
    disallowed = set(transformation_codes) - ALLOWED_NORMALIZE_CODES
    if disallowed:
        finding = make_finding(
            "output.required_missing",
            f"Transformation codes {sorted(disallowed)} are not allowlisted for normalization.",
            object_id=run_id,
        )
        return CorrectionResult(
            attempt=ValidationAttempt(
                attempt_id=_derive_attempt_id(run_id, attempt_ordinal),
                run_id=run_id,
                policy_version=policy_version,
                report=ValidationReport.from_findings(
                    "report", run_id, "normalize", [finding]
                ),
                source_sha256=transformation_record.source_sha256,
                correction_type="normalize",
                prior_attempt_id=prior_attempt_id,
                correction_command_id=correction_command_id,
            ),
            transformation_record=transformation_record,
            findings=(finding,),
        )

    attempt = ValidationAttempt(
        attempt_id=_derive_attempt_id(run_id, attempt_ordinal),
        run_id=run_id,
        policy_version=policy_version,
        report=validation_report,
        source_sha256=transformation_record.result_sha256,
        correction_type="normalize",
        prior_attempt_id=prior_attempt_id,
        correction_command_id=correction_command_id,
    )
    return CorrectionResult(
        attempt=attempt,
        transformation_record=transformation_record,
    )


# --------------------------------------------------------------------------- #
# Action 3: Targeted correction                                               #
# --------------------------------------------------------------------------- #


def build_correction_instruction(
    *,
    correction_type: Literal["packaging", "scientific"],
    findings: tuple[ValidationFinding, ...],
    output_scope: tuple[str, ...],
    user_instruction: str | None = None,
    permitted_pointers: tuple[str, ...] = (),
) -> str:
    """Build the instruction for a targeted correction role invocation.

    The instruction distinguishes:
    - Packaging correction: fix envelope structure, missing fields, format
      issues. No intended scientific change.  When ``permitted_pointers``
      is nonempty the instruction names the exact JSON-pointer locations
      the correction may touch (design 4a: the correction is a patch with
      a verified blast radius).
    - Scientific correction: fix a scientific claim, add missing evidence,
      downgrade an unsupported claim. Within frozen scope.  Scientific
      corrections keep output-level scope and ignore ``permitted_pointers``.
    """
    finding_lines = "\n".join(
        f"  - [{f.code}] {f.message}" for f in findings[:10]
    )
    scope_lines = ", ".join(f"`{s}`" for s in output_scope)

    if correction_type == "packaging":
        header = (
            "You are correcting a packaging issue in your previous output.\n"
            "Do NOT change the scientific content — only fix the structural "
            "fields identified below.\n"
            f"Scope: {scope_lines}\n\n"
            "Findings to address:\n"
            f"{finding_lines}"
        )
        if permitted_pointers:
            pointer_lines = "\n".join(
                f"  - {pointer}" for pointer in sorted(permitted_pointers)
            )
            header += (
                "\n\nPermitted change locations (change ONLY these; every "
                "other byte of the document must remain identical):\n"
                f"{pointer_lines}"
            )
    else:
        header = (
            "You are correcting a scientific issue in your previous output.\n"
            "You may revise the scientific content within the frozen scope.\n"
            "Do NOT expand the phase scope or change the selected method.\n"
            f"Scope: {scope_lines}\n\n"
            "Findings to address:\n"
            f"{finding_lines}"
        )

    if user_instruction:
        header += f"\n\nAdditional researcher guidance:\n{user_instruction}"

    return header


# --------------------------------------------------------------------------- #
# Attempt bounds (HV-5.6)                                                     #
# --------------------------------------------------------------------------- #


def check_correction_bounds(
    *,
    correction_type: CorrectionType,
    prior_packaging_attempts: int,
    prior_scientific_attempts: int,
) -> bool:
    """Check whether another correction attempt is allowed.

    Returns True if the correction can proceed, False if exhausted.
    """
    if correction_type == "packaging":
        return prior_packaging_attempts < MAX_PACKAGING_ATTEMPTS
    if correction_type == "scientific":
        return prior_scientific_attempts < MAX_SCIENTIFIC_ATTEMPTS
    # revalidate and normalize have no bounds
    return True


def is_correction_exhausted(
    *,
    prior_packaging_attempts: int,
    prior_scientific_attempts: int,
) -> bool:
    """Check whether both packaging and scientific attempts are exhausted."""
    return (
        prior_packaging_attempts >= MAX_PACKAGING_ATTEMPTS
        and prior_scientific_attempts >= MAX_SCIENTIFIC_ATTEMPTS
    )


__all__ = [
    "ALLOWED_NORMALIZE_CODES",
    "CorrectionResult",
    "CorrectionType",
    "MAX_PACKAGING_ATTEMPTS",
    "MAX_SCIENTIFIC_ATTEMPTS",
    "OutputCorrectionCommand",
    "ValidationAttempt",
    "attempt_ordinal_from_id",
    "build_correction_instruction",
    "check_correction_bounds",
    "is_correction_exhausted",
    "normalize",
    "revalidate",
]
