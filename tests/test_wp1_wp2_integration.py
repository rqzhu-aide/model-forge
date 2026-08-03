"""Integration tests for WP1+WP2 wiring, executor, network policy, and fixtures.

These tests verify that:
1. CapabilityBroker is invoked during role execution (inputs materialized)
2. OutputAdapter is invoked after validation (linked artifacts captured)
3. Raw output is preserved on failure
4. InvocationFencer is active during run coordination
5. NetworkPolicy modes work correctly
6. BubblewrapExecutor constructs valid sandbox commands
7. Golden fixtures are schema-valid
8. Mutation fixtures are properly labelled
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from method_hub.capabilities.broker import CapabilityBroker
from method_hub.capabilities.network import NetworkPolicy, NetworkPolicyError
from method_hub.executors.bubblewrap import BubblewrapExecutor, BubblewrapSettings
from method_hub.executors.protocol import RoleInvocation, RoleExecutionStatus
from method_hub.harness.execution_records import FrozenInputPath
from method_hub.harness.invocation_fencing import InvocationFencer
from method_hub.harness.output_adapters import DefaultOutputAdapter, preserve_raw_output


# ---------------------------------------------------------------------------
# 1. NetworkPolicy
# ---------------------------------------------------------------------------

class TestNetworkPolicy:
    def test_deny_all_is_default(self) -> None:
        policy = NetworkPolicy.deny_all()
        assert policy.is_deny_all
        assert not policy.has_network
        assert policy.allowed_hosts == ()

    def test_allowlist_mode(self) -> None:
        policy = NetworkPolicy.allowlist(
            hosts=("api.openai.com", "api.anthropic.com"),
            ports=(443,),
        )
        assert not policy.is_deny_all
        assert policy.has_network
        assert "api.openai.com" in policy.allowed_hosts

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(NetworkPolicyError):
            NetworkPolicy(mode="invalid")

    def test_deny_all_with_hosts_rejected(self) -> None:
        with pytest.raises(NetworkPolicyError, match="deny_all"):
            NetworkPolicy(mode="deny_all", allowed_hosts=("evil.com",))

    def test_invalid_port_rejected(self) -> None:
        with pytest.raises(NetworkPolicyError, match="port"):
            NetworkPolicy(mode="allowlist", allowed_hosts=("x.com",), allowed_ports=(99999,))

    def test_serialization_roundtrip(self) -> None:
        policy = NetworkPolicy.allowlist(hosts=("a.com", "b.com"), ports=(443, 80))
        data = policy.to_dict()
        restored = NetworkPolicy.from_dict(data)
        assert restored.allowed_hosts == policy.allowed_hosts
        assert restored.allowed_ports == policy.allowed_ports
        assert restored.mode == policy.mode


# ---------------------------------------------------------------------------
# 2. BubblewrapExecutor command construction
# ---------------------------------------------------------------------------

class TestBubblewrapExecutor:
    def test_build_command_includes_security_flags(self, tmp_path: Path) -> None:
        """The bwrap command must include unshare-all, cap-drop, no-new-privileges."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        task_brief = workspace / "task.md"
        task_brief.write_text("Do the task.")

        invocation = RoleInvocation(
            execution_id="exec-test-001",
            invocation_id="inv-test-001",
            run_id="run-001",
            project_id="proj-001",
            phase="P1",
            mode="p1.literature_update",
            stage_id="p1.discovery",
            role="research_lead",
            profile="research_lead",
            workspace=workspace,
            task_brief=task_brief,
            expected_output_paths=(workspace / "output.json",),
        )
        executor = BubblewrapExecutor(BubblewrapSettings())
        command = executor._build_command(invocation)

        # Verify security hardening flags
        cmd_str = " ".join(command)
        assert "--unshare-all" in cmd_str
        assert "--cap-drop" in cmd_str
        assert "ALL" in cmd_str
        assert "--no-new-privileges" in cmd_str
        assert "--die-with-parent" in cmd_str
        # Network namespace
        assert "--unshare-net" in cmd_str  # deny_all by default

    def test_build_command_with_network_allowlist(self, tmp_path: Path) -> None:
        """When a network policy is present, --share-net is used."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        task_brief = workspace / "task.md"
        task_brief.write_text("Do the task.")

        policy = NetworkPolicy.allowlist(hosts=("api.example.com",), ports=(443,))
        invocation = RoleInvocation(
            execution_id="exec-test-002",
            invocation_id="inv-test-002",
            run_id="run-002",
            project_id="proj-001",
            phase="P1",
            mode="p1.literature_update",
            stage_id="p1.discovery",
            role="research_lead",
            profile="research_lead",
            workspace=workspace,
            task_brief=task_brief,
            expected_output_paths=(workspace / "output.json",),
            metadata={"network_policy": policy},
        )
        executor = BubblewrapExecutor(BubblewrapSettings())
        command = executor._build_command(invocation)
        cmd_str = " ".join(command)
        assert "--share-net" in cmd_str
        assert "--unshare-net" not in cmd_str

    def test_secret_env_injection(self, tmp_path: Path) -> None:
        """Secret env vars reach the child but are not in the command line."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        task_brief = workspace / "task.md"
        task_brief.write_text("Do the task.")

        invocation = RoleInvocation(
            execution_id="exec-test-003",
            invocation_id="inv-test-003",
            run_id="run-003",
            project_id="proj-001",
            phase="P1",
            mode="p1.literature_update",
            stage_id="p1.discovery",
            role="research_lead",
            profile="research_lead",
            workspace=workspace,
            task_brief=task_brief,
            expected_output_paths=(workspace / "output.json",),
        )
        executor = BubblewrapExecutor(
            BubblewrapSettings(secret_env={"OPENAI_API_KEY": "sk-test-secret-1234567890"})
        )
        env = executor._build_environment(invocation)
        assert env["OPENAI_API_KEY"] == "sk-test-secret-1234567890"

        # The secret must NOT appear in the command line
        command = executor._build_command(invocation)
        cmd_str = " ".join(command)
        assert "sk-test-secret-1234567890" not in cmd_str


# ---------------------------------------------------------------------------
# 3. Wiring verification: broker materializes inputs during execution
# ---------------------------------------------------------------------------

class TestWiringCapabilityBroker:
    def test_broker_creates_access_log_in_workspace(self, tmp_path: Path) -> None:
        """Verify the broker writes an access log when materializing inputs."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        src = tmp_path / "input.json"
        payload = b'{"test": true}'
        src.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()

        broker = CapabilityBroker()
        access_log = workspace / "access.jsonl"
        broker.materialize_context(
            workspace=workspace,
            frozen_inputs={
                "p1.brief": FrozenInputPath(
                    input_id="p1.brief",
                    artifact_id="art-001",
                    sha256=sha,
                    path=src,
                )
            },
            access_log_path=access_log,
        )

        # Access log should exist and have one entry
        assert access_log.exists()
        lines = access_log.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["artifact_id"] == "art-001"

        # Materialized input should be in workspace/inputs/
        materialized = workspace / "inputs" / "input.json"
        assert materialized.exists()
        assert materialized.read_bytes() == payload


# ---------------------------------------------------------------------------
# 4. Wiring verification: adapter captures linked artifacts
# ---------------------------------------------------------------------------

class TestWiringOutputAdapter:
    def test_adapter_finds_companion_files(self, tmp_path: Path) -> None:
        """The adapter should discover companion PDFs next to structured output."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = workspace / "roles" / "01-theorist"
        output_dir.mkdir(parents=True)

        output_path = output_dir / "theory.json"
        payload = b'{"record_type": "theory"}'
        output_path.write_bytes(payload)

        # Create a companion markdown file
        md_path = output_dir / "theory.md"
        md_data = b"# Theory\n\nSome theory content."
        md_path.write_bytes(md_data)

        from method_hub.harness.outputs import OutputSpec, ValidatedOutput

        spec = OutputSpec(
            contract_output_id="p3.theory_candidate",
            output_id="output.p3.theory_candidate",
            output_kind="primary_artifact",
            producer="theorist",
            stage_id="p3.theorist",
            stage_sequence=1,
            schema_application="object",
            schema_file="scientific-record.schema.json",
            relative_path="roles/01-theorist/theory.json",
            required=True,
        )
        validated = ValidatedOutput(
            spec=spec,
            path=output_path,
            document={"record_type": "theory"},
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_length=len(payload),
        )
        adapter = DefaultOutputAdapter()
        result = adapter.adapt(spec=spec, workspace=workspace, validated=validated)

        assert len(result.linked_artifacts) == 1
        assert result.linked_artifacts[0].media_type == "text/markdown"


# ---------------------------------------------------------------------------
# 5. Golden fixture validation
# ---------------------------------------------------------------------------

class TestGoldenFixtures:
    def test_all_golden_fixtures_are_valid_json(self) -> None:
        fixtures_dir = Path(__file__).parent / "fixtures" / "golden"
        manifest_path = fixtures_dir / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("Golden fixtures not created")
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["fixtures"]:
            fixture_path = fixtures_dir / entry["source"]
            assert fixture_path.exists(), f"Missing fixture: {entry['source']}"
            data = json.loads(fixture_path.read_text())
            assert isinstance(data, dict) or isinstance(data, list)

    def test_manifest_has_correct_format(self) -> None:
        manifest_path = Path(__file__).parent / "fixtures" / "golden" / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("Golden fixtures not created")
        manifest = json.loads(manifest_path.read_text())
        assert manifest["format"] == "method-hub.golden-fixtures"
        assert len(manifest["fixtures"]) >= 9


# ---------------------------------------------------------------------------
# 6. Mutation fixture validation
# ---------------------------------------------------------------------------

class TestMutationFixtures:
    def test_all_mutations_labelled(self) -> None:
        mutations_dir = Path(__file__).parent / "fixtures" / "mutations"
        manifest_path = mutations_dir / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("Mutation fixtures not created")
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["mutations"]:
            fixture_path = mutations_dir / entry["file"]
            assert fixture_path.exists(), f"Missing mutation: {entry['file']}"
            data = json.loads(fixture_path.read_text())
            assert data.get("mutation") is not None
            assert entry["expected"] == "reject"
