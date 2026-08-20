"""Machine validation reports kept separate from scientific assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


class FindingClass(StrEnum):
    """Classification of a validation finding's impact and recovery path."""

    OPERATIONAL_FAILURE = "operational_failure"
    INTEGRITY_BLOCKER = "integrity_blocker"
    CORRECTABLE_CONTRACT_ERROR = "correctable_contract_error"
    SCIENTIFIC_CLAIM_BLOCKER = "scientific_claim_blocker"
    SCIENTIFIC_ATTENTION = "scientific_attention"
    INFORMATION = "information"


# Policy version — incremented when any policy entry changes.
# 1.8.0 (ADR-015): schema.* findings whose failing property is harness-owned
# for the output's schema route to operational_failure (harness fault), not
# correctable_contract_error.
POLICY_VERSION = "1.8.0"


@dataclass(frozen=True, slots=True)
class FindingPolicy:
    """Per-code validation policy entry."""

    code: str
    finding_class: FindingClass
    default_severity: ValidationSeverity
    blocks_publication: bool
    correction_class: str = "none"
    applicable_phases: tuple[str, ...] = ()
    applicable_modes: tuple[str, ...] = ()
    deterministic_repair_allowed: bool = False
    model_call_required: bool = False
    researcher_override_allowed: bool = False
    rationale: str = ""
    user_guidance: str = ""


def _policy(
    code: str,
    finding_class: FindingClass,
    *,
    blocks_publication: bool = True,
    correction_class: str | None = None,
    phases: tuple[str, ...] = (),
    modes: tuple[str, ...] = (),
    deterministic_repair: bool = False,
    model_call: bool = False,
    researcher_override: bool = False,
    rationale: str = "",
    guidance: str = "",
) -> FindingPolicy:
    """Factory for concise policy definitions."""
    severity_map = {
        FindingClass.OPERATIONAL_FAILURE: ValidationSeverity.ERROR,
        FindingClass.INTEGRITY_BLOCKER: ValidationSeverity.ERROR,
        FindingClass.CORRECTABLE_CONTRACT_ERROR: ValidationSeverity.ERROR,
        FindingClass.SCIENTIFIC_CLAIM_BLOCKER: ValidationSeverity.ERROR,
        FindingClass.SCIENTIFIC_ATTENTION: ValidationSeverity.WARNING,
        FindingClass.INFORMATION: ValidationSeverity.INFORMATION,
    }
    correction_map = {
        FindingClass.OPERATIONAL_FAILURE: "none",
        FindingClass.INTEGRITY_BLOCKER: "none",
        FindingClass.CORRECTABLE_CONTRACT_ERROR: "packaging",
        FindingClass.SCIENTIFIC_CLAIM_BLOCKER: "scientific",
        FindingClass.SCIENTIFIC_ATTENTION: "none",
        FindingClass.INFORMATION: "none",
    }
    return FindingPolicy(
        code=code,
        finding_class=finding_class,
        default_severity=severity_map[finding_class],
        blocks_publication=blocks_publication,
        correction_class=(
            correction_map[finding_class]
            if correction_class is None
            else correction_class
        ),
        applicable_phases=phases,
        applicable_modes=modes,
        deterministic_repair_allowed=deterministic_repair,
        model_call_required=model_call,
        researcher_override_allowed=researcher_override,
        rationale=rationale,
        user_guidance=guidance,
    )


# --------------------------------------------------------------------------- #
# Policy registry
# --------------------------------------------------------------------------- #

_DEFAULT_POLICY = FindingPolicy(
    code="__default__",
    finding_class=FindingClass.INTEGRITY_BLOCKER,
    default_severity=ValidationSeverity.ERROR,
    blocks_publication=True,
    correction_class="none",
    rationale="Unregistered codes default to blocking (fail-closed).",
    user_guidance="This finding code is not in the policy registry; it blocks by default.",
)


def _build_registry() -> dict[str, FindingPolicy]:
    """Build the complete policy registry from the HV-0 inventory."""
    registry: dict[str, FindingPolicy] = {}

    def _register(
        code: str,
        cls: FindingClass,
        **kwargs: Any,
    ) -> None:
        registry[code] = _policy(code, cls, **kwargs)

    # --- Integrity blockers (identity/provenance/digest/path/mode) --- #

    for code in (
        "p2.focused_initial_lineage",
        "p2.focused_method_identity_missing",
        "p2.focused_scope_exceeded",
        "p2.mathematical_digest_unchanged",
        "p2.mathematical_stable_id_changed",
        "p2.mathematical_version_not_advanced",
        "p2.nonmathematical_identity_changed",
        "p2.predecessor_identity_mismatch",
        "p3.development_mode_mismatch",
        "p3.method_identity_mismatch",
        "p4.incomplete_four_slot_update",
        "p4.protocol_method_mismatch",
        "p4.protocol_mode_mismatch",
        "p5.method_identity_mismatch",
        "p5.review_role_mismatch",
        "p5.specialist_prejudged_disposition",
        "submission.artifact_identity_mismatch",
        "submission.artifact_unavailable",
        "submission.digest_mismatch",
        "submission.method_identity_mismatch",
        "submission.method_identity_missing",
        "submission.missing",
        "submission.output_identity_mismatch",
        "submission.output_provenance_mismatch",
        "submission.phase_mismatch",
        "submission.project_mismatch",
        "input.method_identity_mismatch",
        "input.method_identity_missing",
        "input.method_lineage_mismatch",
        "input.p4_prior_package_incomplete",
        "output.not_regular_file",
        "output.unsafe_path",
    ):
        _register(code, FindingClass.INTEGRITY_BLOCKER)

    # A Lane B correction that changed bytes outside its permitted blast
    # radius (design 4a): the attempt is void and can never become a
    # SUCCEEDED correction closure.
    _register(
        "correction.blast_radius_violated",
        FindingClass.INTEGRITY_BLOCKER,
        rationale=(
            "A correction touched outputs or document locations it was not "
            "authorized to change; the attempt is spent."
        ),
        guidance=(
            "Re-issue the correction limited to the permitted change "
            "locations (packaging) or the permitted output scope (scientific)."
        ),
    )

    # --- Correctable contract errors (shape/schema/reference violations) --- #

    for code in (
        "p1.duplicate_source_id",
        "p1.duplicate_source_identifier",
        "p1.duplicate_source_identity",
        "p2.predecessor_generation_missing",
        "p3.duplicate_assumption_id",
        "p3.duplicate_implication_id",
        "p3.duplicate_statement_id",
        "p3.no_assumptions_documented",
        "p3.revision_account_missing",
        "p3.self_dependent_statement",
        "p3.statement_dependency_cycle",
        "p3.unknown_assumption_reference",
        "p3.unknown_empirical_implication",
        "p3.unknown_implication_statement",
        "p3.unknown_revision_statement",
        "p3.unknown_statement_dependency",
        "p3.unknown_statement_reference",
        "p3.conditional_statement_without_assumption",
        "p3.contradiction_without_evidence",
        "p3.incomplete_statement_without_obligation",
        "p3.untested_statement_without_obligation",
        "p3.retracted_statement_without_reason",
        "p4.duplicate_metric_id",
        "p4.duplicate_test_id",
        "p4.duplicate_threshold_id",
        "p4.unknown_decision_threshold",
        "p4.unknown_deviation_test",
        "p4.unknown_threshold_claim",
        "p4.unknown_threshold_metric",
        "p5.disposition_reason_missing",
        "p5.duplicate_issue_disposition",
        "p5.issue_undispositioned",
        "p5.manuscript_basis_missing",
        "p5.manuscript_kind_mismatch",
        "p5.manuscript_missing",
        "p5.review_finding_not_dispositioned",
        "p5.revision_location_missing",
        "p5.unknown_claim_support_reference",
        "submission.artifact_invalid",
        "submission.artifact_pointer_missing",
        "submission.duplicate_output",
        "submission.invalid_document",
        "submission.invalid_output_entry",
        "submission.output_shape_mismatch",
        "submission.required_output_missing",
        "submission.unexpected_output",
        "input.required_context_not_selected",
        "input.required_current_record_missing",
        "input.unknown_context_selection",
        "json.decode_error",
        "json.duplicate_key",
        "json.invalid_input_type",
        "json.non_finite_number",
        "json.read_error",
        "output.expected_array",
        "output.expected_object",
        "output.required_missing",
        "output.role_has_no_contract",
        "output.unknown_schema_application",
        "output.unreadable",
    ):
        _register(
            code,
            FindingClass.CORRECTABLE_CONTRACT_ERROR,
            correction_class="packaging",
            deterministic_repair=True,
        )

    # --- Scientific claim blockers --- #

    for code in (
        "p2.canonical_definition_empty",
        "p2.defining_components_empty",
        "p3.established_statement_unsupported",
        "p3.primary_artifact_not_represented",
        "p4.evidence_method_mismatch",
        "p4.evidence_missing_method_identity",
        "p4.protocol_finalized_after_evidence",
        "p4.reproducibility_artifact_missing",
        "p4.reproducibility_missing",
        "p4.simulation_seed_missing",
        "p5.claim_without_evidence",
        "p5.primary_artifact_not_represented",
    ):
        _register(code, FindingClass.SCIENTIFIC_CLAIM_BLOCKER)

    # --- Scientific attention (preserved, non-blocking) --- #

    # Evidence assessed as not exactly applicable is retained in the record but
    # excluded from current-method synthesis; it warns instead of blocking.
    _register(
        "p4.evidence_not_exactly_applicable",
        FindingClass.SCIENTIFIC_ATTENTION,
        blocks_publication=False,
    )

    # --- Scientific attention (non-blocking warnings) --- #
    # Some methods legitimately have empty assumptions, limitations, or
    # literature provenance (e.g. a novel method with no prior literature),
    # and some sources are researcher-supplied or imported from an existing
    # library rather than discovered by search. These warrant reviewer
    # attention but must not block publication.

    for code in (
        "p1.search_provenance_missing",
        "p2.assumptions_empty",
        "p2.limitations_empty",
        "p2.literature_provenance_empty",
    ):
        _register(code, FindingClass.SCIENTIFIC_ATTENTION, blocks_publication=False)

    # Dynamic schema codes — jsonschema validator names
    # These are unbounded; register a prefix match.
    # The registry handles them via the default fail-closed rule.

    return registry


_REGISTRY: dict[str, FindingPolicy] = _build_registry()


# Dynamically composed codes that are structurally correctable.
# jsonschema emits unbounded ``schema.<rule>`` codes (schema.required,
# schema.minItems, schema.additionalProperties, ...): they are produced by
# structural contract violations in agent output, never by an integrity
# breach, so they classify as correctable contract errors.  They still BLOCK
# publication until corrected; only the recovery routing changes (HV-3's
# needs_output_correction path instead of integrity_rejected).
_SCHEMA_CODE_POLICY = FindingPolicy(
    code="schema.*",
    finding_class=FindingClass.CORRECTABLE_CONTRACT_ERROR,
    default_severity=ValidationSeverity.ERROR,
    blocks_publication=True,
    correction_class="packaging",
    rationale="jsonschema structural violations are correctable contract errors.",
    user_guidance="The output does not satisfy the declared schema; correct the named field.",
)


def get_policy(code: str) -> FindingPolicy:
    """Look up the policy for a finding code.

    Unregistered codes receive the fail-closed default: ERROR severity,
    blocks publication.  Two bounded dynamic families are classified before
    the default: ``schema.*`` (jsonschema structural rules) as correctable
    contract errors; anything else remains an integrity blocker.
    """
    policy = _REGISTRY.get(code)
    if policy is not None:
        return policy
    if code.startswith("schema."):
        return _SCHEMA_CODE_POLICY
    return _DEFAULT_POLICY


def registry_version() -> str:
    """Return the current policy registry version."""
    return POLICY_VERSION


def all_registered_codes() -> frozenset[str]:
    """Return all explicitly registered finding codes."""
    return frozenset(_REGISTRY.keys())


# --------------------------------------------------------------------------- #
# Validation types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True, order=True)
class ValidationFinding:
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    object_id: str | None = None
    json_pointer: str = ""
    finding_class: FindingClass = FindingClass.INTEGRITY_BLOCKER
    blocks_publication: bool = True
    correction_class: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "object_id": self.object_id,
            "json_pointer": self.json_pointer,
            "finding_class": self.finding_class.value,
            "blocks_publication": self.blocks_publication,
            "correction_class": self.correction_class,
        }


def finding_from_dict(item: Any) -> ValidationFinding | None:
    """Rehydrate a serialized finding dict; None for non-dict input."""
    if type(item) is not dict:
        return None
    object_id = item.get("object_id")
    return ValidationFinding(
        code=str(item.get("code", "")),
        message=str(item.get("message", "")),
        severity=ValidationSeverity(str(item.get("severity", "error"))),
        object_id=None if object_id is None else str(object_id),
        json_pointer=str(item.get("json_pointer", "")),
        finding_class=FindingClass(
            str(item.get("finding_class", "integrity_blocker"))
        ),
        blocks_publication=bool(item.get("blocks_publication", True)),
        correction_class=str(item.get("correction_class", "none")),
    )


def make_finding(
    code: str,
    message: str,
    object_id: str | None = None,
    pointer: str = "",
) -> ValidationFinding:
    """Create a ValidationFinding with policy looked up from the registry.

    This replaces the old pattern of hardcoding ``severity=ERROR`` at every
    call site. The severity, finding_class, blocks_publication, and
    correction_class all come from the registry.
    """
    policy = get_policy(code)
    return ValidationFinding(
        code=code,
        message=message,
        severity=policy.default_severity,
        object_id=object_id,
        json_pointer=pointer,
        finding_class=policy.finding_class,
        blocks_publication=policy.blocks_publication,
        correction_class=policy.correction_class,
    )


@dataclass(frozen=True, slots=True)
class ValidationReport:
    report_id: str
    run_id: str
    category: str
    findings: tuple[ValidationFinding, ...] = field(default_factory=tuple)

    @classmethod
    def from_findings(
        cls,
        report_id: str,
        run_id: str,
        category: str,
        findings: Iterable[ValidationFinding],
    ) -> "ValidationReport":
        return cls(report_id, run_id, category, tuple(findings))

    @property
    def passed(self) -> bool:
        return not any(item.blocks_publication for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "category": self.category,
            "passed": self.passed,
            "findings": [item.to_dict() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class TransformationEntry:
    """One mechanical transformation applied during repair."""

    code: str
    json_pointer: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "json_pointer": self.json_pointer,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class OutputTransformationRecord:
    """Structured record of all mechanical transformations applied to one output.

    Records what the repair pass changed so the researcher can inspect exactly
    what was modified between the agent's raw output and the sealed candidate.
    """

    contract_output_id: str
    source_sha256: str
    result_sha256: str
    entries: tuple[TransformationEntry, ...] = field(default_factory=tuple)
    harness_version: str = "1.0.0"
    primary_artifact_unchanged: bool = True

    @property
    def changed(self) -> bool:
        return self.source_sha256 != self.result_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_output_id": self.contract_output_id,
            "source_sha256": self.source_sha256,
            "result_sha256": self.result_sha256,
            "changed": self.changed,
            "entries": [entry.to_dict() for entry in self.entries],
            "harness_version": self.harness_version,
            "primary_artifact_unchanged": self.primary_artifact_unchanged,
        }


__all__ = [
    "FindingClass",
    "FindingPolicy",
    "OutputTransformationRecord",
    "POLICY_VERSION",
    "TransformationEntry",
    "ValidationFinding",
    "ValidationReport",
    "ValidationSeverity",
    "all_registered_codes",
    "finding_from_dict",
    "get_policy",
    "make_finding",
    "registry_version",
]
