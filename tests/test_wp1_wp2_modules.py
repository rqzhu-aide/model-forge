"""Tests for WP1 D1.2 CapabilityBroker, D1.4 InvocationFencing,
WP2 D2.1 OutputAdapter, and D2.2 scientific validators."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from method_hub.capabilities.broker import CapabilityBroker, CapabilityBrokerError
from method_hub.harness.execution_records import FrozenInputPath
from method_hub.harness.invocation_fencing import (
    FencingError,
    FencingToken,
    InvocationFencer,
)
from method_hub.harness.output_adapters import (
    AdaptedOutput,
    DefaultOutputAdapter,
    LinkedArtifact,
    preserve_raw_output,
)
from method_hub.harness.outputs import OutputSpec, ValidatedOutput
from method_hub.harness.scientific_validators import validate_phase_scientific
from method_hub.domain.validation import ValidationFinding, ValidationSeverity
from method_hub.harness.publication import RegisteredValidatedOutput, RegisteredArtifactMetadata


# ---------------------------------------------------------------------------
# CapabilityBroker
# ---------------------------------------------------------------------------

class TestCapabilityBroker:
    def test_materializes_frozen_inputs(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        inputs_dir = workspace / "inputs"

        # Create a source file with known content
        src = tmp_path / "source.json"
        payload = b'{"test": true}'
        src.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()

        frozen = FrozenInputPath(
            input_id="p1.brief",
            artifact_id="art-001",
            sha256=sha,
            path=src,
        )
        broker = CapabilityBroker()
        access_log = workspace / "access.log"
        result = broker.materialize_context(
            workspace=workspace,
            frozen_inputs={"p1.brief": frozen},
            access_log_path=access_log,
        )
        assert "p1.brief" in result
        dest = result["p1.brief"]
        assert dest.parent == inputs_dir.resolve() or dest.parent == inputs_dir
        assert dest.read_bytes() == payload

        # Access log should have one entry
        lines = access_log.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["artifact_id"] == "art-001"
        assert entry["sha256"] == sha

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        inputs_dir = workspace / "inputs"
        inputs_dir.mkdir()

        # Create a source file
        src = tmp_path / "evil.json"
        src.write_bytes(b"{}")
        sha = hashlib.sha256(b"{}").hexdigest()

        frozen = FrozenInputPath(
            input_id="evil",
            artifact_id="art-evil",
            sha256=sha,
            path=Path("../escape.json"),  # name that would escape
        )
        broker = CapabilityBroker()
        with pytest.raises(CapabilityBrokerError, match="escape|unsafe|symlink"):
            broker.materialize_context(
                workspace=workspace,
                frozen_inputs={"evil": frozen},
            )

    def test_rejects_digest_mismatch(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        src = tmp_path / "bad.json"
        src.write_bytes(b'{"data": "wrong"}')

        frozen = FrozenInputPath(
            input_id="bad",
            artifact_id="art-bad",
            sha256="0" * 64,  # wrong digest
            path=src,
        )
        broker = CapabilityBroker()
        with pytest.raises(CapabilityBrokerError, match="Digest mismatch"):
            broker.materialize_context(
                workspace=workspace,
                frozen_inputs={"bad": frozen},
            )


# ---------------------------------------------------------------------------
# InvocationFencer
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, closure_exists: bool = False) -> None:
        self._closure_exists = closure_exists

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=()):
        return type("R", (), {"fetchone": lambda s: {"1": 1} if self._closure_exists else None})()


class _FakeDB:
    def __init__(self):
        self.closure_exists = False

    def connect(self):
        return _FakeConn(closure_exists=self.closure_exists)


class _FakeRepo:
    def __init__(self):
        self._database = _FakeDB()


class TestInvocationFencer:
    def test_fence_prevents_stale_advance(self) -> None:
        fencer = InvocationFencer(_FakeRepo())  # type: ignore
        token0 = fencer.current_token("exec-001")
        assert token0.token == 0

        token1 = fencer.advance("exec-001", token0)
        assert token1.token == 1

        # Stale token (token0) cannot advance
        with pytest.raises(FencingError, match="Stale"):
            fencer.advance("exec-001", token0)

    def test_lease_acquire_and_takeover(self) -> None:
        fencer = InvocationFencer(_FakeRepo(), lease_ttl_seconds=10)  # type: ignore
        lease = fencer.acquire_lease("exec-002", "coordinator-A")
        assert lease.holder == "coordinator-A"

        # Same holder can re-acquire
        lease2 = fencer.acquire_lease("exec-002", "coordinator-A")
        assert lease2.holder == "coordinator-A"

        # Different holder cannot acquire while lease is active
        with pytest.raises(FencingError, match="held by"):
            fencer.acquire_lease("exec-002", "coordinator-B")

        # Release and then another can acquire
        fencer.release_lease("exec-002")
        lease3 = fencer.acquire_lease("exec-002", "coordinator-B")
        assert lease3.holder == "coordinator-B"

    def test_advance_rejects_terminal(self) -> None:
        repo = _FakeRepo()
        fencer = InvocationFencer(repo)  # type: ignore
        token = fencer.current_token("exec-003")

        # Simulate closure existing
        repo._database.closure_exists = True
        assert fencer.is_terminal("exec-003") is True

        with pytest.raises(FencingError, match="terminal"):
            fencer.advance("exec-003", token)


# ---------------------------------------------------------------------------
# OutputAdapter
# ---------------------------------------------------------------------------

class TestOutputAdapter:
    def test_extracts_structured_output(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = workspace / "roles" / "01-research_lead"
        output_dir.mkdir(parents=True)

        output_path = output_dir / "source-changes.json"
        payload = b'[{"source_id": "s1"}]'
        output_path.write_bytes(payload)

        spec = OutputSpec(
            contract_output_id="p1.source_changes",
            output_id="output.p1.source_changes",
            output_kind="scientific_record",
            producer="research_lead",
            stage_id="stage-1",
            stage_sequence=1,
            schema_application="each_item",
            schema_file="literature-source.schema.json",
            relative_path="roles/01-research_lead/source-changes.json",
            required=True,
        )
        validated = ValidatedOutput(
            spec=spec,
            path=output_path,
            document=[{"source_id": "s1"}],
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
        )
        adapter = DefaultOutputAdapter()
        result = adapter.adapt(spec=spec, workspace=workspace, validated=validated)

        assert result.contract_output_id == "p1.source_changes"
        assert result.document == [{"source_id": "s1"}]
        assert result.sha256 == hashlib.sha256(payload).hexdigest()

    def test_binds_linked_artifacts(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = workspace / "roles" / "01-theorist"
        output_dir.mkdir(parents=True)

        output_path = output_dir / "theory.json"
        payload = b'{"record_type": "theory_record"}'
        output_path.write_bytes(payload)

        # Create a companion PDF
        pdf_path = output_dir / "theory.pdf"
        pdf_data = b"%PDF-1.4 fake pdf"
        pdf_path.write_bytes(pdf_data)

        spec = OutputSpec(
            contract_output_id="p3.theory_candidate",
            output_id="output.p3.theory_candidate",
            output_kind="primary_artifact",
            producer="theorist",
            stage_id="stage-1",
            stage_sequence=1,
            schema_application="object",
            schema_file="scientific-record.schema.json",
            relative_path="roles/01-theorist/theory.json",
            required=True,
        )
        validated = ValidatedOutput(
            spec=spec,
            path=output_path,
            document={"record_type": "theory_record"},
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
        )
        adapter = DefaultOutputAdapter()
        result = adapter.adapt(spec=spec, workspace=workspace, validated=validated)

        assert len(result.linked_artifacts) == 1
        linked = result.linked_artifacts[0]
        assert linked.media_type == "application/pdf"
        assert linked.sha256 == hashlib.sha256(pdf_data).hexdigest()
        assert linked.byte_length == len(pdf_data)


# ---------------------------------------------------------------------------
# Scientific validators
# ---------------------------------------------------------------------------

class TestScientificValidators:
    def _make_output(self, document: object) -> RegisteredValidatedOutput:
        return RegisteredValidatedOutput(
            contract_output_id="test",
            document=document,
            artifact=RegisteredArtifactMetadata(
                artifact_id="art",
                sha256="0" * 64,
                byte_length=0,
                media_type="application/json",
                storage_uri="mem://art",
            ),
        )

    def test_p4_four_slot_atomic_update_rejects_partial(self) -> None:
        class FakePlan:
            class identity:
                phase_id = "P4"
            mode_id = "p4.preliminary"
            publication_bindings: list = []

        outputs = {
            "p4.empirical_index_candidate": self._make_output({}),
            # Missing: synthesis, implementation, decision
        }
        findings: list[ValidationFinding] = []
        validate_phase_scientific(
            plan=FakePlan(),  # type: ignore
            outputs=outputs,
            selected_method=None,
            findings=findings,
        )
        codes = [f.code for f in findings]
        assert "p4.incomplete_four_slot_update" in codes

    def test_p5_manuscript_missing_rejected(self) -> None:
        class FakePlan:
            class identity:
                phase_id = "P5"
            mode_id = "p5.assembly"
            publication_bindings: list = []

        findings: list[ValidationFinding] = []
        validate_phase_scientific(
            plan=FakePlan(),  # type: ignore
            outputs={},
            selected_method=None,
            findings=findings,
        )
        codes = [f.code for f in findings]
        assert "p5.manuscript_missing" in codes

    def test_p5_claim_without_evidence_rejected(self) -> None:
        class FakePlan:
            class identity:
                phase_id = "P5"
            mode_id = "p5.assembly"
            publication_bindings: list = []

        manuscript = self._make_output({
            "basis": {"upstream_generations": ["gen-1"]},
        })
        claims = self._make_output([
            {"statement_type": "theorem", "supporting_evidence_ids": []},
        ])
        outputs = {
            "p5.manuscript_candidate": manuscript,
            "p5.claim_traceability": claims,
        }
        findings: list[ValidationFinding] = []
        validate_phase_scientific(
            plan=FakePlan(),  # type: ignore
            outputs=outputs,
            selected_method=None,
            findings=findings,
        )
        codes = [f.code for f in findings]
        assert "p5.claim_without_evidence" in codes
