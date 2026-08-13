"""HV-6.P5 manuscript calibration tests.

Covers three calibrations for honest manuscript science:

1. Functional sections: a manuscript with all required scientific sections
   passes both schema and scientific validation.
2. Honest empties: a review report with no strengths (and no prioritized
   issues) is schema-valid — reviewers may honestly report nothing rather
   than fabricate filler.
3. Severity for display only: agent-authored ``severity`` / ``confidence`` on
   review-finding documents never affect ``blocks_publication``. Publication
   policy keys on harness-owned finding codes via the HV-2 registry, so a
   model writing ``severity=minor`` cannot downgrade a blocking code such as
   ``p5.claim_without_evidence``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from method_hub.domain import MethodIdentity
from method_hub.domain.validation import (
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    get_policy,
    make_finding,
)
from method_hub.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from method_hub.harness.scientific_validators import validate_phase_scientific
from method_hub.schemas import SchemaCatalog

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "architecture"

METHOD = MethodIdentity(
    stable_id="method.overlap_stabilized_score",
    version=1,
    definition_sha256="b274bbb26acde9604faad22d05b3f4015f75491a31b5d0f67f139a64f7a7a4f1",
)

ALL_SECTIONS = [
    "abstract",
    "introduction",
    "method",
    "theory",
    "experiments",
    "discussion",
    "limitations",
    "references",
]

CLAIM_SUPPORT_INDEX = {
    "p1_literature_claim_ids": ["claim.literature.001"],
    "p2_method_claim_ids": ["claim.method.001"],
    "p3_theory_claim_ids": ["claim.theory.001"],
    "p4_empirical_claim_ids": ["claim.empirical.001"],
    "interpretation_claim_ids": ["claim.interpretation.001"],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _claim(statement_id: str, *, supported: bool = True) -> dict[str, Any]:
    return {
        "statement_id": statement_id,
        "statement_type": "result",
        "supporting_evidence_ids": (
            [f"evidence.{statement_id}"] if supported else []
        ),
        "counterevidence_ids": [],
    }


def _manuscript_package(*, kind: str = "assembly_candidate") -> dict[str, Any]:
    document = json.loads(
        (ARCHITECTURE / "examples" / "scientific-record.example.json").read_text(
            encoding="utf-8"
        )
    )
    artifact = document["representations"][0]["artifact"]
    document.update(
        {
            "record_id": "record.manuscript.calibration.001",
            "generation_id": "generation.manuscript.calibration.001",
            "record_type": "manuscript",
            "phase": "P5",
            "source_run_id": "run.p5.calibration.001",
            "authority_at_creation": "run_local_candidate",
            "title": "A Traceable Statistical Method",
            "manuscript_kind": kind,
            "target_audience": "Statistical machine-learning researchers",
            "manuscript_artifact": copy.deepcopy(artifact),
            "sections_present": list(ALL_SECTIONS),
            "claim_support_index": copy.deepcopy(CLAIM_SUPPORT_INDEX),
        }
    )
    document.pop("publication_receipt_id", None)
    document.pop("published_at", None)
    return document


def _review_finding(
    issue_id: str,
    *,
    raised_by: str,
    severity: str = "minor",
    confidence: str = "low",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "issue_id": issue_id,
        "source_run_id": "run.p5.calibration.001",
        "raised_by": raised_by,
        "review_basis_generation_id": "generation.manuscript.calibration.001",
        "location": "Section 3",
        "finding_type": "unsupported_claim",
        "issue": "The claim generalizes beyond the evaluated regimes.",
        "severity": severity,
        "confidence": confidence,
        "scientific_consequence": "The stated scope exceeds the evidence.",
        "evidence_basis": ["Section 3", "Experiment 1"],
        "requested_resolution": "Narrow the claim to the evaluated regimes.",
        "resolution_class": "rewrite",
        "status": "open",
        "content_sha256": "a" * 64,
        "created_at": "2026-08-12T12:00:00Z",
        "authority_at_creation": "run_local_candidate",
    }


def _review_report(
    *,
    strengths: list[str] | None = None,
    prioritized_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "report_id": "report.outside_review.calibration.001",
        "source_run_id": "run.p5.calibration.001",
        "reviewer_role": "outside_reviewer",
        "review_basis_generation_id": "generation.manuscript.calibration.001",
        "reviewed_scope": "Manuscript, supplement, and cited references in the packet.",
        "missing_materials": [],
        "overall_assessment": "The contribution is coherent but empirically narrow.",
        "strengths": strengths if strengths is not None else [],
        "prioritized_issues": (
            prioritized_issues if prioritized_issues is not None else []
        ),
        "novelty_search_boundary": {
            "project_context_policy": "frozen_review_packet_only",
            "external_search_performed": False,
            "sources_consulted": [],
            "query_concepts": [],
            "access_limits": [],
            "assessment_status": "provisional",
            "conclusion": "Novelty is not established beyond the supplied citations.",
        },
        "evidence_that_would_change_assessment": [],
        "content_sha256": "b" * 64,
        "created_at": "2026-08-12T12:30:00Z",
        "authority_at_creation": "run_local_candidate",
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
    mode_id: str,
    documents: dict[str, Any],
    *,
    selected_method: MethodIdentity | None = METHOD,
) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P5"),
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


# ---------------------------------------------------------------------------
# Honest empties: schema accepts review reports with no strengths
# ---------------------------------------------------------------------------


def test_review_report_with_empty_strengths_passes_schema() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    report = _review_report(strengths=[], prioritized_issues=[])
    assert catalog.validate("review-report.schema.json", report) == ()

    # Regression: reports that do name strengths still validate.
    with_strengths = _review_report(
        strengths=["The estimand and principal theorem are stated clearly."],
        prioritized_issues=[],
    )
    assert catalog.validate("review-report.schema.json", with_strengths) == ()


def test_review_report_prioritized_issues_may_be_empty() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    report = _review_report(
        strengths=["The exposition is clear."],
        prioritized_issues=[],
    )
    assert catalog.validate("review-report.schema.json", report) == ()


# ---------------------------------------------------------------------------
# Severity for display only: publication keys on harness finding codes
# ---------------------------------------------------------------------------


def test_publication_blocks_on_harness_code_not_agent_severity() -> None:
    """HV-2 registry: a blocking harness code blocks regardless of document
    content, because `make_finding` derives policy from the code alone."""
    policy = get_policy("p5.claim_without_evidence")
    assert policy.blocks_publication is True

    finding = make_finding("p5.claim_without_evidence", "unsupported claim")
    assert finding.blocks_publication is True
    assert finding.severity is ValidationSeverity.ERROR

    report = ValidationReport.from_findings(
        "report.calibration", "run.calibration", "scientific", [finding]
    )
    assert report.passed is False


def test_review_finding_severity_minor_still_blocks_publication() -> None:
    """A review-revision run where every agent-authored finding says
    severity=minor/confidence=low still blocks publication, because the block
    comes from the harness-owned `p5.claim_without_evidence` code."""
    documents = {
        "p5.claim_traceability": [
            _claim("claim.literature.001"),
            _claim("claim.method.001"),
            _claim("claim.theory.001"),
            _claim("claim.empirical.001"),
            _claim("claim.interpretation.001"),
            _claim("claim.unsupported.001", supported=False),
        ],
        "p5.manuscript_candidate": _manuscript_package(kind="revised_candidate"),
        "p5.theory_audit": [
            _review_finding("issue.theory.001", raised_by="theorist")
        ],
        "p5.empirical_audit": [
            _review_finding("issue.empirical.001", raised_by="data_analyst")
        ],
        "p5.outside_review": _review_report(
            strengths=["The exposition is clear."],
            prioritized_issues=[
                _review_finding(
                    "issue.outside.001", raised_by="outside_reviewer"
                )
            ],
        ),
        "p5.review_issues": [
            {
                "issue_id": "issue.theory.001",
                "disposition": "fixed",
                "revision_locations": ["Section 3"],
            },
            {
                "issue_id": "issue.empirical.001",
                "disposition": "fixed",
                "revision_locations": ["Section 5"],
            },
            {
                "issue_id": "issue.outside.001",
                "disposition": "fixed",
                "revision_locations": ["Abstract"],
            },
        ],
    }

    findings = _validate("p5.review_revision", documents)

    # The only emitted finding is the harness code for the unsupported claim;
    # no finding derives from the agents' severity/confidence values.
    assert [finding.code for finding in findings] == [
        "p5.claim_without_evidence"
    ]
    blocker = findings[0]
    assert blocker.blocks_publication is True

    report = ValidationReport.from_findings(
        "report.calibration", "run.calibration", "scientific", findings
    )
    assert report.passed is False


# ---------------------------------------------------------------------------
# Functional sections: complete manuscript passes schema and validators
# ---------------------------------------------------------------------------


def test_manuscript_with_all_required_sections_passes() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    manuscript = _manuscript_package(kind="assembly_candidate")
    assert catalog.validate("manuscript-package.schema.json", manuscript) == ()

    # Negative control: dropping a required scientific section fails schema.
    incomplete = copy.deepcopy(manuscript)
    incomplete["sections_present"] = [
        section for section in ALL_SECTIONS if section != "theory"
    ]
    assert catalog.validate("manuscript-package.schema.json", incomplete)


def test_complete_manuscript_passes_p5_scientific_validator() -> None:
    documents = {
        "p5.claim_traceability": [
            _claim("claim.literature.001"),
            _claim("claim.method.001"),
            _claim("claim.theory.001"),
            _claim("claim.empirical.001"),
            _claim("claim.interpretation.001"),
        ],
        "p5.manuscript_candidate": _manuscript_package(kind="assembly_candidate"),
    }
    findings = _validate("p5.assembly", documents)
    assert findings == []
