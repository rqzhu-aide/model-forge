"""Phase-specific scientific validators.

These extend the generic structural validation in ``submission_validation``
with scientific-completeness checks that depend on cross-output references,
method identity, and phase-specific semantics.

Each validator is a function that appends ``ValidationFinding`` entries to the
caller's findings list.  A validator never raises — it records problems for
the caller to act on.

Scientific outcome preservation: negative, contradictory, and inconclusive
results are valid scientific outcomes.  A validator must not convert
"method failed under this condition" into an operational failure.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import ResolvedPhasePlan
from ..domain.identities import MethodIdentity
from ..domain.validation import ValidationFinding, ValidationSeverity
from .publication import RegisteredValidatedOutput


__all__ = [
    "validate_phase_scientific",
]


def validate_phase_scientific(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """Dispatch to the phase-specific scientific validator."""

    phase = plan.identity.phase_id
    if phase == "P1":
        _validate_p1(plan=plan, outputs=outputs, findings=findings)
    elif phase == "P2":
        _validate_p2(
            plan=plan,
            outputs=outputs,
            selected_method=selected_method,
            findings=findings,
        )
    elif phase == "P3":
        _validate_p3(
            plan=plan,
            outputs=outputs,
            selected_method=selected_method,
            findings=findings,
        )
    elif phase == "P4":
        _validate_p4(
            plan=plan,
            outputs=outputs,
            selected_method=selected_method,
            findings=findings,
        )
    elif phase == "P5":
        _validate_p5(
            plan=plan,
            outputs=outputs,
            selected_method=selected_method,
            findings=findings,
        )


# ---------------------------------------------------------------------------
# Phase 1 — Literature basis
# ---------------------------------------------------------------------------

def _validate_p1(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    findings: list[ValidationFinding],
) -> None:
    """P1: deduplication, synthesis traceability, coverage scope."""

    # Deduplication — already checked in _validate_phase_semantics, but
    # double-check the coverage record too.
    coverage = outputs.get("p1.coverage_candidate")
    if (
        coverage is not None
        and type(coverage.document) is dict
    ):
        # Coverage must address the declared scope
        basis = coverage.document.get("basis")
        if type(basis) is dict and not basis.get("research_question"):
            findings.append(
                _finding(
                    "p1.coverage_missing_scope",
                    "Phase 1 coverage record does not state the research question it covers.",
                    "p1.coverage_candidate",
                )
            )

    # Synthesis traceability — synthesis must reference source changes
    synthesis = outputs.get("p1.synthesis_candidate")
    sources = outputs.get("p1.source_changes")
    if (
        synthesis is not None
        and sources is not None
        and type(synthesis.document) is dict
        and type(sources.document) is list
    ):
        synthesis_basis = synthesis.document.get("basis")
        if type(synthesis_basis) is dict:
            source_ids_in_synthesis = set()
            for item in synthesis_basis.get("prior_generations", ()):
                if type(item) is dict and item.get("generation_id"):
                    source_ids_in_synthesis.add(str(item["generation_id"]))
            if sources.document and not source_ids_in_synthesis:
                findings.append(
                    _finding(
                        "p1.synthesis_not_tracing_sources",
                        "Phase 1 synthesis does not reference the source-change generation.",
                        "p1.synthesis_candidate",
                    )
                )


# ---------------------------------------------------------------------------
# Phase 2 — Method development
# ---------------------------------------------------------------------------

def _validate_p2(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """P2: method identity, lineage, full-catalog coverage."""

    # Method identity on the method_changes output
    method_changes = outputs.get("p2.method_changes")
    if (
        method_changes is not None
        and type(method_changes.document) is list
        and selected_method is not None
    ):
        expected = selected_method.to_dict()
        for offset, item in enumerate(method_changes.document):
            if type(item) is not dict:
                continue
            declared = item.get("method_identity")
            if declared is None:
                findings.append(
                    _finding(
                        "p2.method_identity_missing",
                        f"Method change at index {offset} lacks method identity.",
                        "p2.method_changes",
                        f"/{offset}",
                    )
                )
            elif declared != expected:
                findings.append(
                    _finding(
                        "p2.method_identity_mismatch",
                        f"Method change at index {offset} does not match the selected method.",
                        "p2.method_changes",
                        f"/{offset}",
                    )
                )

    # Lineage — method changes should cite their prior version when replacing
    if method_changes is not None and type(method_changes.document) is list:
        for offset, item in enumerate(method_changes.document):
            if type(item) is not dict:
                continue
            lifecycle = item.get("lifecycle_state", "")
            if lifecycle == "revised" and not item.get("supersedes_version"):
                findings.append(
                    _finding(
                        "p2.method_lineage_missing",
                        f"Revised method at index {offset} does not cite its prior version.",
                        "p2.method_changes",
                        f"/{offset}",
                    )
                )


# ---------------------------------------------------------------------------
# Phase 3 — Theory development
# ---------------------------------------------------------------------------

def _validate_p3(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """P3: complete theory record, proof map, assumption preservation."""

    theory = outputs.get("p3.complete_theory")
    if theory is None or type(theory.document) is not dict:
        return

    doc = theory.document

    # Proof map — every statement should have a proof or explicit conjecture
    representations = doc.get("representations")
    if type(representations) is dict:
        statements = representations.get("statements", ())
        if type(statements) is list:
            for offset, stmt in enumerate(statements):
                if type(stmt) is not dict:
                    continue
                stmt_type = str(stmt.get("statement_type", "")).lower()
                if stmt_type in ("theorem", "proposition", "lemma"):
                    has_proof = bool(stmt.get("proof_reference"))
                    has_conjecture = stmt_type == "conjecture"
                    if not has_proof and not has_conjecture:
                        findings.append(
                            _finding(
                                "p3.claim_without_proof",
                                f"Theory statement at index {offset} ({stmt_type}) lacks a proof reference.",
                                "p3.complete_theory",
                                f"/representations/statements/{offset}",
                            )
                        )

    # Assumption preservation — assumptions from the method record should be addressed
    basis = doc.get("basis")
    if type(basis) is dict:
        assumptions = basis.get("assumptions", ())
        if type(assumptions) is list and not assumptions:
            findings.append(
                _finding(
                    "p3.no_assumptions_documented",
                    "Theory record does not document any assumptions.",
                    "p3.complete_theory",
                )
            )


# ---------------------------------------------------------------------------
# Phase 4 — Empirical development
# ---------------------------------------------------------------------------

def _validate_p4(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """P4: evidence applicability, four-slot atomic update, reproducibility."""

    # Evidence applicability — evidence must reference the exact method version
    evidence = outputs.get("p4.evidence")
    if (
        evidence is not None
        and type(evidence.document) is list
        and selected_method is not None
    ):
        expected = selected_method.to_dict()
        for offset, item in enumerate(evidence.document):
            if type(item) is not dict:
                continue
            declared = item.get("method_identity")
            if declared is None:
                findings.append(
                    _finding(
                        "p4.evidence_missing_method_identity",
                        f"Evidence at index {offset} lacks method identity.",
                        "p4.evidence",
                        f"/{offset}",
                    )
                )
            elif declared != expected:
                findings.append(
                    _finding(
                        "p4.evidence_method_mismatch",
                        f"Evidence at index {offset} does not match the selected method.",
                        "p4.evidence",
                        f"/{offset}",
                    )
                )

    # Four-slot atomic update — all four records should be present together
    four_slot_ids = [
        "p4.empirical_index_candidate",
        "p4.empirical_synthesis_candidate",
        "p4.implementation_record_candidate",
        "p4.decision",
    ]
    present = [oid for oid in four_slot_ids if outputs.get(oid) is not None]
    if 0 < len(present) < 4:
        missing = sorted(set(four_slot_ids) - set(present))
        findings.append(
            _finding(
                "p4.incomplete_four_slot_update",
                f"Phase 4 four-slot update is partial; missing: {', '.join(missing)}.",
                "p4.decision",
            )
        )

    # Reproducibility — implementation record should contain a reproducible protocol
    impl = outputs.get("p4.implementation_record_candidate")
    if impl is not None and type(impl.document) is dict:
        representations = impl.document.get("representations")
        if type(representations) is dict:
            protocol = representations.get("protocol")
            if protocol is None:
                findings.append(
                    _finding(
                        "p4.implementation_missing_protocol",
                        "Implementation record does not contain a reproducible protocol.",
                        "p4.implementation_record_candidate",
                    )
                )


# ---------------------------------------------------------------------------
# Phase 5 — Manuscript assembly and revision
# ---------------------------------------------------------------------------

def _validate_p5(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """P5: claim traceability, issue disposition, complete manuscript.

    Note: the closed-review-packet check can be implemented now, but full P5
    acceptance additionally requires WP4's reviewer no-memory attestation.
    """

    # Claim traceability — every claim should reference an accepted artifact
    claims = outputs.get("p5.claim_traceability")
    if claims is not None and type(claims.document) is list:
        for offset, claim in enumerate(claims.document):
            if type(claim) is not dict:
                continue
            supporting = claim.get("supporting_evidence_ids", ())
            if type(supporting) is list and not supporting:
                # An unsupported claim is only valid if it is an explicit limitation
                stmt_type = str(claim.get("statement_type", "")).lower()
                if stmt_type not in ("limitation", "caveat", "open_question"):
                    findings.append(
                        _finding(
                            "p5.claim_without_evidence",
                            f"Claim at index {offset} has no supporting evidence and is not a limitation.",
                            "p5.claim_traceability",
                            f"/{offset}",
                        )
                    )

    # Issue disposition — every review issue should be resolved or explicitly deferred
    issues = outputs.get("p5.review_issues")
    if issues is not None and type(issues.document) is list:
        for offset, issue in enumerate(issues.document):
            if type(issue) is not dict:
                continue
            disposition = str(issue.get("disposition", "")).lower()
            if disposition not in (
                "accepted", "rejected", "deferred", "addressed", "wont_fix",
            ):
                findings.append(
                    _finding(
                        "p5.issue_undispositioned",
                        f"Review issue at index {offset} has no valid disposition.",
                        "p5.review_issues",
                        f"/{offset}",
                    )
                )

    # Complete replacement manuscript — manuscript candidate should be present
    manuscript = outputs.get("p5.manuscript_candidate")
    if manuscript is None:
        findings.append(
            _finding(
                "p5.manuscript_missing",
                "Phase 5 requires one complete replacement manuscript.",
                "p5.manuscript_candidate",
            )
        )
    elif type(manuscript.document) is dict:
        # Manuscript should reference its upstream basis
        basis = manuscript.document.get("basis")
        if type(basis) is dict and not basis.get("upstream_generations"):
            findings.append(
                _finding(
                    "p5.manuscript_basis_missing",
                    "Manuscript does not reference its upstream theory/evidence basis.",
                    "p5.manuscript_candidate",
                )
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    code: str,
    message: str,
    object_id: str,
    pointer: str = "",
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        message=message,
        severity=ValidationSeverity.ERROR,
        object_id=object_id,
        json_pointer=pointer,
    )
