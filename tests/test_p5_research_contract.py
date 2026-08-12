from __future__ import annotations

import copy
import json
from pathlib import Path

from method_hub.application.default_instructions import load_instruction
from method_hub.schemas import SchemaCatalog


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "architecture"
P5_CONTRACT = ARCHITECTURE / "contracts" / "phases" / "P5.json"

BRIEF = {
    "research_question": "Does the proposed estimator improve risk?",
    "scope": "Theory and simulation",
    "constraints": ["frozen evidence only"],
    "decision_criteria": ["validity", "reproducibility"],
}


def _p5() -> dict:
    return json.loads(P5_CONTRACT.read_text(encoding="utf-8"))


def _output(document: dict, output_id: str) -> dict:
    return next(
        item for item in document["run_local_outputs"]
        if item["output_id"] == output_id
    )


def _review_stage(document: dict) -> dict:
    return next(
        item for item in document["role_stages"]
        if item["stage_id"] == "p5.parallel_reviews"
    )


def _role_reads(stage: dict, role: str) -> tuple[str, ...]:
    item = next(item for item in stage["role_reads"] if item["role"] == role)
    return tuple(item["input_ids"])


def _open_finding(*, raised_by: str = "outside_reviewer") -> dict:
    return {
        "schema_version": "1.0.0",
        "issue_id": "issue.review.claim_scope.001",
        "source_run_id": "run.p5.review_revision.001",
        "raised_by": raised_by,
        "review_basis_generation_id": "generation.manuscript.001",
        "location": "Abstract, sentence 3",
        "affected_statement_id": "claim.risk.bound.001",
        "finding_type": "unsupported_claim",
        "issue": "The abstract generalizes beyond the evaluated regimes.",
        "severity": "major",
        "confidence": "high",
        "scientific_consequence": "The stated scope exceeds the evidence.",
        "evidence_basis": ["Abstract, sentence 3", "Experiment 1"],
        "requested_resolution": "Narrow the claim to the evaluated regimes.",
        "resolution_class": "rewrite",
        "status": "open",
        "content_sha256": "a" * 64,
        "created_at": "2026-08-11T12:00:00Z",
        "authority_at_creation": "run_local_candidate",
    }


def _manuscript_package() -> dict:
    document = json.loads(
        (ARCHITECTURE / "examples" / "scientific-record.example.json").read_text(
            encoding="utf-8"
        )
    )
    artifact = document["representations"][0]["artifact"]
    document.update(
        {
            "record_id": "record.manuscript.current",
            "generation_id": "generation.manuscript.002",
            "record_type": "manuscript",
            "phase": "P5",
            "source_run_id": "run.p5.assembly.002",
            "authority_at_creation": "run_local_candidate",
            "title": "A Traceable Statistical Method",
            "manuscript_kind": "assembly_candidate",
            "target_audience": "Statistical machine-learning researchers",
            "manuscript_artifact": artifact,
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
                "p1_literature_claim_ids": ["claim.literature.001"],
                "p2_method_claim_ids": ["claim.method.001"],
                "p3_theory_claim_ids": ["claim.theory.001"],
                "p4_empirical_claim_ids": ["claim.empirical.001"],
                "interpretation_claim_ids": ["claim.interpretation.001"],
            },
        }
    )
    document.pop("publication_receipt_id", None)
    document.pop("published_at", None)
    return document


def test_p5_contract_uses_dedicated_manuscript_and_review_schemas() -> None:
    document = _p5()
    assert _output(document, "p5.manuscript_candidate")["schema_uri"].endswith(
        "/manuscript-package.schema.json"
    )
    assert _output(document, "p5.theory_audit")["schema_uri"].endswith(
        "/review-finding.schema.json"
    )
    assert _output(document, "p5.empirical_audit")["schema_uri"].endswith(
        "/review-finding.schema.json"
    )
    outside = _output(document, "p5.outside_review")
    assert outside["schema_application"] == "object"
    assert outside["schema_uri"].endswith("/review-report.schema.json")
    final_issues = _output(document, "p5.review_issues")
    assert final_issues["schema_uri"].endswith("/review-issue.schema.json")


def test_p5_specialists_share_theory_implementation_seam_inputs() -> None:
    stage = _review_stage(_p5())
    theorist = _role_reads(stage, "theorist")
    analyst = _role_reads(stage, "data_analyst")
    assert "p5.theory" in theorist
    assert "p5.implementation_record" in theorist
    assert "p5.theory" in analyst
    assert "p5.implementation_record" in analyst
    assert _role_reads(stage, "outside_reviewer") == ("p5.review_packet",)
    assert "public scholarly search" in stage["isolation_rule"]


def test_review_finding_is_open_and_has_no_lead_disposition() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    finding = _open_finding()
    assert catalog.validate("review-finding.schema.json", finding) == ()

    closed = copy.deepcopy(finding)
    closed["status"] = "fixed"
    assert catalog.validate("review-finding.schema.json", closed)

    dispositioned = copy.deepcopy(finding)
    dispositioned["disposition"] = "fixed"
    assert catalog.validate("review-finding.schema.json", dispositioned)


def test_outside_review_report_carries_required_referee_context() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    report = {
        "schema_version": "1.0.0",
        "report_id": "report.outside_review.001",
        "source_run_id": "run.p5.review_revision.001",
        "reviewer_role": "outside_reviewer",
        "review_basis_generation_id": "generation.manuscript.001",
        "reviewed_scope": "Manuscript, supplement, and cited references in the packet.",
        "missing_materials": ["Public code archive was not supplied."],
        "overall_assessment": "The contribution is coherent but empirically narrow.",
        "strengths": ["The estimand and principal theorem are stated clearly."],
        "prioritized_issues": [_open_finding()],
        "novelty_search_boundary": {
            "project_context_policy": "frozen_review_packet_only",
            "external_search_performed": False,
            "sources_consulted": [],
            "query_concepts": [],
            "access_limits": ["No scholarly search capability was available."],
            "assessment_status": "provisional",
            "conclusion": "Novelty is not established beyond the supplied citations.",
        },
        "evidence_that_would_change_assessment": [
            "A broader comparison under the prespecified regimes."
        ],
        "content_sha256": "b" * 64,
        "created_at": "2026-08-11T12:30:00Z",
        "authority_at_creation": "run_local_candidate",
    }
    assert catalog.validate("review-report.schema.json", report) == ()

    wrong_role = copy.deepcopy(report)
    wrong_role["prioritized_issues"][0]["raised_by"] = "theorist"
    assert catalog.validate("review-report.schema.json", wrong_role)


def test_manuscript_package_requires_real_artifact_and_p1_to_p4_claim_index() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    manuscript = _manuscript_package()
    assert catalog.validate("manuscript-package.schema.json", manuscript) == ()

    missing_artifact = copy.deepcopy(manuscript)
    missing_artifact.pop("manuscript_artifact")
    assert catalog.validate("manuscript-package.schema.json", missing_artifact)

    missing_p3 = copy.deepcopy(manuscript)
    missing_p3["claim_support_index"]["p3_theory_claim_ids"] = []
    assert catalog.validate("manuscript-package.schema.json", missing_p3)


def test_p5_instructions_keep_modes_distinct_and_route_typed_gaps() -> None:
    assembly = load_instruction(
        "p5.assembly",
        BRIEF,
        role="research_lead",
        stage_id="p5.assembly_lead",
    )
    revision = load_instruction(
        "p5.review_revision",
        BRIEF,
        role="research_lead",
        stage_id="p5.revision_lead",
    )
    outside = load_instruction(
        "p5.review_revision",
        BRIEF,
        role="outside_reviewer",
        stage_id="p5.parallel_reviews",
    )

    assert "assembly mode, not review-revision" in assembly
    assert "review-revision mode, not initial assembly" in revision
    for instruction in (assembly, revision):
        for prefix in (
            "METHOD_GAP:",
            "THEORY_GAP:",
            "EMPIRICAL_GAP:",
            "IMPLEMENTATION_GAP:",
        ):
            assert prefix in instruction
    assert "Phase 1" in assembly and "Phase 4" in assembly
    assert "project-specific context" in outside
    assert "public scholarly sources" in outside
    assert "status exactly open" in outside
