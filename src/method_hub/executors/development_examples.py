"""Dedicated schema examples for the local development executor.

These records exercise contract plumbing only. They are deterministic
conformance examples, not research findings and not evidence for a project.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from ..executors.protocol import RoleInvocation
from ..json_io import load_json


def load_dedicated_examples(example_root: Path) -> dict[str, dict[str, Any]]:
    """Build schema-valid examples derived from the shared architecture basis."""

    base = load_json(example_root / "scientific-record.example.json")
    method_identity = copy.deepcopy(base["method_identity"])
    basis = copy.deepcopy(base["basis"])

    theory_artifact = _artifact(
        "artifact.theory_example",
        "artifact://artifact.theory_example",
        "1",
        media_type="text/markdown",
        locator="Theorem 1 and proof",
    )
    proof_artifact = _artifact(
        "artifact.proof_example",
        "artifact://artifact.proof_example",
        "2",
        media_type="text/markdown",
        locator="Proof of Theorem 1",
    )
    theory = _record_base(
        base,
        record_id="record.theory.example",
        generation_id="generation.theory.example.001",
        record_type="theory_record",
        phase="P3",
        source_run_id="run.p3.example.001",
        primary_artifact=theory_artifact,
    )
    theory.update(
        {
            "method_identity": method_identity,
            "primary_artifact": theory_artifact,
            "basis": basis,
            "development_mode": "p3.theory_establishment",
            "theory_scope": (
                "One finite-sample risk statement for the exact demonstration method."
            ),
            "assumptions": [
                {
                    "assumption_id": "assumption.example.moment",
                    "text": "The demonstration loss has a finite second moment.",
                    "scope": "The distribution used in the demonstration theorem.",
                    "status": "active",
                    "source_artifacts": [],
                    "used_by_statement_ids": ["statement.example.theorem"],
                    "sensitivity": (
                        "Without the moment condition, the stated risk bound need not hold."
                    ),
                }
            ],
            "statements": [
                {
                    "statement_id": "statement.example.theorem",
                    "statement_type": "theorem",
                    "text": (
                        "Under the stated moment condition, the demonstration risk is finite."
                    ),
                    "quantifiers": ["For every distribution in the stated scope"],
                    "regime": "finite-sample",
                    "assumption_ids": ["assumption.example.moment"],
                    "status": "established",
                    "justification": {
                        "kind": "proof",
                        "summary": "The proof applies the recorded moment bound.",
                        "artifacts": [proof_artifact],
                    },
                    "depends_on_statement_ids": [],
                    "empirical_implication_ids": ["implication.example.risk"],
                }
            ],
            "empirical_implications": [
                {
                    "implication_id": "implication.example.risk",
                    "statement_ids": ["statement.example.theorem"],
                    "text": "Estimated risk should remain finite in the stated regime.",
                    "conditions": ["The recorded moment condition holds."],
                    "observable_or_metric": "Mean squared error",
                    "expected_pattern": "A finite empirical estimate with bounded uncertainty.",
                    "falsifying_result": "Persistent divergence under verified implementation.",
                }
            ],
            "limitations": [
                "This conformance example does not establish a scientific result."
            ],
            "content_sha256": "3" * 64,
        }
    )

    protocol = {
        "schema_version": "1.0.0",
        "protocol_id": "protocol.empirical.example.001",
        "phase": "P4",
        "source_run_id": "run.p4.example.001",
        "mode": "p4.preliminary",
        "method_identity": method_identity,
        "basis": basis,
        "research_question": (
            "Does the demonstration method satisfy its stated empirical criterion?"
        ),
        "scope": "A small decisive simulation check for harness conformance.",
        "scope_justification": (
            "The check can falsify the demonstration claim without claiming broad evidence."
        ),
        "claim_tests": [
            {
                "test_id": "test.example.risk",
                "claim_id": "claim.rmse.reduction",
                "target_statement_ids": ["statement.example.theorem"],
                "hypothesis": "The recorded error remains below the stated threshold.",
                "design": "Independent simulated data sets under one fixed regime.",
                "falsification_rule": "Reject the claim if the threshold is exceeded.",
                "decision_threshold_ids": ["threshold.example.risk"],
            }
        ],
        "estimand": {
            "name": "Expected squared error",
            "mathematical_definition": "E[(estimate - target)^2]",
            "target_population_or_distribution": "The fixed demonstration distribution.",
            "analysis_unit": "One independently generated data set.",
            "aggregation": "Mean across repetitions.",
            "conditions": ["The implementation matches the selected method."],
        },
        "data_or_simulation_unit": {
            "source_type": "simulation",
            "unit_definition": "One independently generated data set.",
            "sampling_or_generation_process": "Generate from the fixed demonstration law.",
            "sample_sizes": [100],
            "independence_structure": "Repetitions use independent random seeds.",
            "splits": "No train-test reuse across evaluation units.",
            "preprocessing": "No outcome-dependent preprocessing.",
        },
        "baselines": [
            {
                "baseline_id": "baseline.example.reference",
                "name": "Reference estimator",
                "rationale": "Provides a scale-calibrated comparison.",
                "implementation_identity": "reference.example.v1",
                "tuning_policy": "Use the same fixed tuning budget.",
                "compute_budget": "One unit per repetition.",
            }
        ],
        "implementation_strategy": {
            "strategy": "new",
            "verification_checks": ["Check one deterministic fixture."],
            "changes_from_prior": [],
        },
        "tuning_budget": {
            "selection_data": "A fixed development-only calibration set.",
            "search_space": "One prespecified setting.",
            "optimization_rule": "No adaptive search.",
            "maximum_trials": 1,
            "compute_limit": "One trial.",
            "fairness_rule": "Use the same budget for each method.",
        },
        "metrics": [
            {
                "metric_id": "metric.example.risk",
                "name": "Mean squared error",
                "definition": "Mean squared difference from the target.",
                "direction": "minimize",
                "aggregation": "Mean across repetitions.",
                "uncertainty_method": "Normal interval across repetitions.",
            }
        ],
        "repetitions_and_uncertainty": {
            "repetitions": 2,
            "random_seed_policy": "Use the two recorded seeds.",
            "paired_design": True,
            "interval_or_error_method": "Paired standard error.",
            "target_precision": "Development conformance only.",
        },
        "multiplicity": {
            "family_definition": "One prespecified claim.",
            "correction_method": "No correction needed for one claim.",
            "decision_rule": "Apply the single recorded threshold.",
        },
        "stopping_rules": [
            {
                "rule_id": "stopping.example.complete",
                "condition": "Both repetitions finish or one fails integrity checks.",
                "action": "Stop and report the observed outcome.",
            }
        ],
        "leakage_checks": [
            {
                "check_id": "leakage.example.outcome",
                "risk": "Outcome-informed tuning.",
                "procedure": "Verify tuning was fixed before evaluation.",
                "failure_action": "Mark the result exploratory.",
            }
        ],
        "decision_thresholds": [
            {
                "threshold_id": "threshold.example.risk",
                "claim_id": "claim.rmse.reduction",
                "metric_id": "metric.example.risk",
                "criterion": "Mean squared error is below the fixed reference value.",
                "interpretation": "The narrow demonstration claim is supported.",
            }
        ],
        "deviations": [],
        "protocol_status": "prespecified",
        "finalized_at": "2026-08-01T12:00:00Z",
        "content_sha256": "4" * 64,
        "created_at": "2026-08-01T12:00:00Z",
    }

    review_finding = {
        "schema_version": "1.0.0",
        "issue_id": "issue.review.scope_claim.001",
        "source_run_id": "run.p5.review_revision.20260901t100000z",
        "raised_by": "outside_reviewer",
        "review_basis_generation_id": "generation.manuscript.001",
        "location": "Abstract, sentence 4",
        "affected_statement_id": "claim.rmse.reduction",
        "finding_type": "unsupported_claim",
        "issue": "The claim exceeds the scope of the demonstration evidence.",
        "severity": "major",
        "confidence": "high",
        "scientific_consequence": "Readers could infer support outside the evaluated scope.",
        "evidence_basis": ["Abstract, sentence 4", "Demonstration result 1"],
        "requested_resolution": "Restrict the claim to the evaluated regime.",
        "resolution_class": "rewrite",
        "status": "open",
        "content_sha256": "5" * 64,
        "created_at": "2026-09-01T11:00:00Z",
        "authority_at_creation": "run_local_candidate",
    }

    review_report = {
        "schema_version": "1.0.0",
        "report_id": "report.outside.example.001",
        "source_run_id": "run.p5.review_revision.20260901t100000z",
        "reviewer_role": "outside_reviewer",
        "review_basis_generation_id": "generation.manuscript.001",
        "reviewed_scope": "The frozen demonstration manuscript packet.",
        "missing_materials": [],
        "overall_assessment": "The packet is coherent but its scope must remain narrow.",
        "strengths": ["The demonstration estimand is stated directly."],
        "prioritized_issues": [copy.deepcopy(review_finding)],
        "novelty_search_boundary": {
            "project_context_policy": "frozen_review_packet_only",
            "external_search_performed": False,
            "sources_consulted": [],
            "query_concepts": [],
            "access_limits": ["No external scholarly search was performed."],
            "assessment_status": "not_assessed",
            "conclusion": "Novelty is not assessed by this conformance example.",
        },
        "evidence_that_would_change_assessment": [
            "A complete result under the broader stated scope."
        ],
        "content_sha256": "6" * 64,
        "created_at": "2026-09-01T11:30:00Z",
        "authority_at_creation": "run_local_candidate",
    }

    manuscript_artifact = _artifact(
        "artifact.manuscript.example",
        "artifact://artifact.manuscript.example",
        "7",
        media_type="text/markdown",
        locator="Complete manuscript",
    )
    manuscript = _record_base(
        base,
        record_id="record.manuscript.example",
        generation_id="generation.manuscript.001",
        record_type="manuscript",
        phase="P5",
        source_run_id="run.p5.example.001",
        primary_artifact=manuscript_artifact,
    )
    manuscript.update(
        {
            "method_identity": method_identity,
            "basis": basis,
            "title": "A Development-Only Statistical Method Example",
            "manuscript_kind": "assembly_candidate",
            "target_audience": "Statistical machine-learning researchers",
            "manuscript_artifact": manuscript_artifact,
            "sections_present": [
                "abstract",
                "introduction",
                "method",
                "theory",
                "experiments",
                "discussion",
                "limitations",
                "references",
            ],
            "claim_support_index": {
                "p1_literature_claim_ids": ["claim.rmse.reduction"],
                "p2_method_claim_ids": ["claim.rmse.reduction"],
                "p3_theory_claim_ids": ["claim.rmse.reduction"],
                "p4_empirical_claim_ids": ["claim.rmse.reduction"],
                "interpretation_claim_ids": [],
            },
            "content_sha256": "8" * 64,
        }
    )

    return {
        "theory-record.schema.json": theory,
        "empirical-protocol.schema.json": protocol,
        "manuscript-package.schema.json": manuscript,
        "review-finding.schema.json": review_finding,
        "review-report.schema.json": review_report,
    }


def adapt_dedicated_example(
    *,
    schema_file: str,
    document: Mapping[str, Any],
    invocation: RoleInvocation,
) -> dict[str, Any]:
    """Adapt only fields whose schema semantics depend on mode or producer."""

    result = copy.deepcopy(dict(document))
    if schema_file == "theory-record.schema.json":
        result["development_mode"] = invocation.mode
        if invocation.mode == "p3.theory_revision":
            statement_id = result["statements"][0]["statement_id"]
            result["revision_account"] = {
                "prior_generation_id": "generation.theory.example.000",
                "change_summary": "Revalidated the demonstration statement.",
                "strengthened_statement_ids": [],
                "weakened_statement_ids": [],
                "conditioned_statement_ids": [],
                "contradicted_statement_ids": [],
                "retracted_statement_ids": [],
                "new_statement_ids": [statement_id],
                "unresolved_statement_ids": [],
            }
            result["replaces_generation_id"] = "generation.theory.example.000"
        else:
            result.pop("revision_account", None)
            result.pop("replaces_generation_id", None)
    elif schema_file == "empirical-protocol.schema.json":
        result["mode"] = invocation.mode
    elif schema_file == "manuscript-package.schema.json":
        result["manuscript_kind"] = (
            "revised_candidate"
            if invocation.mode == "p5.review_revision"
            else "assembly_candidate"
        )
    elif schema_file == "review-finding.schema.json":
        if invocation.role in {"theorist", "data_analyst", "outside_reviewer"}:
            result["raised_by"] = invocation.role
    return result


def _record_base(
    source: Mapping[str, Any],
    *,
    record_id: str,
    generation_id: str,
    record_type: str,
    phase: str,
    source_run_id: str,
    primary_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(source))
    result.update(
        {
            "record_id": record_id,
            "generation_id": generation_id,
            "generation_number": 1,
            "record_type": record_type,
            "phase": phase,
            "source_run_id": source_run_id,
            "authority_at_creation": "run_local_candidate",
            "representations": [
                {
                    "information_layer": "primary_artifact",
                    "artifact": copy.deepcopy(dict(primary_artifact)),
                }
            ],
            "created_at": "2026-08-01T12:30:00Z",
        }
    )
    result.pop("publication_receipt_id", None)
    result.pop("published_at", None)
    return result


def _artifact(
    artifact_id: str,
    uri: str,
    digest_character: str,
    *,
    media_type: str,
    locator: str,
) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "uri": uri,
        "sha256": digest_character * 64,
        "media_type": media_type,
        "locator": locator,
    }


__all__ = ["adapt_dedicated_example", "load_dedicated_examples"]
