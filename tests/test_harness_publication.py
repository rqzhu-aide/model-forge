from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from model_forge.digests.jcs import canonicalize
from model_forge.harness.publication import (
    ContractPublicationService,
    FrozenPublicationHead,
    PreparedPublisherTransform,
    PublicationError,
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from model_forge.storage.repository import (
    HubRepository,
    RepositoryConflictError,
    ZERO_SHA256,
)


NOW = datetime(2026, 8, 2, 14, 30, tzinfo=timezone.utc)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _repository(tmp_path: Path) -> HubRepository:
    repository = HubRepository(tmp_path / "hub.sqlite3")
    assert repository.initialize() == 14
    repository.create_project("project.publication", {"name": "Publication test"})
    return repository


def _run(repository: HubRepository, suffix: str) -> tuple[str, str]:
    request_id = f"request.{suffix}"
    command_id = f"command.{suffix}"
    run_id = f"run.{suffix}"
    repository.record_raw_command(
        request_id,
        "project.publication",
        _sha(f"raw:{suffix}"),
        {"request": suffix},
    )
    repository.seal_command(
        command_id,
        "project.publication",
        request_id,
        f"idempotency.{suffix}",
        _sha(f"command:{suffix}"),
        {"command": suffix},
    )
    repository.create_run(
        run_id,
        "project.publication",
        command_id,
        "submitted",
        {"state": "submitted"},
        f"event.{suffix}.created",
        _sha(f"event:{suffix}"),
        {"to": "submitted"},
        recorded_at=NOW,
    )
    return run_id, command_id


def _output(
    repository: HubRepository,
    output_id: str,
    document: object,
    *,
    suffix: str | None = None,
) -> RegisteredValidatedOutput:
    label = suffix or output_id
    raw = (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
    artifact = RegisteredArtifactMetadata(
        artifact_id=f"artifact.{label}",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        media_type="application/json",
        storage_uri=f"artifact://sha256/{hashlib.sha256(raw).hexdigest()}",
    )
    repository.record_artifact(
        artifact.artifact_id,
        "project.publication",
        artifact.sha256,
        artifact.byte_length,
        artifact.media_type,
        artifact.storage_uri,
        {"contract_output_id": output_id},
        recorded_at=NOW,
    )
    return RegisteredValidatedOutput(output_id, document, artifact)


def _append_binding(output_id: str = "p1.items") -> dict[str, object]:
    return {
        "binding_id": "p1.append_items",
        "applicable_modes": ["p1.update"],
        "operation": "append",
        "output_ids": [output_id],
        "target": {
            "kind": "cumulative_collection",
            "collection_id": "p1.item_history",
            "object_type": "attention_item",
        },
        "prior_target_policy": "not_applicable",
        "publisher_transform": "none",
        "may_create_scientific_content": False,
    }


def _replace_binding(
    *, output_id: str = "p1.summary", slot_id: str = "p1.summary.current"
) -> dict[str, object]:
    return {
        "binding_id": "p1.replace_summary",
        "applicable_modes": ["p1.update"],
        "operation": "replace",
        "output_ids": [output_id],
        "target": {
            "kind": "current_slot",
            "slot_id": slot_id,
            "record_type": "literature_synthesis",
        },
        "prior_target_policy": "absent_or_match_current",
        "publisher_transform": "none",
        "may_create_scientific_content": False,
    }


def _bundle_binding() -> dict[str, object]:
    return {
        "binding_id": "p5.publish_manuscript",
        "applicable_modes": ["p5.assembly"],
        "operation": "bundle",
        "output_ids": ["p5.manuscript_candidate", "p5.claim_traceability"],
        "components": [
            {
                "component_name": "manuscript",
                "output_id": "p5.manuscript_candidate",
            },
            {
                "component_name": "claim_traceability",
                "output_id": "p5.claim_traceability",
            },
        ],
        "target": {
            "kind": "current_slot",
            "slot_id": "p5.manuscript.current",
            "record_type": "manuscript",
        },
        "prior_target_policy": "absent_or_match_current",
        "publisher_transform": "deterministic_bundle",
        "may_create_scientific_content": False,
    }


def test_append_and_replace_publish_atomically_without_changing_run_status(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "append_replace")
    outputs = {
        "p1.items": _output(
            repository,
            "p1.items",
            [{"item": "first"}, {"item": "second"}],
        ),
        "p1.summary": _output(
            repository, "p1.summary", {"conclusion": "Evidence is mixed."}
        ),
    }
    before = repository.get_run(run_id)["status"]

    result = ContractPublicationService(repository).publish(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[_append_binding(), _replace_binding()],
        outputs=outputs,
        expected_head=FrozenPublicationHead(
            0,
            ZERO_SHA256,
            0,
            {"p1.summary.current": None},
        ),
        published_at=NOW,
    )

    assert repository.get_run(run_id)["status"] == before == "submitted"
    assert len(result.collection_item_ids) == 2
    assert len(set(result.collection_item_ids)) == 2
    assert len(result.generation_ids) == 1
    assert result.new_authority_sequence == 3
    assert result.new_current_revision == 1
    assert result.new_authority_root_sha256 != ZERO_SHA256
    current = repository.get_current_record(
        "project.publication", "p1.summary.current"
    )
    assert current is not None
    assert json.loads(current["payload_json"]) == {
        "conclusion": "Evidence is mixed."
    }
    items = repository.list_collection_items(
        "project.publication", "p1.item_history"
    )
    assert {json.loads(item["payload_json"])["item"] for item in items} == {
        "first",
        "second",
    }
    receipt_row = repository.get_publication_receipt(result.receipt_id)
    assert receipt_row is not None
    receipt = json.loads(receipt_row["payload_json"])
    content_sha256 = receipt.pop("content_sha256")
    assert content_sha256 == result.receipt_sha256
    assert hashlib.sha256(canonicalize(receipt)).hexdigest() == content_sha256


def test_keyed_method_array_uses_exact_pointer_template_and_frozen_heads(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "keyed")
    methods = [
        {"identity": {"stable_id": "method.alpha"}, "summary": "Alpha"},
        {"identity": {"stable_id": "method.beta"}, "summary": "Beta"},
    ]
    output = _output(repository, "p2.method_changes", methods)
    binding = {
        "binding_id": "p2.upsert_method_records",
        "applicable_modes": ["p2.full_catalog"],
        "operation": "upsert_each",
        "output_ids": ["p2.method_changes"],
        "target": {
            "kind": "keyed_current_slots",
            "collection_id": "p2.method_records",
            "record_type": "method_record",
            "item_key_pointer": "/identity/stable_id",
            "slot_template": "methods/{item_key}/current",
        },
        "prior_target_policy": "absent_or_match_current",
        "publisher_transform": "none",
        "may_create_scientific_content": False,
    }

    result = ContractPublicationService(repository).publish(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[binding],
        outputs={"p2.method_changes": output},
        expected_head=FrozenPublicationHead(
            0,
            ZERO_SHA256,
            0,
            {
                "methods/method.alpha/current": None,
                "methods/method.beta/current": None,
            },
        ),
        published_at=NOW,
    )

    assert set(result.current_slots) == {
        "methods/method.alpha/current",
        "methods/method.beta/current",
    }
    for slot, summary in (
        ("methods/method.alpha/current", "Alpha"),
        ("methods/method.beta/current", "Beta"),
    ):
        current = repository.get_current_record("project.publication", slot)
        assert current is not None
        assert json.loads(current["payload_json"])["summary"] == summary


def test_method_bound_bundle_requires_explicit_scope_and_preserves_components(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "bundle")
    manuscript = _output(
        repository,
        "p5.manuscript_candidate",
        {"title": "A method manuscript"},
    )
    trace = _output(
        repository,
        "p5.claim_traceability",
        {"claims": ["claim.one"]},
    )
    outputs = {
        manuscript.contract_output_id: manuscript,
        trace.contract_output_id: trace,
    }
    binding = _bundle_binding()
    service = ContractPublicationService(repository)
    with pytest.raises(PublicationError) as missing_scope:
        service.publish(
            project_id="project.publication",
            run_id=run_id,
            command_id=command_id,
            bindings=[binding],
            outputs=outputs,
            expected_head=FrozenPublicationHead(0, ZERO_SHA256, 0, {}),
            published_at=NOW,
        )
    assert missing_scope.value.code == "publication.method_slot_scope_required"

    slot = "methods/method.alpha/v1/p5.manuscript.current"
    result = service.publish(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[binding],
        outputs=outputs,
        expected_head=FrozenPublicationHead(0, ZERO_SHA256, 0, {slot: None}),
        published_at=NOW,
        slot_scope_prefix="methods/method.alpha/v1",
    )
    assert set(result.current_slots) == {slot}
    current = repository.get_current_record("project.publication", slot)
    assert current is not None
    bundle = json.loads(current["payload_json"])
    assert bundle["format"] == "model-forge.deterministic-bundle"
    assert [item["component_name"] for item in bundle["components"]] == [
        "manuscript",
        "claim_traceability",
    ]
    assert bundle["components"][0]["document"] == manuscript.document
    assert "method_identity" not in bundle


def test_bundle_propagates_identity_and_rejects_conflicting_components(
    tmp_path: Path,
) -> None:
    identity = {
        "stable_id": "method.alpha",
        "version": 1,
        "definition_sha256": "a" * 64,
    }
    slot = "methods/method.alpha/v1/p5.manuscript.current"
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "bundle_identity")
    manuscript = _output(
        repository,
        "p5.manuscript_candidate",
        {
            "title": "A method manuscript",
            "method_identity": identity,
        },
    )
    trace = _output(
        repository,
        "p5.claim_traceability",
        {"claims": ["claim.one"]},
    )
    result = ContractPublicationService(repository).publish(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[_bundle_binding()],
        outputs={
            manuscript.contract_output_id: manuscript,
            trace.contract_output_id: trace,
        },
        expected_head=FrozenPublicationHead(0, ZERO_SHA256, 0, {slot: None}),
        published_at=NOW,
        slot_scope_prefix="methods/method.alpha/v1",
    )
    assert set(result.current_slots) == {slot}
    current = repository.get_current_record("project.publication", slot)
    assert current is not None
    assert json.loads(current["payload_json"])["method_identity"] == identity

    conflict_root = tmp_path / "conflict"
    conflict_root.mkdir()
    conflict_repository = _repository(conflict_root)
    conflict_run_id, conflict_command_id = _run(
        conflict_repository,
        "bundle_identity_conflict",
    )
    conflict_manuscript = _output(
        conflict_repository,
        "p5.manuscript_candidate",
        {
            "title": "A method manuscript",
            "method_identity": identity,
        },
    )
    conflict_trace = _output(
        conflict_repository,
        "p5.claim_traceability",
        {
            "claims": ["claim.one"],
            "method_identity": {
                **identity,
                "definition_sha256": "b" * 64,
            },
        },
    )
    with pytest.raises(PublicationError) as conflicting:
        ContractPublicationService(conflict_repository).publish(
            project_id="project.publication",
            run_id=conflict_run_id,
            command_id=conflict_command_id,
            bindings=[_bundle_binding()],
            outputs={
                conflict_manuscript.contract_output_id: conflict_manuscript,
                conflict_trace.contract_output_id: conflict_trace,
            },
            expected_head=FrozenPublicationHead(
                0,
                ZERO_SHA256,
                0,
                {slot: None},
            ),
            published_at=NOW,
            slot_scope_prefix="methods/method.alpha/v1",
        )
    assert conflicting.value.code == "publication.conflicting_bundle_method_identity"
    assert conflict_repository.get_project("project.publication")[
        "authority_sequence"
    ] == 0


def test_deterministic_index_requires_exact_prepared_transform_basis(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "index")
    changes = _output(
        repository,
        "p1.source_changes",
        [{"source_id": "source.one"}],
    )
    index = _output(
        repository,
        "prepared.p1.library",
        {"source_ids": ["source.one"]},
        suffix="prepared_library",
    )
    binding = {
        "binding_id": "p1.rebuild_library",
        "applicable_modes": ["p1.update"],
        "operation": "replace",
        "output_ids": ["p1.source_changes"],
        "source_input_ids": ["p1.current_library"],
        "target": {
            "kind": "current_slot",
            "slot_id": "p1.library.current",
            "record_type": "literature_library",
        },
        "prior_target_policy": "absent_or_match_current",
        "publisher_transform": "deterministic_index",
        "may_create_scientific_content": False,
    }
    prepared = PreparedPublisherTransform(
        publication_binding_id="p1.rebuild_library",
        transform="deterministic_index",
        document=index.document,
        artifact=index.artifact,
        source_output_sha256={"p1.source_changes": changes.document_sha256},
    )

    result = ContractPublicationService(repository).publish(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[binding],
        outputs={"p1.source_changes": changes},
        expected_head=FrozenPublicationHead(
            0, ZERO_SHA256, 0, {"p1.library.current": None}
        ),
        prepared_transforms={"p1.rebuild_library": prepared},
        published_at=NOW,
    )
    assert result.generation_ids
    current = repository.get_current_record(
        "project.publication", "p1.library.current"
    )
    assert current is not None
    assert json.loads(current["payload_json"]) == index.document


def test_stale_authority_head_surfaces_repository_compare_and_swap_conflict(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    first_run, first_command = _run(repository, "first")
    first_output = _output(repository, "p1.summary", {"version": 1}, suffix="first")
    service = ContractPublicationService(repository)
    first = service.publish(
        project_id="project.publication",
        run_id=first_run,
        command_id=first_command,
        bindings=[_replace_binding()],
        outputs={"p1.summary": first_output},
        expected_head=FrozenPublicationHead(
            0, ZERO_SHA256, 0, {"p1.summary.current": None}
        ),
        published_at=NOW,
    )

    second_run, second_command = _run(repository, "second")
    second_output = _output(
        repository, "p1.summary", {"version": 2}, suffix="second"
    )
    with pytest.raises(RepositoryConflictError) as conflict:
        service.publish(
            project_id="project.publication",
            run_id=second_run,
            command_id=second_command,
            bindings=[_replace_binding()],
            outputs={"p1.summary": second_output},
            expected_head=FrozenPublicationHead(
                0, ZERO_SHA256, 0, {"p1.summary.current": first.generation_ids[0]}
            ),
            published_at=NOW,
        )
    assert conflict.value.code == "repository.publication_basis_changed"
    current = repository.get_current_record(
        "project.publication", "p1.summary.current"
    )
    assert current is not None
    assert current["generation_id"] == first.generation_ids[0]


def test_malformed_collection_and_keyed_shapes_fail_before_transaction(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "malformed")
    bad = _output(repository, "p1.items", ["not an object"])
    with pytest.raises(PublicationError) as invalid:
        ContractPublicationService(repository).publish(
            project_id="project.publication",
            run_id=run_id,
            command_id=command_id,
            bindings=[_append_binding()],
            outputs={"p1.items": bad},
            expected_head=FrozenPublicationHead(0, ZERO_SHA256, 0, {}),
            published_at=NOW,
        )
    assert invalid.value.code == "publication.invalid_collection_item"
    project = repository.get_project("project.publication")
    assert project["authority_sequence"] == 0
    assert project["authority_root_sha256"] == ZERO_SHA256
