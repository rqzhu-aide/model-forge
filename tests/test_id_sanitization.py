"""ISS-7/ISS-8: schema-exact ID sanitization with document-wide reference rewrite.

Covers the three ISS-7 defects:

1. The early-continue in ``_apply_disclosed_mechanical_repairs`` skipped ID
   sanitization entirely for schemas with no timestamps and no
   ``additionalProperties: false`` (the production ``schema.pattern``
   failures on ``/evidence_ids/5`` and ``/statement_ids/4``).
2. Coverage was a key-name heuristic; it is now derived from the schemas'
   actual ``$defs/stableId`` positions (e.g. statement.schema.json's
   ``assumptions`` array items are stableIds although the key does not end
   in ``_ids``).
3. Sanitizing a definition site now rewrites same-valued references
   document-wide, so no dangling cross-references remain.

ISS-8: the subsumed ``_fix_item`` ID clauses are removed; behaviour is
pinned by the full tests/test_harness_repairs.py suite staying green.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

STABLEID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")

PRODUCTION_EVIDENCE_ID = "evidence.kernel_overhead_quantified_50x_at_M_100"
PRODUCTION_STATEMENT_ID = "claim.kernel_overhead_dominates_at_large_M"


def _run_repair(tmp_path: Path, schema_file: str, content):
    """Write ``content`` as an agent output and run the real repair pass."""
    from method_hub.contracts import (
        ResolvedPhasePlan,
        ResolvedRoleStep,
        ResolvedStage,
    )
    from method_hub.domain import PhaseContractIdentity
    from method_hub.harness.outputs import OutputPlan, OutputSpec
    from method_hub.harness.role_execution import (
        _apply_disclosed_mechanical_repairs,
    )

    output_path = tmp_path / "output.json"
    output_path.write_text(json.dumps(content))
    source_sha = hashlib.sha256(
        output_path.read_text().encode("utf-8")
    ).hexdigest()

    spec = OutputSpec(
        contract_output_id="test.output",
        output_id="test.output.v1",
        output_kind="record",
        producer="data_analyst",
        stage_id="test",
        stage_sequence=1,
        schema_file=schema_file,
        schema_application="",
        relative_path="output.json",
        required=True,
    )
    plan = ResolvedPhasePlan(
        identity=PhaseContractIdentity(
            phase_id="P2",
            contract_version="1.0.0",
            phase_contract_sha256="a" * 64,
        ),
        mode_id="p2.method_changes",
        choice_values={},
        context_policy="current_only",
        stages=(ResolvedStage(
            sequence=1,
            stage_id="test",
            execution="serial",
            objective="test",
            role_steps=(ResolvedRoleStep(
                role="data_analyst", input_ids=(), output_ids=("test.output",),
            ),),
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
    records = _apply_disclosed_mechanical_repairs(
        run_root=tmp_path,
        output_plan=OutputPlan(specs=(spec,)),
        stage=plan.stages[0],
        role="data_analyst",
    )
    repaired = json.loads(output_path.read_text())
    return records["test.output"], repaired, source_sha


# ---------------------------------------------------------------------------
# _stableid_positions: schema-exact coverage derivation
# ---------------------------------------------------------------------------

def test_classify_labels_lowercase_id_sanitization_exactly() -> None:
    """K-6: schema-derived ID sanitization and reference rewrites must be
    labeled ``id_sanitization`` even when the raw id contains no uppercase
    (the old key-name + case heuristic recorded them as ``value_rewrite``).
    """
    from method_hub.harness.role_execution import (
        _classify_transformations,
        _sanitize_id,
    )

    raw_id = "claim.kernel overhead at large m"  # all-lowercase, invalid
    sane = _sanitize_id(raw_id)
    assert sane != raw_id
    raw = {
        "statement_id": raw_id,
        "statement_ids": [raw_id],  # same-valued reference site
        "note": "unchanged",
    }
    repaired = {
        "statement_id": sane,
        "statement_ids": [sane],
        "note": "unchanged",
    }
    entries = _classify_transformations(
        raw, repaired, renames={raw_id: sane}
    )
    codes = {entry.code for entry in entries}
    assert codes == {"id_sanitization"}
    pointers = {entry.json_pointer for entry in entries}
    assert pointers == {"/statement_id", "/statement_ids/0"}


def test_classify_still_marks_real_value_rewrites() -> None:
    """K-6: a content change that is NOT an id rename stays value_rewrite."""
    from method_hub.harness.role_execution import _classify_transformations

    raw = {"summary": "old text", "record_id": "record.ok_1"}
    repaired = {"summary": "new text", "record_id": "record.ok_1"}
    entries = _classify_transformations(raw, repaired, renames={})
    assert [entry.code for entry in entries] == ["value_rewrite"]


def test_stableid_positions_match_verified_schema_scan() -> None:
    """Cross-check the walker against the audited stableId positions."""
    from method_hub.harness.role_execution import _stableid_positions

    cov = _stableid_positions("statement.schema.json")
    assert not cov["heuristic"]
    assert {"statement_id", "record_id", "record_generation_id",
            "supersedes_statement_id"} <= cov["scalar_keys"]
    assert {"assumptions", "supporting_evidence_ids",
            "counterevidence_ids"} <= cov["array_keys"]
    # stable_id is reached via cross-file methodIdentity resolution.
    assert "stable_id" in cov["scalar_keys"]

    cov = _stableid_positions("evidence.schema.json")
    assert {"evidence_id", "source_run_id", "supersedes_evidence_id",
            "publication_receipt_id"} <= cov["scalar_keys"]
    assert {"claim_ids"} <= cov["array_keys"]

    cov = _stableid_positions("handoff.schema.json")
    assert {"handoff_id", "run_id"} <= cov["scalar_keys"]
    assert {"basis_generation_ids", "statement_ids",
            "evidence_ids"} <= cov["array_keys"]


def test_stableid_positions_falls_back_to_heuristic_when_schema_missing() -> None:
    from method_hub.harness.role_execution import _stableid_positions

    cov = _stableid_positions("nonexistent.schema.json")
    assert cov["heuristic"] is True


# ---------------------------------------------------------------------------
# Regression: the production early-continue failure
# ---------------------------------------------------------------------------

def test_early_continue_schema_still_gets_id_sanitization(tmp_path: Path) -> None:
    """Production regression: statement.schema.json declares no timestamps and
    no additionalProperties:false, so the OLD code hit the early-continue and
    never ran ID sanitization — exactly how the pattern-invalid values
    'evidence.kernel_overhead_quantified_50x_at_M_100' (/evidence_ids/5) and
    'claim.kernel_overhead_dominates_at_large_M' (/statement_ids/4) survived
    repair in production.  Both must now match the stableId pattern.
    """
    from method_hub.harness.role_execution import _schema_info

    # Pin the fixture to the old early-continue path.
    info = _schema_info("statement.schema.json")
    assert not info["timestamps"]
    assert not (info["no_additional"] and info["properties"])

    content = {
        "schema_version": "1.0.0",
        # Covered scalar position (definition site of the statement id).
        "statement_id": PRODUCTION_STATEMENT_ID,
        # Covered array position (definition site of the evidence id).
        "supporting_evidence_ids": [PRODUCTION_EVIDENCE_ID, "evidence.ok_1"],
        # Same-valued references under keys this schema does not
        # pattern-check: rewritten by the document-wide pass.
        "statement_ids": [PRODUCTION_STATEMENT_ID],
        "evidence_ids": ["evidence.ok_1", PRODUCTION_EVIDENCE_ID],
    }
    record, repaired, source_sha = _run_repair(
        tmp_path, "statement.schema.json", content,
    )

    assert record.changed
    assert record.result_sha256 != source_sha
    for value in (
        repaired["statement_id"],
        *repaired["statement_ids"],
        *repaired["supporting_evidence_ids"],
        *repaired["evidence_ids"],
    ):
        assert STABLEID_RE.fullmatch(value), value
    # References hold the SAME sanitized value as the definition site.
    assert repaired["statement_ids"][0] == repaired["statement_id"]
    assert repaired["evidence_ids"][1] == repaired["supporting_evidence_ids"][0]
    # Already-valid ids are untouched.
    assert repaired["evidence_ids"][0] == "evidence.ok_1"
    assert repaired["supporting_evidence_ids"][1] == "evidence.ok_1"


# ---------------------------------------------------------------------------
# Schema-exact coverage: positions the key-name heuristic missed
# ---------------------------------------------------------------------------

def test_assumptions_array_items_sanitized(tmp_path: Path) -> None:
    """statement.schema.json ``assumptions`` items are stableIds although the
    parent key does not end in ``_ids`` — the old heuristic never looked."""
    content = {
        "statement_id": "stmt.ok",
        "assumptions": ["Has Uppercase", "has space", "already_valid-1"],
    }
    _, repaired, _ = _run_repair(tmp_path, "statement.schema.json", content)

    assert repaired["assumptions"][0] == "has_uppercase"
    # Lowercase-but-invalid values are caught by the fullmatch trigger (the
    # old `item != item.lower()` detection missed them).
    assert repaired["assumptions"][1] == "has_space"
    assert repaired["assumptions"][2] == "already_valid-1"
    for value in repaired["assumptions"]:
        assert STABLEID_RE.fullmatch(value), value


def test_heuristic_fallback_covers_ids_keys_when_schema_unavailable(
    tmp_path: Path,
) -> None:
    """When the schema cannot be loaded, the historical key-name heuristic
    applies so coverage never regresses."""
    content = {"evidence_ids": ["Bad ID"], "note": "Bad ID"}
    _, repaired, _ = _run_repair(
        tmp_path, "nonexistent.schema.json", content,
    )

    assert repaired["evidence_ids"] == ["bad_id"]
    # The reference rewrite applies in fallback mode too.
    assert repaired["note"] == "bad_id"


# ---------------------------------------------------------------------------
# Document-wide reference rewrite
# ---------------------------------------------------------------------------

def test_reference_rewrite_keeps_cross_references_consistent(
    tmp_path: Path,
) -> None:
    """An invalid id defined once and referenced elsewhere — under another
    item's id list and inside a free-text object — is sanitized at the
    definition site and rewritten to the SAME value everywhere."""
    content = [
        {"statement_id": "Stmt.Kernel Overhead", "text": "definition"},
        {
            "statement_id": "stmt.other",
            # Not a stableId position in statement.schema.json; rewritten by
            # the document-wide pass because the value matches a rename.
            "depends_on_statement_ids": ["Stmt.Kernel Overhead"],
            "narrative": {"see_also": "Stmt.Kernel Overhead"},
        },
    ]
    _, repaired, _ = _run_repair(tmp_path, "statement.schema.json", content)

    sanitized = repaired[0]["statement_id"]
    assert STABLEID_RE.fullmatch(sanitized)
    assert sanitized == "stmt.kernel_overhead"
    assert repaired[1]["depends_on_statement_ids"] == [sanitized]
    assert repaired[1]["narrative"]["see_also"] == sanitized
    # Untouched valid id.
    assert repaired[1]["statement_id"] == "stmt.other"


# ---------------------------------------------------------------------------
# No-touch: valid ids and non-covered keys are unchanged
# ---------------------------------------------------------------------------

def test_valid_ids_and_non_covered_strings_untouched(tmp_path: Path) -> None:
    """Nothing to sanitize → identity transformation record; an uppercase
    string under a non-covered, non-pattern key is left alone."""
    content = {
        "schema_version": "1.0.0",
        "statement_id": "stmt.valid_1",
        "record_id": "rec.valid",
        "assumptions": ["valid_assumption"],
        "title": "This Title Has Uppercase",
        "text": "Free Text Stays Exactly As Written",
    }
    record, repaired, source_sha = _run_repair(
        tmp_path, "statement.schema.json", content,
    )

    assert repaired == content
    assert not record.changed
    assert record.result_sha256 == source_sha
    assert record.entries == ()


def test_uncovered_key_with_invalid_value_not_sanitized_in_place(
    tmp_path: Path,
) -> None:
    """A pattern-invalid string under a key the schema does NOT pattern-check
    is only rewritten when it matches a rename from a covered position —
    never sanitized on its own."""
    content = {
        "statement_id": "stmt.valid",
        "arbitrary_note": "Totally Invalid ID!",
    }
    _, repaired, _ = _run_repair(tmp_path, "statement.schema.json", content)

    assert repaired["arbitrary_note"] == "Totally Invalid ID!"


# ---------------------------------------------------------------------------
# ISS-8: legacy id keys no schema declares keep their coverage
# ---------------------------------------------------------------------------

def test_legacy_undeclared_id_keys_still_sanitized(tmp_path: Path) -> None:
    """ISS-8: finding_id/theorem_id/... appear in no schema's stableId
    positions, but the removed _fix_item clause sanitized them — coverage is
    retained via the legacy supplement set."""
    content = {
        "statement_id": "stmt.valid",
        "theorem_id": "Theorem.Bad ID",
        "finding_id": "Finding With Space",
    }
    _, repaired, _ = _run_repair(tmp_path, "statement.schema.json", content)

    assert repaired["theorem_id"] == "theorem.bad_id"
    assert repaired["finding_id"] == "finding_with_space"
