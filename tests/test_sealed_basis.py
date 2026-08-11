"""Tests for WP0 reviewed-basis closure: sealed_basis in run commands.

These tests verify that:
- New commands carry a sealed_basis with authority head, input generations, and role resources.
- The sealed basis is verified at preparation time.
- A legacy command without sealed_basis still works.
- The example fixture validates against schema + digest.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import typing
from pathlib import Path

import pytest

from method_hub.api.models import CreateProjectRequest, StartRunRequest
from method_hub.api.ports import RawRequestBody
from method_hub.application.bootstrap import build_service
from method_hub.application.run_coordinator import RunCoordinator
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.contracts.runtime import RuntimePhaseContract, resolve_runtime_contract
from method_hub.domain.identities import MethodIdentity
from method_hub.executors import DeterministicFakeExecutor
from method_hub.harness.commands import require_complete_sealed_basis
from method_hub.harness.preparation import PreparedRunRecipe
from method_hub.specification import SpecificationPackage
from method_hub.storage.repository import RepositoryConflictError

import yaml


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "team"


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


def _p1_runtime(spec: SpecificationPackage) -> RuntimePhaseContract:
    """Resolve the P1 literature-update runtime contract used by the
    coordinator-unit drift tests (P1 is not method-bound)."""
    identity = spec.phases.identity("P1")
    plan = spec.resolve_phase(
        identity,
        "p1.literature_update",
        {
            "p1.scope": "broad_update",
            "p1.instructions": "Run the literature update.",
            "p1.selected_history": [],
        },
        "current_only",
    )
    return resolve_runtime_contract(spec.phases, plan)


async def _exercise_authority_drift(tmp_path: Path) -> None:
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
        coordinator._verify_sealed_basis(
            command, recipe, runtime=_p1_runtime(service.specification)
        )
    except RepositoryConflictError as e:
        assert "stale_basis" in e.code
        raised = True
    assert raised, "Authority drift must trigger stale_basis error"


def test_positive_start_run_prepares_cleanly(tmp_path: Path) -> None:
    """A complete sealed basis passes the acceptance gate and the run
    prepares without drift rejection: no conflicted/stale_basis terminal and
    the run.prepared event fires."""
    asyncio.run(_exercise_positive_prepare(tmp_path))


async def _exercise_positive_prepare(tmp_path: Path) -> None:
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
        name="Positive prepare test",
        research_question="Does a complete basis prepare cleanly?",
        domains=["statistics"],
        intended_use="Test the full reviewed-basis acceptance path.",
    )
    create_bytes = json.dumps(create.model_dump()).encode("utf-8")
    create_receipt = await service.preserve_raw_request(
        _raw(create_bytes, family="create_project", key="create-positive-prepare")
    )
    project = await service.create_project(create, raw_request=create_receipt)

    phase = await service.get_phase_view(
        project.project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    assert phase.descriptor_basis is not None
    # The acceptance gate requires role resources for every plan role; this
    # assertion is the regression probe for the empty-choices/skill-manifest
    # path bug that left role_resources empty and rejected every start_run.
    assert phase.descriptor_basis["role_resources"], (
        "The phase view must seal role resources for the run roles."
    )
    action = next(item for item in phase.actions if item.action_type == "start_run")
    assert action.enabled is True

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
                key="start-positive-prepare",
                project_id=project.project_id,
            )
        ),
    )
    run_id = str(started.run_id)

    detail = None
    for _ in range(200):
        detail = await service.get_run(project.project_id, run_id)
        if detail.state in {"published", "failed", "rejected", "conflicted", "cancelled"}:
            break
        await asyncio.sleep(0.025)
    assert detail is not None

    # No conflicted/stale_basis terminal: the sealed basis was accepted and
    # verified against the freshly prepared recipe.
    assert detail.state != "conflicted"
    reason = detail.terminal_reason
    assert reason is None or not str(reason.code).startswith("stale_basis")
    events = service.repository.list_run_events(run_id)
    event_types = [json.loads(row["payload_json"])["event_type"] for row in events]
    assert "run.prepared" in event_types, "the run must pass through prepared"
    assert detail.state == "published"


async def _coordinator_fixture(tmp_path: Path):
    """Build a service + coordinator over a fresh project and return the
    live-true descriptor basis plus a matching prepared-recipe document."""
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
        name="Drift fixture",
        research_question="Is the sealed basis verified?",
        domains=["statistics"],
        intended_use="Test sealed-basis drift rejection.",
    )
    create_bytes = json.dumps(create.model_dump()).encode("utf-8")
    create_receipt = await service.preserve_raw_request(
        _raw(create_bytes, family="create_project", key="create-drift-fixture")
    )
    project = await service.create_project(create, raw_request=create_receipt)

    phase = await service.get_phase_view(
        project.project_id,
        "P1",
        mode="p1.literature_update",
        method_id=None,
    )
    assert phase.descriptor_basis is not None
    assert phase.descriptor_basis["role_resources"], (
        "The live-true basis must carry role resources."
    )

    coordinator = RunCoordinator(
        settings=service.settings,
        specification=service.specification,
        repository=service.repository,
        artifacts=service.artifacts,
        role_resources=service.role_resources,
        executor=DeterministicFakeExecutor(),
    )

    basis = copy.deepcopy(phase.descriptor_basis)
    recipe_doc = {
        "project_id": str(project.project_id),
        "frozen_inputs": [
            {
                "contract_input_id": str(item["option_id"]),
                "generation_id": str(item["generation_id"]),
                "artifact": {"sha256": str(item.get("sha256") or "0" * 64)},
            }
            for item in basis["reviewed_current_inputs"]
        ],
        "publication_basis": {
            "authority_sequence": 0,
            "authority_root_sha256": "0" * 64,
            "current_revision": 0,
        },
        "role_resources": copy.deepcopy(basis["role_resources"]),
    }
    return coordinator, basis, recipe_doc


def test_verify_sealed_basis_rejects_unmatched_required_sealed_input(
    tmp_path: Path,
) -> None:
    """A sealed *required* reviewed input whose option_id matches no frozen
    contract input must be rejected as stale_basis.input_generation_drifted."""
    asyncio.run(_exercise_unmatched_sealed_input(tmp_path, required=True))


def test_verify_sealed_basis_skips_unmatched_optional_sealed_input(
    tmp_path: Path,
) -> None:
    """A sealed *optional* reviewed input that the user deselected is
    intentionally absent from the frozen set and must not be treated as
    drift.  resolve_run_inputs omits unselected optional inputs; the sealed
    basis still carries them (it seals every option at view time)."""
    asyncio.run(_exercise_unmatched_sealed_input(tmp_path, required=False))


async def _exercise_unmatched_sealed_input(
    tmp_path: Path, *, required: bool
) -> None:
    coordinator, basis, recipe_doc = await _coordinator_fixture(tmp_path)
    basis = copy.deepcopy(basis)
    entry: dict[str, typing.Any] = {
        "option_id": "p1.vanished_option",
        "generation_id": "generation.123",
    }
    if required:
        entry["required"] = True
    basis["reviewed_current_inputs"] = [entry]
    command = {"project_id": recipe_doc["project_id"], "sealed_basis": basis}
    recipe = PreparedRunRecipe(sha256="0" * 64, document=recipe_doc)
    if required:
        with pytest.raises(RepositoryConflictError) as exc:
            coordinator._verify_sealed_basis(
                command, recipe, runtime=_p1_runtime(coordinator.specification)
            )
        assert exc.value.code == "stale_basis.input_generation_drifted"
    else:
        # Optional + deselected → no error.
        coordinator._verify_sealed_basis(
            command, recipe, runtime=_p1_runtime(coordinator.specification)
        )


def test_verify_sealed_basis_rejects_method_drift(tmp_path: Path) -> None:
    """A sealed method identity with no live method (or vice versa) must be
    rejected as stale_basis.method_drifted."""
    asyncio.run(_exercise_method_drift(tmp_path))


async def _exercise_method_drift(tmp_path: Path) -> None:
    coordinator, basis, recipe_doc = await _coordinator_fixture(tmp_path)
    basis = copy.deepcopy(basis)
    basis["method_identity"] = {
        "stable_id": "method.delta",
        "version": 1,
        "definition_sha256": "0" * 64,
    }
    command = {"project_id": recipe_doc["project_id"], "sealed_basis": basis}
    recipe = PreparedRunRecipe(sha256="0" * 64, document=recipe_doc)
    with pytest.raises(RepositoryConflictError) as exc:
        coordinator._verify_sealed_basis(
            command, recipe, runtime=_p1_runtime(coordinator.specification)
        )
    assert exc.value.code == "stale_basis.method_drifted"


def test_verify_sealed_basis_rejects_missing_live_role(tmp_path: Path) -> None:
    """A sealed role absent from the prepared run's role resources must be
    rejected as stale_basis.role_resource_drifted."""
    asyncio.run(_exercise_missing_live_role(tmp_path))


async def _exercise_missing_live_role(tmp_path: Path) -> None:
    coordinator, basis, recipe_doc = await _coordinator_fixture(tmp_path)
    basis = copy.deepcopy(basis)
    resources = copy.deepcopy(basis["role_resources"])
    resources["ghost_role"] = {
        "profile": "ghost",
        "profile_version": "1.0.0",
        "soul_sha256": "0" * 64,
        "skills": [],
    }
    basis["role_resources"] = resources
    command = {"project_id": recipe_doc["project_id"], "sealed_basis": basis}
    recipe = PreparedRunRecipe(sha256="0" * 64, document=recipe_doc)
    with pytest.raises(RepositoryConflictError) as exc:
        coordinator._verify_sealed_basis(
            command, recipe, runtime=_p1_runtime(coordinator.specification)
        )
    assert exc.value.code == "stale_basis.role_resource_drifted"


def test_verify_sealed_basis_rejects_skill_source_revision_drift(
    tmp_path: Path,
) -> None:
    """A sealed skill whose source revision differs from the frozen snapshot
    must be rejected as stale_basis.role_resource_drifted."""
    asyncio.run(_exercise_skill_source_revision_drift(tmp_path))


async def _exercise_skill_source_revision_drift(tmp_path: Path) -> None:
    coordinator, basis, recipe_doc = await _coordinator_fixture(tmp_path)
    basis = copy.deepcopy(basis)
    resources = copy.deepcopy(basis["role_resources"])
    role = next(iter(resources))
    skills = copy.deepcopy(resources[role]["skills"])
    assert skills, "the sealed role must carry at least one skill"
    skills[0]["source_revision"] = "drifted-revision"
    resources[role]["skills"] = skills
    basis["role_resources"] = resources
    command = {"project_id": recipe_doc["project_id"], "sealed_basis": basis}
    recipe = PreparedRunRecipe(sha256="0" * 64, document=recipe_doc)
    with pytest.raises(RepositoryConflictError) as exc:
        coordinator._verify_sealed_basis(
            command, recipe, runtime=_p1_runtime(coordinator.specification)
        )
    assert exc.value.code == "stale_basis.role_resource_drifted"


def test_verify_sealed_basis_rejects_memory_policy_drift(tmp_path: Path) -> None:
    """WP-H2: a sealed memory policy that differs from the frozen snapshot
    must be rejected as stale_basis.role_resource_drifted."""
    asyncio.run(_exercise_memory_policy_drift(tmp_path))


async def _exercise_memory_policy_drift(tmp_path: Path) -> None:
    coordinator, basis, recipe_doc = await _coordinator_fixture(tmp_path)
    basis = copy.deepcopy(basis)
    resources = copy.deepcopy(basis["role_resources"])
    role = next(iter(resources))
    assert resources[role].get("memory_policy") == "persistent"
    resources[role]["memory_policy"] = "ephemeral"
    basis["role_resources"] = resources
    command = {"project_id": recipe_doc["project_id"], "sealed_basis": basis}
    recipe = PreparedRunRecipe(sha256="0" * 64, document=recipe_doc)
    with pytest.raises(RepositoryConflictError) as exc:
        coordinator._verify_sealed_basis(
            command, recipe, runtime=_p1_runtime(coordinator.specification)
        )
    assert exc.value.code == "stale_basis.role_resource_drifted"


def test_sealed_basis_carries_wp_h2_exact_configuration(tmp_path: Path) -> None:
    """WP-H2: the descriptor basis seals the exact installed role
    configuration: memory policy from the catalog, explicit nulls for
    model/provider (not carried by the WP-C catalog), and the phase
    instruction field present for every role."""
    asyncio.run(_exercise_wp_h2_snapshot_fields(tmp_path))


async def _exercise_wp_h2_snapshot_fields(tmp_path: Path) -> None:
    _, basis, _ = await _coordinator_fixture(tmp_path)
    resources = basis["role_resources"]
    assert resources, "the basis must seal role resources"
    for role, payload in resources.items():
        assert payload["memory_policy"] == "persistent", role
        assert "model" in payload and payload["model"] is None, role
        assert "provider" in payload and payload["provider"] is None, role
        assert "phase_instruction" in payload, role


def test_verify_sealed_basis_passes_legacy_command_without_basis(
    tmp_path: Path,
) -> None:
    """C6: a stored pre-upgrade command without sealed_basis must pass the
    preparation-time verification unchanged."""
    asyncio.run(_exercise_legacy_command_without_basis(tmp_path))


async def _exercise_legacy_command_without_basis(tmp_path: Path) -> None:
    coordinator, _, recipe_doc = await _coordinator_fixture(tmp_path)
    command = {"project_id": recipe_doc["project_id"]}
    assert command.get("sealed_basis") is None
    recipe = PreparedRunRecipe(sha256="0" * 64, document=recipe_doc)
    # Must not raise.
    coordinator._verify_sealed_basis(
        command, recipe, runtime=_p1_runtime(coordinator.specification)
    )


def _complete_gate_basis() -> dict:
    """A well-formed sealed basis that satisfies the acceptance gate."""
    return {
        "authority_head": {
            "authority_sequence": 0,
            "authority_root_sha256": "0" * 64,
            "current_revision": 0,
        },
        "reviewed_current_inputs": [
            {
                "option_id": "p1.literature_notes",
                "generation_id": "generation.1",
                "sha256": "0" * 64,
            }
        ],
        "method_identity": None,
        "role_resources": {
            "lead": {
                "profile": "default",
                "profile_version": "1.0.0",
                "soul_sha256": "0" * 64,
                "skills": [
                    {
                        "skill_id": "stat-paper-reviewer",
                        "source": "bundled",
                        "source_revision": "unknown",
                        "bundle_sha256": "0" * 64,
                    }
                ],
                "model": None,
                "provider": None,
                "memory_policy": "persistent",
                "phase_instruction": None,
                "tools": None,
                "base_configuration": {
                    "file_name": "configs/lead.yaml",
                    "format": "yaml",
                    "sha256": "0" * 64,
                },
                "library_guidance": {
                    "file_name": "guidance/lead.md",
                    "sha256": "0" * 64,
                },
                "custom_skills": [],
            }
        },
    }


def test_gate_rejects_missing_basis() -> None:
    """The acceptance gate must reject a command with no sealed basis."""
    with pytest.raises(ValueError, match="reviewed basis is missing"):
        require_complete_sealed_basis(
            sealed_basis=None,
            phase_roles={"lead"},
            required_input_ids=set(),
            selected_input_ids=set(),
        )


def test_gate_rejects_missing_authority_head() -> None:
    """The acceptance gate must reject a basis without the authority head."""
    basis = _complete_gate_basis()
    del basis["authority_head"]
    with pytest.raises(ValueError, match="authority head"):
        require_complete_sealed_basis(
            sealed_basis=basis,
            phase_roles={"lead"},
            required_input_ids={"p1.literature_notes"},
            selected_input_ids=set(),
        )


def test_gate_rejects_input_without_generation_or_digest() -> None:
    """The acceptance gate must reject a reviewed input sealed without its
    generation id and artifact digest."""
    basis = _complete_gate_basis()
    basis["reviewed_current_inputs"] = [{"option_id": "p1.literature_notes"}]
    with pytest.raises(ValueError, match="generation and artifact digest"):
        require_complete_sealed_basis(
            sealed_basis=basis,
            phase_roles={"lead"},
            required_input_ids={"p1.literature_notes"},
            selected_input_ids=set(),
        )


def test_gate_rejects_method_bound_run_without_sealed_method() -> None:
    """The acceptance gate must reject a method-bound run whose basis does
    not seal the submitted method identity."""
    basis = _complete_gate_basis()
    expected = MethodIdentity.from_dict(
        {
            "stable_id": "method.delta",
            "version": 1,
            "definition_sha256": "0" * 64,
        }
    )
    with pytest.raises(ValueError, match="submitted method identity"):
        require_complete_sealed_basis(
            sealed_basis=basis,
            phase_roles={"lead"},
            required_input_ids=set(),
            selected_input_ids=set(),
            expected_method=expected,
        )


def test_gate_rejects_zero_role_resources() -> None:
    """The acceptance gate must reject a basis with no role resources for
    the roles the phase requires."""
    basis = _complete_gate_basis()
    basis["role_resources"] = {}
    with pytest.raises(ValueError, match="role resources"):
        require_complete_sealed_basis(
            sealed_basis=basis,
            phase_roles={"lead"},
            required_input_ids=set(),
            selected_input_ids=set(),
        )
