"""Contract-bound formal publication for validated run outputs.

This module materializes only the operations declared by an exact resolved
phase contract. It performs no scientific interpretation and does not mutate
the run lifecycle. All formal writes are committed through one repository
publication transaction against frozen authority and current heads.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..contracts import ResolvedPhasePlan
from ..domain.identities import PHASE_IDS
from ..digests.jcs import JCSCanonicalizationError, canonicalize
from ..domain.runs import isoformat_utc
from ..storage.repository import HubRepository
from .preparation import PreparedRunRecipe


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ITEM_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_METHOD_PHASES = frozenset({"P3", "P4", "P5"})
_ZERO_SHA256 = "0" * 64


class PublicationError(ValueError):
    """A publication request is not an exact, safe materialization."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class RegisteredArtifactMetadata:
    """Metadata for an artifact already registered to the same project."""

    artifact_id: str
    sha256: str
    byte_length: int
    media_type: str
    storage_uri: str

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_id")
        _digest(self.sha256, "artifact sha256")
        if type(self.byte_length) is not int or self.byte_length < 0:
            raise _fail(
                "publication.invalid_artifact_size",
                "Artifact byte_length must be a nonnegative integer.",
            )
        _text(self.media_type, "artifact media_type")
        _text(self.storage_uri, "artifact storage_uri")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "media_type": self.media_type,
            "storage_uri": self.storage_uri,
        }


@dataclass(frozen=True, slots=True)
class RegisteredValidatedOutput:
    """A structurally validated document and its registered artifact."""

    contract_output_id: str
    document: Any
    artifact: RegisteredArtifactMetadata

    def __post_init__(self) -> None:
        _text(self.contract_output_id, "contract_output_id")
        _canonical_digest(self.document, self.contract_output_id)

    @property
    def document_sha256(self) -> str:
        return _canonical_digest(self.document, self.contract_output_id)


@dataclass(frozen=True, slots=True)
class PreparedPublisherTransform:
    """A registered deterministic reducer result prepared before publication.

    An index reducer depends on frozen prior formal input as well as run output.
    The reducer therefore runs outside this authority writer. This object binds
    its registered result to the exact source-output document digests so a
    stale or unrelated reducer result cannot be published.
    """

    publication_binding_id: str
    transform: str
    document: Mapping[str, Any]
    artifact: RegisteredArtifactMetadata
    source_output_sha256: Mapping[str, str]
    source_input_sha256: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.publication_binding_id, "publication_binding_id")
        _text(self.transform, "transform")
        if not isinstance(self.document, Mapping):
            raise _fail(
                "publication.invalid_transform_document",
                "A prepared publisher transform must contain one JSON object.",
            )
        _canonical_digest(dict(self.document), self.publication_binding_id)
        if not isinstance(self.source_output_sha256, Mapping):
            raise _fail(
                "publication.invalid_transform_basis",
                "source_output_sha256 must be an output-to-digest mapping.",
            )
        for output_id, digest in self.source_output_sha256.items():
            _text(output_id, "transform source output ID")
            _digest(digest, "transform source output digest")
        if not isinstance(self.source_input_sha256, Mapping):
            raise _fail(
                "publication.invalid_transform_basis",
                "source_input_sha256 must be an input-to-digest mapping.",
            )
        for input_id, digest in self.source_input_sha256.items():
            _text(input_id, "transform source input ID")
            _digest(digest, "transform source input digest")


@dataclass(frozen=True, slots=True)
class FrozenPublicationHead:
    """Authority and current-state expectations sealed before validation."""

    authority_sequence: int
    authority_root_sha256: str
    current_revision: int
    current_generations: Mapping[str, str | None]

    def __post_init__(self) -> None:
        if type(self.authority_sequence) is not int or self.authority_sequence < 0:
            raise _fail(
                "publication.invalid_authority_sequence",
                "authority_sequence must be a nonnegative integer.",
            )
        _digest(self.authority_root_sha256, "authority_root_sha256")
        if type(self.current_revision) is not int or self.current_revision < 0:
            raise _fail(
                "publication.invalid_current_revision",
                "current_revision must be a nonnegative integer.",
            )
        if not isinstance(self.current_generations, Mapping):
            raise _fail(
                "publication.invalid_current_heads",
                "current_generations must map exact slot keys to expected generations.",
            )
        for slot_key, generation_id in self.current_generations.items():
            _safe_slot(slot_key)
            if generation_id is not None:
                _text(generation_id, f"expected generation for {slot_key}")


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Compact result of one atomic formal publication."""

    receipt_id: str
    receipt_sha256: str
    generation_ids: tuple[str, ...]
    collection_item_ids: tuple[str, ...]
    current_slots: Mapping[str, str]
    authority_event_ids: tuple[str, ...]
    new_authority_sequence: int
    new_authority_root_sha256: str
    new_current_revision: int


SlotResolver = Callable[[str, str, str], str]


@dataclass(frozen=True, slots=True)
class _CurrentWrite:
    binding_id: str
    slot_key: str
    record_type: str
    expected_generation_id: str | None
    generation_id: str
    document: Any
    document_sha256: str
    artifact: RegisteredArtifactMetadata
    source_output_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CollectionWrite:
    binding_id: str
    collection_key: str
    object_type: str
    item_id: str
    document: Mapping[str, Any]
    document_sha256: str
    artifact: RegisteredArtifactMetadata
    source_output_id: str


class ContractPublicationService:
    """Materialize exact publication bindings in one atomic transaction."""

    def __init__(self, repository: HubRepository) -> None:
        self.repository = repository

    def validate_materialization(
        self,
        *,
        project_id: str,
        run_id: str,
        command_id: str,
        bindings: ResolvedPhasePlan | PreparedRunRecipe | Sequence[Mapping[str, Any]],
        outputs: Mapping[str, RegisteredValidatedOutput],
        expected_head: FrozenPublicationHead,
        phase: str | None = None,
        slot_scope_prefix: str | None = None,
        slot_resolver: SlotResolver | None = None,
        prepared_transforms: Mapping[str, PreparedPublisherTransform] | None = None,
    ) -> None:
        """Check the complete publication plan without writing formal state."""

        exact_bindings, resolved_phase = _extract_bindings(
            bindings,
            project_id=project_id,
            run_id=run_id,
            command_id=command_id,
            explicit_phase=phase,
        )
        normalized_outputs = _validate_outputs(outputs)
        normalized_transforms = _validate_transforms(prepared_transforms or {})
        if slot_scope_prefix is not None and slot_resolver is not None:
            raise _fail(
                "publication.ambiguous_slot_resolution",
                "Provide a slot_scope_prefix or a slot_resolver, not both.",
            )
        if slot_scope_prefix is not None:
            _safe_slot(slot_scope_prefix)
        current, collection = _materialize_writes(
            project_id=project_id,
            run_id=run_id,
            phase=resolved_phase,
            bindings=exact_bindings,
            outputs=normalized_outputs,
            expected_head=expected_head,
            slot_scope_prefix=slot_scope_prefix,
            slot_resolver=slot_resolver,
            prepared_transforms=normalized_transforms,
        )
        if not current and not collection:
            raise _fail(
                "publication.empty_plan",
                "The selected publication bindings produce no formal writes.",
            )
    def publish(
        self,
        *,
        project_id: str,
        run_id: str,
        command_id: str,
        bindings: ResolvedPhasePlan | PreparedRunRecipe | Sequence[Mapping[str, Any]],
        outputs: Mapping[str, RegisteredValidatedOutput],
        expected_head: FrozenPublicationHead,
        published_at: datetime,
        phase: str | None = None,
        slot_scope_prefix: str | None = None,
        slot_resolver: SlotResolver | None = None,
        prepared_transforms: Mapping[str, PreparedPublisherTransform] | None = None,
    ) -> PublicationResult:
        """Publish validated outputs without changing run state.

        ``RepositoryConflictError`` is intentionally not caught. A stale
        authority root, current revision, or slot generation is an observable
        atomic compare-and-swap conflict for the application layer to present.
        """

        _text(project_id, "project_id")
        _text(run_id, "run_id")
        _text(command_id, "command_id")
        timestamp = isoformat_utc(published_at)
        exact_bindings, resolved_phase = _extract_bindings(
            bindings,
            project_id=project_id,
            run_id=run_id,
            command_id=command_id,
            explicit_phase=phase,
        )
        normalized_outputs = _validate_outputs(outputs)
        normalized_transforms = _validate_transforms(prepared_transforms or {})
        if slot_scope_prefix is not None and slot_resolver is not None:
            raise _fail(
                "publication.ambiguous_slot_resolution",
                "Provide a slot_scope_prefix or a slot_resolver, not both.",
            )
        if slot_scope_prefix is not None:
            _safe_slot(slot_scope_prefix)

        current_writes, collection_writes = _materialize_writes(
            project_id=project_id,
            run_id=run_id,
            phase=resolved_phase,
            bindings=exact_bindings,
            outputs=normalized_outputs,
            expected_head=expected_head,
            slot_scope_prefix=slot_scope_prefix,
            slot_resolver=slot_resolver,
            prepared_transforms=normalized_transforms,
        )
        if not current_writes and not collection_writes:
            raise _fail(
                "publication.empty_plan",
                "The selected publication bindings produce no formal writes.",
            )

        receipt_id = _deterministic_id(
            "receipt",
            {
                "project_id": project_id,
                "run_id": run_id,
                "command_id": command_id,
                "phase": resolved_phase,
                "published_at": timestamp,
                "expected_authority_sequence": expected_head.authority_sequence,
                "expected_authority_root_sha256": expected_head.authority_root_sha256,
                "expected_current_revision": expected_head.current_revision,
                "current_writes": [_current_intent(item) for item in current_writes],
                "collection_writes": [
                    _collection_intent(item) for item in collection_writes
                ],
            },
        )

        generation_ids: list[str] = []
        collection_item_ids: list[str] = []
        current_slots: dict[str, str] = {}
        event_ids: list[str] = []
        event_documents: list[dict[str, Any]] = []
        record_changes: list[dict[str, Any]] = []
        collection_changes: list[dict[str, Any]] = []
        authority_sequence = expected_head.authority_sequence
        authority_root = expected_head.authority_root_sha256

        with self.repository.publication_transaction(
            project_id,
            receipt_id,
            expected_head.authority_sequence,
            expected_head.authority_root_sha256,
            expected_current_revision=expected_head.current_revision,
        ) as publication:
            for write in current_writes:
                publication.add_formal_generation(
                    write.generation_id,
                    write.record_type,
                    write.artifact.artifact_id,
                    write.document_sha256,
                    write.document,
                    logical_slot=write.slot_key,
                    source_run_id=run_id,
                    supersedes_generation_id=write.expected_generation_id,
                    published_at=published_at,
                )
                publication.replace_current_slot(
                    write.slot_key,
                    write.generation_id,
                    expected_generation_id=write.expected_generation_id,
                    updated_at=published_at,
                )
                generation_ids.append(write.generation_id)
                current_slots[write.slot_key] = write.generation_id
                event_type = (
                    "published"
                    if write.expected_generation_id is None
                    else "superseded"
                )
                event, event_sha256, authority_root = _authority_event(
                    project_id=project_id,
                    run_id=run_id,
                    command_id=command_id,
                    receipt_id=receipt_id,
                    binding_id=write.binding_id,
                    event_type=event_type,
                    subject_kind="record_generation",
                    subject_id=write.generation_id,
                    target_id=write.slot_key,
                    prior_generation_id=write.expected_generation_id,
                    content_sha256=write.document_sha256,
                    prior_root_sha256=authority_root,
                    sequence=authority_sequence + 1,
                    created_at=timestamp,
                )
                authority_sequence += 1
                publication.append_authority_event(
                    event["event_id"],
                    event_type,
                    event_sha256,
                    authority_root,
                    event,
                    committed_at=published_at,
                )
                event_ids.append(event["event_id"])
                event_documents.append(event)
                record_changes.append(
                    {
                        "publication_binding_id": write.binding_id,
                        "slot_key": write.slot_key,
                        "record_type": write.record_type,
                        "prior_generation_id": write.expected_generation_id,
                        "new_generation_id": write.generation_id,
                        "content_sha256": write.document_sha256,
                        "artifact": write.artifact.to_dict(),
                        "source_output_ids": list(write.source_output_ids),
                        "authority_event_id": event["event_id"],
                    }
                )

            for write in collection_writes:
                appended = publication.append_collection_item(
                    write.collection_key,
                    write.item_id,
                    write.object_type,
                    write.document_sha256,
                    dict(write.document),
                    artifact_id=write.artifact.artifact_id,
                    source_run_id=run_id,
                    appended_at=published_at,
                )
                if not appended.created:
                    continue
                collection_item_ids.append(write.item_id)
                event, event_sha256, authority_root = _authority_event(
                    project_id=project_id,
                    run_id=run_id,
                    command_id=command_id,
                    receipt_id=receipt_id,
                    binding_id=write.binding_id,
                    event_type="published",
                    subject_kind="cumulative_object",
                    subject_id=write.item_id,
                    target_id=write.collection_key,
                    prior_generation_id=None,
                    content_sha256=write.document_sha256,
                    prior_root_sha256=authority_root,
                    sequence=authority_sequence + 1,
                    created_at=timestamp,
                )
                authority_sequence += 1
                publication.append_authority_event(
                    event["event_id"],
                    "published",
                    event_sha256,
                    authority_root,
                    event,
                    committed_at=published_at,
                )
                event_ids.append(event["event_id"])
                event_documents.append(event)
                collection_changes.append(
                    {
                        "publication_binding_id": write.binding_id,
                        "collection_key": write.collection_key,
                        "object_type": write.object_type,
                        "item_id": write.item_id,
                        "content_sha256": write.document_sha256,
                        "artifact": write.artifact.to_dict(),
                        "source_output_id": write.source_output_id,
                        "authority_event_id": event["event_id"],
                    }
                )

            if not event_ids:
                raise _fail(
                    "publication.no_authority_change",
                    "The transaction contains no new formal authority change.",
                )
            receipt_without_digest: dict[str, Any] = {
                "format": "model-forge.publication-receipt",
                "format_version": "1.0.0",
                "receipt_id": receipt_id,
                "project_id": project_id,
                "run_id": run_id,
                "command_id": command_id,
                "phase": resolved_phase,
                "record_changes": record_changes,
                "cumulative_object_changes": collection_changes,
                "authority_events": event_documents,
                "prior_authority_sequence": expected_head.authority_sequence,
                "new_authority_sequence": authority_sequence,
                "prior_authority_root_sha256": expected_head.authority_root_sha256,
                "new_authority_root_sha256": authority_root,
                "prior_current_revision": expected_head.current_revision,
                "new_current_revision": expected_head.current_revision + 1,
                "atomic": True,
                "published_at": timestamp,
            }
            receipt_sha256 = _canonical_digest(
                receipt_without_digest, "publication receipt"
            )
            receipt = dict(receipt_without_digest)
            receipt["content_sha256"] = receipt_sha256
            publication.record_receipt(
                receipt_sha256,
                receipt,
                run_id=run_id,
                command_id=command_id,
                committed_at=published_at,
            )

        return PublicationResult(
            receipt_id=receipt_id,
            receipt_sha256=receipt_sha256,
            generation_ids=tuple(generation_ids),
            collection_item_ids=tuple(collection_item_ids),
            current_slots=current_slots,
            authority_event_ids=tuple(event_ids),
            new_authority_sequence=authority_sequence,
            new_authority_root_sha256=authority_root,
            new_current_revision=expected_head.current_revision + 1,
        )


def _extract_bindings(
    source: ResolvedPhasePlan | PreparedRunRecipe | Sequence[Mapping[str, Any]],
    *,
    project_id: str,
    run_id: str,
    command_id: str,
    explicit_phase: str | None,
) -> tuple[tuple[Mapping[str, Any], ...], str]:
    phase: str | None = explicit_phase
    if isinstance(source, ResolvedPhasePlan):
        exact = tuple(source.publication_bindings)
        source_phase = source.identity.phase_id
    elif isinstance(source, PreparedRunRecipe):
        document = source.document
        for field, expected in (
            ("project_id", project_id),
            ("run_id", run_id),
            ("command_id", command_id),
        ):
            if document.get(field) != expected:
                raise _fail(
                    "publication.recipe_identity_mismatch",
                    f"Prepared recipe {field} does not match the publication request.",
                )
        raw = document.get("publication_bindings")
        if type(raw) is not list:
            raise _fail(
                "publication.invalid_recipe_bindings",
                "Prepared recipe publication_bindings must be an array.",
            )
        exact = tuple(_mapping(item, "publication binding") for item in raw)
        source_phase = document.get("phase")
    else:
        if isinstance(source, (str, bytes)) or not isinstance(source, Sequence):
            raise _fail(
                "publication.invalid_bindings",
                "bindings must be a resolved plan, prepared recipe, or binding sequence.",
            )
        exact = tuple(_mapping(item, "publication binding") for item in source)
        source_phase = _phase_from_bindings(exact)
    if type(source_phase) is not str or source_phase not in PHASE_IDS:
        raise _fail("publication.invalid_phase", "A valid phase identity is required.")
    if phase is not None and phase != source_phase:
        raise _fail(
            "publication.phase_mismatch",
            "The explicit phase does not match the publication binding source.",
        )
    if not exact:
        raise _fail("publication.empty_bindings", "At least one binding is required.")
    return _validate_bindings(exact), source_phase


def _phase_from_bindings(bindings: Sequence[Mapping[str, Any]]) -> str:
    phases = set()
    for binding in bindings:
        binding_id = binding.get("binding_id")
        if type(binding_id) is not str or "." not in binding_id:
            raise _fail(
                "publication.invalid_binding_id",
                "Raw binding sequences require phase-prefixed binding IDs.",
            )
        phases.add(binding_id.split(".", 1)[0].upper())
    if len(phases) != 1:
        raise _fail(
            "publication.mixed_phase_bindings",
            "One publication transaction cannot mix phase bindings.",
        )
    return next(iter(phases))


def _validate_bindings(
    bindings: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    seen: set[str] = set()
    referenced_outputs: set[str] = set()
    normalized: list[Mapping[str, Any]] = []
    allowed = {
        "binding_id",
        "applicable_modes",
        "operation",
        "output_ids",
        "source_input_ids",
        "components",
        "target",
        "prior_target_policy",
        "publisher_transform",
        "may_create_scientific_content",
    }
    for raw in bindings:
        binding = _mapping(raw, "publication binding")
        unknown = set(binding) - allowed
        required = {
            "binding_id",
            "operation",
            "output_ids",
            "target",
            "prior_target_policy",
            "publisher_transform",
            "may_create_scientific_content",
        }
        missing = required - set(binding)
        if missing or unknown:
            raise _fail(
                "publication.malformed_binding",
                f"Binding has missing fields {sorted(missing)} and unknown fields {sorted(unknown)}.",
            )
        binding_id = _text(binding["binding_id"], "binding_id")
        if binding_id in seen:
            raise _fail(
                "publication.duplicate_binding",
                f"Binding {binding_id!r} appears more than once.",
            )
        seen.add(binding_id)
        operation = binding["operation"]
        if operation not in {"append", "replace", "bundle", "upsert_each"}:
            raise _fail(
                "publication.unsupported_operation",
                f"Binding {binding_id!r} uses unsupported operation {operation!r}.",
            )
        output_ids = _string_array(binding["output_ids"], f"{binding_id} output_ids")
        referenced_outputs.update(output_ids)
        if binding["may_create_scientific_content"] is not False:
            raise _fail(
                "publication.scientific_content_forbidden",
                f"Binding {binding_id!r} permits publisher-created scientific content.",
            )
        target = _mapping(binding["target"], f"{binding_id} target")
        kind = target.get("kind")
        expected_kind = {
            "append": "cumulative_collection",
            "replace": "current_slot",
            "bundle": "current_slot",
            "upsert_each": "keyed_current_slots",
        }[operation]
        if kind != expected_kind:
            raise _fail(
                "publication.operation_target_mismatch",
                f"Binding {binding_id!r} operation {operation!r} requires target kind {expected_kind!r}.",
            )
        _validate_target(target, binding_id)
        policy = binding["prior_target_policy"]
        if kind == "cumulative_collection" and policy != "not_applicable":
            raise _fail(
                "publication.invalid_prior_policy",
                f"Append binding {binding_id!r} requires not_applicable prior policy.",
            )
        if kind != "cumulative_collection" and policy not in {
            "absent_or_match_current",
            "must_match_current",
        }:
            raise _fail(
                "publication.invalid_prior_policy",
                f"Binding {binding_id!r} has an unsupported current-target policy.",
            )
        transform = binding["publisher_transform"]
        if operation in {"append", "upsert_each"} and transform != "none":
            raise _fail(
                "publication.invalid_transform",
                f"Binding {binding_id!r} must use publisher_transform none.",
            )
        if operation == "bundle" and transform != "deterministic_bundle":
            raise _fail(
                "publication.invalid_transform",
                f"Bundle {binding_id!r} must use deterministic_bundle.",
            )
        if operation == "replace" and transform not in {"none", "deterministic_index"}:
            raise _fail(
                "publication.invalid_transform",
                f"Replace binding {binding_id!r} has unsupported transform {transform!r}.",
            )
        if operation == "bundle":
            _validate_components(binding, output_ids)
        elif "components" in binding:
            raise _fail(
                "publication.unexpected_components",
                f"Non-bundle binding {binding_id!r} cannot declare components.",
            )
        normalized.append(binding)
    if not referenced_outputs:
        raise _fail("publication.no_outputs", "Bindings reference no run outputs.")
    return tuple(normalized)


def _validate_target(target: Mapping[str, Any], binding_id: str) -> None:
    kind = target.get("kind")
    fields = {
        "current_slot": {"kind", "slot_id", "record_type"},
        "cumulative_collection": {"kind", "collection_id", "object_type"},
        "keyed_current_slots": {
            "kind",
            "collection_id",
            "record_type",
            "item_key_pointer",
            "slot_template",
        },
    }.get(kind)
    if fields is None or set(target) != fields:
        raise _fail(
            "publication.malformed_target",
            f"Binding {binding_id!r} target has an incomplete or unknown shape.",
        )
    for field in fields - {"kind"}:
        _text(target[field], f"{binding_id} target {field}")
    if kind == "current_slot":
        _safe_slot(target["slot_id"])
    if kind in {"cumulative_collection", "keyed_current_slots"}:
        _safe_slot(target["collection_id"])
    if kind == "keyed_current_slots":
        pointer = target["item_key_pointer"]
        _parse_pointer(pointer)
        template = target["slot_template"]
        if template.count("{item_key}") != 1 or template.replace(
            "{item_key}", ""
        ).find("{") >= 0 or "}" in template.replace("{item_key}", ""):
            raise _fail(
                "publication.invalid_slot_template",
                f"Binding {binding_id!r} slot_template must contain exactly one item_key field.",
            )


def _validate_components(binding: Mapping[str, Any], output_ids: tuple[str, ...]) -> None:
    binding_id = str(binding["binding_id"])
    raw_components = binding.get("components")
    if (
        isinstance(raw_components, (str, bytes))
        or not isinstance(raw_components, Sequence)
        or len(raw_components) < 2
    ):
        raise _fail(
            "publication.invalid_bundle_components",
            f"Bundle {binding_id!r} requires at least two named components.",
        )
    component_names: set[str] = set()
    component_outputs: list[str] = []
    for raw in raw_components:
        component = _mapping(raw, f"{binding_id} component")
        if set(component) != {"component_name", "output_id"}:
            raise _fail(
                "publication.invalid_bundle_components",
                f"Bundle {binding_id!r} component shape is not exact.",
            )
        name = _text(component["component_name"], "component_name")
        output_id = _text(component["output_id"], "component output_id")
        if name in component_names or output_id in component_outputs:
            raise _fail(
                "publication.duplicate_bundle_component",
                f"Bundle {binding_id!r} repeats a component name or output.",
            )
        component_names.add(name)
        component_outputs.append(output_id)
    if tuple(component_outputs) != output_ids:
        raise _fail(
            "publication.bundle_output_mismatch",
            f"Bundle {binding_id!r} components must exactly follow output_ids order.",
        )


def _validate_outputs(
    outputs: Mapping[str, RegisteredValidatedOutput],
) -> Mapping[str, RegisteredValidatedOutput]:
    if not isinstance(outputs, Mapping):
        raise _fail(
            "publication.invalid_outputs",
            "outputs must map contract output IDs to validated outputs.",
        )
    normalized: dict[str, RegisteredValidatedOutput] = {}
    for output_id, output in outputs.items():
        if type(output) is not RegisteredValidatedOutput:
            raise _fail(
                "publication.invalid_output_type",
                f"Output {output_id!r} is not a RegisteredValidatedOutput.",
            )
        if output_id != output.contract_output_id:
            raise _fail(
                "publication.output_key_mismatch",
                f"Output key {output_id!r} does not match its contract output ID.",
            )
        normalized[output_id] = output
    return normalized


def _validate_transforms(
    transforms: Mapping[str, PreparedPublisherTransform],
) -> Mapping[str, PreparedPublisherTransform]:
    if not isinstance(transforms, Mapping):
        raise _fail(
            "publication.invalid_transforms",
            "prepared_transforms must be a binding-to-transform mapping.",
        )
    normalized: dict[str, PreparedPublisherTransform] = {}
    for binding_id, transform in transforms.items():
        if type(transform) is not PreparedPublisherTransform:
            raise _fail(
                "publication.invalid_transform_type",
                f"Transform {binding_id!r} has the wrong type.",
            )
        if binding_id != transform.publication_binding_id:
            raise _fail(
                "publication.transform_key_mismatch",
                f"Transform key {binding_id!r} does not match its binding ID.",
            )
        normalized[binding_id] = transform
    return normalized


def _materialize_writes(
    *,
    project_id: str,
    run_id: str,
    phase: str,
    bindings: Sequence[Mapping[str, Any]],
    outputs: Mapping[str, RegisteredValidatedOutput],
    expected_head: FrozenPublicationHead,
    slot_scope_prefix: str | None,
    slot_resolver: SlotResolver | None,
    prepared_transforms: Mapping[str, PreparedPublisherTransform],
) -> tuple[tuple[_CurrentWrite, ...], tuple[_CollectionWrite, ...]]:
    required_outputs = {
        output_id for binding in bindings for output_id in binding["output_ids"]
    }
    supplied_outputs = set(outputs)
    if supplied_outputs != required_outputs:
        raise _fail(
            "publication.output_coverage_mismatch",
            f"Publication requires {sorted(required_outputs)}, received {sorted(supplied_outputs)}.",
        )
    index_bindings = {
        str(binding["binding_id"])
        for binding in bindings
        if binding["publisher_transform"] == "deterministic_index"
    }
    if set(prepared_transforms) != index_bindings:
        raise _fail(
            "publication.transform_coverage_mismatch",
            f"Prepared index transforms must exactly cover {sorted(index_bindings)}.",
        )
    current: list[_CurrentWrite] = []
    collection: list[_CollectionWrite] = []
    seen_slots: set[str] = set()
    seen_items: set[tuple[str, str]] = set()
    for binding in bindings:
        binding_id = str(binding["binding_id"])
        operation = str(binding["operation"])
        target = binding["target"]
        output_ids = tuple(str(item) for item in binding["output_ids"])
        if operation == "append":
            for output_id in output_ids:
                output = outputs[output_id]
                documents = (
                    tuple(output.document)
                    if type(output.document) is list
                    else (output.document,)
                )
                for document in documents:
                    if type(document) is not dict:
                        raise _fail(
                            "publication.invalid_collection_item",
                            f"Append output {output_id!r} must be an object or an array of objects.",
                        )
                    document_sha256 = _canonical_digest(document, output_id)
                    item_id = _deterministic_id(
                        "collection_item",
                        {
                            "project_id": project_id,
                            "collection_key": target["collection_id"],
                            "object_type": target["object_type"],
                            "content_sha256": document_sha256,
                        },
                    )
                    key = (str(target["collection_id"]), item_id)
                    if key in seen_items:
                        raise _fail(
                            "publication.duplicate_collection_item",
                            f"Binding materialization repeats collection item {item_id!r}.",
                        )
                    seen_items.add(key)
                    collection.append(
                        _CollectionWrite(
                            binding_id=binding_id,
                            collection_key=str(target["collection_id"]),
                            object_type=str(target["object_type"]),
                            item_id=item_id,
                            document=document,
                            document_sha256=document_sha256,
                            artifact=output.artifact,
                            source_output_id=output_id,
                        )
                    )
            continue

        if operation == "upsert_each":
            if len(output_ids) != 1:
                raise _fail(
                    "publication.invalid_keyed_output_count",
                    f"Keyed binding {binding_id!r} requires exactly one array output.",
                )
            output = outputs[output_ids[0]]
            if type(output.document) is not list:
                raise _fail(
                    "publication.invalid_keyed_output",
                    f"Keyed binding {binding_id!r} requires an array of method records.",
                )
            for item in output.document:
                if type(item) is not dict:
                    raise _fail(
                        "publication.invalid_keyed_item",
                        f"Keyed binding {binding_id!r} contains a non-object item.",
                    )
                item_key = _pointer_value(item, str(target["item_key_pointer"]))
                if type(item_key) is not str or _SAFE_ITEM_KEY.fullmatch(item_key) is None:
                    raise _fail(
                        "publication.invalid_item_key",
                        f"Keyed binding {binding_id!r} resolved an unsafe item key.",
                    )
                slot_key = str(target["slot_template"]).replace("{item_key}", item_key)
                _safe_slot(slot_key)
                prior = _expected_generation(
                    expected_head, slot_key, str(binding["prior_target_policy"])
                )
                document_sha256 = _canonical_digest(item, output_ids[0])
                generation_id = _generation_id(
                    project_id=project_id,
                    run_id=run_id,
                    binding_id=binding_id,
                    slot_key=slot_key,
                    record_type=str(target["record_type"]),
                    document_sha256=document_sha256,
                    artifact_id=output.artifact.artifact_id,
                )
                _append_current(
                    current,
                    seen_slots,
                    _CurrentWrite(
                        binding_id=binding_id,
                        slot_key=slot_key,
                        record_type=str(target["record_type"]),
                        expected_generation_id=prior,
                        generation_id=generation_id,
                        document=item,
                        document_sha256=document_sha256,
                        artifact=output.artifact,
                        source_output_ids=output_ids,
                    ),
                )
            continue

        slot_key = _resolve_slot(
            phase=phase,
            binding_id=binding_id,
            declared_slot=str(target["slot_id"]),
            record_type=str(target["record_type"]),
            slot_scope_prefix=slot_scope_prefix,
            slot_resolver=slot_resolver,
        )
        prior = _expected_generation(
            expected_head, slot_key, str(binding["prior_target_policy"])
        )
        if operation == "replace":
            if len(output_ids) != 1:
                raise _fail(
                    "publication.invalid_replace_output_count",
                    f"Replace binding {binding_id!r} requires exactly one output.",
                )
            output = outputs[output_ids[0]]
            if binding["publisher_transform"] == "deterministic_index":
                prepared = prepared_transforms[binding_id]
                if prepared.transform != "deterministic_index":
                    raise _fail(
                        "publication.transform_kind_mismatch",
                        f"Prepared transform for {binding_id!r} has the wrong kind.",
                    )
                expected_digests = {
                    output_id: outputs[output_id].document_sha256
                    for output_id in output_ids
                }
                if dict(prepared.source_output_sha256) != expected_digests:
                    raise _fail(
                        "publication.stale_transform",
                        f"Prepared transform for {binding_id!r} does not match source outputs.",
                    )
                document: Any = dict(prepared.document)
                artifact = prepared.artifact
            else:
                if type(output.document) is not dict:
                    raise _fail(
                        "publication.invalid_current_record",
                        f"Current-slot output {output_ids[0]!r} must be one object.",
                    )
                document = output.document
                artifact = output.artifact
        else:
            document, artifact = _bundle_document(binding, outputs)
        document_sha256 = _canonical_digest(document, binding_id)
        generation_id = _generation_id(
            project_id=project_id,
            run_id=run_id,
            binding_id=binding_id,
            slot_key=slot_key,
            record_type=str(target["record_type"]),
            document_sha256=document_sha256,
            artifact_id=artifact.artifact_id,
        )
        _append_current(
            current,
            seen_slots,
            _CurrentWrite(
                binding_id=binding_id,
                slot_key=slot_key,
                record_type=str(target["record_type"]),
                expected_generation_id=prior,
                generation_id=generation_id,
                document=document,
                document_sha256=document_sha256,
                artifact=artifact,
                source_output_ids=output_ids,
            ),
        )
    return tuple(current), tuple(collection)


def _bundle_document(
    binding: Mapping[str, Any],
    outputs: Mapping[str, RegisteredValidatedOutput],
) -> tuple[dict[str, Any], RegisteredArtifactMetadata]:
    components = []
    method_identity: dict[str, Any] | None = None
    for component in binding["components"]:
        output = outputs[str(component["output_id"])]
        document = output.document
        if isinstance(document, Mapping) and "method_identity" in document:
            declared_identity = document["method_identity"]
            if not isinstance(declared_identity, Mapping):
                raise _fail(
                    "publication.invalid_bundle_method_identity",
                    f"Bundle component {output.contract_output_id!r} declares a "
                    "non-object method identity.",
                )
            candidate_identity = dict(declared_identity)
            if method_identity is None:
                method_identity = candidate_identity
            elif candidate_identity != method_identity:
                raise _fail(
                    "publication.conflicting_bundle_method_identity",
                    "Bundle components declare conflicting method identities.",
                )
        components.append(
            {
                "component_name": str(component["component_name"]),
                "contract_output_id": output.contract_output_id,
                "document_sha256": output.document_sha256,
                "artifact": output.artifact.to_dict(),
                "document": document,
            }
        )
    bundle = {
        "format": "model-forge.deterministic-bundle",
        "format_version": "1.0.0",
        "publication_binding_id": str(binding["binding_id"]),
        "components": components,
    }
    if method_identity is not None:
        bundle["method_identity"] = method_identity
    return (
        bundle,
        outputs[str(binding["components"][0]["output_id"])].artifact,
    )


def _resolve_slot(
    *,
    phase: str,
    binding_id: str,
    declared_slot: str,
    record_type: str,
    slot_scope_prefix: str | None,
    slot_resolver: SlotResolver | None,
) -> str:
    if slot_resolver is not None:
        try:
            result = slot_resolver(binding_id, declared_slot, record_type)
        except Exception as error:
            raise _fail(
                "publication.slot_resolution_failed",
                f"Slot resolver failed for binding {binding_id!r}: {error}.",
            ) from error
        return _safe_slot(result)
    if slot_scope_prefix is not None:
        return _safe_slot(f"{slot_scope_prefix}/{declared_slot}")
    if phase in _METHOD_PHASES:
        raise _fail(
            "publication.method_slot_scope_required",
            f"Method-bound phase {phase} requires an explicit slot scope or resolver.",
        )
    return _safe_slot(declared_slot)


def _expected_generation(
    head: FrozenPublicationHead, slot_key: str, policy: str
) -> str | None:
    if slot_key not in head.current_generations:
        raise _fail(
            "publication.unfrozen_current_slot",
            f"Current slot {slot_key!r} has no frozen expected generation.",
        )
    expected = head.current_generations[slot_key]
    if policy == "must_match_current" and expected is None:
        raise _fail(
            "publication.prior_generation_required",
            f"Current slot {slot_key!r} must have an expected prior generation.",
        )
    return expected


def _append_current(
    writes: list[_CurrentWrite], seen_slots: set[str], write: _CurrentWrite
) -> None:
    if write.slot_key in seen_slots:
        raise _fail(
            "publication.duplicate_current_target",
            f"Current slot {write.slot_key!r} is targeted more than once.",
        )
    seen_slots.add(write.slot_key)
    writes.append(write)


def _generation_id(
    *,
    project_id: str,
    run_id: str,
    binding_id: str,
    slot_key: str,
    record_type: str,
    document_sha256: str,
    artifact_id: str,
) -> str:
    return _deterministic_id(
        "generation",
        {
            "project_id": project_id,
            "run_id": run_id,
            "publication_binding_id": binding_id,
            "slot_key": slot_key,
            "record_type": record_type,
            "document_sha256": document_sha256,
            "artifact_id": artifact_id,
        },
    )


def _authority_event(
    *,
    project_id: str,
    run_id: str,
    command_id: str,
    receipt_id: str,
    binding_id: str,
    event_type: str,
    subject_kind: str,
    subject_id: str,
    target_id: str,
    prior_generation_id: str | None,
    content_sha256: str,
    prior_root_sha256: str,
    sequence: int,
    created_at: str,
) -> tuple[dict[str, Any], str, str]:
    seed: dict[str, Any] = {
        "project_id": project_id,
        "run_id": run_id,
        "command_id": command_id,
        "receipt_id": receipt_id,
        "publication_binding_id": binding_id,
        "event_sequence": sequence,
        "event_type": event_type,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "target_id": target_id,
        "prior_generation_id": prior_generation_id,
        "subject_content_sha256": content_sha256,
        "prior_event_root_sha256": prior_root_sha256,
        "created_at": created_at,
    }
    event_id = _deterministic_id("authority_event", seed)
    content = dict(seed)
    content["event_id"] = event_id
    event_sha256 = _canonical_digest(content, event_id)
    event_root_sha256 = hashlib.sha256(
        bytes.fromhex(prior_root_sha256) + bytes.fromhex(event_sha256)
    ).hexdigest()
    event = dict(content)
    event["content_sha256"] = event_sha256
    event["event_root_sha256"] = event_root_sha256
    return event, event_sha256, event_root_sha256


def _current_intent(write: _CurrentWrite) -> dict[str, Any]:
    return {
        "binding_id": write.binding_id,
        "slot_key": write.slot_key,
        "record_type": write.record_type,
        "expected_generation_id": write.expected_generation_id,
        "generation_id": write.generation_id,
        "document_sha256": write.document_sha256,
        "artifact_id": write.artifact.artifact_id,
        "source_output_ids": list(write.source_output_ids),
    }


def _collection_intent(write: _CollectionWrite) -> dict[str, Any]:
    return {
        "binding_id": write.binding_id,
        "collection_key": write.collection_key,
        "object_type": write.object_type,
        "item_id": write.item_id,
        "document_sha256": write.document_sha256,
        "artifact_id": write.artifact.artifact_id,
        "source_output_id": write.source_output_id,
    }


def _pointer_value(document: Mapping[str, Any], pointer: str) -> Any:
    value: Any = document
    for token in _parse_pointer(pointer):
        if not isinstance(value, Mapping) or token not in value:
            raise _fail(
                "publication.item_key_missing",
                f"Item key pointer {pointer!r} does not resolve exactly.",
            )
        value = value[token]
    return value


def _parse_pointer(pointer: str) -> tuple[str, ...]:
    if type(pointer) is not str or not pointer.startswith("/"):
        raise _fail(
            "publication.invalid_item_key_pointer",
            "item_key_pointer must be a nonempty JSON Pointer.",
        )
    tokens = []
    for raw in pointer[1:].split("/"):
        offset = 0
        while offset < len(raw):
            if raw[offset] == "~" and (
                offset + 1 >= len(raw) or raw[offset + 1] not in "01"
            ):
                raise _fail(
                    "publication.invalid_item_key_pointer",
                    f"JSON Pointer {pointer!r} contains an invalid escape.",
                )
            offset += 2 if raw[offset] == "~" else 1
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _deterministic_id(kind: str, value: Any) -> str:
    return f"{kind}.{_canonical_digest(value, kind)}"


def _canonical_digest(value: Any, label: str) -> str:
    try:
        return hashlib.sha256(canonicalize(value)).hexdigest()
    except JCSCanonicalizationError as error:
        raise _fail(
            "publication.noncanonical_json",
            f"{label} is outside the supported canonical JSON domain: {error}.",
        ) from error


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
        raise _fail(
            "publication.invalid_object", f"{label} must be a JSON object."
        )
    return value


def _string_array(value: Any, label: str) -> tuple[str, ...]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or not value
    ):
        raise _fail(
            "publication.invalid_string_array", f"{label} must be a nonempty array."
        )
    result = tuple(_text(item, label) for item in value)
    if len(result) != len(set(result)):
        raise _fail(
            "publication.duplicate_array_value", f"{label} contains duplicates."
        )
    return result


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise _fail(
            "publication.invalid_text",
            f"{label} must be nonempty text without NUL characters.",
        )
    return value


def _digest(value: Any, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _fail(
            "publication.invalid_sha256",
            f"{label} must be a lowercase SHA-256 digest.",
        )
    return value


def _safe_slot(value: Any) -> str:
    slot = _text(value, "slot key")
    if "\\" in slot or slot.startswith("/") or slot.endswith("/") or "//" in slot:
        raise _fail(
            "publication.unsafe_slot",
            f"Slot key {slot!r} is not a safe logical path.",
        )
    if any(part in {"", ".", ".."} for part in slot.split("/")):
        raise _fail(
            "publication.unsafe_slot",
            f"Slot key {slot!r} contains an unsafe path component.",
        )
    if "{" in slot or "}" in slot:
        raise _fail(
            "publication.unresolved_slot_template",
            f"Slot key {slot!r} still contains a template field.",
        )
    return slot


def _fail(code: str, message: str) -> PublicationError:
    return PublicationError(code, message)


__all__ = [
    "ContractPublicationService",
    "FrozenPublicationHead",
    "PreparedPublisherTransform",
    "PublicationError",
    "PublicationResult",
    "RegisteredArtifactMetadata",
    "RegisteredValidatedOutput",
    "SlotResolver",
]
