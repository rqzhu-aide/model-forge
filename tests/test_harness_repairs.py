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
    from method_hub.harness.role_execution import _fix_self_referential_hashes

    record = {
        "schema_version": "1.0.0",
        "record_id": "rec.test",
        "content_sha256": "TBD_BY_METHOD_HUB_ON_WRITE",
        "record_type": "theory",
        "phase": "P3",
        "title": "Test theory",
    }
    changed = _fix_self_referential_hashes(record, tmp_output)

    assert changed is True
    # Verify the hash is correct: hash of the record minus content_sha256
    snapshot = {k: v for k, v in record.items() if k != "content_sha256"}
    expected = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert record["content_sha256"] == expected


def test_content_sha256_in_list_of_records(tmp_output: Path) -> None:
    """Evidence/attention outputs are arrays of records — each needs its own hash."""
    from method_hub.harness.role_execution import _fix_self_referential_hashes

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
    from method_hub.harness.role_execution import _fix_self_referential_hashes

    record = {"content_sha256": "", "title": "Stable"}
    _fix_self_referential_hashes(record, tmp_output)
    first_hash = record["content_sha256"]

    changed = _fix_self_referential_hashes(record, tmp_output)
    assert changed is False
    assert record["content_sha256"] == first_hash


def test_handoff_artifact_sha256_still_repaired(tmp_output: Path) -> None:
    """The original P2 bug fix (handoff_artifact.sha256) must still work."""
    from method_hub.harness.role_execution import _fix_self_referential_hashes

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
    # The hash must be computed from the record minus the sha256 field
    snapshot = {k: v for k, v in handoff.items()}
    snapshot["handoff_artifact"] = {k: v for k, v in ha.items() if k != "sha256"}
    expected = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert ha["sha256"] == expected


def test_definition_sha256_repaired(tmp_output: Path) -> None:
    """definition_sha256 inside mathematical_definition must be recomputed."""
    from method_hub.harness.role_execution import _fix_self_referential_hashes

    record = {
        "mathematical_definition": {
            "definition_sha256": "placeholder",
            "components": ["target", "algorithm"],
        },
    }
    changed = _fix_self_referential_hashes(record, tmp_output)

    assert changed is True
    md = record["mathematical_definition"]
    snapshot = {k: v for k, v in md.items() if k != "definition_sha256"}
    expected = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert md["definition_sha256"] == expected


# ---------------------------------------------------------------------------
# _strip_empty_strings
# ---------------------------------------------------------------------------

def test_strip_empty_optional_strings() -> None:
    """Empty strings in optional fields should be removed."""
    from method_hub.harness.role_execution import _strip_empty_strings

    data = {"title": "real", "note": "", "optional_field": ""}
    changed = _strip_empty_strings(data, required_fields={"title"})

    assert changed is True
    assert data == {"title": "real"}


def test_strip_preserves_required_empty_strings() -> None:
    """Required fields with empty strings should NOT be stripped."""
    from method_hub.harness.role_execution import _strip_empty_strings

    data = {"title": "", "note": ""}
    changed = _strip_empty_strings(data, required_fields={"title"})

    assert changed is True
    # "title" is required and empty — kept for validation to report
    assert "title" in data
    assert "note" not in data


def test_strip_preserves_nested_required() -> None:
    """Nested required field names should not be stripped at any depth."""
    from method_hub.harness.role_execution import _strip_empty_strings

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
    from method_hub.harness.role_execution import _strip_empty_strings

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
    from method_hub.harness.task_briefs import _neutralize_identities

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
    from method_hub.harness.task_briefs import _neutralize_identities

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
    from method_hub.harness.role_execution import _schema_info

    info = _schema_info("evidence.schema.json")
    nested = info.get("nested_required", set())

    # evidence.schema.json has reproducibility with required fields
    # and applicability_at_creation with required fields
    assert "method_match" in nested or "code_artifacts" in nested


def test_schema_info_handles_missing_file() -> None:
    """_schema_info should return empty sets for unknown schemas."""
    from method_hub.harness.role_execution import _schema_info, _empty_schema_info

    info = _schema_info("nonexistent.schema.json")
    assert info == _empty_schema_info()
    assert "nested_required" in info
    assert "nested_timestamps" in info
