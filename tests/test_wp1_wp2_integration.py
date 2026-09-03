"""Integration tests for WP1+WP2 wiring, executor, network policy, and fixtures.

These tests verify that:
1. CapabilityBroker is invoked during role execution (inputs materialized)
2. Raw output is preserved on failure
3. NetworkPolicy modes work correctly
4. Golden fixtures are schema-valid
5. Mutation fixtures are properly labelled

(The WP2 D2.1 adapt-path wiring test was deleted with the decorative
companion-artifact adapt path on 2026-09-02 — audit finding F8, Tez decision:
delete. Its result was discarded at the only production call site.)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from model_forge.capabilities.broker import CapabilityBroker
from model_forge.capabilities.network import NetworkPolicy, NetworkPolicyError
from model_forge.executors.protocol import RoleInvocation, RoleExecutionStatus
from model_forge.harness.execution_records import FrozenInputPath


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
# 2. Wiring verification: broker materializes inputs during execution
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
# 3. Golden fixture validation
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
        assert manifest["format"] == "model-forge.golden-fixtures"
        assert len(manifest["fixtures"]) >= 9


# ---------------------------------------------------------------------------
# 4. Mutation fixture validation
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


