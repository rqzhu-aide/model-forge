"""ADR-017: P2 structured lead evaluation - enforcement and surfacing.

Covers the three new finding codes (p2.method_evaluation_missing,
p2.method_evaluation_invalid, p2.review_axis_violation) and the
view-model assembly rule (never fabricate; malformed -> None).
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from model_forge.application.view_models import _method_evaluation
from model_forge.domain.validation import (
    FindingClass,
    ValidationFinding,
    get_policy,
)
from model_forge.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from model_forge.harness.scientific_validators import validate_phase_scientific


def _axis(score: Any = 8, justification: str = "Solid on this axis.") -> dict[str, Any]:
    return {"score": score, "justification": justification, "issue_refs": []}


def _evaluation() -> dict[str, Any]:
    return {
        "theoretical_validity": _axis(8, "Definition and identification are complete."),
        "literature_positioning": _axis(7, "Distinct from the nearest baselines."),
        "empirical_feasibility": _axis(6, "Standard compute; directly executable."),
        "adjudicated_at": "2026-08-21T00:00:00+00:00",
        "review_basis_ids": ["report.p2.theory_review.example"],
    }


def _method_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "identity": {
            "stable_id": "method.evaluation.test",
            "version": 1,
            "definition_sha256": "a" * 64,
        },
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
        "lineage": {"change_class": "initial"},
        "evaluation": _evaluation(),
    }
    record.update(overrides)
    return record


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


def _validate(documents: dict[str, Any]) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P2"),
        mode_id="p2.full_catalog",
        publication_bindings=(),
    )
    findings: list[ValidationFinding] = []
    validate_phase_scientific(
        plan=plan,  # type: ignore[arg-type]
        outputs={key: _output(key, value) for key, value in documents.items()},
        selected_method=None,
        findings=findings,
    )
    return findings


def _codes(findings: list[ValidationFinding]) -> list[str]:
    return [finding.code for finding in findings]


def test_conformant_record_produces_no_evaluation_findings() -> None:
    findings = _validate({"p2.method_changes": [_method_record()]})
    assert not [c for c in _codes(findings) if "evaluation" in c]


def test_missing_evaluation_block_is_blocking_and_correctable() -> None:
    method = _method_record()
    del method["evaluation"]

    findings = _validate({"p2.method_changes": [method]})
    codes = _codes(findings)

    assert codes.count("p2.method_evaluation_missing") == 1
    policy = get_policy("p2.method_evaluation_missing")
    assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    assert policy.blocks_publication is True


def test_invalid_axes_flagged_one_finding_per_axis() -> None:
    evaluation = _evaluation()
    evaluation["theoretical_validity"] = _axis(score=11)
    evaluation["literature_positioning"] = _axis(score="8")
    evaluation["empirical_feasibility"] = _axis(justification="   ")

    findings = _validate({"p2.method_changes": [_method_record(evaluation=evaluation)]})
    invalid = [f for f in findings if f.code == "p2.method_evaluation_invalid"]

    assert len(invalid) == 3
    pointers = {f.json_pointer for f in invalid}
    assert pointers == {
        "/0/evaluation/theoretical_validity",
        "/0/evaluation/literature_positioning",
        "/0/evaluation/empirical_feasibility",
    }


def test_bool_score_is_not_an_integer_score() -> None:
    evaluation = _evaluation()
    evaluation["theoretical_validity"] = _axis(score=True)

    findings = _validate({"p2.method_changes": [_method_record(evaluation=evaluation)]})

    assert "p2.method_evaluation_invalid" in _codes(findings)


def test_review_axis_ownership_enforced_per_role() -> None:
    theory_review = {
        "method_evaluations": [
            {
                "stable_id": "method.evaluation.test",
                "axis": "empirical_feasibility",
                "assessment": "Off-axis assessment by the theorist.",
                "issue_refs": [],
            }
        ]
    }
    findings = _validate(
        {
            "p2.method_changes": [_method_record()],
            "p2.theory_review": theory_review,
        }
    )
    assert "p2.review_axis_violation" in _codes(findings)


def test_correct_axis_evaluations_are_clean() -> None:
    review = {
        "method_evaluations": [
            {
                "stable_id": "method.evaluation.test",
                "axis": "theoretical_validity",
                "assessment": "Identification argument verified.",
                "issue_refs": [],
            }
        ]
    }
    findings = _validate(
        {
            "p2.method_changes": [_method_record()],
            "p2.theory_review": review,
            "p2.empirical_review": {
                "method_evaluations": [
                    {
                        "stable_id": "method.evaluation.test",
                        "axis": "empirical_feasibility",
                        "assessment": "Protocol is directly executable.",
                        "issue_refs": [],
                    }
                ]
            },
        }
    )
    assert "p2.review_axis_violation" not in _codes(findings)


def test_view_model_surfaces_complete_evaluation() -> None:
    assembled = _method_evaluation({"evaluation": _evaluation()})

    assert assembled is not None
    assert assembled.theoretical_validity.score == 8
    assert assembled.literature_positioning.score == 7
    assert assembled.empirical_feasibility.score == 6
    assert assembled.review_basis_ids == ["report.p2.theory_review.example"]


def test_view_model_never_fabricates_scores() -> None:
    assert _method_evaluation({}) is None

    malformed = _evaluation()
    malformed["theoretical_validity"]["score"] = 99
    assert _method_evaluation({"evaluation": malformed}) is None

    missing_refs = _evaluation()
    for axis in ("theoretical_validity", "literature_positioning", "empirical_feasibility"):
        missing_refs[axis] = dict(missing_refs[axis])
        missing_refs[axis].pop("issue_refs")
    assert _method_evaluation({"evaluation": missing_refs}) is None

    wrong_type = deepcopy(_evaluation())
    wrong_type["empirical_feasibility"]["score"] = True
    assert _method_evaluation({"evaluation": wrong_type}) is None


def test_review_without_method_evaluations_is_blocking() -> None:
    """E-1e: stage-2 review outputs must carry structured evaluations."""
    findings = _validate(
        {
            "p2.method_changes": [_method_record()],
            "p2.theory_review": {"unresolved_issues": []},
        }
    )
    assert "p2.review_evaluations_missing" in _codes(findings)
    policy = get_policy("p2.review_evaluations_missing")
    assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    assert policy.blocks_publication is True


def test_review_with_method_evaluations_passes_e1e() -> None:
    findings = _validate(
        {
            "p2.method_changes": [_method_record()],
            "p2.theory_review": {
                "method_evaluations": [
                    {
                        "stable_id": "method.example",
                        "axis": "theoretical_validity",
                        "assessment": "Sound on the owned axis.",
                        "issue_refs": [],
                    }
                ]
            },
            "p2.empirical_review": {
                "method_evaluations": [
                    {
                        "stable_id": "method.example",
                        "axis": "empirical_feasibility",
                        "assessment": "Feasible as specified.",
                        "issue_refs": [],
                    }
                ]
            },
        }
    )
    assert "p2.review_evaluations_missing" not in _codes(findings)
    assert "p2.review_axis_violation" not in _codes(findings)
