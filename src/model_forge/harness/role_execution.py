"""Durable lifecycle for one already-frozen scientific role invocation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, thaw_json, utc_now
from ..domain.validation import (
    FindingClass,
    OutputTransformationRecord,
    TransformationEntry,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    registry_version,
)
from ..executors import (
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleExecutor,
    RoleInvocation,
)
from ..json_io import loads_json
from ..schemas import SchemaCatalog
from ..storage import ArtifactStore, WorkspacePaths
from ..storage.repository import (
    HubRepository,
    RepositoryConflictError,
)
from ..capabilities.broker import CapabilityBroker
from ..domain.identities import SCHEMA_VERSION
from .envelope import SealedRunFacts, harness_owned_fields, populate_harness_fields
from .execution_context import RunExecutionContext
from .output_adapters import AdaptedOutput, DefaultOutputAdapter
from .outputs import OutputPlan, OutputSpec, validate_role_outputs
from .task_briefs import render_task_brief


from .execution_observer import RepositoryExecutionObserver as _RepositoryObserver

logger = logging.getLogger(__name__)
from .execution_records import (
    FrozenInputPath,
    RoleClosureResult,
    RoleExecutionInfrastructureError,
    RoleExecutionPending,
    RoleLifecycleError,
    SealedRoleOutput,
    closure_artifact_id as _closure_artifact_id,
    deterministic_id,
    document_sha256,
    immutable_write as _immutable_write,
    output_artifact_id as _output_artifact_id,
    role_identity as _role_identity,
)


def _apply_disclosed_mechanical_repairs(
    *,
    run_root: Path,
    output_plan: OutputPlan,
    stage: ResolvedStage,
    role: str,
    run_id: str = "",
    project_id: str = "",
    run_facts: "SealedRunFacts | None" = None,
    record_type_by_output: Mapping[str, str] | None = None,
    canonical_source_lookup: "Callable[[str], str | None] | None" = None,
    schemas_dir: Path | None = None,
) -> dict[str, "OutputTransformationRecord"]:
    """Apply mechanical repairs to agent outputs and record every change.

    Returns a mapping of ``contract_output_id`` → ``OutputTransformationRecord``
    capturing source digest, result digest, and classified transformation
    entries.  The repaired data is written to disk so that downstream
    validation reads the candidate, not the raw bytes.

    When ``run_facts`` is given, harness-owned envelope fields (HV-4) are
    populated from sealed run facts BEFORE the repair heuristics run, so the
    source digest stays the agent's raw bytes and the transformation record
    captures population as classified entries.  ``record_type_by_output``
    maps contract output IDs to their publication-binding record types.
    """
    from copy import deepcopy
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()
    specs = output_plan.for_stage_role(stage.stage_id, role)
    records: dict[str, OutputTransformationRecord] = {}
    pointer_context = _OutputPointerContext(
        project_id=project_id,
        run_id=run_id,
        run_root=run_root,
        specs=specs,
        canonical_source_lookup=canonical_source_lookup,
    )

    if run_facts is not None and not run_facts.produced_at:
        # One closure timestamp for every populated field: per-spec
        # timestamps would let a later spec (e.g. p4.protocol) carry a LATER
        # finalized_at than an earlier one (p4.evidence created_at), which
        # reads as a false prespecification violation
        # (p4.protocol_finalized_after_evidence).
        from dataclasses import replace as _hoist_replace

        run_facts = _hoist_replace(run_facts, produced_at=ts)

    for spec in specs:
        path = run_root / spec.relative_path
        if not path.exists():
            continue
        try:
            import json as _json

            text = path.read_text()
            data = _json.loads(text)
        except Exception:
            continue

        # Compute source digest from the raw file bytes.
        source_bytes = text.encode("utf-8")
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()

        # Snapshot BEFORE population so the transformation record covers
        # both harness-field population (HV-4) and repair heuristics.
        raw_snapshot = deepcopy(data)
        populated = False

        # HV-4: populate harness-owned fields from sealed run facts.  The
        # source digest and raw snapshot remain the agent's raw content.
        if run_facts is not None:
            from dataclasses import replace as _replace_facts

            facts = run_facts
            record_type = (record_type_by_output or {}).get(
                spec.contract_output_id, ""
            )
            if not record_type:
                # F-1c: contract-declared record_type on the output spec
                # (p3.analyst_audit, p4.analyst_synthesis, p4.theory_audit -
                # scientific-record candidates outside publication bindings).
                record_type = spec.record_type or ""
            if not record_type:
                # F-1b: candidate outputs not named in any publication
                # binding still carry the harness-owned record_type;
                # derive it from the schema's const (mechanical, never
                # agent-authored) - production hole observed on
                # p3.theory_candidate (run 7af5a339, 2026-08-25).
                record_type = _schema_record_type_const(
                    spec.schema_file, schemas_dir=schemas_dir
                )
            if record_type:
                facts = _replace_facts(run_facts, record_type=record_type)
            if isinstance(data, dict):
                data = populate_harness_fields(data, facts, spec.schema_file)
            elif isinstance(data, list):
                data = [
                    populate_harness_fields(item, facts, spec.schema_file, item_index=i)
                    if isinstance(item, dict)
                    else item
                    for i, item in enumerate(data)
                ]
            # Population returns new objects; any difference must be
            # persisted even when the repair heuristics below change nothing.
            populated = data != raw_snapshot

        schema_info = _schema_info(spec.schema_file, schemas_dir=schemas_dir)
        valid_timestamps = schema_info["timestamps"]
        allowed_props = schema_info["properties"]
        no_additional = schema_info["no_additional"]
        required_fields = schema_info["required"]
        nested_required = schema_info.get("nested_required", set())
        nested_timestamps = schema_info.get("nested_timestamps", set())
        # When the schema declares no timestamps and no
        # additionalProperties:false, no per-item repair applies — but ID
        # sanitization (ISS-7) must still run.  The old early-continue here
        # skipped it entirely for exactly those schemas, which let
        # pattern-invalid stableIds survive repair in production.
        skip_item_repairs = not valid_timestamps and not (no_additional and allowed_props)

        def _fix_item(item: dict) -> bool:
            changed = False
            for field in valid_timestamps:
                if field not in item:
                    item[field] = ts
                    changed = True
            if "schema_version" in allowed_props and "schema_version" not in item:
                item["schema_version"] = SCHEMA_VERSION
                changed = True
            identity = item.get("identity")
            if isinstance(identity, dict):
                version = identity.get("version")
                if (
                    isinstance(version, bool)
                    or not isinstance(version, (int, float))
                    or version < 1
                ):
                    identity["version"] = 1
                    changed = True
            if no_additional and allowed_props:
                for key in list(item.keys()):
                    if key not in allowed_props:
                        del item[key]
                        changed = True
            for key in list(item.keys()):
                if item[key] is None and key not in required_fields:
                    del item[key]
                    changed = True
            return changed

        changed = False
        if not skip_item_repairs:
            if isinstance(data, dict):
                changed = _fix_item(data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if _fix_item(item):
                            changed = True
        # ISS-7: sanitize stableId values at exactly the positions the
        # schema pattern-checks — for EVERY successfully parsed output
        # document, even when no other repair applies — then rewrite
        # same-valued references document-wide so sanitizing a definition
        # site never leaves dangling cross-references.
        id_coverage = _stableid_positions(spec.schema_file, schemas_dir=schemas_dir)
        id_renames: dict[str, str] = {}
        if _deep_sanitize_ids(data, id_coverage, renames=id_renames):
            changed = True
        if _rewrite_id_references(data, id_renames):
            changed = True
        if not skip_item_repairs:
            all_required = required_fields | nested_required
            if _strip_empty_strings(data, required_fields=all_required):
                changed = True
            if _add_missing_timestamps(data, nested_timestamps, ts):
                changed = True
            if _fix_self_referential_hashes(data, path, pointer_context=pointer_context):
                changed = True

        # Build transformation entries by diffing raw vs repaired.
        entries = _classify_transformations(raw_snapshot, data, renames=id_renames, harness_owned=harness_owned_fields(spec.schema_file))

        if changed or populated:
            repaired_text = _json.dumps(data, indent=2, ensure_ascii=False)
            path.write_text(repaired_text)
            result_bytes = repaired_text.encode("utf-8")
            result_sha256 = hashlib.sha256(result_bytes).hexdigest()
        else:
            result_sha256 = source_sha256

        records[spec.contract_output_id] = OutputTransformationRecord(
            contract_output_id=spec.contract_output_id,
            source_sha256=source_sha256,
            result_sha256=result_sha256,
            entries=tuple(entries),
            primary_artifact_unchanged=_primary_artifact_unchanged(entries),
        )

    return records


_GENERATION_IDENTITY_FIELDS = frozenset(
    {"generation_id", "generation_number", "review_basis_generation_id"}
)


def _classify_transformations(
    raw: Any,
    repaired: Any,
    pointer: str = "",
    *,
    renames: Mapping[str, str] | None = None,
    harness_owned: frozenset[str] = frozenset(),
) -> list[TransformationEntry]:
    """Diff the raw snapshot against the repaired data, classifying changes.

    Walks both trees in parallel and emits a TransformationEntry for each
    difference found.  The codes identify what kind of mechanical repair
    occurred at each location.  *renames* is the exact old→new identifier
    map produced by ``_deep_sanitize_ids``: any changed string whose raw
    value is a rename source is an ``id_sanitization`` (definition-site
    sanitization or same-valued reference rewrite), never a generic
    ``value_rewrite``.

    *harness_owned* is the schema's harness-owned field set.  Top-level
    removals of harness-owned generation-identity fields are recorded as
    ``generation_identity_strip`` (not null/empty-string/additional-
    properties strips), and top-level overwrites of harness-owned fields
    are recorded as ``harness_population_overwrite`` (not ``value_rewrite``).
    """
    entries: list[TransformationEntry] = []
    id_renames = renames or {}

    # Fast path: identical objects mean no changes.
    if raw == repaired:
        return entries

    _TS_SUFFIXES = ("_at", "_timestamp", "_time")

    def _walk(raw_obj: Any, rep_obj: Any, ptr: str) -> None:
        if raw_obj == rep_obj:
            return
        if isinstance(raw_obj, dict) and isinstance(rep_obj, dict):
            raw_keys = set(raw_obj.keys())
            rep_keys = set(rep_obj.keys())
            # Keys removed from repaired (stripped/deleted)
            for key in sorted(raw_keys - rep_keys):
                child_ptr = f"{ptr}/{key}"
                if not ptr and key in _GENERATION_IDENTITY_FIELDS and key in harness_owned:
                    entries.append(TransformationEntry(
                        code="generation_identity_strip",
                        json_pointer=child_ptr,
                        detail=f"stripped agent-fabricated generation identity '{key}'",
                    ))
                elif key.endswith("_at") or key.endswith("_timestamp") or key.endswith("_time"):
                    if raw_obj[key] is None:
                        entries.append(TransformationEntry(
                            code="null_strip",
                            json_pointer=child_ptr,
                            detail=f"removed null optional field '{key}'",
                        ))
                    else:
                        entries.append(TransformationEntry(
                            code="additional_properties_strip",
                            json_pointer=child_ptr,
                            detail=f"removed undeclared field '{key}'",
                        ))
                elif raw_obj[key] is None:
                    entries.append(TransformationEntry(
                        code="null_strip",
                        json_pointer=child_ptr,
                        detail=f"removed null optional field '{key}'",
                    ))
                elif isinstance(raw_obj[key], str) and raw_obj[key] == "":
                    entries.append(TransformationEntry(
                        code="empty_string_strip",
                        json_pointer=child_ptr,
                        detail=f"removed empty-string field '{key}'",
                    ))
                else:
                    entries.append(TransformationEntry(
                        code="additional_properties_strip",
                        json_pointer=child_ptr,
                        detail=f"removed undeclared field '{key}'",
                    ))
            # Keys added to repaired (injected)
            for key in sorted(rep_keys - raw_keys):
                child_ptr = f"{ptr}/{key}"
                if any(key.endswith(s) for s in _TS_SUFFIXES):
                    entries.append(TransformationEntry(
                        code="timestamp_injection",
                        json_pointer=child_ptr,
                        detail=f"injected missing timestamp '{key}'",
                    ))
                elif key == "schema_version":
                    entries.append(TransformationEntry(
                        code="schema_version_injection",
                        json_pointer=child_ptr,
                        detail="injected missing schema_version",
                    ))
                else:
                    entries.append(TransformationEntry(
                        code="field_injection",
                        json_pointer=child_ptr,
                        detail=f"injected field '{key}'",
                    ))
            # Keys present in both — recurse or classify value change
            for key in sorted(raw_keys & rep_keys):
                child_ptr = f"{ptr}/{key}"
                rv = raw_obj[key]
                pv = rep_obj[key]
                if rv == pv:
                    continue
                if isinstance(rv, (dict, list)) and isinstance(pv, (dict, list)):
                    _walk(rv, pv, child_ptr)
                elif (
                    isinstance(rv, str)
                    and rv in id_renames
                    and pv == id_renames[rv]
                ):
                    entries.append(TransformationEntry(
                        code="id_sanitization",
                        json_pointer=child_ptr,
                        detail=f"sanitized identifier '{key}': {rv} → {pv}",
                    ))
                elif key in ("content_sha256", "definition_sha256") or (
                    key == "sha256" and ptr.endswith("/handoff_artifact")
                ):
                    entries.append(TransformationEntry(
                        code="hash_recomputation",
                        json_pointer=child_ptr,
                        detail=f"recomputed self-referential hash '{key}'",
                    ))
                elif key == "version" and ptr.endswith("/identity"):
                    entries.append(TransformationEntry(
                        code="identity_version_bump",
                        json_pointer=child_ptr,
                        detail=f"bumped identity.version: {rv} → {pv}",
                    ))
                elif not ptr and key in harness_owned:
                    entries.append(TransformationEntry(
                        code="harness_population_overwrite",
                        json_pointer=child_ptr,
                        detail=f"harness-populated field '{key}': {rv!r} → {pv!r}",
                    ))
                else:
                    entries.append(TransformationEntry(
                        code="value_rewrite",
                        json_pointer=child_ptr,
                        detail=f"changed '{key}': {rv!r} → {pv!r}",
                    ))
        elif isinstance(raw_obj, list) and isinstance(rep_obj, list):
            max_len = max(len(raw_obj), len(rep_obj))
            for i in range(max_len):
                child_ptr = f"{ptr}/{i}"
                if i < len(raw_obj) and i < len(rep_obj):
                    if raw_obj[i] != rep_obj[i]:
                        _walk(raw_obj[i], rep_obj[i], child_ptr)
                # Length changes are rare for mechanical repair; skip detail.
        # Scalar mismatch that wasn't caught above (e.g. type changed)
        elif raw_obj != rep_obj:
            if (
                isinstance(raw_obj, str)
                and raw_obj in id_renames
                and rep_obj == id_renames[raw_obj]
            ):
                entries.append(TransformationEntry(
                    code="id_sanitization",
                    json_pointer=ptr,
                    detail=(
                        f"sanitized identifier: {raw_obj} → {rep_obj}"
                    ),
                ))
            else:
                entries.append(TransformationEntry(
                    code="value_rewrite",
                    json_pointer=ptr,
                    detail=f"{raw_obj!r} → {rep_obj!r}",
                ))

    _walk(raw, repaired, pointer)
    return entries


def _primary_artifact_unchanged(
    entries: Iterable[TransformationEntry],
) -> bool:
    """True only when every transformation was a digest recomputation.

    The primary artifact counts as unchanged only when the repair pass
    touched nothing but self-referential hash fields (``hash_recomputation``).
    Any other entry — id sanitization, value rewrites, timestamp/field
    injection, strips, version bumps — alters content the agent authored,
    so the primary artifact is no longer byte-identical in substance.
    """
    return all(entry.code == "hash_recomputation" for entry in entries)


def apply_normalize_transformations(
    data: Any,
    *,
    spec: OutputSpec,
    codes: frozenset[str] | set[str],
    ts: str,
    path: Path,
    renames: dict[str, str] | None = None,
    schemas_dir: Path | None = None,
) -> bool:
    """Apply a selected subset of the role lane's mechanical repairs in place.

    This is the K-1b *normalize* correction-lane primitive: it reuses the
    exact role-lane repair helpers (``_deep_sanitize_ids``,
    ``_rewrite_id_references``, ``_strip_empty_strings``,
    ``_add_missing_timestamps``, ``_fix_self_referential_hashes``) and mirrors
    the structure of ``_apply_disclosed_mechanical_repairs``, but gates every
    repair block on membership in *codes*.  The role lane's monolith is
    untouched and remains byte-identical in behaviour.

    *data* is the already-parsed JSON document (dict or list); it is mutated
    in place.  *ts* is the caller-supplied injection timestamp; *path* is the
    output file path (used only by ``_fix_self_referential_hashes``).
    *renames* is an optional caller-supplied out-param: when provided, it is
    passed to ``_deep_sanitize_ids`` so the caller receives the exact
    old→new identifier map (for ``_classify_transformations``); the default
    ``None`` keeps the previous behaviour of a fresh internal dict.

    The caller MUST pre-validate *codes* against
    ``application.correction.ALLOWED_NORMALIZE_CODES``; this function does not
    validate them itself (importing the application layer here would risk an
    import cycle).  The monolith's ``identity.version`` bump is NEVER applied:
    ``identity_version_bump`` is not an allowlisted normalize code, so that
    block is omitted entirely.

    Returns True iff any transformation changed *data*.
    """
    schema_info = _schema_info(spec.schema_file, schemas_dir=schemas_dir)
    valid_timestamps = schema_info["timestamps"]
    allowed_props = schema_info["properties"]
    no_additional = schema_info["no_additional"]
    required_fields = schema_info["required"]
    nested_required = schema_info.get("nested_required", set())
    nested_timestamps = schema_info.get("nested_timestamps", set())
    # Same rule as the role lane: when the schema declares no timestamps and
    # no additionalProperties:false, no per-item repair applies — but ID
    # sanitization must still run.
    skip_item_repairs = not valid_timestamps and not (no_additional and allowed_props)

    def _fix_item(item: dict) -> bool:
        changed = False
        if "timestamp_injection" in codes:
            for field in valid_timestamps:
                if field not in item:
                    item[field] = ts
                    changed = True
        if (
            "schema_version_injection" in codes
            and "schema_version" in allowed_props
            and "schema_version" not in item
        ):
            item["schema_version"] = SCHEMA_VERSION
            changed = True
        # identity.version bump deliberately omitted: identity_version_bump
        # is not an allowlisted normalize code.
        if "additional_properties_strip" in codes and no_additional and allowed_props:
            for key in list(item.keys()):
                if key not in allowed_props:
                    del item[key]
                    changed = True
        if "null_strip" in codes:
            for key in list(item.keys()):
                if item[key] is None and key not in required_fields:
                    del item[key]
                    changed = True
        return changed

    changed = False
    if not skip_item_repairs:
        if isinstance(data, dict):
            changed = _fix_item(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if _fix_item(item):
                        changed = True
    # ID sanitization runs even when skip_item_repairs (same as the monolith).
    if "id_sanitization" in codes:
        id_coverage = _stableid_positions(spec.schema_file, schemas_dir=schemas_dir)
        renames = {} if renames is None else renames
        if _deep_sanitize_ids(data, id_coverage, renames=renames):
            changed = True
        if _rewrite_id_references(data, renames):
            changed = True
    if not skip_item_repairs:
        if "empty_string_strip" in codes:
            if _strip_empty_strings(data, required_fields=required_fields | nested_required):
                changed = True
        if "timestamp_injection" in codes:
            if _add_missing_timestamps(data, nested_timestamps, ts):
                changed = True
        if "hash_recomputation" in codes:
            if _fix_self_referential_hashes(data, path):
                changed = True
    return changed


def _add_missing_timestamps(
    data: Any, timestamp_map: dict[str, set[str]], ts: str
) -> bool:
    """Add missing timestamp fields at schema-declared locations only.

    *timestamp_map* maps parent property names to the set of timestamp
    fields declared inside that property's object definition.  We only
    inject a timestamp into a dict that is the value of a known parent
    key — never into arbitrary nested objects.
    """
    if not timestamp_map:
        return False

    changed = False

    def _walk(obj: Any, parent_key: str | None = None) -> None:
        nonlocal changed
        if isinstance(obj, dict):
            # Only inject timestamps when we descended through a known
            # parent key (e.g. "alignment_assessment").
            if parent_key and parent_key in timestamp_map:
                for field in timestamp_map[parent_key]:
                    if field not in obj:
                        obj[field] = ts
                        changed = True
            for key, val in obj.items():
                if isinstance(val, (dict, list)):
                    _walk(val, parent_key=key)
        elif isinstance(obj, list):
            # For arrays, propagate the parent key — each element inherits
            # the context of the array property.
            for item in obj:
                if isinstance(item, (dict, list)):
                    _walk(item, parent_key=parent_key)

    _walk(data, parent_key=None)
    return changed


def _strip_empty_strings(
    data: Any, *, required_fields: set[str] | None = None
) -> bool:
    """Remove empty-string values for optional fields.

    JSON Schema uses ``minLength: 1`` to require non-empty strings, but agents
    sometimes write ``""`` for optional fields instead of omitting them.  Walk
    the tree and delete any key whose value is an empty string, so validation
    passes for optional fields that the agent left blank.  Keys declared
    ``required`` by the schema (top-level or nested) are never stripped —
    deleting them would turn a minLength error into a missing-required error.
    """
    # Fields that must never be stripped even if empty.  Schema-required
    # fields are added to this set so a required field with an empty value
    # still reaches validation, which reports the precise minLength failure.
    _KEEP = set(required_fields or ())

    def _walk(obj: Any) -> bool:
        changed = False
        if isinstance(obj, dict):
            # Two-pass: first recurse, then delete empty strings
            for val in obj.values():
                if isinstance(val, (dict, list)):
                    if _walk(val):
                        changed = True
            to_delete = [
                k
                for k, v in obj.items()
                if k not in _KEEP and isinstance(v, str) and v == ""
            ]
            for k in to_delete:
                del obj[k]
                changed = True
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    if _walk(item):
                        changed = True
        return changed

    return _walk(data)


_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_HASH_PLACEHOLDERS = frozenset({
    "tbd_by_model_forge_on_write", "tbd", "placeholder",
    "<...>", "...", "n/a", "todo",
})


def _is_placeholder_hash(value: str) -> bool:
    """Return True if a sha256 value is a placeholder or invalid, not a real hash.

    A valid 64-char lowercase hex string that is NOT in the known placeholder
    set is assumed to be agent-authored (fabricated but pattern-valid).  We
    still re-stamp it so the stored hash is authoritative, not decorative.
    The hash-paradox is fundamental: an agent cannot know the hash of the file
    it is writing, so every hash field is treated as needing computation.
    """
    return True  # Always recompute — agents cannot produce correct self-referential hashes.


def _compute_content_hash(data: Any, exclude_keys: set[str]) -> str:
    """Compute the digest-contract hash of *data* with *exclude_keys* removed.

    Uses RFC 8785 canonicalization (``digests.jcs.canonicalize``) as required
    by ``digest-contracts.json`` (``construction: rfc8785_sha256``).  Plain
    ``json.dumps(sort_keys=True)`` is NOT equivalent: it inserts whitespace
    separators and serializes values differently, so hashes stamped from it
    never match the registered digest contract.
    """

    def _scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _scrub(v)
                for k, v in obj.items()
                if k not in exclude_keys
            }
        if isinstance(obj, list):
            return [_scrub(item) for item in obj]
        return obj

    return hashlib.sha256(canonicalize(_scrub(data))).hexdigest()


class _OutputPointerContext:
    """Resolve ``output://<filename>`` representation pointers (E-2).

    Maps a sibling output filename to its contract output id and the sha256
    of its current on-disk bytes. The repair pass writes each repaired
    output immediately, so contract declaration order controls which bytes
    a pointer sees: compact views are declared before the records that
    reference them.
    """

    def __init__(
        self,
        *,
        project_id: str,
        run_id: str,
        run_root: Path,
        specs: Sequence[Any],
        canonical_source_lookup: "Callable[[str], str | None] | None" = None,
    ) -> None:
        self.project_id = project_id
        self.run_id = run_id
        self._run_root = run_root
        self._by_filename = {
            Path(spec.relative_path).name: spec for spec in specs
        }
        # E-2e: digest -> artifact_id resolution for canonical_artifact
        # input:// pointers (None in contexts without artifact rows).
        self.canonical_source_lookup = canonical_source_lookup

    def locate(self, filename: str) -> tuple[Any, Path] | None:
        """Map a declared output filename to its spec and on-disk path."""
        spec = self._by_filename.get(filename)
        if spec is None:
            return None
        return spec, self._run_root / spec.relative_path

    def resolve(self, filename: str) -> tuple[str, str] | None:
        located = self.locate(filename)
        if located is None:
            return None
        spec, path = located
        if not path.exists():
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return str(spec.contract_output_id), digest


def _stamp_output_pointer(
    artifact: dict,
    *,
    pointer_context: _OutputPointerContext,
    path: Path,
) -> bool:
    """Stamp one ``output://<filename>`` pointer with verified bytes (E-2).

    Stamps the real artifact_id, uri, and sha256 of the target output's
    current on-disk bytes.  When the target IS the file currently being
    repaired (a primary_artifact self-pointer, E-2d), stamping the digest
    of those bytes would dangle: the repair pass rewrites the file with
    the stamped pointer inside, so the sealed bytes differ from the hashed
    bytes.  For that case the exact hashed bytes are first preserved to a
    ``<filename>.as-authored`` sidecar in the same directory and the
    pointer carries the ``<contract_output_id>.as_authored`` artifact
    identity that output sealing registers for the sidecar, so the stamped
    pointer resolves to hash-verified artifact-store bytes.
    """
    uri = artifact.get("uri")
    if not (isinstance(uri, str) and uri.startswith("output://")):
        return False
    located = pointer_context.locate(uri[len("output://"):])
    if located is None:
        return False
    spec, target_path = located
    if not target_path.exists():
        return False
    payload = target_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    output_id = str(spec.contract_output_id)
    if target_path == path:
        sidecar = path.parent / f"{path.name}.as-authored"
        sidecar.write_bytes(payload)
        output_id = f"{output_id}.as_authored"
    stamped_uri = f"artifact://sha256/{digest}"
    stamped_id = deterministic_id(
        "artifact",
        pointer_context.project_id,
        pointer_context.run_id,
        output_id,
        digest,
    )
    if (
        artifact.get("sha256") != digest
        or artifact.get("uri") != stamped_uri
        or artifact.get("artifact_id") != stamped_id
    ):
        artifact["sha256"] = digest
        artifact["uri"] = stamped_uri
        artifact["artifact_id"] = stamped_id
        return True
    return False


def _stamp_canonical_artifact(
    method_record: dict,
    *,
    inputs_dir: Path,
    lookup: "Callable[[str], str | None] | None",
    project_id: str,
    run_id: str,
) -> bool:
    """Stamp one ``input://<filename>`` canonical_artifact pointer (E-2e).

    The agent declares the method record's
    ``mathematical_definition.canonical_artifact`` as
    ``input://<materialized input filename>`` naming the exact
    content-named file in the role's ``inputs/`` directory that the
    canonical definition was taken from, with no artifact_id and no
    sha256.  Materialized inputs are content-named by the sha256 of
    their sealed source bytes, so the closure stamps the real pointer
    mechanically: sha256 of the input file bytes, uri
    ``artifact://sha256/<digest>``, and artifact_id from the artifacts
    table via *lookup* (the sealed role output those bytes came from).
    When the lookup returns None (dev-fixture contexts without artifact
    rows) the artifact_id falls back to a deterministic derivation.  The
    agent's path and locator fields are preserved.  Unresolvable input
    names are left untouched for validation to reject.  Returns True only
    when a field changed.
    """
    mathematical = method_record.get("mathematical_definition")
    if not isinstance(mathematical, dict):
        return False
    artifact = mathematical.get("canonical_artifact")
    if not isinstance(artifact, dict):
        return False
    uri = artifact.get("uri")
    if not (isinstance(uri, str) and uri.startswith("input://")):
        return False
    name = uri[len("input://"):]
    # Basename-only, containment-checked: anything else is left untouched
    # for validation to reject (R19).
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
    ):
        return False
    candidate = inputs_dir / name
    try:
        candidate.resolve().relative_to(inputs_dir.resolve())
    except (OSError, ValueError):
        return False
    if not candidate.is_file():
        return False
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    stamped_uri = f"artifact://sha256/{digest}"
    stamped_id = lookup(digest) if lookup is not None else None
    if not stamped_id:
        stamped_id = deterministic_id(
            "artifact",
            project_id,
            run_id,
            "canonical_source",
            digest,
        )
    if (
        artifact.get("sha256") != digest
        or artifact.get("uri") != stamped_uri
        or artifact.get("artifact_id") != stamped_id
    ):
        artifact["sha256"] = digest
        artifact["uri"] = stamped_uri
        artifact["artifact_id"] = stamped_id
        return True
    return False


def _fix_self_referential_hashes(
    data: Any,
    path: Path,
    pointer_context: "_OutputPointerContext | None" = None,
) -> bool:
    """Compute and stamp all self-referential SHA-256 fields in agent output.

    Agents cannot know the hash of the file they are currently writing.
    This function finds every self-referential hash field and replaces it
    with the correct hash computed from the file content (excluding the
    hash field itself).

    Handles five classes of self-referential hashes:

    1. ``content_sha256`` — top-level field on scientific-record, evidence,
       attention-item, decision-record.  Hash of the entire document minus
       this field.
    2. ``handoff_artifact.sha256`` — nested in handoff records.  Hash of the
       handoff document minus the sha256 sub-field.
    3. ``representations[].artifact`` / top-level ``primary_artifact`` with
       a ``output://<filename>`` uri — layer pointers at declared outputs
       (E-2).  Agents cannot hash their own files, so they declare the
       pointer target by filename and the harness stamps the real
       artifact_id, uri, and sha256 from the target's bytes.  A pointer at
       the record's own output (E-2d) first preserves the exact hashed
       bytes to a ``<filename>.as-authored`` sidecar.  Unresolvable
       pointers are left untouched for validation to reject.
    4. Other ``representations[].artifact`` / ``artifacts[].sha256`` pointer
       hashes — NOT self-referential (they point at previously sealed
       artifacts), so they are left alone.
    5. ``mathematical_definition.canonical_artifact`` with an
       ``input://<filename>`` uri — the method record's canonical pointer
       at a materialized input (E-2e).  Agents cannot know sealed
       digests, so they declare the pointer target by input filename and
       the harness stamps the real artifact_id, uri, and sha256 from the
       input's bytes.  Unresolvable pointers are left untouched for
       validation to reject.

    ``content_sha256`` is recomputed LAST, after the handoff, definition,
    and pointer stamping steps, so the stamped value matches the sealed
    bytes per the ``*.content`` digest contracts
    (``architecture/contracts/digest-contracts.json``): those steps mutate
    the document the digest covers, so an earlier recompute would seal a
    digest of bytes that never existed.
    """
    changed = False

    def _fix_record(obj: dict) -> bool:
        nonlocal changed
        touched = False

        # 1. handoff_artifact.sha256 — recompute from the handoff dict
        ha = obj.get("handoff_artifact")
        if isinstance(ha, dict) and "sha256" in ha:
            snapshot = dict(obj)
            artifact_snapshot = dict(ha)
            artifact_snapshot.pop("sha256", None)
            snapshot["handoff_artifact"] = artifact_snapshot
            correct = hashlib.sha256(canonicalize(snapshot)).hexdigest()
            if ha.get("sha256") != correct:
                ha["sha256"] = correct
                touched = True

        # 2. identity.definition_sha256 — digest contract
        # ``method_record.definition``: payload is
        # ``/mathematical_definition/canonical_definition`` (RFC 8785), and
        # the digest lives at ``/identity/definition_sha256``.  Agents cannot
        # compute the digest of content they are writing (hash paradox), so
        # stamp it whenever the identity object and canonical definition are
        # both present.
        identity = obj.get("identity")
        md = obj.get("mathematical_definition")
        if isinstance(identity, dict) and isinstance(md, dict):
            canonical_definition = md.get("canonical_definition")
            if canonical_definition is not None:
                correct = hashlib.sha256(canonicalize(canonical_definition)).hexdigest()
                if identity.get("definition_sha256") != correct:
                    identity["definition_sha256"] = correct
                    touched = True

        # 3. representations[].artifact and top-level primary_artifact
        # output:// pointers (E-2) — stamp the real pointer to the
        # declared output's bytes.  A pointer at the record's own output
        # (primary_artifact self-pointer, E-2d) first preserves the exact
        # hashed bytes to a <filename>.as-authored sidecar so the stamped
        # pointer resolves to sealed bytes.
        representations = obj.get("representations")
        if (
            pointer_context is not None
            and isinstance(representations, list)
        ):
            for representation in representations:
                if not isinstance(representation, dict):
                    continue
                artifact = representation.get("artifact")
                if not isinstance(artifact, dict):
                    continue
                if _stamp_output_pointer(
                    artifact, pointer_context=pointer_context, path=path
                ):
                    touched = True
        if pointer_context is not None:
            primary = obj.get("primary_artifact")
            if isinstance(primary, dict):
                if _stamp_output_pointer(
                    primary, pointer_context=pointer_context, path=path
                ):
                    touched = True

        # 4. mathematical_definition.canonical_artifact input:// pointers
        # (E-2e) — stamp the real pointer to the materialized input bytes.
        # Materialized inputs live in the role's inputs/ directory (a
        # sibling of the output files inside roles/<NN>-<role>/), derived
        # per output as path.parent.  The existing recursion into the
        # method-changes list covers p2.method_changes records.
        # E-2f: key on mathematical_definition.canonical_artifact alone -
        # an agent identity slip (null identity) must not silently disable
        # stamping; identity problems remain for schema validation.
        if (
            pointer_context is not None
            and isinstance(md, dict)
            and isinstance(md.get("canonical_artifact"), dict)
        ):
            if _stamp_canonical_artifact(
                obj,
                inputs_dir=path.parent / "inputs",
                lookup=pointer_context.canonical_source_lookup,
                project_id=pointer_context.project_id,
                run_id=pointer_context.run_id,
            ):
                touched = True

        # 5. content_sha256 - recompute LAST (hash paradox), after every
        # other stamping step, so the digest covers the sealed document per
        # the *.content digest contracts.
        if "content_sha256" in obj:
            correct = _compute_content_hash(obj, {"content_sha256"})
            if obj.get("content_sha256") != correct:
                obj["content_sha256"] = correct
                touched = True

        return touched

    if isinstance(data, dict):
        if _fix_record(data):
            changed = True
        # Also recurse into nested arrays of records (e.g. evidence list,
        # attention-items list, method-changes list)
        for key, val in data.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and _fix_record(item):
                        changed = True
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if _fix_record(item):
                    changed = True
                # Recurse into nested arrays
                for key, val in item.items():
                    if isinstance(val, list):
                        for sub in val:
                            if isinstance(sub, dict) and _fix_record(sub):
                                changed = True
    return changed


def _default_schemas_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "architecture" / "schemas"


def _schema_record_type_const(
    schema_file: str, *, schemas_dir: Path | None = None
) -> str:
    """Record-type constant pinned by an output schema, if any (F-1b).

    Outputs not named in a publication binding still carry the
    harness-owned record_type field; when the schema pins it with a
    const (e.g. theory-record.schema.json -> "theory_record") the closure
    derives the value mechanically instead of depending on agent-authored
    provenance.  Returns "" when the schema has no const (then the
    publication-binding map or the run facts govern, as before).
    """
    directory = Path(schemas_dir) if schemas_dir is not None else _default_schemas_dir()
    schema_path = directory / schema_file
    if not schema_path.exists():
        return ""
    try:
        import json as _json

        schema = _json.loads(schema_path.read_text())
    except Exception as exc:
        logger.error(
            "schema record_type const unreadable for %s: %s", schema_path, exc
        )
        return ""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return ""
    record_type = properties.get("record_type")
    if isinstance(record_type, dict) and isinstance(record_type.get("const"), str):
        return str(record_type["const"])
    return ""


def _schema_info(schema_file: str, *, schemas_dir: Path | None = None) -> dict[str, Any]:
    """Return schema metadata for deterministic post-processing."""
    directory = Path(schemas_dir) if schemas_dir is not None else _default_schemas_dir()
    schema_path = directory / schema_file
    if not schema_path.exists():
        return _empty_schema_info()
    try:
        import json as _json

        schema = _json.loads(schema_path.read_text())
    except Exception as exc:
        logger.error("schema info unreadable for %s: %s", schema_path, exc)
        return _empty_schema_info()
    properties = schema.get("properties", {})
    props = set(properties.keys())
    timestamps = props & set(_TIMESTAMP_FIELDS)
    no_additional = schema.get("additionalProperties") is False
    required = set(schema.get("required", []))

    # Collect nested required fields from sub-object property definitions
    # and from $defs/$ref-resolved definitions referenced via allOf.
    nested_required = _collect_nested_required(schema)

    # Collect timestamp-like fields declared in nested properties
    # (e.g. alignmentAssessment.assessed_at) as a parent_key → fields map.
    nested_timestamps: dict[str, set[str]] = {}
    _collect_nested_timestamps(schema, nested_timestamps)

    return {
        "timestamps": timestamps,
        "properties": props,
        "no_additional": no_additional,
        "required": required,
        "nested_required": nested_required,
        "nested_timestamps": nested_timestamps,
    }


def _collect_nested_required(schema: dict[str, Any]) -> set[str]:
    """Collect all required field names from nested object definitions.

    These are fields that are ``required`` inside sub-objects (e.g.
    ``artifactPointer.artifact_id``).  ``_strip_empty_strings`` uses this
    set to avoid stripping required nested fields.
    """
    result: set[str] = set()
    properties = schema.get("properties", {})

    def _walk_object(obj_def: dict[str, Any]) -> None:
        if not isinstance(obj_def, dict):
            return
        req = obj_def.get("required", [])
        if isinstance(req, list):
            result.update(req)
        # Recurse into sub-properties
        sub_props = obj_def.get("properties", {})
        if isinstance(sub_props, dict):
            for sub_def in sub_props.values():
                if isinstance(sub_def, dict) and sub_def.get("type") == "object":
                    _walk_object(sub_def)
                # Array of objects
                if isinstance(sub_def, dict) and sub_def.get("type") == "array":
                    items = sub_def.get("items", {})
                    if isinstance(items, dict) and items.get("type") == "object":
                        _walk_object(items)

    for prop_def in properties.values():
        if isinstance(prop_def, dict):
            if prop_def.get("type") == "object":
                _walk_object(prop_def)
            if prop_def.get("type") == "array":
                items = prop_def.get("items", {})
                if isinstance(items, dict) and items.get("type") == "object":
                    _walk_object(items)

    # Also check $defs
    defs = schema.get("$defs", schema.get("definitions", {}))
    if isinstance(defs, dict):
        for def_def in defs.values():
            if isinstance(def_def, dict):
                _walk_object(def_def)

    return result


def _collect_nested_timestamps(schema: dict[str, Any], found: dict[str, set[str]]) -> None:
    """Build a parent_key → {timestamp_field} map from nested schema properties.

    For each object property that contains timestamp-like fields (``_at``,
    ``_timestamp``, ``_time`` suffixes, excluding ``searched_at``), record
    the parent property name → set of timestamp fields.  This lets the
    injector add timestamps only at schema-declared locations.
    """
    _TS_SUFFIXES = ("_at", "_timestamp", "_time")
    properties = schema.get("properties", {})

    # Walk top-level properties
    for prop_name, prop_def in properties.items():
        if isinstance(prop_def, dict):
            sub_props = prop_def.get("properties", {})
            if isinstance(sub_props, dict):
                local_ts: set[str] = set()
                for key, sub_def in sub_props.items():
                    if (
                        key != "searched_at"
                        and isinstance(key, str)
                        and any(key.endswith(s) for s in _TS_SUFFIXES)
                    ):
                        local_ts.add(key)
                if local_ts:
                    found[prop_name] = local_ts
            # Arrays of objects
            if prop_def.get("type") == "array":
                items = prop_def.get("items", {})
                if isinstance(items, dict) and items.get("type") == "object":
                    item_props = items.get("properties", {})
                    if isinstance(item_props, dict):
                        local_ts = set()
                        for key, sub_def in item_props.items():
                            if (
                                key != "searched_at"
                                and isinstance(key, str)
                                and any(key.endswith(s) for s in _TS_SUFFIXES)
                            ):
                                local_ts.add(key)
                        if local_ts:
                            found[prop_name] = local_ts


def _empty_schema_info() -> dict[str, Any]:
    return {
        "timestamps": set(),
        "properties": set(),
        "no_additional": False,
        "required": set(),
        "nested_required": set(),
        "nested_timestamps": {},
    }


def _sanitize_id(val: str) -> str:
    """Force a stableId to match ^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$."""
    sane = val.lower()
    sane = re.sub(r"[^a-z0-9._-]", "_", sane)
    sane = re.sub(r"^[^a-z]+", "", sane) or "id"
    sane = re.sub(r"\.{2,}", ".", sane)
    return sane


# The single stableId pattern, mirroring
# architecture/schemas/common-definitions.schema.json $defs.stableId.
_STABLEID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")

# ISS-8: identifier keys the removed ``_fix_item`` clause sanitized that NO
# current schema declares (verified against architecture/schemas/).  Coverage
# is retained so behaviour does not regress for outputs carrying them; since
# no schema pattern-checks them they cannot produce schema.pattern findings.
_LEGACY_UNDECLARED_ID_KEYS = frozenset({
    "finding_id", "theorem_id", "definition_id",
    "lemma_id", "corollary_id", "proposition_id",
})

_STABLEID_POSITIONS_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def _stableid_positions(
    schema_file: str, *, schemas_dir: Path | None = None
) -> dict[str, Any]:
    """Schema-exact stableId coverage: which keys the schema pattern-checks.

    Walks the schema (properties / items / allOf / anyOf / oneOf / $defs,
    resolving ``#/$defs/...`` and cross-file ``*.schema.json#/$defs/...``
    references) and collects two name sets:

    * ``scalar_keys`` — property names whose value is a stableId
      (e.g. ``evidence_id``, ``statement_id``, ``stable_id``);
    * ``array_keys`` — property names whose array ITEMS are stableIds
      (e.g. ``evidence_ids``, ``assumptions``).

    On ANY load/parse failure the historical key-name heuristic is returned
    (``heuristic: True``) so coverage never regresses when a schema is
    unavailable: scalar = keys ending ``_id`` plus ``stable_id`` /
    ``affected_record_ids``; array = parents ending ``_ids`` plus
    ``affected_record_ids``.
    """
    directory = Path(schemas_dir) if schemas_dir is not None else _default_schemas_dir()
    cache_key = (str(directory), schema_file)
    cached = _STABLEID_POSITIONS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    schema_path = directory / schema_file
    try:
        import json as _json

        if not schema_path.exists():
            raise FileNotFoundError(schema_file)
        schema = _json.loads(schema_path.read_text())

        scalar_keys: set[str] = set()
        array_keys: set[str] = set()

        def _resolve_ref(ref: str, doc: dict[str, Any]):
            """Return (target_node, target_doc) for a $defs-style ref."""
            if ref.startswith("#/$defs/"):
                return doc.get("$defs", {}).get(ref[len("#/$defs/"):]), doc
            if "#/$defs/" in ref:
                other_file, _, frag = ref.partition("#/$defs/")
                if other_file and re.fullmatch(r"[A-Za-z0-9._-]+", other_file):
                    other_path = directory / other_file
                    if other_path.exists():
                        other_doc = _json.loads(other_path.read_text())
                        return other_doc.get("$defs", {}).get(frag), other_doc
            return None, doc

        def _refs_stableid(node: Any, doc: dict[str, Any], visited: frozenset) -> bool:
            """True when the node reaches $defs/stableId via $ref/combiners."""
            if not isinstance(node, dict):
                return False
            ref = node.get("$ref", "")
            if isinstance(ref, str) and ref:
                if ref.endswith("/$defs/stableId"):
                    return True
                if ref not in visited:
                    target, target_doc = _resolve_ref(ref, doc)
                    if target is not None and _refs_stableid(
                        target, target_doc, visited | {ref}
                    ):
                        return True
            for combiner in ("allOf", "anyOf", "oneOf"):
                subs = node.get(combiner)
                if isinstance(subs, list):
                    for sub in subs:
                        if _refs_stableid(sub, doc, visited):
                            return True
            return False

        def _walk(node: Any, doc: dict[str, Any], visited_refs: frozenset) -> None:
            if not isinstance(node, dict):
                return
            ref = node.get("$ref", "")
            if (
                isinstance(ref, str)
                and ref
                and not ref.endswith("/$defs/stableId")
                and ref not in visited_refs
            ):
                target, target_doc = _resolve_ref(ref, doc)
                if target is not None:
                    _walk(target, target_doc, visited_refs | {ref})
            props = node.get("properties")
            if isinstance(props, dict):
                for name, pdef in props.items():
                    if not isinstance(pdef, dict):
                        continue
                    if _refs_stableid(pdef, doc, frozenset()):
                        scalar_keys.add(name)
                    items = pdef.get("items")
                    if _refs_stableid(items, doc, frozenset()):
                        array_keys.add(name)
                    _walk(pdef, doc, visited_refs)
            items = node.get("items")
            if isinstance(items, dict):
                _walk(items, doc, visited_refs)
            for combiner in ("allOf", "anyOf", "oneOf"):
                subs = node.get(combiner)
                if isinstance(subs, list):
                    for sub in subs:
                        _walk(sub, doc, visited_refs)
            defs = node.get("$defs")
            if isinstance(defs, dict):
                for d in defs.values():
                    _walk(d, doc, visited_refs)

        _walk(schema, schema, frozenset())
        result = {
            "scalar_keys": frozenset(scalar_keys),
            "array_keys": frozenset(array_keys),
            "heuristic": False,
        }
        _STABLEID_POSITIONS_CACHE[cache_key] = result
    except FileNotFoundError:
        result = {"scalar_keys": frozenset(), "array_keys": frozenset(), "heuristic": True}
    except Exception as exc:
        logger.error("stableId coverage unreadable for %s: %s", schema_path, exc)
        result = {"scalar_keys": frozenset(), "array_keys": frozenset(), "heuristic": True}
    return result


def _deep_sanitize_ids(
    obj: Any,
    coverage: Mapping[str, Any],
    parent_key: str | None = None,
    renames: dict[str, str] | None = None,
) -> bool:
    """Sanitize stableId values at schema-covered positions, at any depth.

    A string is sanitized iff it does NOT fullmatch the stableId pattern.
    Coverage comes from ``_stableid_positions``: scalar keys in
    ``scalar_keys`` and string items of arrays whose parent key is in
    ``array_keys`` (or the historical key-name heuristic when the schema is
    unavailable).  Every old→new rename is recorded in ``renames`` so the
    caller can rewrite same-valued references document-wide afterwards.
    """
    if renames is None:
        renames = {}
    scalar_keys = coverage["scalar_keys"]
    array_keys = coverage["array_keys"]
    heuristic = coverage.get("heuristic", False)
    changed = False

    def _sanitized(val: str) -> str | None:
        if _STABLEID_PATTERN.fullmatch(val):
            return None
        new = _sanitize_id(val)
        if new == val:
            return None
        # Deterministic even if two different old ids map to the same new
        # id: each old value keeps its own rename entry.
        renames.setdefault(val, new)
        return renames[val]

    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str):
                if heuristic:
                    covered = key.endswith("_id") or key in (
                        "stable_id", "affected_record_ids",
                    )
                else:
                    covered = key in scalar_keys or key in _LEGACY_UNDECLARED_ID_KEYS
                if covered:
                    new = _sanitized(val)
                    if new is not None:
                        obj[key] = new
                        changed = True
            elif isinstance(val, (dict, list)):
                if _deep_sanitize_ids(val, coverage, parent_key=key, renames=renames):
                    changed = True
    elif isinstance(obj, list):
        if parent_key is None:
            covered_array = False
        elif heuristic:
            covered_array = (
                parent_key.endswith("_ids") or parent_key == "affected_record_ids"
            )
        else:
            covered_array = parent_key in array_keys
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if covered_array:
                    new = _sanitized(item)
                    if new is not None:
                        obj[i] = new
                        changed = True
            elif isinstance(item, (dict, list)):
                if _deep_sanitize_ids(item, coverage, renames=renames):
                    changed = True
    return changed


def _rewrite_id_references(obj: Any, renames: Mapping[str, str]) -> bool:
    """Rewrite every string equal to a renamed id, anywhere in the document.

    Runs AFTER ``_deep_sanitize_ids`` so that same-valued references under
    keys the schema does not pattern-check (free-text objects, cross
    references like ``depends_on_statement_ids``) stay consistent with the
    sanitized definition site instead of dangling.
    """
    if not renames:
        return False
    changed = False
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str):
                new = renames.get(val)
                if new is not None:
                    obj[key] = new
                    changed = True
            elif isinstance(val, (dict, list)):
                if _rewrite_id_references(val, renames):
                    changed = True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                new = renames.get(item)
                if new is not None:
                    obj[i] = new
                    changed = True
            elif isinstance(item, (dict, list)):
                if _rewrite_id_references(item, renames):
                    changed = True
    return changed


# Schema file name → which timestamp fields are declared properties
_TIMESTAMP_FIELDS = ("created_at", "updated_at")


class _CorrectionObserver(_RepositoryObserver):
    """Repository observer whose execution linkage carries Lane B provenance.

    The acknowledgement payload records the correction kind, the authorizing
    command, the correction type, and the source closure so the correction
    re-invocation is auditable end to end (K-1c).
    """

    def __init__(
        self,
        *,
        correction_command_id: str,
        correction_type: str,
        source_closure_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._correction_command_id = correction_command_id
        self._correction_type = correction_type
        self._source_closure_id = source_closure_id

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.external_execution_id = external_execution_id
        try:
            self.repository.acknowledge_execution(
                invocation.execution_id,
                external_execution_id,
                {
                    "kind": "role_invocation_correction",
                    "execution_id": invocation.execution_id,
                    "invocation_id": invocation.invocation_id,
                    "external_execution_id": external_execution_id,
                    "correction_command_id": self._correction_command_id,
                    "correction_type": self._correction_type,
                    "source_closure_id": self._source_closure_id,
                },
            )
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            raise RoleExecutionInfrastructureError(
                f"Harness bookkeeping for execution "
                f"{invocation.execution_id} failed: "
                f"{type(error).__name__}: {error}"
            ) from error


class RoleLifecycleService:
    """Execute exactly one role invocation or recover its immutable closure."""

    def __init__(
        self,
        *,
        context: RunExecutionContext,
        repository: HubRepository,
        executor: RoleExecutor,
        schemas: SchemaCatalog,
        artifacts: ArtifactStore,
        workspace: WorkspacePaths,
    ) -> None:
        self.context = context
        self.repository = repository
        self.executor = executor
        self.schemas = schemas
        self.artifacts = artifacts
        self.workspace = workspace
        self._broker = CapabilityBroker()
        self._adapter = DefaultOutputAdapter()

    async def execute_or_reconcile(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        inputs: Mapping[str, FrozenInputPath],
    ) -> RoleClosureResult:
        invocation_id, execution_id, closure_id = _role_identity(
            self.context, stage, role
        )
        # K5-4 (ADR-016): family-aware reconciliation.  A succeeded
        # correction closure supersedes the base closure (D4), so a run
        # resumed after a mid-pipeline correction reconciles the corrected
        # role instead of re-failing on the stale base failure.  Runs with
        # no correction attempts fall back to the identical base read.
        recovered = self.load_existing(stage=stage, role=role)
        if recovered is not None:
            return recovered
        if self.repository.cancellation_requested(str(self.context.run_id)):
            return RoleClosureResult(
                role=role,
                status=RoleExecutionStatus.CANCELLED,
                execution_id=execution_id,
                invocation_id=invocation_id,
                invocation_sha256="0" * 64,
                closure_id=None,
                closure_sha256=None,
                closure_artifact_id=None,
                outputs=(),
                closed_at=None,
            )

        invocation, invocation_document, invocation_sha256 = self._prepare_invocation(
            stage=stage,
            role=role,
            inputs=inputs,
            invocation_id=invocation_id,
            execution_id=execution_id,
        )
        observer = _RepositoryObserver(
            repository=self.repository,
            executor=self.executor,
            invocation_document=invocation_document,
            invocation_sha256=invocation_sha256,
        )
        await observer.launch_intent(invocation)
        acknowledgement = self._acknowledgement(execution_id)
        try:
            if acknowledgement is None:
                result = await self.executor.execute(invocation, observer)
            else:
                external_id = str(acknowledgement["external_execution_id"])
                observer.external_execution_id = external_id
                result = await self.executor.reconcile(external_id)
                if result is None:
                    raise RoleExecutionPending(
                        f"Execution {execution_id} is acknowledged but not terminal."
                    )
        except RoleExecutionPending:
            raise
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            result = RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=observer.external_execution_id,
                exit_code=None,
                summary="The role executor raised an exception.",
                diagnostic_text=f"{type(error).__name__}: {error}",
            )
        if type(result) is not RoleExecutionResult:
            result = RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=observer.external_execution_id,
                exit_code=None,
                summary="The role executor returned an invalid result.",
                diagnostic_text=type(result).__name__,
            )

        return self._validate_and_close(
            stage=stage,
            role=role,
            invocation=invocation,
            invocation_sha256=invocation_sha256,
            closure_id=closure_id,
            result=result,
        )

    async def execute_correction(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        inputs: Mapping[str, FrozenInputPath],
        correction_instruction: str,
        source_output_bytes: Mapping[str, bytes],
        permitted_pointers: frozenset[str],
        output_scope: frozenset[str],
        source_closure_id: str,
    ) -> RoleClosureResult:
        """Re-invoke one stage role under the correction identity (K-1c Lane B).

        Mirrors ``execute_or_reconcile`` with the approved Lane B deviations:
        the invocation/execution/closure identity derives from a context whose
        ``identity_suffix`` is ``f\"correction.{command_id}\"``; the roles/ and
        tasks/ workspace dirs carry the same suffix so base workspace files
        are never touched; the source closure's sealed output bytes are
        materialized (plain write) into the correction output paths so the
        agent edits them in place; and the close path validates the
        correction run root, records exactly one validation attempt row, and
        verifies the blast radius before sealing.  On the reconcile path (a
        durable acknowledgement exists) source-byte materialization is
        skipped so the agent's in-place edits survive an idempotent replay
        (R4).
        """
        command_id = self.context.correction_command_id
        if not command_id:
            raise RoleLifecycleError(
                "execute_correction requires correction_command_id on the context."
            )
        corrected = replace(
            self.context, identity_suffix=f"correction.{command_id}"
        )
        invocation_id, execution_id, closure_id = _role_identity(
            corrected, stage, role
        )
        recovered = self._load_closure(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
            closure_id=closure_id,
        )
        if recovered is not None:
            return recovered
        if self.repository.cancellation_requested(str(self.context.run_id)):
            return RoleClosureResult(
                role=role,
                status=RoleExecutionStatus.CANCELLED,
                execution_id=execution_id,
                invocation_id=invocation_id,
                invocation_sha256="0" * 64,
                closure_id=None,
                closure_sha256=None,
                closure_artifact_id=None,
                outputs=(),
                closed_at=None,
            )

        acknowledgement = self._acknowledgement(execution_id)
        output_plan = self._correction_output_plan(stage, role, command_id)
        (
            invocation,
            invocation_document,
            invocation_sha256,
        ) = self._prepare_correction_invocation(
            stage=stage,
            role=role,
            inputs=inputs,
            correction_instruction=correction_instruction,
            source_output_bytes=source_output_bytes,
            output_plan=output_plan,
            command_id=command_id,
            invocation_id=invocation_id,
            execution_id=execution_id,
            source_closure_id=source_closure_id,
            materialize_source_bytes=acknowledgement is None,
        )
        observer = _CorrectionObserver(
            repository=self.repository,
            executor=self.executor,
            invocation_document=invocation_document,
            invocation_sha256=invocation_sha256,
            correction_command_id=command_id,
            correction_type=self.context.correction_type,
            source_closure_id=source_closure_id,
        )
        await observer.launch_intent(invocation)
        try:
            if acknowledgement is None:
                result = await self.executor.execute(invocation, observer)
            else:
                external_id = str(acknowledgement["external_execution_id"])
                observer.external_execution_id = external_id
                result = await self.executor.reconcile(external_id)
                if result is None:
                    raise RoleExecutionPending(
                        f"Execution {execution_id} is acknowledged but not terminal."
                    )
        except RoleExecutionPending:
            raise
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            result = RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=observer.external_execution_id,
                exit_code=None,
                summary="The role executor raised an exception.",
                diagnostic_text=f"{type(error).__name__}: {error}",
            )
        if type(result) is not RoleExecutionResult:
            result = RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=observer.external_execution_id,
                exit_code=None,
                summary="The role executor returned an invalid result.",
                diagnostic_text=type(result).__name__,
            )

        return self._validate_and_close_correction(
            stage=stage,
            role=role,
            invocation=invocation,
            invocation_sha256=invocation_sha256,
            closure_id=closure_id,
            result=result,
            output_plan=output_plan,
            source_output_bytes=source_output_bytes,
            permitted_pointers=permitted_pointers,
            output_scope=output_scope,
        )

    def _correction_output_plan(
        self, stage: ResolvedStage, role: str, command_id: str
    ) -> OutputPlan:
        """Rewire the target role's output paths into its correction dir.

        Only the corrected stage-role's specs move; every other spec keeps
        its frozen path so ``for_stage_role`` lookups stay exact.
        """
        prefix = f"roles/{stage.sequence:02d}-{role}/"
        replacement = f"roles/{stage.sequence:02d}-{role}.correction.{command_id}/"
        specs = tuple(
            replace(
                spec,
                relative_path=replacement + spec.relative_path[len(prefix):],
            )
            if spec.relative_path.startswith(prefix)
            else spec
            for spec in self.context.output_plan.specs
        )
        return OutputPlan(specs)

    def _prepare_correction_invocation(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        inputs: Mapping[str, FrozenInputPath],
        correction_instruction: str,
        source_output_bytes: Mapping[str, bytes],
        output_plan: OutputPlan,
        command_id: str,
        invocation_id: str,
        execution_id: str,
        source_closure_id: str,
        materialize_source_bytes: bool,
    ) -> tuple[RoleInvocation, dict[str, Any], str]:
        """Mirror ``_prepare_invocation`` under the correction workspace."""
        role_step = stage.step_for(role)
        missing = sorted(set(role_step.input_ids) - set(inputs))
        if missing:
            raise RoleLifecycleError(
                f"Role {role!r} is missing frozen inputs {missing}."
            )
        run_relative = f"runs/{self.context.run_id}"
        role_relative = (
            f"{run_relative}/roles/{stage.sequence:02d}-{role}"
            f".correction.{command_id}"
        )
        task_relative = (
            f"{run_relative}/tasks/{stage.sequence:02d}-{role}"
            f".correction.{command_id}"
        )
        role_root = self.workspace.ensure_directory(role_relative)
        self.workspace.ensure_directory(task_relative)
        task_path = self.workspace.for_write(f"{task_relative}/task.md")
        access_log_path = role_root / "access.jsonl"
        compact_views = self._materialize_compact_views(
            role_root=role_root,
            inputs=inputs,
            input_ids=role_step.input_ids,
            access_log_path=access_log_path,
        )

        stage_role_instruction = ""
        if self.context.role_instructions:
            stage_role_key = f"{stage.stage_id}.{role}"
            stage_role_instruction = self.context.role_instructions.get(
                stage_role_key, ""
            )

        brief_plan = self._brief_plan(stage, role)
        task_text = render_task_brief(
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            plan=brief_plan,
            stage=stage,
            role=role,
            input_paths={key: str(item.path) for key, item in inputs.items()},
            output_plan=self.context.output_plan,
            phase_instruction=self.context.phase_instruction,
            mode_instruction=self.context.mode_instruction,
            stage_role_instruction=stage_role_instruction,
            researcher_instruction=correction_instruction,
            scientific_stance=self.context.role_souls[role],
            same_group_roles=stage.roles,
            schema_catalog=self.schemas,
            researcher_method_spec=self.context.researcher_method_spec,
            compact_views=compact_views,
        )
        task_payload = task_text.encode("utf-8")
        _immutable_write(task_path, task_payload)

        self._broker.materialize_context(
            workspace=role_root,
            frozen_inputs={
                input_id: inputs[input_id] for input_id in role_step.input_ids
            },
            access_log_path=access_log_path,
        )

        specs = output_plan.for_stage_role(stage.stage_id, role)
        run_root = self.workspace.ensure_directory(run_relative)
        output_paths = tuple(
            self.workspace.for_write(f"{run_relative}/{spec.relative_path}")
            for spec in specs
        )
        # Materialize the source closure's sealed candidate bytes into the
        # correction output paths so the agent edits them in place.  Plain
        # writes (NOT _immutable_write): these are working copies, and the
        # bytes were digest-verified by the caller before this point.
        # K5-3: a closure that failed before output sealing has no bytes for
        # some (or all) plan-declared outputs; those are skipped here and
        # the re-invoked role rewrites them from scratch.  When a durable
        # acknowledgement exists the correction workspace may hold the
        # agent's in-place edits from before a crash; re-materializing
        # source bytes would clobber them and record a silent no-op as
        # success (R4), so the caller skips materialization on the
        # reconcile path (the `_recovery_invocation` pattern).
        for spec, output_path in zip(specs, output_paths):
            source = source_output_bytes.get(spec.contract_output_id)
            if source is None or not materialize_source_bytes:
                continue
            output_path.write_bytes(source)

        input_bindings = [
            {
                "input_id": input_id,
                "artifact_id": inputs[input_id].artifact_id,
                "sha256": inputs[input_id].sha256,
            }
            for input_id in role_step.input_ids
        ]
        invocation_document: dict[str, Any] = {
            "format": "model-forge.role-invocation-start",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "kind": "role_invocation_correction",
            "correction_command_id": command_id,
            "correction_type": self.context.correction_type,
            "source_closure_id": source_closure_id,
            "invocation_id": invocation_id,
            "execution_id": execution_id,
            "run_id": str(self.context.run_id),
            "project_id": str(self.context.project_id),
            "manifest_sha256": str(self.context.manifest_sha256),
            "phase": self.context.plan.identity.phase_id,
            "mode": self.context.plan.mode_id,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "execution": stage.execution,
            "role": role,
            "profile": self.context.profile_for(role),
            "input_bindings": input_bindings,
            "output_ids": [spec.contract_output_id for spec in specs],
            "task_brief_sha256": hashlib.sha256(task_payload).hexdigest(),
            "role_soul_sha256": hashlib.sha256(
                self.context.role_souls[role].encode("utf-8")
            ).hexdigest(),
            "preloaded_skills": list(self.context.preloaded_skills.get(role, ())),
            "timeout_seconds": self.context.timeout_seconds,
        }
        invocation_sha256 = document_sha256(invocation_document)
        invocation = RoleInvocation(
            execution_id=execution_id,
            invocation_id=invocation_id,
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            phase=self.context.plan.identity.phase_id,
            mode=self.context.plan.mode_id,
            stage_id=stage.stage_id,
            role=role,
            profile=self.context.profile_for(role),
            workspace=role_root,
            task_brief=task_path,
            expected_output_paths=output_paths,
            preloaded_skills=self.context.preloaded_skills.get(role, ()),
            timeout_seconds=self.context.timeout_seconds,
            metadata=MappingProxyType(
                {
                    "manifest_sha256": str(self.context.manifest_sha256),
                    "invocation_sha256": invocation_sha256,
                    "run_root": str(run_root),
                    "expected_outputs": [
                        {
                            "contract_output_id": spec.contract_output_id,
                            "schema_file": spec.schema_file,
                            "schema_application": spec.schema_application,
                            "relative_path": spec.relative_path,
                        }
                        for spec in specs
                    ],
                }
            ),
        )
        return invocation, invocation_document, invocation_sha256

    def _validate_and_close_correction(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation: RoleInvocation,
        invocation_sha256: str,
        closure_id: str,
        result: RoleExecutionResult,
        output_plan: OutputPlan,
        source_output_bytes: Mapping[str, bytes],
        permitted_pointers: frozenset[str],
        output_scope: frozenset[str],
    ) -> RoleClosureResult:
        """Validate, verify the blast radius, and seal a correction closure.

        Exactly one ``run_validation_attempts`` row is recorded per
        correction re-invocation (DEVIATION B), chained to the prior attempt
        and bound to the authorizing correction command.  A validation
        failure or a blast-radius violation seals a FAILED closure (the
        attempt is spent) so it never enters the family-aware
        ``load_existing`` walk.
        """
        run_id = str(self.context.run_id)
        status = RoleExecutionStatus(result.status)
        failure_code: str | None = None
        raw_seal_sha256: str | None = None
        sealed_outputs: tuple[SealedRoleOutput, ...] = ()
        findings: list[dict[str, Any]] = []
        transformation_summaries: list[dict[str, Any]] = []
        if self.repository.cancellation_requested(run_id):
            status = RoleExecutionStatus.CANCELLED
        elif status is RoleExecutionStatus.SUCCEEDED:
            # HV-1.1: Seal the raw output bytes BEFORE any mechanical repair
            # rewrites the workspace in place.  Repair and validation failure
            # must never destroy the agent's original bytes: the sealed raw
            # snapshot is always recoverable from the artifact store.
            # Fail closed when preservation fails: without the raw snapshot
            # the harness could not prove which bytes the agent wrote.
            raw_seal_sha256 = None
            try:
                from .output_adapters import preserve_raw_output
                raw_seal_sha256 = preserve_raw_output(
                    workspace=invocation.workspace,
                    run_id=invocation.run_id,
                    role=role,
                    artifacts=self.artifacts,
                )
            except Exception as error:
                logger.exception(
                    "Raw output preservation failed for run %s role %s",
                    invocation.run_id,
                    role,
                )
                status = RoleExecutionStatus.FAILED
                failure_code = "output.raw_preservation_failed"
                result = RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=result.external_execution_id,
                    exit_code=result.exit_code,
                    summary="Raw output preservation failed; the candidate was not validated.",
                    diagnostic_text=f"{type(error).__name__}: {error}",
                )
            if status is RoleExecutionStatus.SUCCEEDED:
                # F-3: correction closures run the same disclosed mechanical
                # repair + harness-owned envelope population stage (HV-4) as
                # normal closures, restricted to the correction's permitted
                # output scope so materialized source bytes for out-of-scope
                # outputs stay byte-identical for blast-radius verification.
                scoped_plan = replace(
                    output_plan,
                    specs=tuple(
                        spec
                        for spec in output_plan.specs
                        if spec.contract_output_id in output_scope
                    ),
                )

                # Snapshot the agent's raw bytes for ALL of the role's specs
                # (not only the in-scope repair plan) BEFORE the repair pass:
                # blast-radius verification below judges the agent's own edits.
                # Untouched out-of-scope outputs then compare equal to their
                # materialized source bytes, and agent tampering with an
                # out-of-scope output is caught instead of comparing against
                # an absent corrected document (R3).
                agent_raw_bytes: dict[str, bytes] = {}
                for role_spec in output_plan.for_stage_role(stage.stage_id, role):
                    raw_path = (
                        self.workspace.for_read(f"runs/{run_id}")
                        / role_spec.relative_path
                    )
                    if raw_path.is_file():
                        agent_raw_bytes[role_spec.contract_output_id] = (
                            raw_path.read_bytes()
                        )

                def _canonical_source_lookup(digest: str) -> "str | None":
                    with self.repository.database.connect() as connection:
                        row = connection.execute(
                            "SELECT artifact_id FROM artifacts "
                            "WHERE sha256 = ? AND project_id = ? "
                            "ORDER BY rowid LIMIT 1",
                            (digest, str(self.context.project_id)),
                        ).fetchone()
                    if row is None:
                        return None
                    return str(row["artifact_id"])

                run_facts = self._sealed_run_facts(stage, role)
                repair_records = _apply_disclosed_mechanical_repairs(
                    run_root=self.workspace.for_read(f"runs/{run_id}"),
                    output_plan=scoped_plan,
                    stage=stage,
                    role=role,
                    run_id=run_id,
                    project_id=str(self.context.project_id),
                    run_facts=run_facts,
                    record_type_by_output=self._record_type_by_output(),
                    canonical_source_lookup=_canonical_source_lookup,
                    schemas_dir=self.schemas.directory,
                )
                transformation_summaries = [
                    record.to_dict() for record in repair_records.values()
                ]
                validation = validate_role_outputs(
                    schema_catalog=self.schemas,
                    run_root=self.workspace.for_read(f"runs/{run_id}"),
                    output_plan=output_plan,
                    stage=stage,
                    role=role,
                    method_bound=bool(run_facts.method_identity),
                )
                findings = [item.to_dict() for item in validation.findings]
                sealed_outputs = tuple(
                    self._seal_output(item.spec, item.path, item.sha256)
                    for item in validation.outputs
                )
                violations: tuple[ValidationFinding, ...] = ()
                if not validation.passed:
                    status = RoleExecutionStatus.FAILED
                    failure_code = "output.structural_validation_failed"
                else:
                    # Lazy import: application.correction_execution already
                    # imports harness.stage_execution, so a top-level import here
                    # would be circular (DEVIATION B).
                    from ..application.correction_execution import (
                        verify_correction_blast_radius,
                    )

                    source_documents = {
                        contract_output_id: json.loads(data)
                        for contract_output_id, data in source_output_bytes.items()
                    }
                    corrected_documents = {
                        contract_output_id: json.loads(data)
                        for contract_output_id, data in agent_raw_bytes.items()
                    }
                    violations = verify_correction_blast_radius(
                        source_outputs=source_documents,
                        corrected_outputs=corrected_documents,
                        correction_type=self.context.correction_type,
                        permitted_pointers=permitted_pointers,
                        output_scope=output_scope,
                    )
                    if violations:
                        status = RoleExecutionStatus.FAILED
                        failure_code = "correction.blast_radius_violated"
                        findings = [item.to_dict() for item in violations]
                ordinal = self.repository.count_validation_attempts(run_id) + 1
                attempt_id = f"attempt.{run_id}.{ordinal}"
                report = ValidationReport.from_findings(
                    f"report.{attempt_id}",
                    run_id,
                    self.context.correction_type,
                    list(violations) if violations else validation.findings,
                )
                digest_input = (
                    f"{self.context.correction_type}:"
                    + "".join(sorted(item.sha256 for item in validation.outputs))
                )
                source_sha256 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
                prior = self.repository.get_latest_validation_attempt(run_id)
                prior_attempt_id = (
                    str(prior["attempt_id"]) if prior is not None else None
                )
                self.repository.record_validation_attempt(
                    attempt_id,
                    run_id,
                    ordinal,
                    registry_version(),
                    json.dumps(report.to_dict(), sort_keys=True),
                    source_sha256,
                    correction_type=self.context.correction_type,
                    prior_attempt_id=prior_attempt_id,
                    correction_command_id=self.context.correction_command_id,
                )
        elif status is RoleExecutionStatus.FAILED:
            failure_code = "executor.role_failed"
            if self.context.correction_type is not None:
                # HV-5.6: an executor-failed correction invocation still
                # spends the bounded attempt. Without this row a persistently
                # failing agent could be retried forever and the run would
                # never reach correction_exhausted.
                ordinal = self.repository.count_validation_attempts(run_id) + 1
                attempt_id = f"attempt.{run_id}.{ordinal}"
                report = ValidationReport.from_findings(
                    f"report.{attempt_id}",
                    run_id,
                    self.context.correction_type,
                    [
                        ValidationFinding(
                            code="executor.role_failed",
                            message=(
                                "The correction executor failed before "
                                "producing validatable outputs; the bounded "
                                "correction attempt is spent."
                            ),
                            severity=ValidationSeverity.ERROR,
                            finding_class=FindingClass.OPERATIONAL_FAILURE,
                            correction_class="none",
                        )
                    ],
                )
                prior = self.repository.get_latest_validation_attempt(run_id)
                self.repository.record_validation_attempt(
                    attempt_id,
                    run_id,
                    ordinal,
                    registry_version(),
                    json.dumps(report.to_dict(), sort_keys=True),
                    hashlib.sha256(
                        f"{self.context.correction_type}:executor_failed".encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                    correction_type=self.context.correction_type,
                    prior_attempt_id=(
                        str(prior["attempt_id"]) if prior is not None else None
                    ),
                    correction_command_id=self.context.correction_command_id,
                )

        if status is RoleExecutionStatus.CANCELLED:
            failure_code = None
        closed_at = isoformat_utc(utc_now())
        closure_document: dict[str, Any] = {
            "format": "model-forge.role-invocation-closure",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "closure_id": closure_id,
            "execution_id": invocation.execution_id,
            "invocation_id": invocation.invocation_id,
            "invocation_sha256": invocation_sha256,
            "run_id": invocation.run_id,
            "project_id": invocation.project_id,
            "phase": invocation.phase,
            "mode": invocation.mode,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "role": role,
            "status": status.value,
            "external_execution_id": result.external_execution_id,
            "exit_code": result.exit_code,
            "summary": result.summary,
            "diagnostic_text": result.diagnostic_text,
            "failure_code": failure_code,
            "outputs": [self._output_document(item) for item in sealed_outputs],
            "findings": findings,
            "output_transformations": transformation_summaries,
            "raw_output_sha256": raw_seal_sha256,
            "closed_at": closed_at,
        }
        closure_sha256 = document_sha256(closure_document)
        closure_document["closure_sha256"] = closure_sha256
        closure_bytes = canonicalize(closure_document)
        stored = self.artifacts.put_bytes(
            closure_bytes, expected_sha256=hashlib.sha256(closure_bytes).hexdigest()
        )
        closure_artifact_id = _closure_artifact_id(closure_id)
        self.repository.record_artifact(
            closure_artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "role_invocation_closure",
                "run_id": run_id,
                "closure_id": closure_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        try:
            self.repository.close_execution(
                invocation.execution_id,
                closure_id,
                closure_sha256,
                closure_document,
            )
        except RepositoryConflictError:
            recovered = self._load_closure(
                stage=stage,
                role=role,
                invocation_id=invocation.invocation_id,
                execution_id=invocation.execution_id,
                closure_id=closure_id,
            )
            if recovered is not None:
                return recovered
            raise
        return RoleClosureResult(
            role=role,
            status=status,
            execution_id=invocation.execution_id,
            invocation_id=invocation.invocation_id,
            invocation_sha256=invocation_sha256,
            closure_id=closure_id,
            closure_sha256=closure_sha256,
            closure_artifact_id=closure_artifact_id,
            outputs=sealed_outputs,
            closed_at=closed_at,
            failure_code=failure_code,
        )

    def load_existing(
        self, *, stage: ResolvedStage, role: str
    ) -> RoleClosureResult | None:
        # The correction family takes precedence (D4, 2026-08-17): a
        # succeeded correction closure is the latest user-authorized output
        # for this role and supersedes the base closure.  Base-first
        # loading was designed for the FAILED-run case (base closure
        # failed); for REJECTED runs every base closure SUCCEEDED, so
        # base-first would silently reuse the pre-correction outputs and a
        # Lane B correction would never take effect.  Walk the run's
        # correction attempts newest-first and return the first succeeded
        # correction closure; fall back to the base closure otherwise.
        attempts = self.repository.list_validation_attempts(str(self.context.run_id))
        for attempt in reversed(attempts):
            command_id = attempt["correction_command_id"]
            if not command_id:
                continue
            corrected = replace(
                self.context, identity_suffix=f"correction.{command_id}"
            )
            c_invocation_id, c_execution_id, c_closure_id = _role_identity(
                corrected, stage, role
            )
            closure = self._load_closure(
                stage=stage,
                role=role,
                invocation_id=c_invocation_id,
                execution_id=c_execution_id,
                closure_id=c_closure_id,
            )
            if closure is not None and closure.status is RoleExecutionStatus.SUCCEEDED:
                return closure
        invocation_id, execution_id, closure_id = _role_identity(
            self.context, stage, role
        )
        return self._load_closure(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
            closure_id=closure_id,
        )

    async def settle_cancellation(
        self, *, stage: ResolvedStage, role: str
    ) -> bool:
        """Stop and seal one prior acknowledged execution without relaunching it."""

        invocation_id, execution_id, closure_id = _role_identity(
            self.context, stage, role
        )
        recovered = self._load_closure(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
            closure_id=closure_id,
        )
        if recovered is not None:
            return True
        intent = self.repository.get_execution_for_invocation(invocation_id)
        if intent is None:
            return True
        acknowledgement = self._acknowledgement(execution_id)
        if acknowledgement is None:
            raise RoleExecutionPending(
                f"Execution {execution_id} has a launch intent but no durable acknowledgement."
            )
        external_id = str(acknowledgement["external_execution_id"])
        await self.executor.cancel(external_id)
        result = await self.executor.reconcile(external_id)
        if result is None:
            return False
        invocation_document = loads_json(
            intent["payload_json"], source=f"execution intent {execution_id}"
        )
        if type(invocation_document) is not dict:
            raise RoleLifecycleError("Execution intent payload must be an object.")
        invocation = self._recovery_invocation(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
        )
        closure = self._validate_and_close(
            stage=stage,
            role=role,
            invocation=invocation,
            invocation_sha256=str(intent["invocation_sha256"]),
            closure_id=closure_id,
            result=result,
        )
        return closure.status is RoleExecutionStatus.CANCELLED

    def _recovery_invocation(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation_id: str,
        execution_id: str,
    ) -> RoleInvocation:
        run_relative = f"runs/{self.context.run_id}"
        role_relative = f"{run_relative}/roles/{stage.sequence:02d}-{role}"
        task_relative = f"{run_relative}/tasks/{stage.sequence:02d}-{role}/task.md"
        specs = self.context.output_plan.for_stage_role(stage.stage_id, role)
        return RoleInvocation(
            execution_id=execution_id,
            invocation_id=invocation_id,
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            phase=self.context.plan.identity.phase_id,
            mode=self.context.plan.mode_id,
            stage_id=stage.stage_id,
            role=role,
            profile=self.context.profile_for(role),
            workspace=self.workspace.ensure_directory(role_relative),
            task_brief=self.workspace.for_write(task_relative),
            expected_output_paths=tuple(
                self.workspace.for_write(f"{run_relative}/{spec.relative_path}")
                for spec in specs
            ),
            preloaded_skills=self.context.preloaded_skills.get(role, ()),
            timeout_seconds=self.context.timeout_seconds,
            metadata=MappingProxyType(
                {"manifest_sha256": str(self.context.manifest_sha256)}
            ),
        )

    def _materialize_compact_views(
        self,
        *,
        role_root: Path,
        inputs: Mapping[str, Any],
        input_ids: Iterable[str],
        access_log_path: Path,
    ) -> dict[str, str]:
        """E-2b: materialize layer-3 compact decision views beside the inputs.

        For each frozen input whose record payload declares a
        ``compact_decision_view`` representation with real bytes in the
        artifact store, write ``inputs/compact/<input_id>.md`` (the summary
        markdown from the compact-view envelope) and log the access.
        Returns ``input_id -> workspace-relative compact path`` for the
        brief. Placeholder or missing artifacts are skipped silently:
        legacy records and the development loop keep full-record-only
        behavior.
        """
        compact: dict[str, str] = {}
        compact_dir = role_root / "inputs" / "compact"
        from datetime import datetime, timezone

        for input_id in input_ids:
            frozen = inputs.get(input_id)
            if frozen is None:
                continue
            try:
                document = json.loads(Path(frozen.path).read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(document, dict):
                continue
            representations = document.get("representations")
            if not isinstance(representations, list):
                continue
            for representation in representations:
                if not isinstance(representation, dict):
                    continue
                if representation.get("information_layer") != "compact_decision_view":
                    continue
                artifact = representation.get("artifact")
                if not isinstance(artifact, dict):
                    continue
                sha256 = str(artifact.get("sha256", ""))
                uri = str(artifact.get("uri", ""))
                if (
                    len(sha256) != 64
                    or len(set(sha256)) == 1
                    or not uri.startswith("artifact://")
                ):
                    continue
                try:
                    raw = self.artifacts.read_bytes(sha256)
                except Exception:
                    continue
                markdown = ""
                try:
                    envelope = json.loads(raw.decode("utf-8"))
                    if isinstance(envelope, dict):
                        markdown = str(envelope.get("summary_markdown", ""))
                except Exception:
                    markdown = ""
                if not markdown.strip():
                    # R24: a summary-less envelope has no compact content;
                    # skip it instead of dumping raw bytes into the brief.
                    continue
                compact_dir.mkdir(parents=True, exist_ok=True)
                dest = compact_dir / f"{input_id}.md"
                dest.write_text(markdown, encoding="utf-8")
                entry = {
                    "artifact_id": str(artifact.get("artifact_id", "")),
                    "sha256": sha256,
                    "byte_length": len(raw),
                    "materialized_path": str(dest),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                with open(access_log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
                compact[input_id] = f"inputs/compact/{input_id}.md"
                break
        return compact

    def _prepare_invocation(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        inputs: Mapping[str, FrozenInputPath],
        invocation_id: str,
        execution_id: str,
    ) -> tuple[RoleInvocation, dict[str, Any], str]:
        role_step = stage.step_for(role)
        missing = sorted(set(role_step.input_ids) - set(inputs))
        if missing:
            raise RoleLifecycleError(
                f"Role {role!r} is missing frozen inputs {missing}."
            )
        run_relative = f"runs/{self.context.run_id}"
        role_relative = f"{run_relative}/roles/{stage.sequence:02d}-{role}"
        task_relative = f"{run_relative}/tasks/{stage.sequence:02d}-{role}"
        role_root = self.workspace.ensure_directory(role_relative)
        task_root = self.workspace.ensure_directory(task_relative)
        task_path = self.workspace.for_write(f"{task_relative}/task.md")
        access_log_path = role_root / "access.jsonl"
        compact_views = self._materialize_compact_views(
            role_root=role_root,
            inputs=inputs,
            input_ids=role_step.input_ids,
            access_log_path=access_log_path,
        )

        # Keep the frozen mode, stage-role, and researcher directions as
        # separate layers. The task renderer establishes their priority.
        stage_role_instruction = ""
        if self.context.role_instructions:
            stage_role_key = f"{stage.stage_id}.{role}"
            stage_role_instruction = self.context.role_instructions.get(
                stage_role_key, ""
            )

        brief_plan = self._brief_plan(stage, role)
        task_text = render_task_brief(
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            plan=brief_plan,
            stage=stage,
            role=role,
            input_paths={key: str(item.path) for key, item in inputs.items()},
            output_plan=self.context.output_plan,
            phase_instruction=self.context.phase_instruction,
            mode_instruction=self.context.mode_instruction,
            stage_role_instruction=stage_role_instruction,
            researcher_instruction=self.context.researcher_instruction,
            scientific_stance=self.context.role_souls[role],
            same_group_roles=stage.roles,
            schema_catalog=self.schemas,
            researcher_method_spec=self.context.researcher_method_spec,
            compact_views=compact_views,
        )
        task_payload = task_text.encode("utf-8")
        _immutable_write(task_path, task_payload)

        # Materialize frozen inputs into the role workspace via the
        # capability broker, verifying digests and logging every access.
        self._broker.materialize_context(
            workspace=role_root,
            frozen_inputs={
                input_id: inputs[input_id] for input_id in role_step.input_ids
            },
            access_log_path=access_log_path,
        )

        specs = self.context.output_plan.for_stage_role(stage.stage_id, role)
        run_root = self.workspace.ensure_directory(run_relative)
        output_paths = tuple(
            self.workspace.for_write(f"{run_relative}/{spec.relative_path}")
            for spec in specs
        )
        input_bindings = [
            {
                "input_id": input_id,
                "artifact_id": inputs[input_id].artifact_id,
                "sha256": inputs[input_id].sha256,
            }
            for input_id in role_step.input_ids
        ]
        invocation_document: dict[str, Any] = {
            "format": "model-forge.role-invocation-start",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "invocation_id": invocation_id,
            "execution_id": execution_id,
            "run_id": str(self.context.run_id),
            "project_id": str(self.context.project_id),
            "manifest_sha256": str(self.context.manifest_sha256),
            "phase": self.context.plan.identity.phase_id,
            "mode": self.context.plan.mode_id,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "execution": stage.execution,
            "role": role,
            "profile": self.context.profile_for(role),
            "input_bindings": input_bindings,
            "output_ids": [spec.contract_output_id for spec in specs],
            "task_brief_sha256": hashlib.sha256(task_payload).hexdigest(),
            "role_soul_sha256": hashlib.sha256(
                self.context.role_souls[role].encode("utf-8")
            ).hexdigest(),
            "preloaded_skills": list(self.context.preloaded_skills.get(role, ())),
            "timeout_seconds": self.context.timeout_seconds,
        }
        invocation_sha256 = document_sha256(invocation_document)
        invocation = RoleInvocation(
            execution_id=execution_id,
            invocation_id=invocation_id,
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            phase=self.context.plan.identity.phase_id,
            mode=self.context.plan.mode_id,
            stage_id=stage.stage_id,
            role=role,
            profile=self.context.profile_for(role),
            workspace=role_root,
            task_brief=task_path,
            expected_output_paths=output_paths,
            preloaded_skills=self.context.preloaded_skills.get(role, ()),
            timeout_seconds=self.context.timeout_seconds,
            metadata=MappingProxyType(
                {
                    "manifest_sha256": str(self.context.manifest_sha256),
                    "invocation_sha256": invocation_sha256,
                    "run_root": str(run_root),
                    "expected_outputs": [
                        {
                            "contract_output_id": spec.contract_output_id,
                            "schema_file": spec.schema_file,
                            "schema_application": spec.schema_application,
                            "relative_path": spec.relative_path,
                        }
                        for spec in specs
                    ],
                }
            ),
        )
        return invocation, invocation_document, invocation_sha256

    def _brief_plan(self, stage: ResolvedStage, role: str) -> ResolvedPhasePlan:
        role_inputs = set(stage.step_for(role).input_ids)
        contexts = {
            str(item["context_id"]): item
            for item in self.context.plan.prepared_contexts
        }
        if not role_inputs or not role_inputs.issubset(contexts):
            return replace(
                self.context.plan,
                choice_values=thaw_json(self.context.plan.choice_values),
            )
        allowed_choices = {
            choice_id
            for context_id in role_inputs
            for choice_id in contexts[context_id].get("source_choice_ids", ())
        }
        choices = {
            key: thaw_json(value)
            for key, value in self.context.plan.choice_values.items()
            if key in allowed_choices
        }
        return replace(
            self.context.plan,
            choice_values=MappingProxyType(choices),
        )

    def _sealed_run_facts(self, stage: ResolvedStage, role: str) -> SealedRunFacts:
        """Build the harness-known run facts for envelope population (HV-4).

        Every value is derivable from the frozen plan, manifest, and recipe:
        no agent-supplied content is consulted.
        """
        method_identity: dict[str, Any] = {}
        for key, value in self.context.plan.choice_values.items():
            if str(key).endswith(".selected_method") and isinstance(value, Mapping):
                method_identity = {str(k): v for k, v in value.items()}
        # to_role names the single role of the next stage. When the next
        # stage fans out to multiple roles there is no unique successor,
        # so to_role stays empty - it is not only empty when terminal
        # (R23).
        to_role = ""
        for later in self.context.plan.stages:
            if later.sequence > stage.sequence:
                later_roles = [step.role for step in later.role_steps]
                if len(later_roles) == 1:
                    to_role = later_roles[0]
                break
        review_basis_generation_id = ""
        for item in self.context.recipe.document.get("frozen_inputs", ()):
            # P5 contract 2.4.0 renamed the review-revision manuscript gate
            # to p5.review_target_manuscript; manifests sealed under older
            # contracts carry p5.current_manuscript in the same role.
            if str(item.get("contract_input_id")) in {
                "p5.review_target_manuscript",
                "p5.current_manuscript",
            }:
                review_basis_generation_id = str(item.get("generation_id", ""))
        return SealedRunFacts(
            project_id=str(self.context.project_id),
            run_id=str(self.context.run_id),
            phase=self.context.plan.identity.phase_id,
            mode=self.context.plan.mode_id,
            role=role,
            method_identity=method_identity,
            manifest_sha256=str(self.context.manifest_sha256),
            sequence=stage.sequence,
            to_role=to_role,
            review_basis_generation_id=review_basis_generation_id,
        )

    def _record_type_by_output(self) -> dict[str, str]:
        """Map contract output IDs to their publication-binding record type."""
        result: dict[str, str] = {}
        for binding in self.context.plan.publication_bindings:
            target = binding.get("target", {})
            record_type = str(target.get("record_type", "")) if isinstance(target, Mapping) else ""
            if not record_type:
                continue
            for output_id in binding.get("output_ids", ()):
                result[str(output_id)] = record_type
        return result

    def _validate_and_close(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation: RoleInvocation,
        invocation_sha256: str,
        closure_id: str,
        result: RoleExecutionResult,
    ) -> RoleClosureResult:
        status = RoleExecutionStatus(result.status)
        failure_code: str | None = None
        raw_seal_sha256: str | None = None
        sealed_outputs: tuple[SealedRoleOutput, ...] = ()
        findings: list[dict[str, Any]] = []
        transformation_summaries: list[dict[str, Any]] = []
        if self.repository.cancellation_requested(str(self.context.run_id)):
            status = RoleExecutionStatus.CANCELLED
        elif status is RoleExecutionStatus.SUCCEEDED:
            # HV-1.1: Seal the raw output bytes BEFORE any mechanical repair
            # rewrites the workspace in place.  Repair and validation failure
            # must never destroy the agent's original bytes: the sealed raw
            # snapshot is always recoverable from the artifact store.
            # Fail closed when preservation fails: without the raw snapshot
            # the harness could not prove which bytes the agent wrote.
            raw_seal_sha256 = None
            try:
                from .output_adapters import preserve_raw_output
                raw_seal_sha256 = preserve_raw_output(
                    workspace=invocation.workspace,
                    run_id=invocation.run_id,
                    role=role,
                    artifacts=self.artifacts,
                )
            except Exception as error:
                logger.exception(
                    "Raw output preservation failed for run %s role %s",
                    invocation.run_id,
                    role,
                )
                status = RoleExecutionStatus.FAILED
                failure_code = "output.raw_preservation_failed"
                result = RoleExecutionResult(
                    status=RoleExecutionStatus.FAILED,
                    external_execution_id=result.external_execution_id,
                    exit_code=result.exit_code,
                    summary="Raw output preservation failed; the candidate was not validated.",
                    diagnostic_text=f"{type(error).__name__}: {error}",
                )
            if status is RoleExecutionStatus.SUCCEEDED:
                # Apply mechanical repairs to a copy of the raw output. The
                # repair function records source/result digests and classified
                # transformation entries for each output.  Harness-owned envelope
                # fields (HV-4) are populated from sealed run facts inside the
                # same pass, so the source digest remains the agent's raw bytes.
                # E-2e: canonical_artifact input:// pointers resolve their
                # artifact_id against the artifacts table (sealed role outputs
                # carry the true identity of the materialized input bytes).
                def _canonical_source_lookup(digest: str) -> "str | None":
                    with self.repository.database.connect() as connection:
                        row = connection.execute(
                            "SELECT artifact_id FROM artifacts "
                            "WHERE sha256 = ? AND project_id = ? "
                            "ORDER BY rowid LIMIT 1",
                            (digest, str(self.context.project_id)),
                        ).fetchone()
                    if row is None:
                        return None
                    return str(row["artifact_id"])

                run_facts = self._sealed_run_facts(stage, role)
                repair_records = _apply_disclosed_mechanical_repairs(
                    run_root=self.workspace.for_read(f"runs/{self.context.run_id}"),
                    output_plan=self.context.output_plan,
                    stage=stage,
                    role=role,
                    run_id=str(self.context.run_id),
                    project_id=str(self.context.project_id),
                    run_facts=run_facts,
                    record_type_by_output=self._record_type_by_output(),
                    canonical_source_lookup=_canonical_source_lookup,
                    schemas_dir=self.schemas.directory,
                )
                validation = validate_role_outputs(
                    schema_catalog=self.schemas,
                    run_root=self.workspace.for_read(f"runs/{self.context.run_id}"),
                    output_plan=self.context.output_plan,
                    stage=stage,
                    role=role,
                    method_bound=bool(run_facts.method_identity),
                )
                findings = [item.to_dict() for item in validation.findings]
                if not validation.passed:
                    status = RoleExecutionStatus.FAILED
                    failure_code = "output.structural_validation_failed"
                sealed_outputs = tuple(
                    self._seal_output(item.spec, item.path, item.sha256)
                    for item in validation.outputs
                )
                # Store transformation records on the closure for auditability.
                transformation_summaries = [
                    record.to_dict() for record in repair_records.values()
                ]
            if status is RoleExecutionStatus.SUCCEEDED:
                # Adapt validated outputs to capture linked artifacts
                for item in validation.outputs:
                    self._adapter.adapt(
                        spec=item.spec,
                        workspace=invocation.workspace,
                        validated=item,
                    )
        elif status is RoleExecutionStatus.FAILED:
            failure_code = "executor.role_failed"
            # Preserve raw output for debugging even on failure
            raw_seal_sha256 = None
            try:
                from .output_adapters import preserve_raw_output
                raw_seal_sha256 = preserve_raw_output(
                    workspace=invocation.workspace,
                    run_id=invocation.run_id,
                    role=role,
                    artifacts=self.artifacts,
                )
            except Exception:
                logger.exception(
                    "Raw output preservation failed for failed run %s role %s",
                    invocation.run_id,
                    role,
                )
                raw_seal_sha256 = None

        if status is RoleExecutionStatus.CANCELLED:
            failure_code = None
        closed_at = isoformat_utc(utc_now())
        closure_document: dict[str, Any] = {
            "format": "model-forge.role-invocation-closure",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "closure_id": closure_id,
            "execution_id": invocation.execution_id,
            "invocation_id": invocation.invocation_id,
            "invocation_sha256": invocation_sha256,
            "run_id": invocation.run_id,
            "project_id": invocation.project_id,
            "phase": invocation.phase,
            "mode": invocation.mode,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "role": role,
            "status": status.value,
            "external_execution_id": result.external_execution_id,
            "exit_code": result.exit_code,
            "summary": result.summary,
            "diagnostic_text": result.diagnostic_text,
            "failure_code": failure_code,
            "outputs": [self._output_document(item) for item in sealed_outputs],
            "findings": findings,
            "output_transformations": transformation_summaries,
            "raw_output_sha256": raw_seal_sha256,
            "closed_at": closed_at,
        }
        closure_sha256 = document_sha256(closure_document)
        closure_document["closure_sha256"] = closure_sha256
        closure_bytes = canonicalize(closure_document)
        stored = self.artifacts.put_bytes(
            closure_bytes, expected_sha256=hashlib.sha256(closure_bytes).hexdigest()
        )
        closure_artifact_id = _closure_artifact_id(closure_id)
        self.repository.record_artifact(
            closure_artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "role_invocation_closure",
                "run_id": str(self.context.run_id),
                "closure_id": closure_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        try:
            self.repository.close_execution(
                invocation.execution_id,
                closure_id,
                closure_sha256,
                closure_document,
            )
        except RepositoryConflictError:
            recovered = self._load_closure(
                stage=stage,
                role=role,
                invocation_id=invocation.invocation_id,
                execution_id=invocation.execution_id,
                closure_id=closure_id,
            )
            if recovered is not None:
                return recovered
            raise
        return RoleClosureResult(
            role=role,
            status=status,
            execution_id=invocation.execution_id,
            invocation_id=invocation.invocation_id,
            invocation_sha256=invocation_sha256,
            closure_id=closure_id,
            closure_sha256=closure_sha256,
            closure_artifact_id=closure_artifact_id,
            outputs=sealed_outputs,
            closed_at=closed_at,
            failure_code=failure_code,
        )

    def _seal_output(
        self, spec: OutputSpec, path: Path, expected_sha256: str
    ) -> SealedRoleOutput:
        payload = path.read_bytes()
        stored = self.artifacts.put_bytes(payload, expected_sha256=expected_sha256)
        artifact_id = _output_artifact_id(
            self.context, spec, str(stored.sha256)
        )
        self.repository.record_artifact(
            artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "validated_role_output",
                "run_id": str(self.context.run_id),
                "contract_output_id": spec.contract_output_id,
                "output_id": spec.output_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        self._seal_authored_snapshot(spec, path)
        return SealedRoleOutput(
            contract_output_id=spec.contract_output_id,
            output_id=spec.output_id,
            artifact_id=artifact_id,
            sha256=str(stored.sha256),
            size=stored.size,
            media_type="application/json",
            storage_relative_path=stored.relative_path,
        )

    def _seal_authored_snapshot(self, spec: OutputSpec, path: Path) -> None:
        """Seal the ``<filename>.as-authored`` sidecar when present (E-2d).

        The repair pass writes this sidecar when it stamps a primary
        artifact self-pointer: the pointer digest covers the pre-repair
        bytes, which differ from the sealed output bytes (the repair
        rewrites the file with the stamped pointer inside).  Storing the
        sidecar under the ``<contract_output_id>.as_authored`` identity
        makes the stamped pointer resolve to hash-verified artifact-store
        bytes; the artifact_id derivation here must match the stamping
        side in ``_stamp_output_pointer``.
        """
        sidecar = path.parent / f"{path.name}.as-authored"
        if not sidecar.exists():
            return
        payload = sidecar.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        stored = self.artifacts.put_bytes(payload, expected_sha256=digest)
        artifact_id = deterministic_id(
            "artifact",
            str(self.context.project_id),
            str(self.context.run_id),
            f"{spec.contract_output_id}.as_authored",
            str(stored.sha256),
        )
        self.repository.record_artifact(
            artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "authored_snapshot",
                "run_id": str(self.context.run_id),
                "contract_output_id": f"{spec.contract_output_id}.as_authored",
                "output_id": spec.output_id,
                "storage_relative_path": stored.relative_path,
            },
        )

    def _load_closure(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation_id: str,
        execution_id: str,
        closure_id: str,
    ) -> RoleClosureResult | None:
        with self.repository.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM role_execution_closures WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if row is None:
            return None
        document = loads_json(
            row["payload_json"], source=f"repository closure {closure_id}"
        )
        expected = {
            "closure_id": closure_id,
            "execution_id": execution_id,
            "invocation_id": invocation_id,
            "run_id": str(self.context.run_id),
            "project_id": str(self.context.project_id),
            "phase": self.context.plan.identity.phase_id,
            "mode": self.context.plan.mode_id,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "role": role,
        }
        if type(document) is not dict or any(
            document.get(key) != value for key, value in expected.items()
        ):
            raise RoleLifecycleError(
                f"Stored closure {closure_id} does not match its frozen invocation."
            )
        closure_sha256 = document.get("closure_sha256")
        unhashed = dict(document)
        unhashed.pop("closure_sha256", None)
        if (
            closure_sha256 != row["closure_sha256"]
            or document_sha256(unhashed) != closure_sha256
        ):
            raise RoleLifecycleError(f"Stored closure {closure_id} has an invalid digest.")
        with self.repository.database.connect() as connection:
            intent_row = connection.execute(
                "SELECT * FROM role_execution_intents WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if (
            intent_row is None
            or intent_row["invocation_id"] != invocation_id
            or intent_row["invocation_sha256"] != document.get("invocation_sha256")
        ):
            raise RoleLifecycleError(
                f"Stored closure {closure_id} is not bound to its execution intent."
            )
        status = RoleExecutionStatus(document["status"])
        outputs = tuple(self._parse_output(item) for item in document.get("outputs", ()))
        expected_specs = {
            spec.contract_output_id: spec
            for spec in self.context.output_plan.for_stage_role(stage.stage_id, role)
        }
        expected_outputs = set(expected_specs)
        actual_outputs = {item.contract_output_id for item in outputs}
        if len(actual_outputs) != len(outputs) or not actual_outputs.issubset(expected_outputs):
            raise RoleLifecycleError(
                f"Closure {closure_id} contains undeclared or duplicate outputs."
            )
        # A successful closure must bind every REQUIRED output.  Optional
        # outputs (for example P5's assembly report and review artifacts) may
        # legitimately be absent; requiring strict equality would make such
        # closures impossible to reload during recovery.
        required_outputs = {
            contract_output_id
            for contract_output_id, spec in expected_specs.items()
            if spec.required
        }
        if (
            status is RoleExecutionStatus.SUCCEEDED
            and not required_outputs.issubset(actual_outputs)
        ):
            raise RoleLifecycleError(
                f"Successful closure {closure_id} does not bind every required output."
            )
        for output in outputs:
            spec = expected_specs[output.contract_output_id]
            if output.output_id != spec.output_id or output.media_type != "application/json":
                raise RoleLifecycleError(
                    f"Closure {closure_id} changes the contract binding for "
                    f"{output.contract_output_id!r}."
                )
            stored_output = self.artifacts.verify(output.sha256)
            if stored_output.relative_path != output.storage_relative_path:
                raise RoleLifecycleError(
                    f"Closure {closure_id} cites the wrong storage path for "
                    f"{output.contract_output_id!r}."
                )
            with self.repository.database.connect() as connection:
                output_row = connection.execute(
                    "SELECT * FROM artifacts WHERE artifact_id = ?",
                    (output.artifact_id,),
                ).fetchone()
            if (
                output_row is None
                or output_row["project_id"] != str(self.context.project_id)
                or output_row["sha256"] != output.sha256
                or output_row["size"] != output.size
            ):
                raise RoleLifecycleError(
                    f"Closure {closure_id} has an inconsistent artifact record for "
                    f"{output.contract_output_id!r}."
                )
        closure_artifact_id = _closure_artifact_id(closure_id)
        with self.repository.database.connect() as connection:
            artifact_row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (closure_artifact_id,)
            ).fetchone()
        if artifact_row is None:
            raise RoleLifecycleError(f"Closure artifact {closure_artifact_id} is missing.")
        closure_bytes = canonicalize(document)
        closure_artifact_sha256 = hashlib.sha256(closure_bytes).hexdigest()
        if (
            artifact_row["project_id"] != str(self.context.project_id)
            or artifact_row["sha256"] != closure_artifact_sha256
        ):
            raise RoleLifecycleError(
                f"Closure artifact {closure_artifact_id} does not bind the closure bytes."
            )
        self.artifacts.verify(closure_artifact_sha256)
        return RoleClosureResult(
            role=role,
            status=status,
            execution_id=execution_id,
            invocation_id=invocation_id,
            invocation_sha256=str(document["invocation_sha256"]),
            closure_id=closure_id,
            closure_sha256=str(closure_sha256),
            closure_artifact_id=closure_artifact_id,
            outputs=outputs,
            closed_at=str(document["closed_at"]),
            failure_code=document.get("failure_code"),
            reconciled=True,
        )

    def _acknowledgement(self, execution_id: str) -> Any | None:
        with self.repository.database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM role_execution_acknowledgements
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()

    @staticmethod
    def _output_document(output: SealedRoleOutput) -> dict[str, Any]:
        return {
            "contract_output_id": output.contract_output_id,
            "output_id": output.output_id,
            "artifact_id": output.artifact_id,
            "sha256": output.sha256,
            "size": output.size,
            "media_type": output.media_type,
            "storage_relative_path": output.storage_relative_path,
        }

    @staticmethod
    def _parse_output(document: Any) -> SealedRoleOutput:
        if type(document) is not dict:
            raise RoleLifecycleError("Stored closure output must be a JSON object.")
        try:
            size = document["size"]
            if type(size) is not int or size < 0:
                raise TypeError("size must be a nonnegative integer")
            return SealedRoleOutput(
                contract_output_id=str(document["contract_output_id"]),
                output_id=str(document["output_id"]),
                artifact_id=str(document["artifact_id"]),
                sha256=str(document["sha256"]),
                size=size,
                media_type=str(document["media_type"]),
                storage_relative_path=str(document["storage_relative_path"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RoleLifecycleError("Stored closure output is malformed.") from error


__all__ = [
    "FrozenInputPath",
    "RoleClosureResult",
    "RoleExecutionInfrastructureError",
    "RoleExecutionPending",
    "RoleLifecycleError",
    "RoleLifecycleService",
    "SealedRoleOutput",
    "deterministic_id",
    "document_sha256",
]
