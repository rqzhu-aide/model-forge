"""Pure deterministic reducers for contract-declared current indexes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from ..contracts import ResolvedPhasePlan
from ..digests.jcs import canonicalize
from ..json_io import loads_json
from ..storage import ArtifactStore
from ..storage.repository import HubRepository
from .execution_records import deterministic_id, document_sha256
from .preparation import PreparedRunRecipe
from .publication import (
    PreparedPublisherTransform,
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)


Reducer = Callable[[Any | None, list[dict[str, Any]]], dict[str, Any]]


def prepare_index_transforms(
    *,
    repository: HubRepository,
    artifacts: ArtifactStore,
    project_id: str,
    run_id: str,
    recipe: PreparedRunRecipe,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
) -> dict[str, PreparedPublisherTransform]:
    """Materialize every declared deterministic index from frozen inputs."""

    frozen_inputs = {
        str(item["contract_input_id"]): item
        for item in recipe.document.get("frozen_inputs", ())
    }
    result: dict[str, PreparedPublisherTransform] = {}
    for binding in plan.publication_bindings:
        if binding["publisher_transform"] != "deterministic_index":
            continue
        binding_id = str(binding["binding_id"])
        reducer = _reducer(binding_id)
        output_ids = tuple(str(value) for value in binding["output_ids"])
        changes: list[dict[str, Any]] = []
        for output_id in output_ids:
            document = outputs[output_id].document
            if type(document) is list:
                if any(type(item) is not dict for item in document):
                    raise ValueError(
                        f"Index source output {output_id!r} contains a non-object item."
                    )
                changes.extend(dict(item) for item in document)
            elif type(document) is dict:
                changes.append(dict(document))
            else:
                raise ValueError(
                    f"Index source output {output_id!r} has an invalid shape."
                )

        source_inputs: dict[str, str] = {}
        prior: Any | None = None
        source_input_ids = tuple(
            str(value) for value in binding.get("source_input_ids", ())
        )
        if len(source_input_ids) > 1:
            raise ValueError(
                f"Index reducer {binding_id!r} supports at most one prior current input."
            )
        if source_input_ids:
            input_id = source_input_ids[0]
            frozen = frozen_inputs.get(input_id)
            if frozen is not None:
                pointer = frozen["artifact"]
                digest = str(pointer["sha256"])
                source_inputs[input_id] = digest
                prior = loads_json(
                    artifacts.read_bytes(digest),
                    source=f"frozen input {input_id}",
                )

        document = reducer(prior, changes)
        payload = canonicalize(document)
        stored = artifacts.put_bytes(payload)
        artifact_id = deterministic_id(
            "artifact",
            "publisher_transform",
            project_id,
            run_id,
            binding_id,
            document_sha256(document),
        )
        repository.record_artifact(
            artifact_id,
            project_id,
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "prepared_publisher_transform",
                "run_id": run_id,
                "publication_binding_id": binding_id,
                "storage_relative_path": stored.relative_path,
                "source_input_sha256": source_inputs,
                "source_output_sha256": {
                    output_id: outputs[output_id].document_sha256
                    for output_id in output_ids
                },
            },
        )
        result[binding_id] = PreparedPublisherTransform(
            publication_binding_id=binding_id,
            transform="deterministic_index",
            document=document,
            artifact=RegisteredArtifactMetadata(
                artifact_id=artifact_id,
                sha256=str(stored.sha256),
                byte_length=stored.size,
                media_type="application/json",
                storage_uri=f"artifact://sha256/{stored.sha256}",
            ),
            source_output_sha256={
                output_id: outputs[output_id].document_sha256
                for output_id in output_ids
            },
            source_input_sha256=source_inputs,
        )
    return result


def _reducer(binding_id: str) -> Reducer:
    reducers: dict[str, Reducer] = {
        "p1.rebuild_literature_library": _literature_library,
        "p2.rebuild_method_catalog": _method_catalog,
        "p5.replace_review_issue_ledger": _review_issue_ledger,
    }
    try:
        return reducers[binding_id]
    except KeyError as error:
        raise ValueError(
            f"No deterministic reducer is registered for {binding_id!r}."
        ) from error


def _literature_library(
    prior: Any | None, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    prior_items = _prior_items(prior, "sources")
    merged = {_literature_key(item): item for item in prior_items}
    for item in changes:
        merged[_literature_key(item)] = item
    keys = sorted(merged)
    return {
        "format": "method-hub.literature-library-index",
        "format_version": "1.0.0",
        "record_type": "literature_library",
        "source_count": len(keys),
        "source_keys": keys,
        "sources": [merged[key] for key in keys],
    }


def _method_catalog(
    prior: Any | None, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    prior_items = _prior_items(prior, "methods")
    merged = {_method_key(item): item for item in prior_items}
    for item in changes:
        merged[_method_key(item)] = item
    keys = sorted(merged)
    methods = [merged[key] for key in keys]
    return {
        "format": "method-hub.method-catalog-index",
        "format_version": "1.0.0",
        "record_type": "method_catalog",
        "method_count": len(methods),
        "active_method_count": sum(
            item.get("lifecycle_state", "proposed") != "retired" for item in methods
        ),
        "methods": methods,
        "projections": [
            {
                "identity": item["identity"],
                "title": item.get("title", item["identity"]["stable_id"]),
                "summary": item.get("summary", ""),
                "lifecycle_state": item.get("lifecycle_state", "proposed"),
            }
            for item in methods
        ],
    }


def _review_issue_ledger(
    prior: Any | None, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    prior_items = _prior_items(prior, "issues")
    merged = {_review_issue_key(item): item for item in prior_items}
    for item in changes:
        merged[_review_issue_key(item)] = item
    keys = sorted(merged)
    issues = [merged[key] for key in keys]
    return {
        "format": "method-hub.review-issue-ledger",
        "format_version": "1.0.0",
        "record_type": "review_issue_ledger",
        "issue_count": len(issues),
        "issues": issues,
    }


def _prior_items(prior: Any | None, field: str) -> list[dict[str, Any]]:
    if type(prior) is not dict or type(prior.get(field)) is not list:
        return []
    return [dict(item) for item in prior[field] if type(item) is dict]


def _literature_key(document: Mapping[str, Any]) -> str:
    identifiers = document.get("identifiers", ())
    if type(identifiers) is list:
        values = sorted(
            f"{str(item.get('kind', '')).casefold()}:{str(item.get('value', '')).casefold()}"
            for item in identifiers
            if type(item) is dict and item.get("kind") and item.get("value")
        )
        if values:
            return values[0]
    for field in ("source_id", "record_id"):
        value = document.get(field)
        if type(value) is str and value:
            return value.casefold()
    return document_sha256(document)


def _method_key(document: Mapping[str, Any]) -> str:
    identity = document.get("identity")
    if type(identity) is not dict or type(identity.get("stable_id")) is not str:
        raise ValueError("Method index item lacks identity.stable_id.")
    return str(identity["stable_id"])


def _review_issue_key(document: Mapping[str, Any]) -> str:
    for field in ("issue_id", "record_id"):
        value = document.get(field)
        if type(value) is str and value:
            return value
    return document_sha256(document)


__all__ = ["prepare_index_transforms"]
