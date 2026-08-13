"""Tests for the HV-4 harness-owned envelope construction.

Exercises:
1. Harness-owned field population for every schema type
2. Agent-authored fields are preserved untouched
3. content_sha256 is always recomputed (hash paradox)
4. Determinism: same inputs → same output
5. No scientific content is added or modified
6. prepare_candidate_output with missing/invalid payloads
7. Schema-derived ownership sets are non-empty and partition cleanly
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from method_hub.harness.envelope import (
    CandidateOutput,
    SealedRunFacts,
    agent_authored_fields,
    harness_owned_fields,
    populate_harness_fields,
    prepare_candidate_output,
)
from method_hub.harness.outputs import OutputSpec


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _facts(**overrides) -> SealedRunFacts:
    defaults = dict(
        project_id="proj.test",
        run_id="run-abc123def456",
        phase="P3",
        mode="focused_method",
        role="theorist",
        method_identity={
            "stable_id": "method.test",
            "version": 1,
            "definition_sha256": "a" * 64,
        },
        generation_id="gen.001",
        generation_number=1,
        schema_version="1.0.0",
        manifest_sha256="b" * 64,
        sealed_basis_digest="c" * 64,
        produced_at="2026-01-01T00:00:00Z",
        record_type="theory",
    )
    defaults.update(overrides)
    return SealedRunFacts(**defaults)


def _spec(schema_file: str, output_id: str = "test.output") -> OutputSpec:
    return OutputSpec(
        contract_output_id=output_id,
        output_id=f"{output_id}.v1",
        output_kind="record",
        producer="theorist",
        stage_id="stage.test",
        stage_sequence=1,
        schema_application="single",
        schema_file=schema_file,
        relative_path=f"outputs/{output_id}.json",
        required=True,
    )


# --------------------------------------------------------------------------- #
# HV-4.1: Harness-owned field registry                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "schema_file",
    [
        "method.schema.json",
        "theory-record.schema.json",
        "empirical-protocol.schema.json",
        "manuscript-package.schema.json",
        "review-finding.schema.json",
        "review-report.schema.json",
        "evidence.schema.json",
        "literature-source.schema.json",
    ],
)
def test_harness_owned_fields_non_empty(schema_file: str) -> None:
    """Every registered schema must have harness-owned fields."""
    fields = harness_owned_fields(schema_file)
    assert len(fields) > 0
    # All schemas must have content_sha256 and schema_version as harness-owned
    assert "content_sha256" in fields
    assert "schema_version" in fields


def test_unknown_schema_falls_back_to_common() -> None:
    """Unregistered schemas get the common harness-owned set."""
    fields = harness_owned_fields("unknown.schema.json")
    assert "content_sha256" in fields
    assert "created_at" in fields


def test_agent_authored_fields_partition() -> None:
    """harness_owned + agent_authored = all properties (no overlap)."""
    all_props = frozenset({
        "schema_version", "record_id", "phase", "source_run_id",
        "method_identity", "title", "scientific_question", "content_sha256",
        "created_at", "assumptions", "limitations",
    })
    harness = harness_owned_fields("method.schema.json")
    agent = agent_authored_fields("method.schema.json", all_props)
    # No overlap
    assert not (harness & agent & all_props)
    # Union covers all props that are in the schema
    covered = (harness | agent) & all_props
    assert covered == all_props


# --------------------------------------------------------------------------- #
# HV-4.2: populate_harness_fields — identity and provenance                   #
# --------------------------------------------------------------------------- #


def test_populate_identity_fields() -> None:
    """Harness-owned identity fields are populated from sealed run facts."""
    payload = {"title": "Test Method", "scientific_question": "What?"}
    doc = populate_harness_fields(payload, _facts(), "method.schema.json")

    assert doc["schema_version"] == "1.0.0"
    assert doc["identity"] == {
        "stable_id": "method.test",
        "version": 1,
        "definition_sha256": "a" * 64,
    }


def test_populate_phase_and_mode() -> None:
    """Phase and mode are populated from sealed run facts."""
    payload = {"research_question": "Test?"}
    doc = populate_harness_fields(
        payload, _facts(phase="P4"), "empirical-protocol.schema.json"
    )

    assert doc["phase"] == "P4"
    assert doc["mode"] == "focused_method"


def test_populate_record_type() -> None:
    """record_type is populated when provided in run facts."""
    payload = {"theory_scope": "Test scope"}
    doc = populate_harness_fields(
        payload,
        _facts(record_type="theory"),
        "theory-record.schema.json",
    )

    assert doc["record_type"] == "theory"


def test_populate_timestamps() -> None:
    """Harness-owned timestamps are populated."""
    payload = {"title": "Test"}
    facts = _facts(produced_at="2026-06-01T12:00:00Z")
    doc = populate_harness_fields(payload, facts, "method.schema.json")

    assert doc["created_at"] == "2026-06-01T12:00:00Z"
    assert doc["updated_at"] == "2026-06-01T12:00:00Z"


def test_populate_review_fields() -> None:
    """Review-specific harness fields (raised_by, reviewer_role) are populated."""
    payload = {"issue": "A problem", "finding_type": "logical"}
    doc = populate_harness_fields(
        payload, _facts(role="reviewer"), "review-finding.schema.json"
    )

    assert doc["raised_by"] == "reviewer"
    assert doc["source_run_id"] == "run-abc123def456"


def test_populate_authority_at_creation() -> None:
    """authority_at_creation is populated with manifest and basis digests."""
    payload = {"title": "Test"}
    doc = populate_harness_fields(payload, _facts(), "method.schema.json")

    assert doc["authority_at_creation"]["source_run_id"] == "run-abc123def456"
    assert doc["authority_at_creation"]["manifest_sha256"] == "b" * 64


# --------------------------------------------------------------------------- #
# HV-4.3: content_sha256 is always recomputed                                 #
# --------------------------------------------------------------------------- #


def test_content_sha256_recomputed() -> None:
    """content_sha256 must be recomputed even if the agent wrote a value."""
    payload = {
        "title": "Test",
        "content_sha256": "0" * 64,  # Wrong hash
    }
    doc = populate_harness_fields(payload, _facts(), "method.schema.json")

    assert doc["content_sha256"] != "0" * 64
    assert len(doc["content_sha256"]) == 64


def test_content_sha256_deterministic() -> None:
    """Same content + facts → same content_sha256."""
    payload1 = {"title": "Test", "assumptions": []}
    payload2 = {"title": "Test", "assumptions": []}

    doc1 = populate_harness_fields(payload1, _facts(), "method.schema.json")
    doc2 = populate_harness_fields(payload2, _facts(), "method.schema.json")

    assert doc1["content_sha256"] == doc2["content_sha256"]


def test_content_sha256_changes_with_content() -> None:
    """Different scientific content → different content_sha256."""
    doc1 = populate_harness_fields(
        {"title": "A"}, _facts(), "method.schema.json"
    )
    doc2 = populate_harness_fields(
        {"title": "B"}, _facts(), "method.schema.json"
    )

    assert doc1["content_sha256"] != doc2["content_sha256"]


# --------------------------------------------------------------------------- #
# No scientific content is modified                                           #
# --------------------------------------------------------------------------- #


def test_agent_fields_preserved() -> None:
    """Agent-authored scientific fields are preserved untouched."""
    payload = {
        "title": "Important Method",
        "scientific_question": "Does X work?",
        "rationale": "Because Y.",
        "summary": "We test X.",
        "assumptions": [{"assumption_id": "a1", "statement": "Normal data."}],
        "limitations": ["Small sample"],
    }
    doc = populate_harness_fields(payload, _facts(), "method.schema.json")

    assert doc["title"] == "Important Method"
    assert doc["scientific_question"] == "Does X work?"
    assert doc["rationale"] == "Because Y."
    assert doc["summary"] == "We test X."
    assert doc["assumptions"] == [{"assumption_id": "a1", "statement": "Normal data."}]
    assert doc["limitations"] == ["Small sample"]


def test_no_scientific_fields_added() -> None:
    """Harness population does not add any scientific field."""
    payload = {"title": "Test"}
    doc = populate_harness_fields(payload, _facts(), "method.schema.json")

    # The harness should not invent scientific fields
    assert "scientific_question" not in doc or doc["scientific_question"] == payload.get("scientific_question")
    assert "rationale" not in doc or doc["rationale"] == payload.get("rationale")
    assert "assumptions" not in doc or doc["assumptions"] == payload.get("assumptions")


def test_original_payload_not_mutated() -> None:
    """populate_harness_fields must not mutate the input payload."""
    payload = {"title": "Test", "assumptions": []}
    original = copy.deepcopy(payload)
    populate_harness_fields(payload, _facts(), "method.schema.json")
    assert payload == original


# --------------------------------------------------------------------------- #
# HV-4.4: prepare_candidate_output                                            #
# --------------------------------------------------------------------------- #


def test_prepare_candidate_output_success(tmp_path: Path) -> None:
    """A valid raw payload produces a candidate with populated fields."""
    payload = {"title": "Test Method", "scientific_question": "What?"}
    raw_path = tmp_path / "outputs" / "test.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(json.dumps(payload))

    spec = _spec("method.schema.json")
    result = prepare_candidate_output(raw_path, _facts(), spec)

    assert isinstance(result, CandidateOutput)
    assert result.document["title"] == "Test Method"
    assert result.document["identity"]["stable_id"] == "method.test"
    assert len(result.document["content_sha256"]) == 64
    assert len(result.populated_fields) > 0


def test_prepare_candidate_output_missing_file(tmp_path: Path) -> None:
    """Missing raw payload produces a blocking finding."""
    raw_path = tmp_path / "nonexistent.json"
    spec = _spec("method.schema.json")
    result = prepare_candidate_output(raw_path, _facts(), spec)

    assert len(result.findings) == 1
    assert result.findings[0].code == "output.required_missing"
    assert result.findings[0].blocks_publication is True
    assert result.document == {}


def test_prepare_candidate_output_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON produces a blocking finding."""
    raw_path = tmp_path / "outputs" / "bad.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("{not valid json")

    spec = _spec("method.schema.json")
    result = prepare_candidate_output(raw_path, _facts(), spec)

    assert len(result.findings) == 1
    assert result.findings[0].code == "json.decode_error"
    assert result.findings[0].blocks_publication is True


def test_prepare_candidate_output_non_object(tmp_path: Path) -> None:
    """A JSON array instead of an object produces a blocking finding."""
    raw_path = tmp_path / "outputs" / "array.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("[1, 2, 3]")

    spec = _spec("method.schema.json")
    result = prepare_candidate_output(raw_path, _facts(), spec)

    assert len(result.findings) == 1
    assert result.findings[0].code == "json.invalid_input_type"


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #


def test_full_determinism() -> None:
    """Same inputs always produce the same document (except timestamps)."""
    payload = {
        "title": "Test",
        "scientific_question": "What?",
        "assumptions": [],
        "limitations": [],
    }
    facts = _facts(produced_at="2026-01-01T00:00:00Z")

    doc1 = populate_harness_fields(payload, facts, "method.schema.json")
    doc2 = populate_harness_fields(payload, facts, "method.schema.json")

    assert doc1 == doc2


def test_record_id_deterministic() -> None:
    """Record ID is derived deterministically from run facts."""
    facts = _facts()
    doc = populate_harness_fields(
        {"theory_scope": "test"}, facts, "theory-record.schema.json"
    )
    # Record ID should contain the run ID fragment
    assert "runabc123def" in doc["record_id"]
