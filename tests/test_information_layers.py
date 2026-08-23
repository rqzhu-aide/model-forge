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

from model_forge.domain.validation import FindingClass, get_policy
from model_forge.harness.role_execution import (
    _OutputPointerContext,
    _fix_self_referential_hashes,
)
from model_forge.harness.scientific_validators import _validate_compact_view_pointers


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


def test_validation_flags_other_layers_and_ignores_missing_representations() -> None:
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
    assert _codes(findings) == ["p1.primary_pointer_invalid"]
    findings.clear()
    _validate_compact_view_pointers({}, code_prefix="p1", object_id="o", findings=findings)
    _validate_compact_view_pointers(None, code_prefix="p1", object_id="o", findings=findings)
    assert findings == []


def test_validation_rejects_unstamped_primary_pointer() -> None:
    findings: list = []
    doc = {
        "representations": [
            {
                "information_layer": "primary_artifact",
                "artifact": {"uri": "output://synthesis-candidate.json"},
            }
        ]
    }
    _validate_compact_view_pointers(
        doc, code_prefix="p1", object_id="p1.synthesis_candidate", findings=findings,
    )
    assert _codes(findings) == ["p1.primary_pointer_invalid"]


def test_primary_pointer_codes_are_registered_correctable() -> None:
    for code in ("p1.primary_pointer_invalid", "p3.primary_pointer_invalid"):
        policy = get_policy(code)
        assert policy is not None
        assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
        assert policy.deterministic_repair_allowed is True


def test_compact_pointer_codes_are_registered_correctable() -> None:
    for code in ("p1.compact_view_pointer_invalid", "p3.compact_view_pointer_invalid"):
        policy = get_policy(code)
        assert policy is not None
        assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR


# ---------------------------------------------------------------------------
# E-2b: layer-aware materialization
# ---------------------------------------------------------------------------

def _service_with_store(tmp_path: Path):
    from model_forge.harness.role_execution import RoleLifecycleService
    from model_forge.storage import ArtifactStore
    from model_forge.storage.paths import WorkspacePaths

    service = object.__new__(RoleLifecycleService)
    service.artifacts = ArtifactStore(WorkspacePaths(tmp_path / "workspace", create=True))
    return service


def _frozen(tmp_path: Path, input_id: str, document: dict) -> SimpleNamespace:
    path = tmp_path / f"{input_id.replace('.', '-')}.json"
    path.write_text(json.dumps(document))
    return SimpleNamespace(path=path, input_id=input_id)


def _compact_record(markdown: str, sha: str) -> dict:
    return {
        "record_id": "rec.test",
        "representations": [
            {
                "information_layer": "compact_decision_view",
                "artifact": {
                    "artifact_id": "artifact.compact.test",
                    "uri": f"artifact://sha256/{sha}",
                    "sha256": sha,
                    "media_type": "application/json",
                },
            }
        ],
    }


def test_compact_view_is_materialized_with_markdown(tmp_path: Path) -> None:
    service = _service_with_store(tmp_path)
    envelope = json.dumps({"schema_version": "1.0.0", "title": "t", "summary_markdown": "READ ME FIRST."}).encode()
    stored = service.artifacts.put_bytes(envelope)
    role_root = tmp_path / "role"
    role_root.mkdir()
    record = _compact_record("unused", str(stored.sha256))
    inputs = {"p2.literature_synthesis": _frozen(tmp_path, "p2.literature_synthesis", record)}

    compact = service._materialize_compact_views(
        role_root=role_root,
        inputs=inputs,
        input_ids=["p2.literature_synthesis"],
        access_log_path=role_root / "access.jsonl",
    )

    assert compact == {"p2.literature_synthesis": "inputs/compact/p2.literature_synthesis.md"}
    assert (role_root / "inputs/compact/p2.literature_synthesis.md").read_text() == "READ ME FIRST."
    log_lines = (role_root / "access.jsonl").read_text().strip().splitlines()
    assert len(log_lines) == 1
    assert json.loads(log_lines[0])["sha256"] == str(stored.sha256)


def test_placeholder_or_missing_compact_is_skipped(tmp_path: Path) -> None:
    service = _service_with_store(tmp_path)
    role_root = tmp_path / "role"
    role_root.mkdir()
    fake = _compact_record("x", "1" * 64)
    real_but_absent = _compact_record("x", "ab" * 32)  # well-formed, not in store
    plain = {"record_id": "rec.plain"}
    inputs = {
        "a": _frozen(tmp_path, "a", fake),
        "b": _frozen(tmp_path, "b", real_but_absent),
        "c": _frozen(tmp_path, "c", plain),
    }
    compact = service._materialize_compact_views(
        role_root=role_root,
        inputs=inputs,
        input_ids=["a", "b", "c"],
        access_log_path=role_root / "access.jsonl",
    )
    assert compact == {}
    assert not (role_root / "inputs").exists()


def test_brief_names_compact_view_and_reading_order(tmp_path: Path) -> None:
    from model_forge.harness.task_briefs import render_task_brief

    plan = SimpleNamespace(identity=SimpleNamespace(phase_id="P2"), mode_id="p2.full_catalog", choice_values={})
    step = SimpleNamespace(input_ids=("p2.literature_synthesis",))
    stage = SimpleNamespace(
        stage_id="p2.independent_proposals",
        objective="Propose.",
        execution="parallel",
        roles=("theorist",),
        step_for=lambda role: step,
    )
    output_plan = SimpleNamespace(for_stage_role=lambda stage_id, role: ())
    text = render_task_brief(
        run_id="run.test",
        project_id="project.test",
        plan=plan,
        stage=stage,
        role="theorist",
        input_paths={"p2.literature_synthesis": "/tmp/full.json"},
        output_plan=output_plan,
        phase_instruction="Do the phase.",
        compact_views={"p2.literature_synthesis": "inputs/compact/p2.literature_synthesis.md"},
    )
    assert "(compact decision view: `inputs/compact/p2.literature_synthesis.md`)" in text
    assert "read the compact view FIRST" in text


# ---------------------------------------------------------------------------
# E-2d: primary self-pointer stamping and as-authored sealing
# ---------------------------------------------------------------------------

def test_primary_self_pointer_is_stamped_sidecarred_and_sealed(tmp_path: Path) -> None:
    """A record's output:// self-pointer to its own primary layer resolves.

    The repair pass stamps the pointer with the digest of the exact
    as-authored bytes, preserves those bytes in a ``.as-authored``
    sidecar, and sealing stores the sidecar so the stamped pointer
    resolves to hash-verified artifact-store bytes.
    """
    filename = "synthesis-candidate.json"
    record = {
        "record_id": "rec.test",
        "primary_artifact": {
            "uri": f"output://{filename}",
            "media_type": "application/json",
        },
        "representations": [
            {
                "information_layer": "primary_artifact",
                "artifact": {
                    "uri": f"output://{filename}",
                    "media_type": "application/json",
                },
            }
        ],
    }
    authored = json.dumps(record, sort_keys=True).encode()
    context = _context(tmp_path, {filename: authored.decode()})
    path = tmp_path / filename

    changed = _fix_self_referential_hashes(record, path, pointer_context=context)

    assert changed is True
    digest = hashlib.sha256(authored).hexdigest()
    sidecar = tmp_path / f"{filename}.as-authored"
    assert sidecar.read_bytes() == authored
    stamped = record["representations"][0]["artifact"]
    assert stamped["sha256"] == digest
    assert stamped["uri"] == f"artifact://sha256/{digest}"
    # The top-level primary_artifact dict is stamped identically.
    assert record["primary_artifact"] == {
        "uri": stamped["uri"],
        "media_type": "application/json",
        "sha256": digest,
        "artifact_id": stamped["artifact_id"],
    }

    service = _service_with_store(tmp_path)
    service.context = SimpleNamespace(project_id="project.test", run_id="run.test")
    recorded: list[tuple] = []
    service.repository = SimpleNamespace(
        record_artifact=lambda *args: recorded.append(args)
    )
    spec = SimpleNamespace(
        contract_output_id="p1.synthesis_candidate",
        output_id="output.p1.synthesis_candidate",
    )
    service._seal_authored_snapshot(spec, path)

    stored = service.artifacts.read_bytes(digest)
    assert stored == authored
    assert hashlib.sha256(stored).hexdigest() == stamped["sha256"]
    assert recorded and recorded[0][0] == stamped["artifact_id"]


def test_seal_authored_snapshot_is_idempotent_without_sidecar(tmp_path: Path) -> None:
    service = _service_with_store(tmp_path)
    service.context = SimpleNamespace(project_id="project.test", run_id="run.test")
    service.repository = SimpleNamespace(
        record_artifact=lambda *args: (_ for _ in ()).throw(AssertionError("no row"))
    )
    spec = SimpleNamespace(
        contract_output_id="p1.synthesis_candidate",
        output_id="output.p1.synthesis_candidate",
    )
    path = tmp_path / "synthesis-candidate.json"
    path.write_text("{}")
    service._seal_authored_snapshot(spec, path)  # no sidecar: no-op
