"""Regression tests for the P-I hardening package (Lane A: R18, R19, R24,
R25, R29, R30, R31).

Pins: architecture/plan/harness-audit-2026-08-31-pi-pins.md.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_forge.harness import role_execution
from model_forge.harness.output_adapters import (
    DefaultOutputAdapter,
    preserve_raw_output,
)
from model_forge.harness.outputs import (
    OutputPlan,
    OutputSpec,
    ValidatedOutput,
    validate_role_outputs,
)
from model_forge.harness.scientific_validators import _has_cycle


# ---------------------------------------------------------------------------
# R18: pre-resolve symlink check (outputs.py)
# ---------------------------------------------------------------------------

def test_symlinked_output_is_not_regular_file(tmp_path: Path) -> None:
    spec = OutputSpec(
        contract_output_id="p1.probe_output",
        output_id="output.p1.probe_output",
        output_kind="scientific_record",
        producer="research_lead",
        stage_id="stage-1",
        stage_sequence=1,
        schema_application="object",
        schema_file="probe.schema.json",
        relative_path="roles/01-research_lead/probe-output.json",
        required=True,
        record_type="",
    )
    plan = OutputPlan((spec,))
    stage = SimpleNamespace(stage_id=spec.stage_id)

    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "roles" / "01-research_lead" / "probe-output.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    catalog = SimpleNamespace(validate=lambda *args, **kwargs: [])
    result = validate_role_outputs(
        schema_catalog=catalog,
        run_root=tmp_path,
        output_plan=plan,
        stage=stage,
        role=spec.producer,
    )

    assert result.outputs == ()
    assert len(result.findings) == 1
    assert result.findings[0].code == "output.not_regular_file"


# ---------------------------------------------------------------------------
# R19: input:// basename/containment check (role_execution.py)
# ---------------------------------------------------------------------------

def test_canonical_input_pointer_rejects_traversal(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"top secret bytes")

    method_record = {
        "mathematical_definition": {
            "canonical_artifact": {"uri": "input://../secret.txt"},
        },
    }
    changed = role_execution._stamp_canonical_artifact(
        method_record,
        inputs_dir=inputs_dir,
        lookup=None,
        project_id="p",
        run_id="r",
    )
    assert changed is False
    artifact = method_record["mathematical_definition"]["canonical_artifact"]
    assert artifact["uri"] == "input://../secret.txt"
    assert "sha256" not in artifact

    # Positive control: a real in-sandbox input stamps normally.
    real = inputs_dir / "real.bin"
    payload = b"real input bytes"
    real.write_bytes(payload)
    ok_record = {
        "mathematical_definition": {
            "canonical_artifact": {"uri": "input://real.bin"},
        },
    }
    changed = role_execution._stamp_canonical_artifact(
        ok_record,
        inputs_dir=inputs_dir,
        lookup=None,
        project_id="p",
        run_id="r",
    )
    assert changed is True
    digest = hashlib.sha256(payload).hexdigest()
    stamped = ok_record["mathematical_definition"]["canonical_artifact"]
    assert stamped["uri"] == f"artifact://sha256/{digest}"
    assert stamped["sha256"] == digest


# ---------------------------------------------------------------------------
# R24: compact-view fallback skips summary-less JSON envelopes
# ---------------------------------------------------------------------------

def test_compact_view_skips_summary_less_envelope(tmp_path: Path) -> None:
    # Note: the pin's literal "a"*64 sha256 is skipped by the live
    # placeholder guard (len(set(sha256)) == 1) before read_bytes, so real
    # digests are used to exercise the R24 fallback path.
    bare_bytes = json.dumps({"format": "x"}).encode("utf-8")
    summary_bytes = json.dumps(
        {"format": "x", "summary_markdown": "# compact summary"}
    ).encode("utf-8")
    bare_sha = hashlib.sha256(bare_bytes).hexdigest()
    summary_sha = hashlib.sha256(summary_bytes).hexdigest()
    envelopes = {bare_sha: bare_bytes, summary_sha: summary_bytes}
    artifacts = SimpleNamespace(read_bytes=lambda sha256: envelopes[sha256])

    service = role_execution.RoleLifecycleService.__new__(
        role_execution.RoleLifecycleService
    )
    service.artifacts = artifacts

    def _record(path: Path, sha256: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "representations": [
                        {
                            "information_layer": "compact_decision_view",
                            "artifact": {
                                "sha256": sha256,
                                "uri": "artifact://sha256/" + sha256,
                                "artifact_id": "art",
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    bare_record = tmp_path / "bare.json"
    _record(bare_record, bare_sha)
    summary_record = tmp_path / "summary.json"
    _record(summary_record, summary_sha)

    role_root = tmp_path / "role"
    inputs = {
        "bare": SimpleNamespace(path=str(bare_record)),
        "good": SimpleNamespace(path=str(summary_record)),
    }
    compact = service._materialize_compact_views(
        role_root=role_root,
        inputs=inputs,
        input_ids=["bare", "good"],
        access_log_path=tmp_path / "access.jsonl",
    )

    assert "bare" not in compact
    assert not (role_root / "inputs" / "compact" / "bare.md").exists()
    # Positive control: an envelope carrying summary_markdown materializes.
    assert compact["good"] == "inputs/compact/good.md"
    assert (role_root / "inputs" / "compact" / "good.md").read_text(
        encoding="utf-8"
    ) == "# compact summary"


# ---------------------------------------------------------------------------
# R25: cache only successful parses in _STABLEID_POSITIONS_CACHE
# ---------------------------------------------------------------------------

def test_stableid_positions_cache_stores_successes_only() -> None:
    name = "zz-r25-probe.schema.json"
    schemas_dir = (
        Path(role_execution.__file__).resolve().parents[3]
        / "architecture"
        / "schemas"
    )
    probe = schemas_dir / name
    try:
        role_execution._STABLEID_POSITIONS_CACHE.pop(name, None)
        assert not probe.exists()
        missing = role_execution._stableid_positions(name)
        assert missing["heuristic"] is True

        probe.write_text(
            json.dumps(
                {
                    "$defs": {"stableId": {"type": "string"}},
                    "type": "object",
                    "properties": {"probe_id": {"$ref": "#/$defs/stableId"}},
                }
            ),
            encoding="utf-8",
        )
        # No cache pop: the transient failure must not have been cached.
        parsed = role_execution._stableid_positions(name)
        assert parsed["heuristic"] is False
        assert "probe_id" in parsed["scalar_keys"]
    finally:
        probe.unlink(missing_ok=True)
        role_execution._STABLEID_POSITIONS_CACHE.pop(name, None)


# ---------------------------------------------------------------------------
# R29: iterative DFS in _has_cycle
# ---------------------------------------------------------------------------

def test_has_cycle_deep_chain_iterative() -> None:
    graph = {str(i): {str(i + 1)} for i in range(4999)}
    graph[str(4999)] = set()
    assert _has_cycle(graph) is False


def test_has_cycle_deep_cycle_detected() -> None:
    graph = {str(i): {str(i + 1)} for i in range(4999)}
    graph[str(4999)] = {"0"}
    assert _has_cycle(graph) is True


# ---------------------------------------------------------------------------
# R30: hasattr feature-check for put_bytes
# ---------------------------------------------------------------------------

def test_preserve_raw_output_propagates_put_bytes_failures(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("x", encoding="utf-8")

    def put_bytes(data: bytes):
        raise AttributeError("genuine bug")

    artifacts = SimpleNamespace(put_bytes=put_bytes)
    with pytest.raises(AttributeError, match="genuine bug"):
        preserve_raw_output(workspace, "run", "role", artifacts)


def test_preserve_raw_output_fallback_when_put_bytes_missing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("x", encoding="utf-8")

    store_root = tmp_path / "store"
    artifacts = SimpleNamespace(_paths=SimpleNamespace(root=store_root))
    sha256 = preserve_raw_output(workspace, "run", "role", artifacts)

    tarball = (
        store_root
        / "raw-outputs"
        / sha256[:2]
        / sha256[2:4]
        / f"{sha256}.tar.gz"
    )
    assert tarball.is_file()
    assert hashlib.sha256(tarball.read_bytes()).hexdigest() == sha256


# ---------------------------------------------------------------------------
# R31: companion-scan relative_to guard + stale-leftover skip
# ---------------------------------------------------------------------------

def _adapter_fixture(output_dir: Path, stem: str = "theory") -> tuple:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}.json"
    payload = b'{"record_type": "theory_record"}'
    output_path.write_bytes(payload)
    spec = OutputSpec(
        contract_output_id="p3.theory_candidate",
        output_id="output.p3.theory_candidate",
        output_kind="primary_artifact",
        producer="theorist",
        stage_id="stage-1",
        stage_sequence=1,
        schema_application="object",
        schema_file="scientific-record.schema.json",
        relative_path=f"roles/01-theorist/{stem}.json",
        required=True,
    )
    validated = ValidatedOutput(
        spec=spec,
        path=output_path,
        document={"record_type": "theory_record"},
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
    )
    return spec, validated


def test_companion_scan_skips_outside_workspace(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    spec, validated = _adapter_fixture(elsewhere)
    (elsewhere / "theory.md").write_text("# notes", encoding="utf-8")

    workspace = tmp_path / "unrelated"
    workspace.mkdir()

    adapter = DefaultOutputAdapter()
    result = adapter.adapt(spec=spec, workspace=workspace, validated=validated)
    assert result.linked_artifacts == ()


def test_companion_scan_skips_stale_leftovers(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "roles" / "01-theorist"
    spec, validated = _adapter_fixture(output_dir)

    stale = output_dir / "theory.md"
    stale.write_text("stale", encoding="utf-8")
    fresh = output_dir / "theory.txt"
    fresh.write_text("fresh", encoding="utf-8")

    output_mtime = validated.path.stat().st_mtime
    os.utime(stale, (output_mtime - 100, output_mtime - 100))
    os.utime(fresh, (output_mtime, output_mtime))

    adapter = DefaultOutputAdapter()
    result = adapter.adapt(spec=spec, workspace=workspace, validated=validated)

    assert len(result.linked_artifacts) == 1
    linked = result.linked_artifacts[0]
    assert linked.source_path == "roles/01-theorist/theory.txt"
    assert linked.media_type == "text/plain"
