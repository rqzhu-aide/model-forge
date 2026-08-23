"""Regression tests for the harness repair functions.

These tests verify the mechanical repair layer that runs after agent output
is collected, before schema validation:

1. ``_fix_self_referential_hashes`` — content_sha256, handoff_artifact.sha256
2. ``_strip_empty_strings`` — empty optional fields removed, required kept
3. ``_add_missing_timestamps`` — nested timestamps filled
4. ``_neutralize_identities`` — task brief template placeholders
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from copy import deepcopy

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_output(tmp_path: Path) -> Path:
    """A temporary file path that repair functions can write to."""
    p = tmp_path / "output.json"
    p.write_text("{}")
    return p


# ---------------------------------------------------------------------------
# _fix_self_referential_hashes — content_sha256
# ---------------------------------------------------------------------------

def test_content_sha256_is_computed_from_record_content(tmp_output: Path) -> None:
    """content_sha256 must be the hash of the record minus the field itself."""
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    record = {
        "schema_version": "1.0.0",
        "record_id": "rec.test",
        "content_sha256": "TBD_BY_MODEL_FORGE_ON_WRITE",
        "record_type": "theory",
        "phase": "P3",
        "title": "Test theory",
    }
    changed = _fix_self_referential_hashes(record, tmp_output)

    assert changed is True
    # Verify the hash is correct: RFC 8785 hash of the record minus content_sha256
    from model_forge.digests.jcs import canonicalize

    snapshot = {k: v for k, v in record.items() if k != "content_sha256"}
    expected = hashlib.sha256(canonicalize(snapshot)).hexdigest()
    assert record["content_sha256"] == expected


def test_content_sha256_in_list_of_records(tmp_output: Path) -> None:
    """Evidence/attention outputs are arrays of records — each needs its own hash."""
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    records = [
        {"evidence_id": "ev.1", "content_sha256": "placeholder"},
        {"evidence_id": "ev.2", "content_sha256": "placeholder"},
    ]
    changed = _fix_self_referential_hashes(records, tmp_output)

    assert changed is True
    # Each record must have a different hash (different content)
    assert records[0]["content_sha256"] != records[1]["content_sha256"]
    # Both must be valid 64-char hex
    assert len(records[0]["content_sha256"]) == 64
    assert len(records[1]["content_sha256"]) == 64


def test_content_sha256_idempotent(tmp_output: Path) -> None:
    """Running the repair twice should not change an already-correct hash."""
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    record = {"content_sha256": "", "title": "Stable"}
    _fix_self_referential_hashes(record, tmp_output)
    first_hash = record["content_sha256"]

    changed = _fix_self_referential_hashes(record, tmp_output)
    assert changed is False
    assert record["content_sha256"] == first_hash


def test_handoff_artifact_sha256_still_repaired(tmp_output: Path) -> None:
    """The original P2 bug fix (handoff_artifact.sha256) must still work."""
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    handoff = {
        "handoff_id": "ho.1",
        "handoff_artifact": {
            "media_type": "application/json",
            "sha256": "TBD",
        },
        "completed_work": ["did_something"],
    }
    changed = _fix_self_referential_hashes(handoff, tmp_output)

    assert changed is True
    ha = handoff["handoff_artifact"]
    assert len(ha["sha256"]) == 64
    # The hash must be the RFC 8785 hash of the record minus the sha256 field
    from model_forge.digests.jcs import canonicalize

    snapshot = {k: v for k, v in handoff.items()}
    snapshot["handoff_artifact"] = {k: v for k, v in ha.items() if k != "sha256"}
    expected = hashlib.sha256(canonicalize(snapshot)).hexdigest()
    assert ha["sha256"] == expected


def test_definition_sha256_repaired(tmp_output: Path) -> None:
    """identity.definition_sha256 follows the method_record.definition digest
    contract: RFC 8785 over /mathematical_definition/canonical_definition."""
    from model_forge.digests.jcs import canonicalize
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    record = {
        "identity": {
            "stable_id": "mth_test",
            "version": 1,
            "definition_sha256": "placeholder",
        },
        "mathematical_definition": {
            "canonical_definition": {"target_or_estimand": "x"},
            "components": ["target", "algorithm"],
        },
    }
    changed = _fix_self_referential_hashes(record, tmp_output)

    assert changed is True
    expected = hashlib.sha256(
        canonicalize({"target_or_estimand": "x"})
    ).hexdigest()
    assert record["identity"]["definition_sha256"] == expected


def test_definition_sha256_added_when_absent(tmp_output: Path) -> None:
    """An identity without the digest gets it stamped from the canonical
    definition (agents cannot compute it: hash paradox)."""
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    record = {
        "identity": {"stable_id": "mth_test", "version": 1},
        "mathematical_definition": {"canonical_definition": {"a": 1}},
    }
    changed = _fix_self_referential_hashes(record, tmp_output)
    assert changed is True
    assert len(record["identity"]["definition_sha256"]) == 64


# ---------------------------------------------------------------------------
# _strip_empty_strings
# ---------------------------------------------------------------------------

def test_strip_empty_optional_strings() -> None:
    """Empty strings in optional fields should be removed."""
    from model_forge.harness.role_execution import _strip_empty_strings

    data = {"title": "real", "note": "", "optional_field": ""}
    changed = _strip_empty_strings(data, required_fields={"title"})

    assert changed is True
    assert data == {"title": "real"}


def test_strip_preserves_required_empty_strings() -> None:
    """Required fields with empty strings should NOT be stripped."""
    from model_forge.harness.role_execution import _strip_empty_strings

    data = {"title": "", "note": ""}
    changed = _strip_empty_strings(data, required_fields={"title"})

    assert changed is True
    # "title" is required and empty — kept for validation to report
    assert "title" in data
    assert "note" not in data


def test_strip_preserves_nested_required() -> None:
    """Nested required field names should not be stripped at any depth."""
    from model_forge.harness.role_execution import _strip_empty_strings

    data = {
        "artifact": {
            "artifact_id": "",
            "uri": "",
            "description": "",
        },
    }
    nested_required = {"artifact_id", "uri"}
    changed = _strip_empty_strings(data, required_fields=nested_required)

    assert changed is True
    # artifact_id and uri are required — kept. description is optional — stripped.
    assert data["artifact"]["artifact_id"] == ""
    assert data["artifact"]["uri"] == ""
    assert "description" not in data["artifact"]


def test_strip_recursive_in_lists() -> None:
    """Empty strings inside list elements should be stripped."""
    from model_forge.harness.role_execution import _strip_empty_strings

    data = {
        "items": [
            {"id": "a", "note": ""},
            {"id": "b", "note": "real"},
        ],
    }
    changed = _strip_empty_strings(data, required_fields=set())

    assert changed is True
    assert data["items"][0] == {"id": "a"}
    assert data["items"][1] == {"id": "b", "note": "real"}


# ---------------------------------------------------------------------------
# _neutralize_identities
# ---------------------------------------------------------------------------

def test_neutralize_bare_sha256() -> None:
    """The bare key 'sha256' must be neutralized in task brief examples."""
    from model_forge.harness.task_briefs import _neutralize_identities

    data = {
        "artifacts": [
            {"sha256": "abc123def456", "uri": "/path"},
        ],
        "content_sha256": "deadbeef",
    }
    result = _neutralize_identities(data)

    assert result["artifacts"][0]["sha256"] == "<...>"
    assert result["content_sha256"] == "<...>"
    # Non-id fields preserved
    assert result["artifacts"][0]["uri"] == "/path"


def test_neutralize_handoff_artifact_sha256() -> None:
    """handoff_artifact.sha256 must be neutralized."""
    from model_forge.harness.task_briefs import _neutralize_identities

    data = {
        "handoff_artifact": {
            "sha256": "abc123",
            "media_type": "application/json",
        },
    }
    result = _neutralize_identities(data)

    assert result["handoff_artifact"]["sha256"] == "<...>"
    assert result["handoff_artifact"]["media_type"] == "application/json"


# ---------------------------------------------------------------------------
# _schema_info — nested required collection
# ---------------------------------------------------------------------------

def test_schema_info_collects_nested_required() -> None:
    """_schema_info should return nested_required from sub-object definitions."""
    from model_forge.harness.role_execution import _schema_info

    info = _schema_info("evidence.schema.json")
    nested = info.get("nested_required", set())

    # evidence.schema.json has reproducibility with required fields
    # and applicability_at_creation with required fields
    assert "method_match" in nested or "code_artifacts" in nested


def test_schema_info_does_not_fabricate_search_provenance() -> None:
    """Search occurrence time must be supplied by the producer, not repaired."""
    from model_forge.harness.role_execution import _schema_info

    info = _schema_info("review-report.schema.json")
    assert "searched_at" not in info["nested_timestamps"]


def test_schema_info_handles_missing_file() -> None:
    """_schema_info should return empty sets for unknown schemas."""
    from model_forge.harness.role_execution import _schema_info, _empty_schema_info

    info = _schema_info("nonexistent.schema.json")
    assert info == _empty_schema_info()
    assert "nested_required" in info
    assert "nested_timestamps" in info


# --------------------------------------------------------------------------- #
# HV-1.1+1.2: Seal raw output before repair + OutputTransformationRecord      #
# --------------------------------------------------------------------------- #

def test_repair_returns_transformation_record_with_source_digest(tmp_path: Path) -> None:
    """The repair function must return a record with the pre-repair digest."""
    from model_forge.harness.role_execution import _apply_disclosed_mechanical_repairs
    from model_forge.harness.outputs import OutputPlan, OutputSpec
    from model_forge.contracts import (
        ResolvedPhasePlan,
        ResolvedRoleStep,
        ResolvedStage,
    )
    from model_forge.domain import PhaseContractIdentity
    import json as _json
    import hashlib

    # Create a minimal output file that needs timestamp injection
    output_path = tmp_path / "output.json"
    raw_content = {"record_id": "rec.test", "title": "Test"}
    output_path.write_text(_json.dumps(raw_content))

    source_sha = hashlib.sha256(
        output_path.read_text().encode("utf-8")
    ).hexdigest()

    spec = OutputSpec(
        contract_output_id="test.output",
        output_id="test.output.v1",
        output_kind="record",
        producer="theorist",
        stage_id="test",
        stage_sequence=1,
        schema_file="method.schema.json",
        schema_application="",
        relative_path="output.json",
        required=True,
    )
    plan = ResolvedPhasePlan(
        identity=PhaseContractIdentity(
            phase_id="P3",
            contract_version="1.0.0",
            phase_contract_sha256="a" * 64,
        ),
        mode_id="p3.theory_establishment",
        choice_values={},
        context_policy="current_only",
        stages=(ResolvedStage(
            sequence=1,
            stage_id="test",
            execution="serial",
            objective="test",
            role_steps=(ResolvedRoleStep(role="theorist", input_ids=(), output_ids=("test.output",)),),
            writes=(),
            handoff_required=False,
            isolation_rule=None,
        ),),
        output_contracts=(),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )
    output_plan = OutputPlan(specs=(spec,))
    stage = plan.stages[0]

    records = _apply_disclosed_mechanical_repairs(
        run_root=tmp_path,
        output_plan=output_plan,
        stage=stage,
        role="theorist",
    )

    assert "test.output" in records
    record = records["test.output"]
    assert record.source_sha256 == source_sha
    # The repaired content should differ (timestamps injected)
    assert record.changed
    assert record.result_sha256 != source_sha


def test_repair_identity_transform_when_no_changes(tmp_path: Path) -> None:
    """When no repair applies, source and result digests are identical."""
    from model_forge.harness.role_execution import _apply_disclosed_mechanical_repairs
    from model_forge.harness.outputs import OutputPlan, OutputSpec
    from model_forge.contracts import (
        ResolvedPhasePlan,
        ResolvedRoleStep,
        ResolvedStage,
    )
    from model_forge.domain import PhaseContractIdentity
    import json as _json
    import hashlib

    # Create a file with an unknown schema (no timestamps/properties to repair)
    output_path = tmp_path / "output.json"
    raw_content = {"foo": "bar"}
    output_path.write_text(_json.dumps(raw_content))
    source_sha = hashlib.sha256(
        output_path.read_text().encode("utf-8")
    ).hexdigest()

    spec = OutputSpec(
        contract_output_id="test.output",
        output_id="test.output.v1",
        output_kind="record",
        producer="research_lead",
        stage_id="test",
        stage_sequence=1,
        schema_file="nonexistent.schema.json",
        schema_application="",
        relative_path="output.json",
        required=True,
    )
    plan = ResolvedPhasePlan(
        identity=PhaseContractIdentity(
            phase_id="P1",
            contract_version="1.0.0",
            phase_contract_sha256="a" * 64,
        ),
        mode_id="p1.literature_update",
        choice_values={},
        context_policy="current_only",
        stages=(ResolvedStage(
            sequence=1,
            stage_id="test",
            execution="serial",
            objective="test",
            role_steps=(ResolvedRoleStep(role="research_lead", input_ids=(), output_ids=("test.output",)),),
            writes=(),
            handoff_required=False,
            isolation_rule=None,
        ),),
        output_contracts=(),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )
    output_plan = OutputPlan(specs=(spec,))
    stage = plan.stages[0]

    records = _apply_disclosed_mechanical_repairs(
        run_root=tmp_path,
        output_plan=output_plan,
        stage=stage,
        role="research_lead",
    )

    record = records["test.output"]
    assert record.source_sha256 == source_sha
    assert record.result_sha256 == source_sha
    assert not record.changed


def test_classify_transformations_captures_field_stripping() -> None:
    """_classify_transformations must record additional_properties_strip."""
    from model_forge.harness.role_execution import _classify_transformations

    raw = {"title": "real", "undeclared_field": "data", "note": ""}
    repaired = {"title": "real"}
    entries = _classify_transformations(raw, repaired)

    codes = {e.code for e in entries}
    assert "additional_properties_strip" in codes or "empty_string_strip" in codes
    assert any(e.json_pointer for e in entries)


def test_classify_transformations_captures_timestamp_injection() -> None:
    """_classify_transformations must record timestamp_injection."""
    from model_forge.harness.role_execution import _classify_transformations

    raw = {"title": "real"}
    repaired = {"title": "real", "created_at": "2026-01-01T00:00:00Z"}
    entries = _classify_transformations(raw, repaired)

    ts_entry = next(e for e in entries if e.code == "timestamp_injection")
    assert "created_at" in ts_entry.detail


def test_classify_transformations_captures_hash_recomputation() -> None:
    """_classify_transformations must record hash_recomputation."""
    from model_forge.harness.role_execution import _classify_transformations

    raw = {"content_sha256": "placeholder"}
    repaired = {"content_sha256": "a" * 64}
    entries = _classify_transformations(raw, repaired)

    hash_entry = next(e for e in entries if e.code == "hash_recomputation")
    assert "content_sha256" in hash_entry.detail


def test_classify_transformations_empty_when_identical() -> None:
    """No entries when raw and repaired are identical."""
    from model_forge.harness.role_execution import _classify_transformations

    raw = {"title": "real", "nested": {"a": 1}}
    entries = _classify_transformations(raw, dict(raw))
    assert entries == []


# --------------------------------------------------------------------------- #
# HV-1.3: Schema-path-aware timestamp injection                               #
# --------------------------------------------------------------------------- #

def test_timestamp_injection_respects_parent_key_scope() -> None:
    """Timestamps should only be injected into dicts under the correct parent key."""
    from model_forge.harness.role_execution import _add_missing_timestamps

    data = {
        "title": "real",
        "assumptions": {"text": "no timestamps here"},
        "alignment_assessment": {"state": "exact"},
    }
    ts_map = {"alignment_assessment": {"assessed_at"}}
    changed = _add_missing_timestamps(data, ts_map, "2026-01-01T00:00:00Z")

    assert changed
    # assessed_at injected ONLY under alignment_assessment
    assert "assessed_at" in data["alignment_assessment"]
    # NOT injected into the assumptions dict
    assert "assessed_at" not in data["assumptions"]
    # NOT injected at the top level
    assert "assessed_at" not in data


def test_timestamp_injection_handles_array_of_objects() -> None:
    """Timestamps should be injected into array elements under the parent key."""
    from model_forge.harness.role_execution import _add_missing_timestamps

    data = {
        "assessments": [
            {"state": "exact"},
            {"state": "compatible"},
        ],
    }
    ts_map = {"assessments": {"assessed_at"}}
    changed = _add_missing_timestamps(data, ts_map, "2026-01-01T00:00:00Z")

    assert changed
    assert "assessed_at" in data["assessments"][0]
    assert "assessed_at" in data["assessments"][1]


def test_collect_nested_timestamps_returns_parent_keyed_map() -> None:
    """_collect_nested_timestamps should return a dict, not a flat set."""
    from model_forge.harness.role_execution import _collect_nested_timestamps

    schema = {
        "properties": {
            "alignment_assessment": {
                "type": "object",
                "properties": {
                    "state": {"type": "string"},
                    "assessed_at": {"type": "string", "format": "date-time"},
                },
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "collected_at": {"type": "string", "format": "date-time"},
                    },
                },
            },
        },
    }
    found: dict[str, set[str]] = {}
    _collect_nested_timestamps(schema, found)

    assert "alignment_assessment" in found
    assert "assessed_at" in found["alignment_assessment"]
    assert "evidence" in found
    assert "collected_at" in found["evidence"]


# --------------------------------------------------------------------------- #
# HV-1.5/1.6: Mode shim fix                                                   #
# --------------------------------------------------------------------------- #

def test_build_plan_from_manifest_passes_real_mode() -> None:
    """The plan built from the manifest must carry the real mode_id."""
    from model_forge.application.output_validation import _build_plan_from_manifest

    manifest = {
        "phase": "P3",
        "mode": "p3.theory_revision",
        "phase_contract_version": "1.0.0",
        "phase_contract_sha256": "a" * 64,
    }
    plan = _build_plan_from_manifest(manifest)
    assert plan.mode_id == "p3.theory_revision"
    assert plan.identity.phase_id == "P3"


def test_build_plan_from_manifest_defaults_safely() -> None:
    """Missing mode/phase should default safely without raising."""
    from model_forge.application.output_validation import _build_plan_from_manifest

    # Empty manifest — phase defaults to "run" (not a valid PhaseContractIdentity
    # phase_id, but this function doesn't validate; it constructs for the
    # validator dispatch which handles unknown phases by skipping).
    plan = _build_plan_from_manifest({})
    assert plan.mode_id == ""


# --------------------------------------------------------------------------- #
# OutputTransformationRecord and TransformationEntry dataclasses              #
# --------------------------------------------------------------------------- #

def test_output_transformation_record_serialization() -> None:
    """OutputTransformationRecord.to_dict() should serialize all fields."""
    from model_forge.domain.validation import (
        OutputTransformationRecord,
        TransformationEntry,
    )

    record = OutputTransformationRecord(
        contract_output_id="test.output",
        source_sha256="a" * 64,
        result_sha256="b" * 64,
        entries=(
            TransformationEntry(
                code="timestamp_injection",
                json_pointer="/created_at",
                detail="injected missing timestamp",
            ),
        ),
    )
    d = record.to_dict()
    assert d["contract_output_id"] == "test.output"
    assert d["source_sha256"] == "a" * 64
    assert d["result_sha256"] == "b" * 64
    assert d["changed"] is True
    assert len(d["entries"]) == 1
    assert d["entries"][0]["code"] == "timestamp_injection"
    assert d["primary_artifact_unchanged"] is True


def test_output_transformation_record_unchanged_when_same_digest() -> None:
    """The changed property should be False when source == result."""
    from model_forge.domain.validation import OutputTransformationRecord

    record = OutputTransformationRecord(
        contract_output_id="test.output",
        source_sha256="a" * 64,
        result_sha256="a" * 64,
    )
    assert not record.changed
