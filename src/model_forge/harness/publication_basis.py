"""Freeze and recover the exact formal head used by one run."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..contracts import ResolvedPhasePlan
from ..domain.identities import MethodIdentity
from ..storage.repository import HubRepository
from .publication import FrozenPublicationHead, RegisteredValidatedOutput


_METHOD_PHASES = frozenset({"P3", "P4", "P5"})


def method_scope_prefix(method: MethodIdentity) -> str:
    """Return the durable logical namespace for one exact method version."""

    return (
        f"methods/{method.stable_id}/v{method.version}/"
        f"{method.definition_sha256}"
    )


def capture_publication_basis(
    *,
    repository: HubRepository,
    project_id: str,
    plan: ResolvedPhasePlan,
    method: MethodIdentity | None,
) -> dict[str, Any]:
    """Capture an exhaustive current-slot inventory at preparation time."""

    project, current_rows = repository.capture_head_and_current_slots(project_id)
    current = {
        str(row["slot_key"]): str(row["generation_id"]) for row in current_rows
    }
    scope: str | None = None
    if plan.identity.phase_id in _METHOD_PHASES:
        if method is None:
            raise ValueError(
                f"{plan.identity.phase_id} publication requires an exact method identity."
            )
        scope = method_scope_prefix(method)

    for binding in plan.publication_bindings:
        target = binding["target"]
        if str(target["kind"]) != "current_slot":
            continue
        slot = str(target["slot_id"])
        if scope is not None:
            slot = f"{scope}/{slot}"
        current.setdefault(slot, None)

    return {
        "authority_sequence": int(project["authority_sequence"]),
        "authority_root_sha256": str(project["authority_root_sha256"]),
        "current_revision": int(project["current_revision"]),
        "complete_current_slot_inventory": True,
        "current_generations": current,
        "slot_scope_prefix": scope,
    }


def recover_publication_head(
    basis: Mapping[str, Any],
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
) -> FrozenPublicationHead:
    """Recover the frozen head and resolve output-keyed absent slots safely."""

    if basis.get("complete_current_slot_inventory") is not True:
        raise ValueError("Publication basis is not an exhaustive current-slot inventory.")
    sealed = basis.get("current_generations")
    if not isinstance(sealed, Mapping):
        raise ValueError(
            "Publication basis lacks the sealed current-slot inventory."
        )
    generations = dict(sealed)
    for binding in plan.publication_bindings:
        if str(binding["operation"]) != "upsert_each":
            continue
        output_ids = tuple(str(value) for value in binding["output_ids"])
        if len(output_ids) != 1:
            raise ValueError("Keyed publication requires exactly one source output.")
        document = outputs[output_ids[0]].document
        if type(document) is not list:
            raise ValueError("Keyed publication source must be an array.")
        target = binding["target"]
        pointer = str(target["item_key_pointer"])
        template = str(target["slot_template"])
        for item in document:
            key = _pointer(item, pointer)
            if type(key) is not str or not key:
                raise ValueError("Keyed publication resolved an invalid item key.")
            generations.setdefault(template.replace("{item_key}", key), None)
    return FrozenPublicationHead(
        authority_sequence=int(basis["authority_sequence"]),
        authority_root_sha256=str(basis["authority_root_sha256"]),
        current_revision=int(basis["current_revision"]),
        current_generations=generations,
    )


def _pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must be absolute.")
    value = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or token not in value:
            raise ValueError(f"JSON pointer {pointer!r} is unavailable.")
        value = value[token]
    return value


__all__ = [
    "capture_publication_basis",
    "method_scope_prefix",
    "recover_publication_head",
]
