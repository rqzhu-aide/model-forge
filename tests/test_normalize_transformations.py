"""P4a: selective normalize transformation primitive (K-1b).

Covers ``apply_normalize_transformations`` in
``method_hub.harness.role_execution``:

1. Per-code isolation — each of the seven allowlisted normalize codes
   applied alone produces exactly its own change and no other.
2. Parity with the role-lane monolith — all seven codes together produce
   the same JSON as ``_apply_disclosed_mechanical_repairs`` on a document
   without any ``identity.version < 1`` case (timestamps sentinel-ized).
3. The monolith's ``identity.version`` bump is never applied.
4. skip_item_repairs parity — for a schema with no timestamps and no
   ``additionalProperties: false`` only ``id_sanitization`` has any effect.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from method_hub.harness.role_execution import (
    _compute_content_hash,
    _sanitize_id,
    apply_normalize_transformations,
)

TS = "2026-01-01T00:00:00+00:00"

ALL_CODES = frozenset({
    "timestamp_injection",
    "id_sanitization",
    "hash_recomputation",
    "additional_properties_strip",
    "schema_version_injection",
    "null_strip",
    "empty_string_strip",
})

# theory-record.schema.json: additionalProperties:false, created_at
# timestamp, schema_version + content_sha256 declared, record_id is a
# schema-covered stableId, and it has declared optional properties
# (publication_receipt_id, published_at) for null/empty-string strips.
THEORY_SPEC = SimpleNamespace(
    schema_file="theory-record.schema.json",
    relative_path="output.json",
)

RAW_ID = "Bad ID Here"
SANE_ID = _sanitize_id(RAW_ID)


def _craft_doc() -> dict:
    """One document carrying exactly one defect per normalize code."""
    return {
        "record_id": RAW_ID,                     # id_sanitization
        "title": "A crafted theory record",
        "publication_receipt_id": None,          # null_strip (optional, declared)
        "published_at": "",                      # empty_string_strip (optional, declared)
        "bogus_extra_key": "junk",               # additional_properties_strip
        "content_sha256": "0" * 64,              # hash_recomputation
        # created_at missing                      # timestamp_injection
        # schema_version missing                  # schema_version_injection
    }


def _apply(doc: dict, codes, spec=THEORY_SPEC, path: Path | None = None, tmp_path: Path | None = None) -> bool:
    return apply_normalize_transformations(
        doc,
        spec=spec,
        codes=codes,
        ts=TS,
        path=path or (tmp_path or Path("/tmp")) / "output.json",
    )


# --------------------------------------------------------------------------- #
# 1. Per-code isolation                                                        #
# --------------------------------------------------------------------------- #

def test_timestamp_injection_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"timestamp_injection"}, tmp_path=tmp_path) is True
    assert doc["created_at"] == TS
    # Nothing else changed.
    assert "schema_version" not in doc
    assert doc["bogus_extra_key"] == "junk"
    assert doc["publication_receipt_id"] is None
    assert "publication_receipt_id" in doc
    assert doc["published_at"] == ""
    assert doc["record_id"] == RAW_ID
    assert doc["content_sha256"] == "0" * 64


def test_schema_version_injection_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"schema_version_injection"}, tmp_path=tmp_path) is True
    assert doc["schema_version"] == "1.0.0"
    assert "created_at" not in doc
    assert doc["bogus_extra_key"] == "junk"
    assert doc["publication_receipt_id"] is None
    assert doc["published_at"] == ""
    assert doc["record_id"] == RAW_ID
    assert doc["content_sha256"] == "0" * 64


def test_additional_properties_strip_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"additional_properties_strip"}, tmp_path=tmp_path) is True
    assert "bogus_extra_key" not in doc
    # Declared keys (even null/empty) survive; no injections happened.
    assert doc["publication_receipt_id"] is None
    assert "publication_receipt_id" in doc
    assert doc["published_at"] == ""
    assert "created_at" not in doc
    assert "schema_version" not in doc
    assert doc["record_id"] == RAW_ID
    assert doc["content_sha256"] == "0" * 64


def test_null_strip_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"null_strip"}, tmp_path=tmp_path) is True
    assert "publication_receipt_id" not in doc
    assert doc["published_at"] == ""
    assert doc["bogus_extra_key"] == "junk"
    assert "created_at" not in doc
    assert "schema_version" not in doc
    assert doc["record_id"] == RAW_ID
    assert doc["content_sha256"] == "0" * 64


def test_empty_string_strip_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"empty_string_strip"}, tmp_path=tmp_path) is True
    assert "published_at" not in doc
    assert doc["publication_receipt_id"] is None
    assert "publication_receipt_id" in doc
    assert doc["bogus_extra_key"] == "junk"
    assert "created_at" not in doc
    assert "schema_version" not in doc
    assert doc["record_id"] == RAW_ID
    assert doc["content_sha256"] == "0" * 64


def test_id_sanitization_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"id_sanitization"}, tmp_path=tmp_path) is True
    assert doc["record_id"] == SANE_ID
    assert doc["record_id"] != RAW_ID
    assert "created_at" not in doc
    assert "schema_version" not in doc
    assert doc["bogus_extra_key"] == "junk"
    assert doc["publication_receipt_id"] is None
    assert doc["published_at"] == ""
    assert doc["content_sha256"] == "0" * 64


def test_hash_recomputation_alone(tmp_path: Path) -> None:
    doc = _craft_doc()
    assert _apply(doc, {"hash_recomputation"}, tmp_path=tmp_path) is True
    assert doc["content_sha256"] != "0" * 64
    assert doc["content_sha256"] == _compute_content_hash(doc, {"content_sha256"})
    assert "created_at" not in doc
    assert "schema_version" not in doc
    assert doc["bogus_extra_key"] == "junk"
    assert doc["publication_receipt_id"] is None
    assert doc["published_at"] == ""
    assert doc["record_id"] == RAW_ID


def test_no_codes_changes_nothing(tmp_path: Path) -> None:
    doc = _craft_doc()
    original = deepcopy(doc)
    assert _apply(doc, set(), tmp_path=tmp_path) is False
    assert doc == original


# --------------------------------------------------------------------------- #
# 2. Parity with the role-lane monolith (all seven codes)                     #
# --------------------------------------------------------------------------- #

_TS_SUFFIXES = ("_at", "_timestamp", "_time")


def _sentinelize(obj):
    """Replace timestamp-valued and self-referential-hash fields with sentinels."""
    if isinstance(obj, dict):
        out = {}
        for key, val in obj.items():
            if key == "content_sha256" and isinstance(val, str):
                out[key] = "<HASH>"
            elif isinstance(val, str) and any(key.endswith(s) for s in _TS_SUFFIXES):
                out[key] = "<TS>"
            else:
                out[key] = _sentinelize(val)
        return out
    if isinstance(obj, list):
        return [_sentinelize(item) for item in obj]
    return obj


def test_parity_with_monolith_all_seven_codes(tmp_path: Path) -> None:
    """All seven codes == _apply_disclosed_mechanical_repairs (minus timestamps)."""
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

    raw_doc = _craft_doc()

    # Monolith path: write the raw doc and run the real repair pass.
    run_root = tmp_path / "run_root"
    run_root.mkdir()
    output_path = run_root / "output.json"
    output_path.write_text(json.dumps(raw_doc))

    spec = OutputSpec(
        contract_output_id="test.output",
        output_id="test.output.v1",
        output_kind="record",
        producer="data_analyst",
        stage_id="test",
        stage_sequence=1,
        schema_file="theory-record.schema.json",
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
        run_root=run_root,
        output_plan=OutputPlan(specs=(spec,)),
        stage=plan.stages[0],
        role="data_analyst",
        run_facts=None,
    )
    assert records["test.output"].changed
    monolith_result = json.loads(output_path.read_text())

    # Normalize primitive path: all seven codes on a fresh deep copy.
    normalize_doc = deepcopy(raw_doc)
    changed = apply_normalize_transformations(
        normalize_doc,
        spec=THEORY_SPEC,
        codes=ALL_CODES,
        ts=TS,
        path=tmp_path / "normalize" / "output.json",
    )
    assert changed is True

    assert _sentinelize(normalize_doc) == _sentinelize(monolith_result)


# --------------------------------------------------------------------------- #
# 3. identity.version bump is never applied                                   #
# --------------------------------------------------------------------------- #

def test_identity_version_bump_never_applied(tmp_path: Path) -> None:
    """identity.version 0 stays 0 even with all seven codes.

    method.schema.json declares ``identity`` and has additionalProperties
    not false, so the identity object itself is never stripped.
    """
    spec = SimpleNamespace(
        schema_file="method.schema.json",
        relative_path="output.json",
    )
    doc = {"identity": {"version": 0}, "title": "t"}
    changed = apply_normalize_transformations(
        doc,
        spec=spec,
        codes=ALL_CODES,
        ts=TS,
        path=tmp_path / "output.json",
    )
    assert changed is True  # timestamps/schema_version still injected
    assert doc["identity"]["version"] == 0


# --------------------------------------------------------------------------- #
# 4. skip_item_repairs parity (monolith's ISS-7 comment case)                 #
# --------------------------------------------------------------------------- #

def test_skip_item_repairs_only_id_sanitization_applies(tmp_path: Path) -> None:
    """statement.schema.json: no timestamps, no additionalProperties:false.

    Only id_sanitization has any effect — undeclared keys, nulls, empty
    strings, and missing schema_version are all left alone, exactly like the
    monolith's ISS-7 path.
    """
    spec = SimpleNamespace(
        schema_file="statement.schema.json",
        relative_path="output.json",
    )
    doc = {
        "statement_id": RAW_ID,
        "text": "a statement",
        "extra_key": "x",
        "note": None,
        "blank": "",
        # schema_version missing — declared in the schema, but per-item
        # repairs are skipped so it must NOT be injected.
    }
    changed = apply_normalize_transformations(
        doc,
        spec=spec,
        codes=ALL_CODES,
        ts=TS,
        path=tmp_path / "output.json",
    )
    assert changed is True
    assert doc["statement_id"] == SANE_ID
    # Everything else untouched.
    assert doc["extra_key"] == "x"
    assert doc["note"] is None
    assert "note" in doc
    assert doc["blank"] == ""
    assert "schema_version" not in doc
    assert "created_at" not in doc
