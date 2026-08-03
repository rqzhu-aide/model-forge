"""Tests for WP0 reviewed-basis closure: sealed_basis in run commands.

These tests verify that:
- New commands carry a sealed_basis with authority head, input generations, and role resources.
- The sealed basis is verified at preparation time.
- A legacy command without sealed_basis still works.
- The example fixture validates against schema + digest.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import typing
from pathlib import Path

from method_hub.api.models import CreateProjectRequest, StartRunRequest
from method_hub.api.ports import RawRequestBody
from method_hub.application.bootstrap import build_service
from method_hub.application.settings import ApplicationSettings
from method_hub.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def _raw(
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str | None = None,
) -> RawRequestBody:
    return RawRequestBody(
        body=body,
        byte_length=len(body),
        media_type="application/json",
        content_sha256=hashlib.sha256(body).hexdigest(),
        method="POST",
        path="/api/v1/projects",
        command_family=family,  # type: ignore[arg-type]
        project_id=project_id,
        idempotency_key=key,
    )


def test_sealed_basis_example_validates_against_schema_and_digest() -> None:
    """The sealed-basis example fixture must pass schema + digest validation."""
    spec = SpecificationPackage.load(ARCHITECTURE)
    example = json.loads(
        (ARCHITECTURE / "examples" / "run-command-with-sealed-basis.example.json").read_text()
    )
    spec.schemas.require_valid("run-command.schema.json", example)
    spec.digests.require_match("run_command.content", example)


def test_legacy_command_without_sealed_basis_still_validates() -> None:
    """A command without sealed_basis (pre-upgrade) must still validate."""
    spec = SpecificationPackage.load(ARCHITECTURE)
    example = json.loads(
        (ARCHITECTURE / "examples" / "run-command.example.json").read_text()
    )
    assert "sealed_basis" not in example
    spec.schemas.require_valid("run-command.schema.json", example)
    spec.digests.require_match("run_command.content", example)


def test_stale_basis_error_code_registered() -> None:
    """STALE_BASIS must be in the command error code enum and error rules."""
    from method_hub.api.errors import ERROR_RULES, CommandErrorCode

    literal_values = typing.get_args(CommandErrorCode)
    assert "STALE_BASIS" in literal_values
    assert "STALE_BASIS" in ERROR_RULES


def test_new_command_carries_sealed_basis(tmp_path: Path) -> None:
    """A run command built by start_run must carry sealed_basis with the
    descriptor basis fields."""
    asyncio.run(_exercise_sealed_basis(tmp_path))


async def _exercise_sealed_basis(tmp_path: Path) -> None:
    service = build_service(
        ApplicationSettings(
            data_root=tmp_path / "data",
            architecture_root=ARCHITECTURE,
            executor_kind="fake",
            development_mode=True,
            frontend_dist=tmp_path / "missing-web",
        )
    )
    create = CreateProjectRequest(
        name="Sealed basis test",
        research_question="Does the sealed basis appear in the command?",
        domains=["statistics"],
        intended_use="Test the reviewed-basis closure.",
    )
    create_bytes = json.dumps(create.model_dump()).encode("utf-8")
    create_receipt = await service.preserve_raw_request(
        _raw(create_bytes, family="create_project", key="create-sealed-basis-test")
    )
    project = await service.create_project(create, raw_request=create_receipt)

    phase = await service.get_phase_view(
        project.project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    action = next(item for item in phase.actions if item.action_type == "start_run")
    assert action.enabled is True
    assert phase.descriptor_basis is not None

    selected = [
        item.option_id for item in phase.run_configuration.current_inputs
    ]
    command = StartRunRequest(
        action_descriptor_id=action.descriptor_id,
        phase="P1",
        mode="p1.literature_update",
        choice_values={
            "p1.scope": "broad_update",
            "p1.instructions": "Run the literature update.",
            "p1.selected_history": [],
        },
        context_policy="current_only",
        selected_context_option_ids=selected,
    )
    body = json.dumps(command.model_dump()).encode("utf-8")
    started = await service.start_run(
        project.project_id,
        command,
        raw_request=await service.preserve_raw_request(
            _raw(
                body,
                family="start_run",
                key="start-sealed-basis-test",
                project_id=project.project_id,
            )
        ),
    )

    # Check the sealed command has sealed_basis
    run_row = service.repository.get_run(str(started.run_id))
    command_row = service.repository.get_sealed_command(
        str(run_row["command_id"])
    )
    sealed_command = json.loads(command_row["payload_json"])
    assert "sealed_basis" in sealed_command, "New command must carry sealed_basis"

    basis = sealed_command["sealed_basis"]
    assert "authority_head" in basis
    assert "reviewed_current_inputs" in basis
    assert basis["action_type"] == "start_run"
    assert basis["phase"] == "P1"

    # Each reviewed input must have generation_id
    for item in basis["reviewed_current_inputs"]:
        assert "generation_id" in item, "reviewed input must seal generation_id"

    # Let the run complete cleanly
    for _ in range(200):
        detail = await service.get_run(project.project_id, started.run_id)
        if detail.state in {"published", "failed", "rejected", "conflicted", "cancelled"}:
            break
        await asyncio.sleep(0.025)


def test_phase_view_exposes_descriptor_basis(tmp_path: Path) -> None:
    """The PhaseView model must expose descriptor_basis for sealed_basis extraction."""
    asyncio.run(_exercise_descriptor_basis(tmp_path))


async def _exercise_descriptor_basis(tmp_path: Path) -> None:
    service = build_service(
        ApplicationSettings(
            data_root=tmp_path / "data",
            architecture_root=ARCHITECTURE,
            executor_kind="fake",
            development_mode=True,
            frontend_dist=tmp_path / "missing-web",
        )
    )
    create = CreateProjectRequest(
        name="Descriptor basis test",
        research_question="Is the descriptor basis exposed?",
        domains=["statistics"],
        intended_use="Test descriptor basis exposure.",
    )
    create_bytes = json.dumps(create.model_dump()).encode("utf-8")
    create_receipt = await service.preserve_raw_request(
        _raw(create_bytes, family="create_project", key="create-desc-basis-test")
    )
    project = await service.create_project(create, raw_request=create_receipt)

    phase = await service.get_phase_view(
        project.project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    assert phase.descriptor_basis is not None
    assert "authority_head" in phase.descriptor_basis
    assert "reviewed_current_inputs" in phase.descriptor_basis
    # generation_id must be present on each reviewed input
    for item in phase.descriptor_basis["reviewed_current_inputs"]:
        assert "generation_id" in item


def test_verify_sealed_basis_detects_authority_drift(tmp_path: Path) -> None:
    """_verify_sealed_basis must reject when the authority head has drifted."""
    asyncio.run(_exercise_authority_drift(tmp_path))


async def _exercise_authority_drift(tmp_path: Path) -> None:
    from method_hub.storage.repository import RepositoryConflictError

    service = build_service(
        ApplicationSettings(
            data_root=tmp_path / "data",
            architecture_root=ARCHITECTURE,
            executor_kind="fake",
            development_mode=True,
            frontend_dist=tmp_path / "missing-web",
        )
    )
    create = CreateProjectRequest(
        name="Authority drift test",
        research_question="Does stale basis detection work?",
        domains=["statistics"],
        intended_use="Test authority drift detection.",
    )
    create_bytes = json.dumps(create.model_dump()).encode("utf-8")
    create_receipt = await service.preserve_raw_request(
        _raw(create_bytes, family="create_project", key="create-auth-drift-test")
    )
    project = await service.create_project(create, raw_request=create_receipt)

    phase = await service.get_phase_view(
        project.project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    assert phase.descriptor_basis is not None

    # Build a stale sealed basis with wrong authority head
    stale_basis = dict(phase.descriptor_basis)
    stale_basis["authority_head"] = {
        "authority_sequence": 999,
        "authority_root_sha256": "0" * 64,
        "current_revision": 999,
    }

    # Reconstruct a minimal coordinator for unit testing
    from method_hub.application.run_coordinator import RunCoordinator
    from method_hub.executors import DeterministicFakeExecutor
    from method_hub.harness.preparation import PreparedRunRecipe

    coordinator = RunCoordinator(
        settings=service.settings,
        specification=service.specification,
        repository=service.repository,
        artifacts=service.artifacts,
        role_resources=service.role_resources,
        executor=DeterministicFakeExecutor(),
    )

    command = {
        "project_id": str(project.project_id),
        "sealed_basis": stale_basis,
    }
    recipe_doc = {
        "project_id": str(project.project_id),
        "frozen_inputs": [],
        "publication_basis": {
            "authority_sequence": 0,
            "authority_root_sha256": "0" * 64,
            "current_revision": 0,
        },
    }
    recipe = PreparedRunRecipe(
        sha256="0" * 64,
        document=recipe_doc,
    )

    # The verification should raise RepositoryConflictError with stale_basis code
    raised = False
    try:
        coordinator._verify_sealed_basis(command, recipe)
    except RepositoryConflictError as e:
        assert "stale_basis" in e.code
        raised = True
    assert raised, "Authority drift must trigger stale_basis error"
