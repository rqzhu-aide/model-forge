"""Tests for the HV-4 harness-owned envelope construction.

Exercises:
1. Harness-owned field population for every schema type
2. Agent-authored fields are preserved untouched
3. content_sha256 is always recomputed (hash paradox)
4. Determinism: same inputs → same output
5. No scientific content is added or modified
6. Production close-path population + structural output validation
   (migrated from the retired prepare_candidate_output tests, F16)
7. Schema-derived ownership sets are non-empty and partition cleanly
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_forge.domain.validation import FindingClass, make_finding
from model_forge.harness.envelope import (
    SealedRunFacts,
    agent_authored_fields,
    harness_owned_fields,
    populate_harness_fields,
    reclassify_harness_owned_finding,
)
from model_forge.harness.outputs import (
    OutputPlan,
    OutputSpec,
    validate_role_outputs,
)
from model_forge.harness.role_execution import _apply_disclosed_mechanical_repairs


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


def _close_spec(
    schema_file: str,
    output_id: str = "test.output",
    *,
    schema_application: str = "object",
) -> OutputSpec:
    return OutputSpec(
        contract_output_id=output_id,
        output_id=f"{output_id}.v1",
        output_kind="record",
        producer="theorist",
        stage_id="stage.test",
        stage_sequence=1,
        schema_application=schema_application,
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
    """authority_at_creation is the creationAuthority enum marker.

    Role outputs are always run-local candidates; publication is what makes
    a formal generation.  The field is a string enum per
    common-definitions ``creationAuthority``, not a digest structure.
    """
    payload = {"title": "Test"}
    doc = populate_harness_fields(payload, _facts(), "method.schema.json")

    assert doc["authority_at_creation"] == "run_local_candidate"


def test_harness_owned_timestamps_override_agent_values() -> None:
    """Harness-owned run-bound fields are overwritten, not preserved.

    An agent-written created_at is not authoritative: the harness stamps the
    sealed timestamp regardless of what the agent wrote.
    """
    payload = {"title": "Test", "created_at": "1999-01-01T00:00:00Z"}
    doc = populate_harness_fields(
        payload, _facts(produced_at="2026-06-01T12:00:00Z"), "method.schema.json"
    )
    assert doc["created_at"] == "2026-06-01T12:00:00Z"


def test_record_id_filled_only_when_missing() -> None:
    """Agent-authored record identities are preserved (cross-reference
    integrity); missing ones are filled deterministically."""
    payload = {"record_id": "rec.agent.authored", "title": "T"}
    doc = populate_harness_fields(payload, _facts(), "theory-record.schema.json")
    assert doc["record_id"] == "rec.agent.authored"

    doc2 = populate_harness_fields({"title": "T"}, _facts(), "theory-record.schema.json")
    assert doc2["record_id"].startswith("theory.record.")


def test_record_ids_unique_per_item_index() -> None:
    """Array items never receive duplicate derived identities."""
    facts = _facts()
    doc0 = populate_harness_fields({}, facts, "evidence.schema.json", item_index=0)
    doc1 = populate_harness_fields({}, facts, "evidence.schema.json", item_index=1)
    assert doc0["evidence_id"] != doc1["evidence_id"]


def test_method_identity_not_populated_when_unbound() -> None:
    """Catalog modes have no selected method: agent-authored identities stay."""
    facts = _facts(method_identity={})
    payload = {"identity": {"stable_id": "mth_new", "version": 1,
                            "definition_sha256": "d" * 64}}
    doc = populate_harness_fields(payload, facts, "method.schema.json")
    assert doc["identity"]["stable_id"] == "mth_new"


def test_run_local_candidate_strips_publication_provenance() -> None:
    """Candidates must not carry formal-generation fields.

    scientific-record.schema.json forbids publication_receipt_id/published_at
    unless authority_at_creation is formal_generation (allOf if/else rule).
    Population sets run_local_candidate and strips both fields.
    """
    payload = {
        "title": "T",
        "published_at": "2026-01-01T00:00:00Z",
        "publication_receipt_id": "pub.fake",
    }
    doc = populate_harness_fields(payload, _facts(), "theory-record.schema.json")
    assert doc["authority_at_creation"] == "run_local_candidate"
    assert "published_at" not in doc
    assert "publication_receipt_id" not in doc


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
# HV-4.4 (production path): close-lane population + structural validation     #
# --------------------------------------------------------------------------- #
# Migrated from the retired ``prepare_candidate_output`` pinning tests
# (Audit-2026-09-02 F16).  These exercise the production close path:
# ``_apply_disclosed_mechanical_repairs`` populates harness-owned fields from
# sealed run facts and writes the candidate back to disk, and
# ``validate_role_outputs`` reports the structural findings the close path
# actually runs.  The missing-file case is covered by
# tests/test_harness_outputs.py::test_missing_role_outputs_are_reported_without_publication
# and was dropped as a duplicate.


def _write_raw(run_root: Path, spec: OutputSpec, text: str) -> Path:
    path = run_root.joinpath(*spec.relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _close_lane_repairs(run_root: Path, spec: OutputSpec):
    return _apply_disclosed_mechanical_repairs(
        run_root=run_root,
        output_plan=OutputPlan((spec,)),
        stage=SimpleNamespace(stage_id=spec.stage_id),
        role=spec.producer,
        run_facts=_facts(),
    )


def _validate_close_lane(run_root: Path, spec: OutputSpec):
    return validate_role_outputs(
        schema_catalog=SimpleNamespace(validate=lambda *args, **kwargs: []),
        run_root=run_root,
        output_plan=OutputPlan((spec,)),
        stage=SimpleNamespace(stage_id=spec.stage_id),
        role=spec.producer,
    )


def test_close_lane_populates_candidate_from_raw_payload(tmp_path: Path) -> None:
    """A valid raw payload is populated with harness-owned fields in place.

    Production equivalent of the retired prepare_candidate_output success
    path: raw payload on disk in, populated candidate on disk out.
    """
    spec = _close_spec("method.schema.json")
    payload = {"title": "Test Method", "scientific_question": "What?"}
    path = _write_raw(tmp_path, spec, json.dumps(payload))
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    records = _close_lane_repairs(tmp_path, spec)

    document = json.loads(path.read_text())
    assert document["title"] == "Test Method"
    assert document["identity"]["stable_id"] == "method.test"
    assert len(document["content_sha256"]) == 64
    record = records["test.output"]
    assert record.source_sha256 == source_sha256
    assert record.changed


def test_close_lane_populates_each_item_array_with_unique_ids(tmp_path: Path) -> None:
    """Array outputs are populated per element with unique derived ids.

    Production equivalent of the retired each_item success path.
    """
    spec = _close_spec(
        "evidence.schema.json", "test.items", schema_application="each_item"
    )
    payload = [{"note": "first"}, {"note": "second"}]
    path = _write_raw(tmp_path, spec, json.dumps(payload))

    _close_lane_repairs(tmp_path, spec)

    document = json.loads(path.read_text())
    assert isinstance(document, list)
    assert len(document) == 2
    assert document[0]["evidence_id"] != document[1]["evidence_id"]
    assert all(len(item["content_sha256"]) == 64 for item in document)
    # Agent-authored content preserved
    assert document[0]["note"] == "first"
    assert document[1]["note"] == "second"


def test_validate_role_outputs_reports_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON at a declared output path is a blocking finding on the
    production validation path (the retired pipeline's json.decode_error
    case)."""
    spec = _close_spec("method.schema.json")
    _write_raw(tmp_path, spec, "{not valid json")

    result = _validate_close_lane(tmp_path, spec)

    assert result.passed is False
    assert len(result.findings) == 1
    assert result.findings[0].code == "json.decode_error"
    assert result.findings[0].blocks_publication is True


def test_validate_role_outputs_reports_array_where_object_expected(
    tmp_path: Path,
) -> None:
    """A JSON array where the contract declares an object output is a
    blocking shape finding.

    Production reports ``output.expected_object``; the retired pipeline
    reported ``json.invalid_input_type`` for the same shape error.
    """
    spec = _close_spec("method.schema.json")
    _write_raw(tmp_path, spec, "[1, 2, 3]")

    result = _validate_close_lane(tmp_path, spec)

    assert result.passed is False
    assert [finding.code for finding in result.findings] == ["output.expected_object"]


def test_validate_role_outputs_reports_object_where_array_expected(
    tmp_path: Path,
) -> None:
    """An object where the contract requires an each_item (array) output is
    a blocking shape finding (production ``output.expected_array``; the
    shape error is reported, not silently coerced)."""
    spec = _close_spec(
        "evidence.schema.json", "test.items", schema_application="each_item"
    )
    _write_raw(tmp_path, spec, json.dumps({"note": "not an array"}))

    result = _validate_close_lane(tmp_path, spec)

    assert result.passed is False
    assert [finding.code for finding in result.findings] == ["output.expected_array"]


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


# --------------------------------------------------------------------------- #
# ADR-015: to_role broadcast + harness-owned finding reclassification (K5-1)  #
# --------------------------------------------------------------------------- #


def test_to_role_written_when_next_stage_has_one_role() -> None:
    result = populate_harness_fields(
        {}, _facts(to_role="theorist"), "handoff.schema.json"
    )
    assert result["to_role"] == "theorist"


def test_to_role_omitted_when_unresolvable_broadcast() -> None:
    result = populate_harness_fields({}, _facts(), "handoff.schema.json")
    assert "to_role" not in result


def test_reclassify_routes_harness_owned_field_to_operational_failure() -> None:
    finding = make_finding(
        code="schema.enum",
        message="'bogus' is not one of [...]",
        object_id="p2.handoff",
        pointer="/from_role",
    )
    assert finding.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    rerouted = reclassify_harness_owned_finding(
        finding, schema_file="handoff.schema.json", failing_property="from_role"
    )
    assert rerouted.finding_class is FindingClass.OPERATIONAL_FAILURE
    assert rerouted.correction_class == "none"
    assert rerouted.blocks_publication is True
    assert "harness" in rerouted.message.lower()
    assert "from_role" in rerouted.message


def test_reclassify_leaves_agent_owned_fields_correctable() -> None:
    finding = make_finding(
        code="schema.type",
        message="123 is not of type 'string'",
        object_id="p2.handoff",
        pointer="/completed_work",
    )
    unchanged = reclassify_harness_owned_finding(
        finding, schema_file="handoff.schema.json", failing_property="completed_work"
    )
    assert unchanged is finding


def test_reclassify_ignores_non_correctable_and_unknown_property() -> None:
    blocking = make_finding(
        code="artifact.digest_mismatch",
        message="digest mismatch",
        object_id="p2.handoff",
    )
    assert (
        reclassify_harness_owned_finding(
            blocking, schema_file="handoff.schema.json", failing_property="run_id"
        )
        is blocking
    )
    correctable = make_finding(
        code="schema.required", message="'x' is required", object_id="p2.handoff"
    )
    assert (
        reclassify_harness_owned_finding(
            correctable, schema_file="handoff.schema.json", failing_property=None
        )
        is correctable
    )


# --------------------------------------------------------------------------- #
# P-D: provenance strip-when-empty (R9) + mode-aware reclassification (R10)   #
# --------------------------------------------------------------------------- #


def test_review_basis_generation_id_stripped_when_run_fact_empty() -> None:
    result = populate_harness_fields(
        {"review_basis_generation_id": "generation.fabricated.001"},
        _facts(review_basis_generation_id=""),
        "review-finding.schema.json",
    )
    assert "review_basis_generation_id" not in result


def test_to_role_stripped_when_terminal() -> None:
    result = populate_harness_fields(
        {"to_role": "theorist"}, _facts(), "handoff.schema.json"
    )
    assert "to_role" not in result


def test_record_type_stripped_when_unresolved() -> None:
    result = populate_harness_fields(
        {"record_type": "manuscript"},
        _facts(record_type=""),
        "scientific-record.schema.json",
    )
    assert "record_type" not in result


def test_catalog_mode_method_identity_finding_stays_correctable() -> None:
    finding = make_finding(
        code="schema.type",
        message="1 is not of type 'string'",
        object_id="p2.method",
        pointer="/identity/version",
    )
    assert finding.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    unchanged = reclassify_harness_owned_finding(
        finding,
        schema_file="method.schema.json",
        failing_property="identity",
        method_bound=False,
    )
    assert unchanged is finding
    assert unchanged.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR


def test_method_bound_method_identity_finding_stays_operational() -> None:
    finding = make_finding(
        code="schema.type",
        message="1 is not of type 'string'",
        object_id="p2.method",
        pointer="/identity/version",
    )
    rerouted = reclassify_harness_owned_finding(
        finding,
        schema_file="method.schema.json",
        failing_property="identity",
        method_bound=True,
    )
    assert rerouted.finding_class is FindingClass.OPERATIONAL_FAILURE
    assert rerouted.correction_class == "none"
