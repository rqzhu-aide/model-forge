"""Phase-specific scientific validators.

Structural schemas establish shape. These checks establish cross-record
identity, internal references, scientific completeness, and provenance. They
do not judge whether a scientific conclusion is favorable. Contradictory,
negative, and inconclusive results remain valid outcomes when documented.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from ..contracts import ResolvedPhasePlan
from ..domain.identities import MethodIdentity
from ..domain.validation import ValidationFinding, make_finding
from .publication import RegisteredValidatedOutput


__all__ = ["validate_phase_scientific"]


def validate_phase_scientific(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """Apply scientific checks that depend on the complete phase output set."""

    phase = plan.identity.phase_id
    if phase == "P1":
        _validate_p1(outputs=outputs, findings=findings)
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
# Phase 1: literature basis
# ---------------------------------------------------------------------------


def _validate_p1(
    *,
    outputs: Mapping[str, RegisteredValidatedOutput],
    findings: list[ValidationFinding],
) -> None:
    """Require stable, nonduplicated sources with reproducible search origin."""

    source_changes = _list_document(outputs, "p1.source_changes")
    seen_source_ids: set[str] = set()
    seen_identifiers: set[tuple[str, str]] = set()
    for offset, source in enumerate(source_changes):
        if not isinstance(source, Mapping):
            continue
        source_id = _text(source.get("source_id"))
        if source_id:
            if source_id in seen_source_ids:
                findings.append(
                    _finding(
                        "p1.duplicate_source_id",
                        f"Source {source_id!r} occurs more than once in this update.",
                        "p1.source_changes",
                        f"/{offset}/source_id",
                    )
                )
            seen_source_ids.add(source_id)

        identifiers = source.get("identifiers")
        if isinstance(identifiers, list):
            for identifier_offset, identifier in enumerate(identifiers):
                if not isinstance(identifier, Mapping):
                    continue
                key = (
                    _text(identifier.get("kind")).lower(),
                    _text(identifier.get("value")).lower(),
                )
                if not all(key):
                    continue
                if key in seen_identifiers:
                    findings.append(
                        _finding(
                            "p1.duplicate_source_identifier",
                            "The same external source identifier occurs more than once in this update.",
                            "p1.source_changes",
                            f"/{offset}/identifiers/{identifier_offset}",
                        )
                    )
                seen_identifiers.add(key)

        provenance = source.get("search_provenance")
        if not isinstance(provenance, list) or not provenance:
            findings.append(
                _finding(
                    "p1.search_provenance_missing",
                    "Every added source must preserve at least one search source, query, role, run, and timestamp.",
                    "p1.source_changes",
                    f"/{offset}/search_provenance",
                )
            )


# ---------------------------------------------------------------------------
# Phase 2: method development
# ---------------------------------------------------------------------------


def _validate_p2(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """Require substantive method definitions and mode-correct lineage."""

    methods = _list_document(outputs, "p2.method_changes")
    for offset, method in enumerate(methods):
        if not isinstance(method, Mapping):
            continue
        _validate_method_definition(method, offset=offset, findings=findings)
        _validate_method_evaluation(method, offset=offset, findings=findings)

    for output_id, allowed_axis, message in (
        (
            "p2.theory_review",
            "theoretical_validity",
            "The theorist evaluates only the theoretical validity axis (ADR-017).",
        ),
        (
            "p2.empirical_review",
            "empirical_feasibility",
            "The data analyst evaluates only the empirical feasibility axis (ADR-017).",
        ),
    ):
        review = _mapping_document(outputs, output_id)
        if review is None:
            continue
        evaluations = review.get("method_evaluations", [])
        if not isinstance(evaluations, list):
            continue
        for index, entry in enumerate(evaluations):
            if not isinstance(entry, Mapping):
                continue
            if entry.get("axis") not in (None, allowed_axis):
                findings.append(
                    _finding(
                        "p2.review_axis_violation",
                        message,
                        output_id,
                        f"/method_evaluations/{index}/axis",
                    )
                )

    if plan.mode_id != "p2.focused_method":
        return

    if selected_method is None:
        findings.append(
            _finding(
                "p2.focused_method_identity_missing",
                "Focused-method work requires the exact selected method identity.",
                "p2.method_changes",
            )
        )
        return
    if len(methods) > 1:
        findings.append(
            _finding(
                "p2.focused_scope_exceeded",
                "Focused-method work may return at most one method record.",
                "p2.method_changes",
            )
        )

    expected = selected_method.to_dict()
    for offset, method in enumerate(methods):
        if not isinstance(method, Mapping):
            continue
        declared = _method_identity(method)
        lineage = method.get("lineage")
        lineage = lineage if isinstance(lineage, Mapping) else {}
        predecessor = lineage.get("predecessor")
        change_class = _text(lineage.get("change_class"))

        if change_class == "initial":
            findings.append(
                _finding(
                    "p2.focused_initial_lineage",
                    "An existing focused method cannot be emitted with initial lineage.",
                    "p2.method_changes",
                    f"/{offset}/lineage/change_class",
                )
            )
        if not _identity_matches(predecessor, expected):
            findings.append(
                _finding(
                    "p2.predecessor_identity_mismatch",
                    "The focused method must name the exact selected version as its predecessor.",
                    "p2.method_changes",
                    f"/{offset}/lineage/predecessor",
                )
            )
        if not _text(lineage.get("predecessor_generation_id")):
            findings.append(
                _finding(
                    "p2.predecessor_generation_missing",
                    "The focused method must name the predecessor generation it revises or reassesses.",
                    "p2.method_changes",
                    f"/{offset}/lineage/predecessor_generation_id",
                )
            )

        if change_class in {"editorial", "lifecycle"}:
            if not _identity_matches(declared, expected):
                findings.append(
                    _finding(
                        "p2.nonmathematical_identity_changed",
                        "Editorial and lifecycle updates must preserve method ID, version, and definition digest.",
                        "p2.method_changes",
                        f"/{offset}/identity",
                    )
                )
        elif change_class == "mathematical":
            if not _same_stable_id(declared, expected):
                findings.append(
                    _finding(
                        "p2.mathematical_stable_id_changed",
                        "A mathematical revision must preserve the stable method ID.",
                        "p2.method_changes",
                        f"/{offset}/identity/stable_id",
                    )
                )
            if not isinstance(declared, Mapping) or declared.get("version") != expected["version"] + 1:
                findings.append(
                    _finding(
                        "p2.mathematical_version_not_advanced",
                        "A mathematical revision must advance the method version by exactly one.",
                        "p2.method_changes",
                        f"/{offset}/identity/version",
                    )
                )
            if (
                isinstance(declared, Mapping)
                and declared.get("definition_sha256")
                == expected["definition_sha256"]
            ):
                findings.append(
                    _finding(
                        "p2.mathematical_digest_unchanged",
                        "A calculation-defining revision must change the definition digest.",
                        "p2.method_changes",
                        f"/{offset}/identity/definition_sha256",
                    )
                )


def _validate_method_definition(
    method: Mapping[str, Any],
    *,
    offset: int,
    findings: list[ValidationFinding],
) -> None:
    mathematical = method.get("mathematical_definition")
    if not isinstance(mathematical, Mapping):
        return
    canonical = mathematical.get("canonical_definition")
    canonical = canonical if isinstance(canonical, Mapping) else {}
    for field in ("target_or_estimand", "objective_or_estimating_equation"):
        if not _substantive_named_object(canonical.get(field)):
            findings.append(
                _finding(
                    "p2.canonical_definition_empty",
                    f"The canonical method definition must state a substantive {field.replace('_', ' ')}.",
                    "p2.method_changes",
                    f"/{offset}/mathematical_definition/canonical_definition/{field}",
                )
            )

    components = mathematical.get("defining_components")
    if not isinstance(components, list) or not components:
        findings.append(
            _finding(
                "p2.defining_components_empty",
                "The method record must enumerate the components that determine its calculation.",
                "p2.method_changes",
                f"/{offset}/mathematical_definition/defining_components",
            )
        )

    for field, label in (
        ("assumptions", "assumptions"),
        ("literature_provenance", "literature provenance"),
        ("limitations", "limitations"),
    ):
        value = method.get(field)
        if not isinstance(value, list) or not value:
            findings.append(
                _finding(
                    f"p2.{field}_empty",
                    f"The method record must state its {label}; use an explicit not-applicable entry when justified.",
                    "p2.method_changes",
                    f"/{offset}/{field}",
                )
            )


_EVALUATION_AXES = (
    "theoretical_validity",
    "literature_positioning",
    "empirical_feasibility",
)


def _validate_method_evaluation(
    method: Mapping[str, Any],
    *,
    offset: int,
    findings: list[ValidationFinding],
) -> None:
    evaluation = method.get("evaluation")
    if not isinstance(evaluation, Mapping):
        findings.append(
            _finding(
                "p2.method_evaluation_missing",
                "Every method in the change set must carry the lead's three-axis evaluation (ADR-017).",
                "p2.method_changes",
                f"/{offset}/evaluation",
            )
        )
        return
    for axis in _EVALUATION_AXES:
        entry = evaluation.get(axis)
        score = entry.get("score") if isinstance(entry, Mapping) else None
        justification = (
            entry.get("justification") if isinstance(entry, Mapping) else None
        )
        valid = (
            isinstance(entry, Mapping)
            and type(score) is int
            and 1 <= score <= 10
            and isinstance(justification, str)
            and bool(justification.strip())
        )
        if not valid:
            findings.append(
                _finding(
                    "p2.method_evaluation_invalid",
                    "Each evaluation axis needs an integer score 1-10 and a non-empty justification.",
                    "p2.method_changes",
                    f"/{offset}/evaluation/{axis}",
                )
            )


# ---------------------------------------------------------------------------
# Phase 3: theory development
# ---------------------------------------------------------------------------


def _validate_p3(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """Check exact method identity and statement-level theory integrity."""

    theory = _mapping_document(outputs, "p3.complete_theory")
    if theory is None:
        return

    basis = theory.get("basis")
    if isinstance(basis, list) and not basis:
        findings.append(
            _finding(
                "p3.no_assumptions_documented",
                "The theory record does not document any basis records.",
                "p3.complete_theory",
                "/basis",
            )
        )

    # Legacy records are checked by the generic lane. The dedicated record
    # below is recognized by its statement ledger.
    statements_value = theory.get("statements")
    if not isinstance(statements_value, list):
        return

    if selected_method is not None and not _identity_matches(
        theory.get("method_identity"), selected_method.to_dict()
    ):
        findings.append(
            _finding(
                "p3.method_identity_mismatch",
                "The theory record must use the exact selected method ID, version, and definition digest.",
                "p3.complete_theory",
                "/method_identity",
            )
        )

    if theory.get("development_mode") != plan.mode_id:
        findings.append(
            _finding(
                "p3.development_mode_mismatch",
                "The theory record development mode does not match the authorized run mode.",
                "p3.complete_theory",
                "/development_mode",
            )
        )

    _validate_primary_artifact(
        theory,
        primary_field="primary_artifact",
        object_id="p3.complete_theory",
        code_prefix="p3",
        findings=findings,
    )

    assumptions = theory.get("assumptions")
    assumptions = assumptions if isinstance(assumptions, list) else []
    implications = theory.get("empirical_implications")
    implications = implications if isinstance(implications, list) else []
    assumption_ids = _unique_ids(
        assumptions,
        key="assumption_id",
        object_id="p3.complete_theory",
        pointer="/assumptions",
        code="p3.duplicate_assumption_id",
        findings=findings,
    )
    statement_ids = _unique_ids(
        statements_value,
        key="statement_id",
        object_id="p3.complete_theory",
        pointer="/statements",
        code="p3.duplicate_statement_id",
        findings=findings,
    )
    implication_ids = _unique_ids(
        implications,
        key="implication_id",
        object_id="p3.complete_theory",
        pointer="/empirical_implications",
        code="p3.duplicate_implication_id",
        findings=findings,
    )

    for offset, assumption in enumerate(assumptions):
        if not isinstance(assumption, Mapping):
            continue
        _require_resolved_ids(
            assumption.get("used_by_statement_ids"),
            valid_ids=statement_ids,
            code="p3.unknown_statement_reference",
            message="An assumption refers to a statement that is absent from this theory record.",
            object_id="p3.complete_theory",
            pointer=f"/assumptions/{offset}/used_by_statement_ids",
            findings=findings,
        )

    dependency_graph: dict[str, set[str]] = {}
    for offset, statement in enumerate(statements_value):
        if not isinstance(statement, Mapping):
            continue
        statement_id = _text(statement.get("statement_id"))
        _require_resolved_ids(
            statement.get("assumption_ids"),
            valid_ids=assumption_ids,
            code="p3.unknown_assumption_reference",
            message="A theory statement refers to an assumption that is absent from this record.",
            object_id="p3.complete_theory",
            pointer=f"/statements/{offset}/assumption_ids",
            findings=findings,
        )
        dependencies = _string_set(statement.get("depends_on_statement_ids"))
        _require_resolved_ids(
            dependencies,
            valid_ids=statement_ids,
            code="p3.unknown_statement_dependency",
            message="A theory statement depends on a statement that is absent from this record.",
            object_id="p3.complete_theory",
            pointer=f"/statements/{offset}/depends_on_statement_ids",
            findings=findings,
        )
        if statement_id and statement_id in dependencies:
            findings.append(
                _finding(
                    "p3.self_dependent_statement",
                    "A theory statement cannot depend on itself.",
                    "p3.complete_theory",
                    f"/statements/{offset}/depends_on_statement_ids",
                )
            )
        if statement_id:
            dependency_graph[statement_id] = dependencies & statement_ids

        _require_resolved_ids(
            statement.get("empirical_implication_ids"),
            valid_ids=implication_ids,
            code="p3.unknown_empirical_implication",
            message="A theory statement refers to an empirical implication that is absent from this record.",
            object_id="p3.complete_theory",
            pointer=f"/statements/{offset}/empirical_implication_ids",
            findings=findings,
        )
        _validate_theory_statement(
            statement,
            offset=offset,
            findings=findings,
        )

    if _has_cycle(dependency_graph):
        findings.append(
            _finding(
                "p3.statement_dependency_cycle",
                "The theory statement dependency graph contains a cycle.",
                "p3.complete_theory",
                "/statements",
            )
        )

    for offset, implication in enumerate(implications):
        if not isinstance(implication, Mapping):
            continue
        _require_resolved_ids(
            implication.get("statement_ids"),
            valid_ids=statement_ids,
            code="p3.unknown_implication_statement",
            message="An empirical implication refers to a statement that is absent from this record.",
            object_id="p3.complete_theory",
            pointer=f"/empirical_implications/{offset}/statement_ids",
            findings=findings,
        )

    revision = theory.get("revision_account")
    if plan.mode_id == "p3.theory_revision":
        if not isinstance(revision, Mapping):
            findings.append(
                _finding(
                    "p3.revision_account_missing",
                    "Theory revision requires an explicit account of changed and unresolved statements.",
                    "p3.complete_theory",
                    "/revision_account",
                )
            )
        else:
            for field in (
                "strengthened_statement_ids",
                "weakened_statement_ids",
                "conditioned_statement_ids",
                "contradicted_statement_ids",
                "retracted_statement_ids",
                "new_statement_ids",
                "unresolved_statement_ids",
            ):
                _require_resolved_ids(
                    revision.get(field),
                    valid_ids=statement_ids,
                    code="p3.unknown_revision_statement",
                    message="The revision account refers to a statement absent from the replacement theory record.",
                    object_id="p3.complete_theory",
                    pointer=f"/revision_account/{field}",
                    findings=findings,
                )


def _validate_theory_statement(
    statement: Mapping[str, Any],
    *,
    offset: int,
    findings: list[ValidationFinding],
) -> None:
    statement_type = _text(statement.get("statement_type"))
    status = _text(statement.get("status"))
    justification = statement.get("justification")
    justification = justification if isinstance(justification, Mapping) else {}
    kind = _text(justification.get("kind"))
    artifacts = justification.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, list) else []
    formal_types = {"lemma", "proposition", "theorem", "corollary"}

    if status == "established" and statement_type in formal_types:
        if kind not in {"proof", "derivation"} or not artifacts:
            findings.append(
                _finding(
                    "p3.established_statement_unsupported",
                    "An established formal statement requires a proof or derivation artifact.",
                    "p3.complete_theory",
                    f"/statements/{offset}/justification",
                )
            )
    if status == "incomplete":
        if kind != "open_obligation" or not _text(
            justification.get("open_obligation")
        ):
            findings.append(
                _finding(
                    "p3.incomplete_statement_without_obligation",
                    "An incomplete statement must identify the remaining proof obligation.",
                    "p3.complete_theory",
                    f"/statements/{offset}/justification",
                )
            )
    if status == "contradicted":
        if kind not in {"counterexample", "empirical_evidence"} or not artifacts:
            findings.append(
                _finding(
                    "p3.contradiction_without_evidence",
                    "A contradicted statement must point to a counterexample or empirical evidence artifact.",
                    "p3.complete_theory",
                    f"/statements/{offset}/justification",
                )
            )
    if status == "conditional":
        if not _string_set(statement.get("assumption_ids")):
            findings.append(
                _finding(
                    "p3.conditional_statement_without_assumption",
                    "A conditional statement must reference at least one conditioning assumption.",
                    "p3.complete_theory",
                    f"/statements/{offset}/assumption_ids",
                )
            )
    if status == "untested":
        if kind != "open_obligation" or not _text(
            justification.get("open_obligation")
        ):
            findings.append(
                _finding(
                    "p3.untested_statement_without_obligation",
                    "An untested statement must identify the explicit open obligation that remains.",
                    "p3.complete_theory",
                    f"/statements/{offset}/justification",
                )
            )
    if status == "retracted":
        if not _text(justification.get("summary")):
            findings.append(
                _finding(
                    "p3.retracted_statement_without_reason",
                    "A retracted statement must give the reason for its retraction.",
                    "p3.complete_theory",
                    f"/statements/{offset}/justification",
                )
            )


# ---------------------------------------------------------------------------
# Phase 4: empirical development
# ---------------------------------------------------------------------------


def _validate_p4(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """Check protocol integrity, evidence applicability, and atomic updates."""

    expected = selected_method.to_dict() if selected_method is not None else None
    protocol = _mapping_document(outputs, "p4.protocol")
    if protocol is not None:
        if protocol.get("mode") != plan.mode_id:
            findings.append(
                _finding(
                    "p4.protocol_mode_mismatch",
                    "The empirical protocol scope does not match the authorized run mode.",
                    "p4.protocol",
                    "/mode",
                )
            )
        if expected is not None and not _identity_matches(
            protocol.get("method_identity"), expected
        ):
            findings.append(
                _finding(
                    "p4.protocol_method_mismatch",
                    "The empirical protocol must use the exact selected method identity.",
                    "p4.protocol",
                    "/method_identity",
                )
            )
        _validate_empirical_protocol(protocol, findings=findings)

    evidence = _list_document(outputs, "p4.evidence")
    identity_required_kinds = {
        "proof",
        "computation",
        "simulation",
        "experiment",
        "external_validation",
    }
    reproducible_kinds = {
        "computation",
        "simulation",
        "experiment",
        "external_validation",
    }
    protocol_time = _parse_datetime(protocol.get("finalized_at")) if protocol else None
    comprehensive = plan.mode_id == "p4.comprehensive"
    for offset, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            continue
        kind = _text(item.get("evidence_kind")).lower()
        declared = _method_identity(item)
        if kind in identity_required_kinds:
            if declared is None:
                findings.append(
                    _finding(
                        "p4.evidence_missing_method_identity",
                        f"Evidence at index {offset} ({kind}) lacks method identity.",
                        "p4.evidence",
                        f"/{offset}/method_identity",
                    )
                )
            elif expected is not None and not _identity_matches(declared, expected):
                findings.append(
                    _finding(
                        "p4.evidence_method_mismatch",
                        "Method-bound evidence must match the selected method ID, version, and definition digest.",
                        "p4.evidence",
                        f"/{offset}/method_identity",
                    )
                )
            applicability = item.get("applicability_at_creation")
            match = (
                applicability.get("method_match")
                if isinstance(applicability, Mapping)
                else None
            )
            if match != "exact":
                findings.append(
                    _finding(
                        "p4.evidence_not_exactly_applicable",
                        "Evidence is preserved but not exactly applicable to the selected method; it is excluded from current-method synthesis.",
                        "p4.evidence",
                        f"/{offset}/applicability_at_creation/method_match",
                    )
                )

        if kind in reproducible_kinds:
            _validate_reproducibility(
                item,
                offset=offset,
                enforce=comprehensive,
                findings=findings,
            )

        evidence_time = _parse_datetime(item.get("created_at"))
        if protocol_time is not None and evidence_time is not None and protocol_time > evidence_time:
            findings.append(
                _finding(
                    "p4.protocol_finalized_after_evidence",
                    "The protocol timestamp is later than an evidence timestamp; prespecification cannot be established.",
                    "p4.protocol",
                    "/finalized_at",
                )
            )

    four_slot_ids = {
        "p4.empirical_index_candidate",
        "p4.empirical_synthesis_candidate",
        "p4.implementation_record_candidate",
        "p4.decision",
    }
    present = {output_id for output_id in four_slot_ids if output_id in outputs}
    if present and present != four_slot_ids:
        missing = ", ".join(sorted(four_slot_ids - present))
        findings.append(
            _finding(
                "p4.incomplete_four_slot_update",
                f"Phase 4 four-slot update is partial; missing: {missing}.",
                "p4.decision",
            )
        )


def _validate_empirical_protocol(
    protocol: Mapping[str, Any],
    *,
    findings: list[ValidationFinding],
) -> None:
    claim_tests = protocol.get("claim_tests")
    claim_tests = claim_tests if isinstance(claim_tests, list) else []
    metrics = protocol.get("metrics")
    metrics = metrics if isinstance(metrics, list) else []
    thresholds = protocol.get("decision_thresholds")
    thresholds = thresholds if isinstance(thresholds, list) else []
    test_ids = _unique_ids(
        claim_tests,
        key="test_id",
        object_id="p4.protocol",
        pointer="/claim_tests",
        code="p4.duplicate_test_id",
        findings=findings,
    )
    metric_ids = _unique_ids(
        metrics,
        key="metric_id",
        object_id="p4.protocol",
        pointer="/metrics",
        code="p4.duplicate_metric_id",
        findings=findings,
    )
    threshold_ids = _unique_ids(
        thresholds,
        key="threshold_id",
        object_id="p4.protocol",
        pointer="/decision_thresholds",
        code="p4.duplicate_threshold_id",
        findings=findings,
    )
    claim_ids = {
        _text(item.get("claim_id"))
        for item in claim_tests
        if isinstance(item, Mapping) and _text(item.get("claim_id"))
    }
    for offset, claim_test in enumerate(claim_tests):
        if not isinstance(claim_test, Mapping):
            continue
        _require_resolved_ids(
            claim_test.get("decision_threshold_ids"),
            valid_ids=threshold_ids,
            code="p4.unknown_decision_threshold",
            message="A claim test refers to a decision threshold absent from the protocol.",
            object_id="p4.protocol",
            pointer=f"/claim_tests/{offset}/decision_threshold_ids",
            findings=findings,
        )
    for offset, threshold in enumerate(thresholds):
        if not isinstance(threshold, Mapping):
            continue
        if _text(threshold.get("metric_id")) not in metric_ids:
            findings.append(
                _finding(
                    "p4.unknown_threshold_metric",
                    "A decision threshold refers to a metric absent from the protocol.",
                    "p4.protocol",
                    f"/decision_thresholds/{offset}/metric_id",
                )
            )
        if _text(threshold.get("claim_id")) not in claim_ids:
            findings.append(
                _finding(
                    "p4.unknown_threshold_claim",
                    "A decision threshold refers to a claim absent from the protocol claim tests.",
                    "p4.protocol",
                    f"/decision_thresholds/{offset}/claim_id",
                )
            )
    deviations = protocol.get("deviations")
    if isinstance(deviations, list):
        for offset, deviation in enumerate(deviations):
            if not isinstance(deviation, Mapping):
                continue
            _require_resolved_ids(
                deviation.get("affected_test_ids"),
                valid_ids=test_ids,
                code="p4.unknown_deviation_test",
                message="A protocol deviation refers to a claim test absent from the protocol.",
                object_id="p4.protocol",
                pointer=f"/deviations/{offset}/affected_test_ids",
                findings=findings,
            )


def _validate_reproducibility(
    evidence: Mapping[str, Any],
    *,
    offset: int,
    enforce: bool,
    findings: list[ValidationFinding],
) -> None:
    """Require a complete reproducibility record for reproducible evidence.

    Enforcement is mode-aware: preliminary studies may omit reproducibility
    (exploratory scope), comprehensive studies must provide it.
    """
    if not enforce:
        return
    reproducibility = evidence.get("reproducibility")
    if not isinstance(reproducibility, Mapping):
        findings.append(
            _finding(
                "p4.reproducibility_missing",
                "Computational or empirical evidence requires a reproducibility record.",
                "p4.evidence",
                f"/{offset}/reproducibility",
            )
        )
        return
    for field in (
        "code_artifacts",
        "configuration_artifacts",
        "environment_artifacts",
    ):
        value = reproducibility.get(field)
        if not isinstance(value, list) or not value:
            findings.append(
                _finding(
                    "p4.reproducibility_artifact_missing",
                    f"Reproducibility metadata must include at least one {field.replace('_', ' ')} entry.",
                    "p4.evidence",
                    f"/{offset}/reproducibility/{field}",
                )
            )
    if _text(evidence.get("evidence_kind")).lower() == "simulation":
        seeds = reproducibility.get("random_seeds")
        if not isinstance(seeds, list) or not seeds:
            findings.append(
                _finding(
                    "p4.simulation_seed_missing",
                    "Simulation evidence must record the random seeds used.",
                    "p4.evidence",
                    f"/{offset}/reproducibility/random_seeds",
                )
            )


# ---------------------------------------------------------------------------
# Phase 5: manuscript assembly and revision
# ---------------------------------------------------------------------------


def _validate_p5(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    """Check manuscript support and preserve review versus disposition roles."""

    claims = _list_document(outputs, "p5.claim_traceability")
    claim_ids = {
        _text(claim.get("statement_id"))
        for claim in claims
        if isinstance(claim, Mapping) and _text(claim.get("statement_id"))
    }
    for offset, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            continue
        supporting = claim.get("supporting_evidence_ids")
        counter = claim.get("counterevidence_ids")
        has_support = isinstance(supporting, list) and bool(supporting)
        has_counter = isinstance(counter, list) and bool(counter)
        statement_type = _text(claim.get("statement_type")).lower()
        if not has_support and not has_counter and statement_type not in {
            "limitation",
            "open_question",
        }:
            findings.append(
                _finding(
                    "p5.claim_without_evidence",
                    "A manuscript claim has neither supporting evidence nor counterevidence and is not an explicit limitation or open question.",
                    "p5.claim_traceability",
                    f"/{offset}",
                )
            )

    manuscript = _mapping_document(outputs, "p5.manuscript_candidate")
    if manuscript is None:
        findings.append(
            _finding(
                "p5.manuscript_missing",
                "Phase 5 requires one complete replacement manuscript package.",
                "p5.manuscript_candidate",
            )
        )
    else:
        _validate_manuscript_package(
            manuscript,
            plan=plan,
            selected_method=selected_method,
            claim_ids=claim_ids,
            findings=findings,
        )

    if plan.mode_id != "p5.review_revision":
        return

    finding_ids: set[str] = set()
    for output_id, expected_role in (
        ("p5.theory_audit", "theorist"),
        ("p5.empirical_audit", "data_analyst"),
    ):
        findings_doc = _list_document(outputs, output_id)
        for offset, review_finding in enumerate(findings_doc):
            if not isinstance(review_finding, Mapping):
                continue
            _validate_open_review_finding(
                review_finding,
                output_id=output_id,
                offset=offset,
                expected_role=expected_role,
                findings=findings,
            )
            issue_id = _text(review_finding.get("issue_id"))
            if issue_id:
                finding_ids.add(issue_id)

    outside_report = _mapping_document(outputs, "p5.outside_review")
    if outside_report is not None:
        prioritized = outside_report.get("prioritized_issues")
        prioritized = prioritized if isinstance(prioritized, list) else []
        for offset, review_finding in enumerate(prioritized):
            if not isinstance(review_finding, Mapping):
                continue
            _validate_open_review_finding(
                review_finding,
                output_id="p5.outside_review",
                offset=offset,
                expected_role="outside_reviewer",
                findings=findings,
                pointer_prefix="/prioritized_issues",
            )
            issue_id = _text(review_finding.get("issue_id"))
            if issue_id:
                finding_ids.add(issue_id)

    issues = _list_document(outputs, "p5.review_issues")
    disposition_ids: set[str] = set()
    for offset, issue in enumerate(issues):
        if not isinstance(issue, Mapping):
            continue
        issue_id = _text(issue.get("issue_id"))
        if issue_id in disposition_ids:
            findings.append(
                _finding(
                    "p5.duplicate_issue_disposition",
                    "A review issue has more than one final disposition in this run.",
                    "p5.review_issues",
                    f"/{offset}/issue_id",
                )
            )
        if issue_id:
            disposition_ids.add(issue_id)
        disposition = _text(issue.get("disposition")).lower()
        if disposition in {"", "open"}:
            findings.append(
                _finding(
                    "p5.issue_undispositioned",
                    "Every review finding must receive a final lead disposition in review-revision mode.",
                    "p5.review_issues",
                    f"/{offset}/disposition",
                )
            )
        if disposition in {"fixed", "partially_fixed"}:
            locations = issue.get("revision_locations")
            if not isinstance(locations, list) or not locations:
                findings.append(
                    _finding(
                        "p5.revision_location_missing",
                        "A fixed or partially fixed issue must identify the resulting manuscript location.",
                        "p5.review_issues",
                        f"/{offset}/revision_locations",
                    )
                )
        if disposition in {"deferred", "rejected"} and not _text(
            issue.get("disposition_reason")
        ):
            findings.append(
                _finding(
                    "p5.disposition_reason_missing",
                    "A deferred or rejected issue requires a scientific justification.",
                    "p5.review_issues",
                    f"/{offset}/disposition_reason",
                )
            )

    missing_dispositions = sorted(finding_ids - disposition_ids)
    if missing_dispositions:
        findings.append(
            _finding(
                "p5.review_finding_not_dispositioned",
                "Review findings lack lead dispositions: " + ", ".join(missing_dispositions) + ".",
                "p5.review_issues",
            )
        )


def _validate_manuscript_package(
    manuscript: Mapping[str, Any],
    *,
    plan: ResolvedPhasePlan,
    selected_method: MethodIdentity | None,
    claim_ids: set[str],
    findings: list[ValidationFinding],
) -> None:
    expected_kind = {
        "p5.assembly": "assembly_candidate",
        "p5.review_revision": "revised_candidate",
    }.get(plan.mode_id)
    if expected_kind is not None and manuscript.get("manuscript_kind") != expected_kind:
        findings.append(
            _finding(
                "p5.manuscript_kind_mismatch",
                "The manuscript package kind does not match the authorized Phase 5 mode.",
                "p5.manuscript_candidate",
                "/manuscript_kind",
            )
        )
    if selected_method is not None and not _identity_matches(
        manuscript.get("method_identity"), selected_method.to_dict()
    ):
        findings.append(
            _finding(
                "p5.method_identity_mismatch",
                "The manuscript package must use the exact selected method identity.",
                "p5.manuscript_candidate",
                "/method_identity",
            )
        )
    basis = manuscript.get("basis")
    if isinstance(basis, list) and not basis:
        findings.append(
            _finding(
                "p5.manuscript_basis_missing",
                "The manuscript package must identify its frozen upstream basis.",
                "p5.manuscript_candidate",
                "/basis",
            )
        )
    elif isinstance(basis, Mapping) and not basis.get("upstream_generations"):
        findings.append(
            _finding(
                "p5.manuscript_basis_missing",
                "The manuscript package must identify its frozen upstream basis.",
                "p5.manuscript_candidate",
                "/basis",
            )
        )

    if "manuscript_artifact" in manuscript:
        proxy = dict(manuscript)
        proxy["primary_artifact"] = manuscript.get("manuscript_artifact")
        _validate_primary_artifact(
            proxy,
            primary_field="primary_artifact",
            object_id="p5.manuscript_candidate",
            code_prefix="p5",
            findings=findings,
        )

    support_index = manuscript.get("claim_support_index")
    if isinstance(support_index, Mapping):
        for category, values in support_index.items():
            if not isinstance(values, list):
                continue
            unknown = sorted(_string_set(values) - claim_ids)
            if unknown:
                findings.append(
                    _finding(
                        "p5.unknown_claim_support_reference",
                        f"Claim-support category {category!r} refers to claims absent from the traceability record: {', '.join(unknown)}.",
                        "p5.manuscript_candidate",
                        f"/claim_support_index/{category}",
                    )
                )


def _validate_open_review_finding(
    review_finding: Mapping[str, Any],
    *,
    output_id: str,
    offset: int,
    expected_role: str,
    findings: list[ValidationFinding],
    pointer_prefix: str = "",
) -> None:
    pointer = f"{pointer_prefix}/{offset}"
    if review_finding.get("status") != "open":
        findings.append(
            _finding(
                "p5.specialist_prejudged_disposition",
                "Reviewers report open findings; only the research lead assigns dispositions.",
                output_id,
                f"{pointer}/status",
            )
        )
    if review_finding.get("raised_by") != expected_role:
        findings.append(
            _finding(
                "p5.review_role_mismatch",
                "The review finding is attributed to the wrong research role.",
                output_id,
                f"{pointer}/raised_by",
            )
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _list_document(
    outputs: Mapping[str, RegisteredValidatedOutput], output_id: str
) -> list[Any]:
    output = outputs.get(output_id)
    if output is None or not isinstance(output.document, list):
        return []
    return output.document


def _mapping_document(
    outputs: Mapping[str, RegisteredValidatedOutput], output_id: str
) -> Mapping[str, Any] | None:
    output = outputs.get(output_id)
    if output is None or not isinstance(output.document, Mapping):
        return None
    return output.document


def _method_identity(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    declared = value.get("method_identity")
    if not isinstance(declared, Mapping):
        declared = value.get("identity")
    return declared if isinstance(declared, Mapping) else None


def _identity_matches(value: Any, expected: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    return all(value.get(field) == expected.get(field) for field in (
        "stable_id",
        "version",
        "definition_sha256",
    ))


def _same_stable_id(value: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(value, Mapping) and value.get("stable_id") == expected.get(
        "stable_id"
    )


def _substantive_named_object(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return any(_text(value.get(field)) for field in (
        "object_id",
        "symbol",
        "definition",
        "domain",
    ))


def _validate_primary_artifact(
    document: Mapping[str, Any],
    *,
    primary_field: str,
    object_id: str,
    code_prefix: str,
    findings: list[ValidationFinding],
) -> None:
    primary = document.get(primary_field)
    representations = document.get("representations")
    if not isinstance(primary, Mapping) or not isinstance(representations, list):
        return
    matches = False
    for representation in representations:
        if not isinstance(representation, Mapping):
            continue
        if representation.get("information_layer") != "primary_artifact":
            continue
        artifact = representation.get("artifact")
        if _artifact_pointer_matches(artifact, primary):
            matches = True
            break
    if not matches:
        findings.append(
            _finding(
                f"{code_prefix}.primary_artifact_not_represented",
                "The declared primary artifact must be the primary-artifact representation of the record.",
                object_id,
                f"/{primary_field}",
            )
        )


def _artifact_pointer_matches(left: Any, right: Mapping[str, Any]) -> bool:
    if not isinstance(left, Mapping):
        return False
    return all(left.get(field) == right.get(field) for field in (
        "artifact_id",
        "uri",
        "sha256",
    ))


def _unique_ids(
    items: Sequence[Any],
    *,
    key: str,
    object_id: str,
    pointer: str,
    code: str,
    findings: list[ValidationFinding],
) -> set[str]:
    seen: set[str] = set()
    for offset, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        value = _text(item.get(key))
        if not value:
            continue
        if value in seen:
            findings.append(
                _finding(
                    code,
                    f"Identifier {value!r} occurs more than once.",
                    object_id,
                    f"{pointer}/{offset}/{key}",
                )
            )
        seen.add(value)
    return seen


def _require_resolved_ids(
    values: Any,
    *,
    valid_ids: set[str],
    code: str,
    message: str,
    object_id: str,
    pointer: str,
    findings: list[ValidationFinding],
) -> None:
    missing = sorted(_string_set(values) - valid_ids)
    if missing:
        findings.append(
            _finding(
                code,
                message + " Missing: " + ", ".join(missing) + ".",
                object_id,
                pointer,
            )
        )


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {_text(item) for item in value if _text(item)}


def _has_cycle(graph: Mapping[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(dependency) for dependency in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _finding(
    code: str,
    message: str,
    object_id: str,
    pointer: str = "",
) -> ValidationFinding:
    return make_finding(
        code=code,
        message=message,
        object_id=object_id,
        pointer=pointer,
    )
