"""E-2e: P2 canonical_artifact pointer stamping and validation.

Covers the closure stamping of ``input://<materialized input filename>``
canonical_artifact declarations (role_execution._stamp_canonical_artifact
via _fix_self_referential_hashes case 5) and the
``p2.canonical_pointer_invalid`` validation rule
(scientific_validators._validate_canonical_artifact_pointer).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from model_forge.domain.validation import FindingClass, get_policy
from model_forge.harness.execution_records import deterministic_id
from model_forge.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from model_forge.harness.role_execution import (
    _OutputPointerContext,
    _fix_self_referential_hashes,
)
from model_forge.harness.scientific_validators import (
    _validate_canonical_artifact_pointer,
    validate_phase_scientific,
)
from model_forge.domain.validation import ValidationFinding


def _context(tmp_path: Path, lookup=None) -> _OutputPointerContext:
    return _OutputPointerContext(
        project_id="project.test",
        run_id="run.test",
        run_root=tmp_path,
        specs=(),
        canonical_source_lookup=lookup,
    )


def _method_record(uri: str, **artifact_extra: Any) -> dict[str, Any]:
    artifact = {
        "uri": uri,
        "media_type": "application/json",
        "path": uri.removeprefix("input://"),
        "locator": "Definition 1",
    }
    artifact.update(artifact_extra)
    return {
        "identity": {"stable_id": "method.canonical.test", "version": 1},
        "mathematical_definition": {
            "canonical_definition": {
                "target_or_estimand": {"definition": "A test estimand."},
            },
            "canonical_artifact": artifact,
        },
    }


# ---------------------------------------------------------------------------
# Stamping
# ---------------------------------------------------------------------------


def test_canonical_pointer_is_stamped_from_input_bytes(tmp_path: Path) -> None:
    payload = b'{"proposal": "theory"}'
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "ab12sourcebytes").write_bytes(payload)
    record = _method_record("input://ab12sourcebytes")
    context = _context(tmp_path, lookup=lambda digest: "artifact.sealed-source")

    changed = _fix_self_referential_hashes(
        record, tmp_path / "method-changes.json", pointer_context=context
    )

    assert changed is True
    artifact = record["mathematical_definition"]["canonical_artifact"]
    digest = hashlib.sha256(payload).hexdigest()
    assert artifact["sha256"] == digest
    assert artifact["uri"] == f"artifact://sha256/{digest}"
    assert artifact["artifact_id"] == "artifact.sealed-source"
    # agent-authored fields preserved
    assert artifact["path"] == "ab12sourcebytes"
    assert artifact["locator"] == "Definition 1"


def test_canonical_pointer_lookup_none_falls_back_to_deterministic_id(
    tmp_path: Path,
) -> None:
    payload = b'{"proposal": "empirical"}'
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "cd34sourcebytes").write_bytes(payload)
    record = _method_record("input://cd34sourcebytes")
    context = _context(tmp_path, lookup=lambda digest: None)

    changed = _fix_self_referential_hashes(
        record, tmp_path / "method-changes.json", pointer_context=context
    )

    assert changed is True
    artifact = record["mathematical_definition"]["canonical_artifact"]
    digest = hashlib.sha256(payload).hexdigest()
    assert artifact["artifact_id"] == deterministic_id(
        "artifact", "project.test", "run.test", "canonical_source", digest
    )


def test_null_identity_does_not_disable_stamping(tmp_path: Path) -> None:
    # E-2f regression: an agent identity slip (identity: null, observed in
    # production on run.p2.p2-full-catalog.4a71023d 2026-08-24) must not
    # silently disable canonical_artifact stamping; identity problems are
    # for schema validation to report, not for the stamping discriminator.
    payload = b'{"proposal": "theory"}'
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "ef56sourcebytes").write_bytes(payload)
    record = _method_record("input://ef56sourcebytes")
    record["identity"] = None
    context = _context(tmp_path, lookup=lambda digest: "artifact.sealed-source")

    changed = _fix_self_referential_hashes(
        record, tmp_path / "method-changes.json", pointer_context=context
    )

    assert changed is True
    artifact = record["mathematical_definition"]["canonical_artifact"]
    digest = hashlib.sha256(payload).hexdigest()
    assert artifact["sha256"] == digest
    assert artifact["uri"] == f"artifact://sha256/{digest}"
    assert artifact["artifact_id"] == "artifact.sealed-source"
    assert record["identity"] is None  # untouched: schema validation's job


def test_unresolvable_input_pointer_is_left_for_validation(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir()  # no matching file inside
    record = _method_record("input://missing99")
    context = _context(tmp_path, lookup=lambda digest: "artifact.never")

    _fix_self_referential_hashes(
        record, tmp_path / "method-changes.json", pointer_context=context
    )

    artifact = record["mathematical_definition"]["canonical_artifact"]
    assert artifact["uri"] == "input://missing99"
    assert "sha256" not in artifact
    assert "artifact_id" not in artifact


def test_non_input_uri_is_left_alone(tmp_path: Path) -> None:
    record = _method_record(
        "artifact://sha256/" + "ab" * 32, sha256="ab" * 32
    )
    context = _context(tmp_path, lookup=lambda digest: "artifact.never")

    _fix_self_referential_hashes(
        record, tmp_path / "method-changes.json", pointer_context=context
    )

    artifact = record["mathematical_definition"]["canonical_artifact"]
    assert artifact["uri"] == "artifact://sha256/" + "ab" * 32
    assert artifact["sha256"] == "ab" * 32
    assert "artifact_id" not in artifact


def test_method_changes_list_recursion_stamps_every_record(tmp_path: Path) -> None:
    payload = b'{"proposal": "x"}'
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "ef56sourcebytes").write_bytes(payload)
    document = [
        _method_record("input://ef56sourcebytes"),
        _method_record("input://ef56sourcebytes"),
    ]
    context = _context(tmp_path, lookup=lambda digest: "artifact.sealed-source")

    changed = _fix_self_referential_hashes(
        document, tmp_path / "method-changes.json", pointer_context=context
    )

    assert changed is True
    digest = hashlib.sha256(payload).hexdigest()
    for record in document:
        artifact = record["mathematical_definition"]["canonical_artifact"]
        assert artifact["sha256"] == digest
        assert artifact["artifact_id"] == "artifact.sealed-source"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _codes(findings: list) -> list[str]:
    return [f.code for f in findings]


def test_validation_rejects_unstamped_input_pointer() -> None:
    findings: list = []
    _validate_canonical_artifact_pointer(
        _method_record("input://ab12sourcebytes"), offset=0, findings=findings
    )
    assert _codes(findings) == ["p2.canonical_pointer_invalid"]
    assert findings[0].json_pointer == "/0/mathematical_definition/canonical_artifact"


def test_validation_rejects_synthetic_sha() -> None:
    record = _method_record(
        "artifact://sha256/" + "7" * 64, sha256="7" * 64
    )
    findings: list = []
    _validate_canonical_artifact_pointer(record, offset=2, findings=findings)
    assert _codes(findings) == ["p2.canonical_pointer_invalid"]


def test_validation_accepts_stamped_pointer() -> None:
    digest = hashlib.sha256(b'{"proposal": "real"}').hexdigest()
    record = _method_record(
        f"artifact://sha256/{digest}",
        sha256=digest,
        artifact_id="artifact.sealed-source",
    )
    findings: list = []
    _validate_canonical_artifact_pointer(record, offset=0, findings=findings)
    assert findings == []


def test_canonical_pointer_code_is_registered_correctable() -> None:
    policy = get_policy("p2.canonical_pointer_invalid")
    assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    assert policy.deterministic_repair_allowed is True
    assert policy.blocks_publication is True


# ---------------------------------------------------------------------------
# Integration through validate_phase_scientific (P2)
# ---------------------------------------------------------------------------


def _evaluation() -> dict[str, Any]:
    axis = {"score": 7, "justification": "Solid.", "issue_refs": []}
    return {
        "theoretical_validity": dict(axis),
        "literature_positioning": dict(axis),
        "empirical_feasibility": dict(axis),
        "adjudicated_at": "2026-08-23T00:00:00+00:00",
        "review_basis_ids": ["report.p2.theory_review.example"],
    }


def _full_method_record(uri: str, **artifact_extra: Any) -> dict[str, Any]:
    record = _method_record(uri, **artifact_extra)
    record["identity"]["definition_sha256"] = "a" * 64
    record["assumptions"] = ["Independent observations."]
    record["literature_provenance"] = ["record.literature.001"]
    record["limitations"] = ["Distribution-specific."]
    record["lineage"] = {"change_class": "initial"}
    record["evaluation"] = _evaluation()
    return record


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


def _validate(documents: dict[str, Any]) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P2"),
        mode_id="p2.full_catalog",
        publication_bindings=(),
    )
    findings: list[ValidationFinding] = []
    validate_phase_scientific(
        plan=plan,  # type: ignore[arg-type]
        outputs={key: _output(key, value) for key, value in documents.items()},
        selected_method=None,
        findings=findings,
    )
    return findings


def test_p2_unstamped_canonical_pointer_is_flagged_end_to_end() -> None:
    findings = _validate(
        {"p2.method_changes": [_full_method_record("input://ab12sourcebytes")]}
    )
    assert _codes(findings).count("p2.canonical_pointer_invalid") == 1


def test_p2_stamped_canonical_pointer_produces_no_finding() -> None:
    digest = hashlib.sha256(b'{"proposal": "real"}').hexdigest()
    record = _full_method_record(
        f"artifact://sha256/{digest}",
        sha256=digest,
        artifact_id="artifact.sealed-source",
    )
    findings = _validate({"p2.method_changes": [record]})
    assert "p2.canonical_pointer_invalid" not in _codes(findings)


def test_golden_method_example_passes_canonical_pointer_validation() -> None:
    import json

    golden = json.loads(
        Path("tests/fixtures/golden/method.example.json").read_text()
    )
    findings: list = []
    _validate_canonical_artifact_pointer(golden, offset=0, findings=findings)
    assert findings == []
