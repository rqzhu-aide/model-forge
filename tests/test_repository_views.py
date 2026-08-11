from __future__ import annotations

import hashlib

from method_hub.application.repository_views import RepositoryQueries, row_json
from method_hub.digests.jcs import canonicalize
from method_hub.domain.identities import MethodIdentity
from method_hub.storage.repository import HubRepository


def test_repository_queries_list_project_payloads(tmp_path) -> None:
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project(
        "project.example",
        {"name": "Example", "research_question": "What is learned?"},
    )
    queries = RepositoryQueries(repository)

    rows = queries.list_projects()

    assert len(rows) == 1
    assert row_json(rows[0])["name"] == "Example"


def _publish_theory_record(repository: HubRepository, project_id: str) -> None:
    """Publish one method-bound theory record through the formal path."""
    method = MethodIdentity("method.demo", 1, "b" * 64)
    payload = {
        "record_id": "record.theory.001",
        "record_type": "theory_record",
        "method_identity": method.to_dict(),
        "summary": "Convergence holds under a curvature condition.",
    }
    digest = hashlib.sha256(canonicalize(payload)).hexdigest()
    repository.record_artifact(
        "artifact.theory.001",
        project_id,
        digest,
        len(canonicalize(payload)),
        "application/json",
        f"artifact://sha256/{digest}",
        {"purpose": "test theory record"},
    )
    project = repository.get_project(project_id)
    sequence = int(project["authority_sequence"])
    root = str(project["authority_root_sha256"])
    event = {
        "event_id": "authority_event.test.theory",
        "event_type": "formal_generation_published",
        "project_id": project_id,
        "generation_id": "generation.theory.001",
    }
    event_sha = hashlib.sha256(canonicalize(event)).hexdigest()
    event_root = hashlib.sha256(
        bytes.fromhex(root) + bytes.fromhex(event_sha)
    ).hexdigest()
    receipt = {
        "receipt_id": "receipt.test.theory",
        "project_id": project_id,
        "generations": ["generation.theory.001"],
    }
    with repository.publication_transaction(
        project_id,
        "receipt.test.theory",
        sequence,
        root,
        expected_current_revision=int(project["current_revision"]),
    ) as publication:
        publication.add_formal_generation(
            "generation.theory.001",
            "theory_record",
            "artifact.theory.001",
            digest,
            payload,
            logical_slot="p3.theory_record.current",
        )
        publication.replace_current_slot(
            "p3.theory_record.current",
            "generation.theory.001",
            expected_generation_id=None,
        )
        publication.append_authority_event(
            "authority_event.test.theory",
            "formal_generation_published",
            event_sha,
            event_root,
            event,
        )
        publication.record_receipt(
            hashlib.sha256(canonicalize(receipt)).hexdigest(),
            receipt,
        )


def test_current_record_method_scoped_policy_requires_a_method(tmp_path) -> None:
    """An exact / same_stable_method lookup with NO selected method must not
    fall back to the newest record of the type: that would silently bind
    method-specific context into a run that never selected a method."""
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project(
        "project.example",
        {"name": "Example", "research_question": "What is learned?"},
    )
    _publish_theory_record(repository, "project.example")
    queries = RepositoryQueries(repository)

    method = MethodIdentity("method.demo", 1, "b" * 64)
    other = MethodIdentity("method.other", 1, "c" * 64)

    assert (
        queries.current_record(
            project_id="project.example",
            record_type="theory_record",
            method_identity=None,
            match_policy="exact",
        )
        is None
    )
    assert (
        queries.current_record(
            project_id="project.example",
            record_type="theory_record",
            method_identity=None,
            match_policy="same_stable_method",
        )
        is None
    )
    # not_applicable lookups are method-free by contract and still resolve.
    assert (
        queries.current_record(
            project_id="project.example",
            record_type="theory_record",
            method_identity=None,
            match_policy="not_applicable",
        )
        is not None
    )
    assert (
        queries.current_record(
            project_id="project.example",
            record_type="theory_record",
            method_identity=method,
            match_policy="exact",
        )
        is not None
    )
    assert (
        queries.current_record(
            project_id="project.example",
            record_type="theory_record",
            method_identity=other,
            match_policy="exact",
        )
        is None
    )
