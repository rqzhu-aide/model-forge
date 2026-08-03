from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from method_hub.domain.identities import PhaseContractIdentity
from method_hub.domain.runs import RunRequest
from method_hub.harness.commands import build_run_command
from method_hub.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_build_run_command_is_schema_valid_and_digest_bound() -> None:
    package = SpecificationPackage.load(ARCHITECTURE)
    identity = package.phases.identity("P1")
    request = RunRequest(
        project_id="project.demo",
        phase_contract=PhaseContractIdentity(
            identity.phase_id,
            identity.contract_version,
            identity.phase_contract_sha256,
        ),
        mode="p1.literature_update",
        choice_values={
            "p1.scope": "broad_update",
            "p1.instructions": "Update the literature basis.",
            "p1.selected_history": [],
        },
        context_policy="current_only",
        user_id="researcher.demo",
        idempotency_key="request-command-builder-001",
    )
    command = build_run_command(
        request,
        package,
        requested_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        command_id="command.p1.demo.001",
    )
    package.schemas.require_valid("run-command.schema.json", command)
    assert package.digests.require_match("run_command.content", command) == command[
        "content_sha256"
    ]
    assert command["choice_values"]["p1.scope"] == "broad_update"
