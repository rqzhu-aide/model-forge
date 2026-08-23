from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from method_hub.domain import MethodIdentity
from method_hub.domain.validation import ValidationFinding
from method_hub.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from method_hub.harness.scientific_validators import validate_phase_scientific


METHOD = MethodIdentity(
    stable_id="method.validator.integrity",
    version=1,
    definition_sha256="a" * 64,
)
OTHER_METHOD = {
    "stable_id": METHOD.stable_id.value,
    "version": 2,
    "definition_sha256": "b" * 64,
}
ARTIFACT = {
    "artifact_id": "artifact.validator.primary",
    "uri": "artifact://validator/primary",
    # Non-degenerate digest: repeated single-character sha256 values are
    # rejected as synthetic pointers (E-2d, policy 1.11.0).
    "sha256": "c3ab8ff13720e8ad9047dd39466b3c8974e592c2fa383d4a3960714caef0c4f2",
}


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
    phase_id: str,
    mode_id: str,
    documents: dict[str, Any],
    *,
    selected_method: MethodIdentity | None = METHOD,
) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id=phase_id),
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
    identity: dict[str, Any] | None = None,
    predecessor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "identity": deepcopy(identity or METHOD.to_dict()),
        "mathematical_definition": {
            "canonical_definition": {
                "target_or_estimand": {
                    "definition": "Population prediction risk."
                },
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
            "predecessor": deepcopy(predecessor or METHOD.to_dict()),
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


def test_p2_rejects_empty_canonical_definition() -> None:
    method = _method_record()
    method["mathematical_definition"]["canonical_definition"] = {
        "target_or_estimand": {},
        "objective_or_estimating_equation": {},
    }
    method["mathematical_definition"]["defining_components"] = []
    method["assumptions"] = []
    method["literature_provenance"] = []
    method["limitations"] = []

    findings = _validate(
        "P2",
        "p2.full_catalog",
        {"p2.method_changes": [method]},
        selected_method=None,
    )
    codes = _codes(findings)

    assert codes.count("p2.canonical_definition_empty") == 2
    assert "p2.defining_components_empty" in codes
    assert "p2.assumptions_empty" in codes
    assert "p2.literature_provenance_empty" in codes
    assert "p2.limitations_empty" in codes


def test_p2_focused_lineage_enforces_version_and_definition_digest() -> None:
    editorial = _method_record(identity=OTHER_METHOD)
    editorial_codes = _codes(
        _validate(
            "P2",
            "p2.focused_method",
            {"p2.method_changes": [editorial]},
        )
    )
    assert "p2.nonmathematical_identity_changed" in editorial_codes

    unchanged_math = _method_record(change_class="mathematical")
    unchanged_codes = _codes(
        _validate(
            "P2",
            "p2.focused_method",
            {"p2.method_changes": [unchanged_math]},
        )
    )
    assert "p2.mathematical_version_not_advanced" in unchanged_codes
    assert "p2.mathematical_digest_unchanged" in unchanged_codes

    wrong_predecessor = _method_record(
        change_class="mathematical",
        identity=OTHER_METHOD,
        predecessor=OTHER_METHOD,
    )
    predecessor_codes = _codes(
        _validate(
            "P2",
            "p2.focused_method",
            {"p2.method_changes": [wrong_predecessor]},
        )
    )
    assert "p2.predecessor_identity_mismatch" in predecessor_codes

    valid_math = _method_record(
        change_class="mathematical",
        identity=OTHER_METHOD,
    )
    valid_codes = _codes(
        _validate(
            "P2",
            "p2.focused_method",
            {"p2.method_changes": [valid_math]},
        )
    )
    assert not [code for code in valid_codes if code.startswith("p2.")]


def _theory_record(
    *,
    identity: dict[str, Any] | None = None,
    mode: str = "p3.theory_establishment",
) -> dict[str, Any]:
    return {
        "method_identity": deepcopy(identity or METHOD.to_dict()),
        "development_mode": mode,
        "basis": [{"record_id": "record.method.001"}],
        "primary_artifact": deepcopy(ARTIFACT),
        "representations": [
            {
                "information_layer": "primary_artifact",
                "artifact": deepcopy(ARTIFACT),
            }
        ],
        "assumptions": [
            {
                "assumption_id": "assumption.regularity.001",
                "used_by_statement_ids": ["statement.main.001"],
            }
        ],
        "statements": [
            {
                "statement_id": "statement.main.001",
                "statement_type": "theorem",
                "status": "established",
                "assumption_ids": ["assumption.regularity.001"],
                "depends_on_statement_ids": [],
                "empirical_implication_ids": ["implication.main.001"],
                "justification": {
                    "kind": "proof",
                    "summary": "A complete proof is in the primary artifact.",
                    "artifacts": [deepcopy(ARTIFACT)],
                },
            }
        ],
        "empirical_implications": [
            {
                "implication_id": "implication.main.001",
                "statement_ids": ["statement.main.001"],
            }
        ],
        "scientific_outcome": {"state": "supported"},
    }


def test_p3_requires_exact_method_identity() -> None:
    findings = _validate(
        "P3",
        "p3.theory_establishment",
        {"p3.complete_theory": _theory_record(identity=OTHER_METHOD)},
    )
    assert "p3.method_identity_mismatch" in _codes(findings)


def test_p3_rejects_dangling_and_cyclic_statement_references() -> None:
    theory = _theory_record()
    theory["assumptions"][0]["used_by_statement_ids"] = [
        "statement.one",
        "statement.absent",
    ]
    theory["statements"] = [
        {
            "statement_id": "statement.one",
            "statement_type": "proposition",
            "status": "conditional",
            "assumption_ids": ["assumption.absent"],
            "depends_on_statement_ids": ["statement.two", "statement.absent"],
            "empirical_implication_ids": ["implication.absent"],
            "justification": {
                "kind": "proof",
                "summary": "Conditional argument.",
                "artifacts": [deepcopy(ARTIFACT)],
            },
        },
        {
            "statement_id": "statement.two",
            "statement_type": "lemma",
            "status": "conditional",
            "assumption_ids": ["assumption.regularity.001"],
            "depends_on_statement_ids": ["statement.one"],
            "empirical_implication_ids": ["implication.main.001"],
            "justification": {
                "kind": "proof",
                "summary": "Conditional argument.",
                "artifacts": [deepcopy(ARTIFACT)],
            },
        },
    ]
    theory["empirical_implications"][0]["statement_ids"] = [
        "statement.one",
        "statement.absent",
    ]

    codes = _codes(
        _validate(
            "P3",
            "p3.theory_establishment",
            {"p3.complete_theory": theory},
        )
    )

    assert "p3.unknown_statement_reference" in codes
    assert "p3.unknown_assumption_reference" in codes
    assert "p3.unknown_statement_dependency" in codes
    assert "p3.unknown_empirical_implication" in codes
    assert "p3.unknown_implication_statement" in codes
    assert "p3.statement_dependency_cycle" in codes


def test_p3_established_statement_requires_a_proof_artifact() -> None:
    theory = _theory_record()
    theory["statements"][0]["justification"]["artifacts"] = []

    findings = _validate(
        "P3",
        "p3.theory_establishment",
        {"p3.complete_theory": theory},
    )
    assert "p3.established_statement_unsupported" in _codes(findings)


def test_p3_accepts_documented_contradiction_and_negative_outcome() -> None:
    theory = _theory_record()
    theory["statements"][0]["status"] = "contradicted"
    theory["statements"][0]["justification"] = {
        "kind": "counterexample",
        "summary": "A boundary construction contradicts the stated rate.",
        "artifacts": [deepcopy(ARTIFACT)],
    }
    theory["scientific_outcome"] = {"state": "contradicted"}

    findings = _validate(
        "P3",
        "p3.theory_establishment",
        {"p3.complete_theory": theory},
    )
    assert findings == []


def test_p3_conditional_statement_requires_conditioning_assumption() -> None:
    theory = _theory_record()
    theory["statements"][0]["status"] = "conditional"
    theory["statements"][0]["assumption_ids"] = []

    findings = _validate(
        "P3",
        "p3.theory_establishment",
        {"p3.complete_theory": theory},
    )
    assert "p3.conditional_statement_without_assumption" in _codes(findings)

    theory["statements"][0]["assumption_ids"] = ["assumption.regularity.001"]
    assert (
        _validate(
            "P3",
            "p3.theory_establishment",
            {"p3.complete_theory": theory},
        )
        == []
    )


def test_p3_untested_statement_requires_open_obligation() -> None:
    theory = _theory_record()
    theory["statements"][0]["status"] = "untested"

    findings = _validate(
        "P3",
        "p3.theory_establishment",
        {"p3.complete_theory": theory},
    )
    assert "p3.untested_statement_without_obligation" in _codes(findings)

    theory["statements"][0]["justification"] = {
        "kind": "open_obligation",
        "summary": "The statement remains untested.",
        "open_obligation": "Provide a proof or a counterexample in a future generation.",
    }
    assert (
        _validate(
            "P3",
            "p3.theory_establishment",
            {"p3.complete_theory": theory},
        )
        == []
    )


def test_p3_retracted_statement_requires_reason() -> None:
    theory = _theory_record()
    theory["statements"][0]["status"] = "retracted"
    theory["statements"][0]["justification"] = {
        "kind": "counterexample",
        "summary": "",
        "artifacts": [deepcopy(ARTIFACT)],
    }

    findings = _validate(
        "P3",
        "p3.theory_establishment",
        {"p3.complete_theory": theory},
    )
    assert "p3.retracted_statement_without_reason" in _codes(findings)

    theory["statements"][0]["justification"]["summary"] = (
        "A boundary construction invalidates the claim; it is superseded by statement.main.002."
    )
    assert (
        _validate(
            "P3",
            "p3.theory_establishment",
            {"p3.complete_theory": theory},
        )
        == []
    )


def _protocol(
    *,
    identity: dict[str, Any] | None = None,
    mode: str = "p4.preliminary",
) -> dict[str, Any]:
    return {
        "mode": mode,
        "method_identity": deepcopy(identity or METHOD.to_dict()),
        "claim_tests": [
            {
                "test_id": "test.risk.001",
                "claim_id": "claim.risk.001",
                "decision_threshold_ids": ["threshold.risk.001"],
            }
        ],
        "metrics": [{"metric_id": "metric.risk.001"}],
        "decision_thresholds": [
            {
                "threshold_id": "threshold.risk.001",
                "claim_id": "claim.risk.001",
                "metric_id": "metric.risk.001",
            }
        ],
        "deviations": [],
        "finalized_at": "2026-08-11T12:00:00Z",
    }


def _reproducibility(*, empty: bool = False) -> dict[str, Any]:
    values = [] if empty else [deepcopy(ARTIFACT)]
    return {
        "code_artifacts": deepcopy(values),
        "data_artifacts": deepcopy(values),
        "configuration_artifacts": deepcopy(values),
        "random_seeds": [] if empty else [7],
        "environment_artifacts": deepcopy(values),
    }


def _evidence(
    *,
    identity: dict[str, Any] | None = None,
    outcome: str = "supported",
    reproducibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_kind": "simulation",
        "method_identity": deepcopy(identity or METHOD.to_dict()),
        "applicability_at_creation": {"method_match": "exact"},
        "reproducibility": deepcopy(reproducibility or _reproducibility()),
        "scientific_outcome": {"state": outcome},
        "created_at": "2026-08-11T13:00:00Z",
    }


def test_p4_protocol_rejects_dangling_internal_references() -> None:
    protocol = _protocol()
    protocol["claim_tests"][0]["decision_threshold_ids"] = [
        "threshold.absent"
    ]
    protocol["decision_thresholds"][0]["metric_id"] = "metric.absent"
    protocol["decision_thresholds"][0]["claim_id"] = "claim.absent"
    protocol["deviations"] = [
        {"deviation_id": "deviation.001", "affected_test_ids": ["test.absent"]}
    ]

    codes = _codes(
        _validate(
            "P4",
            "p4.preliminary",
            {"p4.protocol": protocol},
        )
    )

    assert "p4.unknown_decision_threshold" in codes
    assert "p4.unknown_threshold_metric" in codes
    assert "p4.unknown_threshold_claim" in codes
    assert "p4.unknown_deviation_test" in codes


def test_p4_requires_exact_protocol_and_evidence_method_identity() -> None:
    evidence = _evidence(identity=OTHER_METHOD)
    evidence["applicability_at_creation"]["method_match"] = "older_method_version"
    findings = _validate(
        "P4",
        "p4.preliminary",
        {
            "p4.protocol": _protocol(identity=OTHER_METHOD),
            "p4.evidence": [evidence],
        },
    )
    codes = _codes(findings)

    assert "p4.protocol_method_mismatch" in codes
    assert "p4.evidence_method_mismatch" in codes
    assert "p4.evidence_not_exactly_applicable" in codes


def test_p4_requires_reproducibility_artifacts_and_simulation_seeds() -> None:
    missing = _evidence()
    missing.pop("reproducibility")
    empty = _evidence(reproducibility=_reproducibility(empty=True))

    findings = _validate(
        "P4",
        "p4.comprehensive",
        {
            "p4.protocol": _protocol(),
            "p4.evidence": [missing, empty],
        },
    )
    codes = _codes(findings)

    assert codes.count("p4.reproducibility_missing") == 1
    assert codes.count("p4.reproducibility_artifact_missing") == 3
    assert codes.count("p4.simulation_seed_missing") == 1


def test_p4_accepts_reproducible_negative_outcome() -> None:
    findings = _validate(
        "P4",
        "p4.preliminary",
        {
            "p4.protocol": _protocol(),
            "p4.evidence": [_evidence(outcome="contradicted")],
        },
    )
    assert findings == []


def _claim(
    claim_id: str = "claim.manuscript.001",
    *,
    supporting: list[str] | None = None,
    counter: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "statement_id": claim_id,
        "statement_type": "theorem",
        "supporting_evidence_ids": (
            ["evidence.support.001"] if supporting is None else supporting
        ),
        "counterevidence_ids": [] if counter is None else counter,
    }


def _manuscript(
    *,
    kind: str = "revised_candidate",
    identity: dict[str, Any] | None = None,
    claim_id: str = "claim.manuscript.001",
) -> dict[str, Any]:
    return {
        "manuscript_kind": kind,
        "method_identity": deepcopy(identity or METHOD.to_dict()),
        "basis": [{"record_id": "record.upstream.001"}],
        "manuscript_artifact": deepcopy(ARTIFACT),
        "representations": [
            {
                "information_layer": "primary_artifact",
                "artifact": deepcopy(ARTIFACT),
            }
        ],
        "claim_support_index": {
            "p1_literature_claim_ids": [claim_id],
            "p2_method_claim_ids": [claim_id],
            "p3_theory_claim_ids": [claim_id],
            "p4_empirical_claim_ids": [claim_id],
            "interpretation_claim_ids": [],
        },
    }


def _review_finding(issue_id: str, raised_by: str) -> dict[str, Any]:
    return {"issue_id": issue_id, "raised_by": raised_by, "status": "open"}


def _review_issue(
    issue_id: str,
    *,
    disposition: str = "fixed",
    locations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "disposition": disposition,
        "disposition_reason": "The lead assessed the finding against the basis.",
        "revision_locations": ["Results, paragraph 2"] if locations is None else locations,
    }


def _valid_review_outputs() -> dict[str, Any]:
    return {
        "p5.claim_traceability": [_claim()],
        "p5.manuscript_candidate": _manuscript(),
        "p5.theory_audit": [
            _review_finding("issue.theory.001", "theorist")
        ],
        "p5.empirical_audit": [
            _review_finding("issue.empirical.001", "data_analyst")
        ],
        "p5.outside_review": {
            "prioritized_issues": [
                _review_finding("issue.outside.001", "outside_reviewer")
            ]
        },
        "p5.review_issues": [
            _review_issue("issue.theory.001"),
            _review_issue("issue.empirical.001"),
            _review_issue("issue.outside.001"),
        ],
    }


def test_p5_open_reviewer_findings_receive_lead_dispositions() -> None:
    assert _validate(
        "P5",
        "p5.review_revision",
        _valid_review_outputs(),
    ) == []

    outputs = _valid_review_outputs()
    outputs["p5.theory_audit"][0]["status"] = "fixed"
    outputs["p5.empirical_audit"][0]["raised_by"] = "theorist"
    outputs["p5.review_issues"] = [
        _review_issue("issue.theory.001", disposition="open"),
        _review_issue("issue.empirical.001", locations=[]),
    ]
    findings = _validate("P5", "p5.review_revision", outputs)
    codes = _codes(findings)

    assert "p5.specialist_prejudged_disposition" in codes
    assert "p5.review_role_mismatch" in codes
    assert "p5.issue_undispositioned" in codes
    assert "p5.revision_location_missing" in codes
    assert "p5.review_finding_not_dispositioned" in codes


def test_p5_dead_disposition_members_are_not_treated_as_live() -> None:
    outputs = _valid_review_outputs()
    addressed = _review_issue("issue.theory.001", disposition="addressed", locations=[])
    addressed["disposition_reason"] = ""
    wont_fix = _review_issue("issue.empirical.001", disposition="wont_fix")
    wont_fix["disposition_reason"] = ""
    outputs["p5.review_issues"] = [addressed, wont_fix]

    codes = _codes(_validate("P5", "p5.review_revision", outputs))

    assert "p5.revision_location_missing" not in codes
    assert "p5.disposition_reason_missing" not in codes


def test_p5_manuscript_requires_exact_identity_and_known_supported_claims() -> None:
    claim = _claim(supporting=[], counter=[])
    manuscript = _manuscript(
        kind="assembly_candidate",
        identity=OTHER_METHOD,
    )
    manuscript["claim_support_index"]["p4_empirical_claim_ids"] = [
        "claim.absent"
    ]

    findings = _validate(
        "P5",
        "p5.assembly",
        {
            "p5.claim_traceability": [claim],
            "p5.manuscript_candidate": manuscript,
        },
    )
    codes = _codes(findings)

    assert "p5.claim_without_evidence" in codes
    assert "p5.method_identity_mismatch" in codes
    assert "p5.unknown_claim_support_reference" in codes


def test_p5_support_index_cannot_bypass_empty_traceability() -> None:
    findings = _validate(
        "P5",
        "p5.assembly",
        {
            "p5.claim_traceability": [],
            "p5.manuscript_candidate": _manuscript(
                kind="assembly_candidate",
                claim_id="claim.orphan.001",
            ),
        },
    )
    assert "p5.unknown_claim_support_reference" in _codes(findings)


def test_p5_accepts_a_claim_supported_by_counterevidence() -> None:
    claim = _claim(supporting=[], counter=["evidence.counter.001"])
    manuscript = _manuscript(kind="assembly_candidate")
    manuscript["scientific_outcome"] = {"state": "contradicted"}

    findings = _validate(
        "P5",
        "p5.assembly",
        {
            "p5.claim_traceability": [claim],
            "p5.manuscript_candidate": manuscript,
        },
    )
    assert findings == []
