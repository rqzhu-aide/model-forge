"""HV-6.P2: Methods calibration — empty categories warn, identity stays strict.

Some methods legitimately have empty assumptions, limitations, or literature
provenance (e.g. a novel method with no prior literature). Those three codes
are reclassified from CORRECTABLE_CONTRACT_ERROR (blocking) to
SCIENTIFIC_ATTENTION (WARNING, non-blocking). Mathematical identity checks
must remain INTEGRITY_BLOCKERs.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from method_hub.domain import MethodIdentity
from method_hub.domain.validation import (
    FindingClass,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    get_policy,
)
from method_hub.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from method_hub.harness.scientific_validators import validate_phase_scientific


METHOD = MethodIdentity(
    stable_id="method.calibration.test",
    version=1,
    definition_sha256="a" * 64,
)


def _output(output_id: str, document: Any) -> RegisteredValidatedOutput:
    return RegisteredValidatedOutput(
        contract_output_id=output_id,
        document=document,
        artifact=RegisteredArtifactMetadata(
            artifact_id=f"artifact.{output_id.replace('.', '_')}",
            sha256="d" * 64,
            byte_length=1,
            media_type="application/json",
            storage_uri=f"memory://{output_id}",
        ),
    )


def _validate(
    mode_id: str,
    documents: dict[str, Any],
    *,
    selected_method: MethodIdentity | None = None,
) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P2"),
        mode_id=mode_id,
        publication_bindings=(),
    )
    findings: list[ValidationFinding] = []
    validate_phase_scientific(
        plan=plan,  # type: ignore[arg-type]
        outputs={key: _output(key, value) for key, value in documents.items()},
        selected_method=selected_method,
        findings=findings,
    )
    return findings


def _codes(findings: list[ValidationFinding]) -> list[str]:
    return [finding.code for finding in findings]


def _method_record(
    *,
    change_class: str = "editorial",
    **overrides: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "identity": deepcopy(METHOD.to_dict()),
        "mathematical_definition": {
            "canonical_definition": {
                "target_or_estimand": {"definition": "Population prediction risk."},
                "objective_or_estimating_equation": {
                    "definition": "Minimize the population risk."
                },
            },
            "defining_components": ["loss", "regularizer"],
        },
        "assumptions": ["Independent observations."],
        "literature_provenance": ["record.literature.001"],
        "limitations": ["The guarantee is distribution-specific."],
        "lineage": {
            "change_class": change_class,
            "predecessor": deepcopy(METHOD.to_dict()),
            "predecessor_generation_id": "generation.method.001",
        },
        "evaluation": {
            "theoretical_validity": {
                "score": 8,
                "justification": "Definition and identification argument are complete.",
                "issue_refs": [],
            },
            "literature_positioning": {
                "score": 7,
                "justification": "Clearly distinct from the nearest published baselines.",
                "issue_refs": [],
            },
            "empirical_feasibility": {
                "score": 6,
                "justification": "Standard compute; the protocol is directly executable.",
                "issue_refs": [],
            },
            "adjudicated_at": "2026-08-21T00:00:00+00:00",
            "review_basis_ids": ["report.p2.theory_review.example"],
        },
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------- #
# Empty categories: WARNING, not blocking                                     #
# --------------------------------------------------------------------------- #


def test_empty_assumptions_is_warning_not_blocking() -> None:
    """A method with empty assumptions must pass with a WARNING only."""
    method = _method_record(assumptions=[])

    findings = _validate(
        "p2.full_catalog",
        {"p2.method_changes": [method]},
    )

    matching = [f for f in findings if f.code == "p2.assumptions_empty"]
    assert len(matching) == 1
    finding = matching[0]
    assert finding.finding_class is FindingClass.SCIENTIFIC_ATTENTION
    assert finding.severity is ValidationSeverity.WARNING
    assert finding.blocks_publication is False

    report = ValidationReport.from_findings("r1", "run1", "P2", findings)
    assert report.passed is True


def test_empty_limitations_is_warning_not_blocking() -> None:
    """A method with empty limitations must pass with a WARNING only."""
    method = _method_record(limitations=[])

    findings = _validate(
        "p2.full_catalog",
        {"p2.method_changes": [method]},
    )

    matching = [f for f in findings if f.code == "p2.limitations_empty"]
    assert len(matching) == 1
    finding = matching[0]
    assert finding.finding_class is FindingClass.SCIENTIFIC_ATTENTION
    assert finding.severity is ValidationSeverity.WARNING
    assert finding.blocks_publication is False

    report = ValidationReport.from_findings("r1", "run1", "P2", findings)
    assert report.passed is True


def test_empty_literature_provenance_is_warning_not_blocking() -> None:
    """A novel method with no prior literature must pass with a WARNING only."""
    method = _method_record(literature_provenance=[])

    findings = _validate(
        "p2.full_catalog",
        {"p2.method_changes": [method]},
    )

    matching = [f for f in findings if f.code == "p2.literature_provenance_empty"]
    assert len(matching) == 1
    finding = matching[0]
    assert finding.finding_class is FindingClass.SCIENTIFIC_ATTENTION
    assert finding.severity is ValidationSeverity.WARNING
    assert finding.blocks_publication is False

    report = ValidationReport.from_findings("r1", "run1", "P2", findings)
    assert report.passed is True


# --------------------------------------------------------------------------- #
# Mathematical identity: still blocking                                      #
# --------------------------------------------------------------------------- #


def test_unchanged_mathematical_digest_still_blocks() -> None:
    """A mathematical revision that keeps the definition digest must block."""
    method = _method_record(
        change_class="mathematical",
        identity={
            "stable_id": METHOD.stable_id.value,
            "version": 2,
            "definition_sha256": METHOD.definition_sha256.value,  # unchanged
        },
    )

    findings = _validate(
        "p2.focused_method",
        {"p2.method_changes": [method]},
        selected_method=METHOD,
    )

    matching = [f for f in findings if f.code == "p2.mathematical_digest_unchanged"]
    assert len(matching) == 1
    finding = matching[0]
    assert finding.finding_class is FindingClass.INTEGRITY_BLOCKER
    assert finding.severity is ValidationSeverity.ERROR
    assert finding.blocks_publication is True

    report = ValidationReport.from_findings("r1", "run1", "P2", findings)
    assert report.passed is False


def test_changed_stable_id_still_blocks() -> None:
    """A mathematical revision that changes the stable ID must block."""
    method = _method_record(
        change_class="mathematical",
        identity={
            "stable_id": "method.calibration.other",
            "version": 2,
            "definition_sha256": "b" * 64,
        },
    )

    findings = _validate(
        "p2.focused_method",
        {"p2.method_changes": [method]},
        selected_method=METHOD,
    )

    matching = [f for f in findings if f.code == "p2.mathematical_stable_id_changed"]
    assert len(matching) == 1
    finding = matching[0]
    assert finding.finding_class is FindingClass.INTEGRITY_BLOCKER
    assert finding.severity is ValidationSeverity.ERROR
    assert finding.blocks_publication is True

    report = ValidationReport.from_findings("r1", "run1", "P2", findings)
    assert report.passed is False


# --------------------------------------------------------------------------- #
# Identity codes stay strict (regression guard)                               #
# --------------------------------------------------------------------------- #

_IDENTITY_CODES = (
    "p2.mathematical_digest_unchanged",
    "p2.mathematical_stable_id_changed",
    "p2.mathematical_version_not_advanced",
    "p2.predecessor_identity_mismatch",
    "p2.nonmathematical_identity_changed",
)


def test_identity_codes_remain_integrity_blockers() -> None:
    """The mathematical identity codes must never be downgraded."""
    for code in _IDENTITY_CODES:
        policy = get_policy(code)
        assert policy.finding_class is FindingClass.INTEGRITY_BLOCKER, code
        assert policy.default_severity is ValidationSeverity.ERROR, code
        assert policy.blocks_publication is True, code
