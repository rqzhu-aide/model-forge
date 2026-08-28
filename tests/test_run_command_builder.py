from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from model_forge.domain.identities import PhaseContractIdentity
from model_forge.domain.runs import RunRequest
from model_forge.harness.commands import build_run_command
from model_forge.specification import SpecificationPackage


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


def test_seeded_run_command_seals_and_validates() -> None:
    """SD-1: a run command carrying seed_inputs seals with the seeds inside
    the content digest, and validates against the extended schema."""
    package = SpecificationPackage.load(ARCHITECTURE)
    request = RunRequest(
        project_id="project.demo",
        phase_contract=package.phases.identity("P1"),
        mode="p1.literature_update",
        choice_values={
            "p1.scope": "broad_update",
            "p1.instructions": "Update the literature basis.",
            "p1.selected_history": [],
        },
        context_policy="current_only",
        user_id="researcher.demo",
        idempotency_key="request-command-builder-seed-001",
        seed_inputs={
            "p1.literature_library": {
                "content": "# Seeded library\n",
                "media_type": "text/markdown",
            }
        },
    )
    command = build_run_command(
        request,
        package,
        requested_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        command_id="command.p1.demo.seed.001",
    )
    package.schemas.require_valid("run-command.schema.json", command)
    assert command["seed_inputs"]["p1.literature_library"]["content"] == (
        "# Seeded library\n"
    )
    # The seed is inside the sealed content: removing it changes the digest.
    assert package.digests.require_match("run_command.content", command) == command[
        "content_sha256"
    ]
    seedless = dict(command)
    del seedless["seed_inputs"]
    assert (
        package.digests.compute("run_command.content", seedless)
        != command["content_sha256"]
    )


def test_seed_inputs_reject_malformed_entries() -> None:
    package = SpecificationPackage.load(ARCHITECTURE)
    with pytest.raises(Exception, match="schema"):
        build_run_command(
            RunRequest(
                project_id="project.demo",
                phase_contract=package.phases.identity("P1"),
                mode="p1.literature_update",
                choice_values={
                    "p1.scope": "broad_update",
                    "p1.instructions": "Update the literature basis.",
                    "p1.selected_history": [],
                },
                context_policy="current_only",
                user_id="researcher.demo",
                idempotency_key="request-command-builder-seed-002",
                seed_inputs={
                    "p1.literature_library": {
                        "content": "",
                        "media_type": "text/markdown",
                    }
                },
            ),
            package,
            requested_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
            command_id="command.p1.demo.seed.002",
        )
