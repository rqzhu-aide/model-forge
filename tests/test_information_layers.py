"""E-2: information layers made real - pointer stamping and validation.

1. ``_fix_self_referential_hashes`` with an ``_OutputPointerContext`` stamps
   ``representations[].artifact`` entries declared as ``output://<filename>``
   with the real artifact_id / uri / sha256 of the sibling output bytes.
2. ``_validate_compact_view_pointers`` rejects compact_decision_view pointers
   that are unstamped (output://) or synthetic (degenerate sha256), so a
   placeholder layer can never seal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from method_hub.domain.validation import FindingClass, get_policy
from method_hub.harness.role_execution import (
    _OutputPointerContext,
    _fix_self_referential_hashes,
)
from method_hub.harness.scientific_validators import _validate_compact_view_pointers


def _context(tmp_path: Path, files: dict[str, str]) -> _OutputPointerContext:
    specs = [
        SimpleNamespace(relative_path=name, contract_output_id=f"p1.{name.removesuffix('.json').replace('-', '_')}")
        for name in files
    ]
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return _OutputPointerContext(
        project_id="project.test",
        run_id="run.test",
        run_root=tmp_path,
        specs=specs,
    )


def _record_with_pointer(uri: str) -> dict:
    return {
        "record_id": "rec.test",
        "representations": [
            {
                "information_layer": "compact_decision_view",
                "artifact": {"uri": uri, "media_type": "application/json"},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Stamping
# ---------------------------------------------------------------------------

def test_output_pointer_is_stamped_with_real_values(tmp_path: Path) -> None:
    context = _context(tmp_path, {"synthesis-compact.json": '{"title": "x"}'})
    record = _record_with_pointer("output://synthesis-compact.json")
    changed = _fix_self_referential_hashes(record, tmp_path / "synthesis-candidate.json", pointer_context=context)

    assert changed is True
    artifact = record["representations"][0]["artifact"]
    expected_sha = hashlib.sha256(b'{"title": "x"}').hexdigest()
    assert artifact["sha256"] == expected_sha
    assert artifact["uri"] == f"artifact://sha256/{expected_sha}"
    assert artifact["artifact_id"].startswith("artifact.")
    assert "p1.synthesis_compact" in artifact["artifact_id"] or len(artifact["artifact_id"]) > 12


def test_sealed_artifact_pointers_are_left_alone(tmp_path: Path) -> None:
    context = _context(tmp_path, {})
    record = _record_with_pointer("artifact://sha256/" + "ab" * 32)
    record["representations"][0]["artifact"]["sha256"] = "ab" * 32
    changed = _fix_self_referential_hashes(record, tmp_path / "x.json", pointer_context=context)
    assert changed is False
    assert record["representations"][0]["artifact"]["uri"].startswith("artifact://")


def test_unresolvable_output_pointer_is_left_for_validation(tmp_path: Path) -> None:
    context = _context(tmp_path, {})  # no sibling file
    record = _record_with_pointer("output://missing.json")
    changed = _fix_self_referential_hashes(record, tmp_path / "x.json", pointer_context=context)
    assert changed is False
    assert record["representations"][0]["artifact"]["uri"] == "output://missing.json"


def test_no_pointer_context_leaves_pointers_untouched(tmp_path: Path) -> None:
    record = _record_with_pointer("output://synthesis-compact.json")
    changed = _fix_self_referential_hashes(record, tmp_path / "x.json")
    assert changed is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _codes(findings: list) -> list[str]:
    return [f.code for f in findings]


def test_validation_rejects_unstamped_output_pointer() -> None:
    findings: list = []
    _validate_compact_view_pointers(
        _record_with_pointer("output://synthesis-compact.json"),
        code_prefix="p1",
        object_id="p1.synthesis_candidate",
        findings=findings,
    )
    assert _codes(findings) == ["p1.compact_view_pointer_invalid"]


def test_validation_rejects_synthetic_sha() -> None:
    record = _record_with_pointer("artifact://sha256/" + "9" * 64)
    record["representations"][0]["artifact"]["sha256"] = "9" * 64
    findings: list = []
    _validate_compact_view_pointers(
        record, code_prefix="p3", object_id="p3.complete_theory", findings=findings,
    )
    assert _codes(findings) == ["p3.compact_view_pointer_invalid"]


def test_validation_accepts_real_pointer() -> None:
    record = _record_with_pointer("artifact://sha256/" + "ab" * 32)
    record["representations"][0]["artifact"].update(
        {"sha256": "ab" * 32, "artifact_id": "artifact.real"}
    )
    findings: list = []
    _validate_compact_view_pointers(
        record, code_prefix="p1", object_id="p1.synthesis_candidate", findings=findings,
    )
    assert findings == []


def test_validation_ignores_other_layers_and_missing_representations() -> None:
    findings: list = []
    doc = {
        "representations": [
            {
                "information_layer": "primary_artifact",
                "artifact": {"uri": "artifact://x", "sha256": "1" * 64},
            }
        ]
    }
    _validate_compact_view_pointers(doc, code_prefix="p1", object_id="o", findings=findings)
    _validate_compact_view_pointers({}, code_prefix="p1", object_id="o", findings=findings)
    _validate_compact_view_pointers(None, code_prefix="p1", object_id="o", findings=findings)
    assert findings == []


def test_compact_pointer_codes_are_registered_correctable() -> None:
    for code in ("p1.compact_view_pointer_invalid", "p3.compact_view_pointer_invalid"):
        policy = get_policy(code)
        assert policy is not None
        assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
