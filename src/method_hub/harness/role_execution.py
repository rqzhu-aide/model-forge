"""Durable lifecycle for one already-frozen scientific role invocation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, thaw_json, utc_now
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
from .execution_context import RunExecutionContext
from .output_adapters import AdaptedOutput, DefaultOutputAdapter
from .outputs import OutputPlan, OutputSpec, validate_role_outputs
from .task_briefs import render_task_brief


from .execution_observer import RepositoryExecutionObserver as _RepositoryObserver
from .execution_records import (
    FrozenInputPath,
    RoleClosureResult,
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
) -> None:
    """Apply only mechanical, non-semantic repairs to agent outputs.

    This post-processor fixes deterministic schema-compliance issues that
    are purely mechanical — never content-bearing:

    - Missing ``created_at`` / ``updated_at`` timestamps.
    - Missing ``schema_version`` (always ``"1.0.0"``).
    - ID sanitization (force ``stableId`` fields to match the regex).
    - Stripping fields not declared when ``additionalProperties: false``.
    - Stripping ``null`` values for optional fields.

    It does **not** fabricate semantic content.  Missing authors, missing
    checks, wrong severity enums, missing lineage, etc. are left for
    validation to catch with a precise error so the agent learns the schema.
    """
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()
    specs = output_plan.for_stage_role(stage.stage_id, role)
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

        schema_info = _schema_info(spec.schema_file)
        valid_timestamps = schema_info["timestamps"]
        allowed_props = schema_info["properties"]
        no_additional = schema_info["no_additional"]
        required_fields = schema_info["required"]
        nested_required = schema_info.get("nested_required", set())
        nested_timestamps = schema_info.get("nested_timestamps", set())
        if not valid_timestamps and not (no_additional and allowed_props):
            continue

        def _fix_item(item: dict) -> bool:
            changed = False
            # Sanitize stableId fields — lowercase, replace invalid chars
            _ID_KEYS = ("object_id", "issue_id", "issue_version_id",
                        "statement_id", "affected_statement_id",
                        "finding_id", "claim_id", "theorem_id",
                        "definition_id", "assumption_id", "lemma_id",
                        "corollary_id", "proposition_id")
            for key in _ID_KEYS:
                val = item.get(key)
                if isinstance(val, str) and val != val.lower():
                    sane = _sanitize_id(val)
                    if sane != val:
                        item[key] = sane
                        changed = True
            # Sanitize ID arrays (evidence_ids, statement_ids, etc.). Only
            # touch lists whose key marks them as ID arrays — never prose
            # arrays (completed_work, required_checks, ...).
            for key, val in list(item.items()):
                if isinstance(val, list) and (
                    key.endswith("_ids") or key == "affected_record_ids"
                ):
                    new_vals = []
                    mod = False
                    for v in val:
                        if isinstance(v, str) and v != v.lower() and re.search(r"^[a-z]", v) is None or (isinstance(v, str) and re.search(r"[A-Z]", v) and re.search(r"[._-]", v)):
                            sane = _sanitize_id(v)
                            if sane != v:
                                new_vals.append(sane)
                                mod = True
                                continue
                        new_vals.append(v)
                    if mod:
                        item[key] = new_vals
                        changed = True
            # Add missing timestamps
            for field in valid_timestamps:
                if field not in item:
                    item[field] = ts
                    changed = True
            # Add missing schema_version if the schema declares it
            if "schema_version" in allowed_props and "schema_version" not in item:
                item["schema_version"] = "1.0.0"
                changed = True
            # Fix method identity version (must be >= 1)
            identity = item.get("identity")
            if isinstance(identity, dict) and identity.get("version", 1) < 1:
                identity["version"] = 1
                changed = True
            # Strip non-declared fields when additionalProperties is false
            if no_additional and allowed_props:
                for key in list(item.keys()):
                    if key not in allowed_props:
                        del item[key]
                        changed = True
            # Strip null values for optional string fields (agents write null
            # where schema expects a string; e.g. rerun_question in attention items)
            for key in list(item.keys()):
                if item[key] is None and key not in required_fields:
                    del item[key]
                    changed = True
            return changed

        def _deep_sanitize_ids(obj: Any, parent_key: str | None = None) -> bool:
            """Recursively walk the JSON tree and sanitize stableId strings.

            Catches IDs nested deep inside canonical_definition, evidence
            arrays, assumptions, etc. that _fix_item doesn't reach.  String
            elements of a list are only sanitized when the parent key marks
            the list as an ID array (``*_ids``) — never prose arrays.
            """
            changed = False
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if isinstance(val, str) and (
                        key.endswith("_id")
                        or key in ("stable_id", "affected_record_ids")
                    ):
                        if val != val.lower() or re.search(r"[^a-z0-9._-]", val):
                            sane = _sanitize_id(val)
                            if sane != val:
                                obj[key] = sane
                                changed = True
                    elif isinstance(val, (dict, list)):
                        if _deep_sanitize_ids(val, parent_key=key):
                            changed = True
            elif isinstance(obj, list):
                is_id_array = parent_key is not None and (
                    parent_key.endswith("_ids")
                    or parent_key == "affected_record_ids"
                )
                for i, item in enumerate(obj):
                    if (
                        is_id_array
                        and isinstance(item, str)
                        and item != item.lower()
                    ):
                        # Sanitize strings in ID arrays (evidence_ids, etc.)
                        sane = _sanitize_id(item)
                        if sane != item:
                            obj[i] = sane
                            changed = True
                    elif isinstance(item, (dict, list)):
                        if _deep_sanitize_ids(item):
                            changed = True
            return changed

        changed = False
        if isinstance(data, dict):
            changed = _fix_item(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if _fix_item(item):
                        changed = True
        # Deep recursive pass: catch IDs nested in canonical_definition,
        # evidence arrays, assumptions, theorems, etc.
        if _deep_sanitize_ids(data):
            changed = True
        # Remove empty-string values that violate minLength: 1 constraints.
        # Agents sometimes write "" for optional fields instead of omitting
        # them.  Required fields (top-level and nested) are never stripped
        # (that would turn a minLength error into a missing-required error).
        all_required = required_fields | nested_required
        if _strip_empty_strings(data, required_fields=all_required):
            changed = True

        # Add missing nested timestamps (e.g. assessed_at inside
        # alignmentAssessment) — agents miss these because they're buried
        # deep in the schema.
        if _add_missing_timestamps(data, nested_timestamps, ts):
            changed = True
        # Fix self-referential hashes: agents can't know the hash of the
        # file they're writing. Compute content_sha256, handoff_artifact.sha256,
        # and definition_sha256 from the output content (excluding the hash
        # field itself). Runs AFTER all other repairs so the stored hash
        # matches the file actually written to disk.
        if _fix_self_referential_hashes(data, path):
            changed = True
        if changed:
            path.write_text(
                _json.dumps(data, indent=2, ensure_ascii=False),
            )


def _add_missing_timestamps(
    data: Any, timestamp_fields: set[str], ts: str
) -> bool:
    """Add missing timestamp fields anywhere in the JSON tree.

    Some schemas require timestamps in nested objects (e.g.
    ``alignmentAssessment.assessed_at``) that agents miss because
    they're buried deep.  Walk the tree and fill them in.
    """
    if not timestamp_fields:
        return False

    changed = False

    def _walk(obj: Any) -> None:
        nonlocal changed
        if isinstance(obj, dict):
            for key in timestamp_fields:
                if key not in obj:
                    obj[key] = ts
                    changed = True
            for val in obj.values():
                if isinstance(val, (dict, list)):
                    _walk(val)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    _walk(item)

    _walk(data)
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
    "tbd_by_method_hub_on_write", "tbd", "placeholder",
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
    """Compute SHA-256 of *data* with *exclude_keys* removed at every level.

    Uses canonical JSON (sorted keys, ensure_ascii=False) so the result is
    deterministic regardless of key insertion order.
    """
    import hashlib
    import json as _json

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

    cleaned = _scrub(data)
    encoded = _json.dumps(cleaned, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fix_self_referential_hashes(data: Any, path: Path) -> bool:
    """Compute and stamp all self-referential SHA-256 fields in agent output.

    Agents cannot know the hash of the file they are currently writing.
    This function finds every self-referential hash field and replaces it
    with the correct hash computed from the file content (excluding the
    hash field itself).

    Handles three classes of self-referential hashes:

    1. ``content_sha256`` — top-level field on scientific-record, evidence,
       attention-item, decision-record.  Hash of the entire document minus
       this field.
    2. ``handoff_artifact.sha256`` — nested in handoff records.  Hash of the
       handoff document minus the sha256 sub-field.
    3. ``representations[].artifact.sha256`` / ``artifacts[].sha256`` —
       pointer hashes inside representation/evidence arrays.  These are NOT
       self-referential (they point at other files), so they are left alone.
       Agents source these from the run workspace.
    """
    changed = False

    def _fix_record(obj: dict) -> bool:
        nonlocal changed
        touched = False

        # 1. content_sha256 — always recompute (hash paradox)
        if "content_sha256" in obj:
            correct = _compute_content_hash(obj, {"content_sha256"})
            if obj.get("content_sha256") != correct:
                obj["content_sha256"] = correct
                touched = True

        # 2. handoff_artifact.sha256 — recompute from the handoff dict
        ha = obj.get("handoff_artifact")
        if isinstance(ha, dict) and "sha256" in ha:
            snapshot = dict(obj)
            artifact_snapshot = dict(ha)
            artifact_snapshot.pop("sha256", None)
            snapshot["handoff_artifact"] = artifact_snapshot
            encoded = _json_dumps_canonical(snapshot)
            correct = hashlib.sha256(encoded).hexdigest()
            if ha.get("sha256") != correct:
                ha["sha256"] = correct
                touched = True

        # 3. definition_sha256 inside mathematical definitions — these are
        # content hashes of the definition, NOT the file. Recompute from the
        # definition content if it looks like a placeholder.
        md = obj.get("mathematical_definition")
        if isinstance(md, dict) and "definition_sha256" in md:
            correct = _compute_content_hash(md, {"definition_sha256"})
            if md.get("definition_sha256") != correct:
                md["definition_sha256"] = correct
                touched = True

        return touched

    import hashlib
    import json as _json

    def _json_dumps_canonical(obj: Any) -> bytes:
        return _json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")

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


def _schema_info(schema_file: str) -> dict[str, Any]:
    """Return schema metadata for deterministic post-processing."""
    try:
        import json as _json

        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[3]
        schema_path = root / "architecture" / "schemas" / schema_file
        if not schema_path.exists():
            return _empty_schema_info()
        schema = _json.loads(schema_path.read_text())
        properties = schema.get("properties", {})
        props = set(properties.keys())
        timestamps = props & set(_TIMESTAMP_FIELDS)
        no_additional = schema.get("additionalProperties") is False
        required = set(schema.get("required", []))

        # Collect nested required fields from sub-object property definitions
        # and from $defs/$ref-resolved definitions referenced via allOf.
        nested_required = _collect_nested_required(schema)

        # Collect timestamp-like fields declared in nested properties
        # (e.g. alignmentAssessment.assessed_at).
        nested_timestamps = set()
        _collect_nested_timestamps(schema, nested_timestamps)

        return {
            "timestamps": timestamps,
            "properties": props,
            "no_additional": no_additional,
            "required": required,
            "nested_required": nested_required,
            "nested_timestamps": nested_timestamps,
        }
    except Exception:
        return _empty_schema_info()


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


def _collect_nested_timestamps(schema: dict[str, Any], found: set[str]) -> None:
    """Find timestamp-like field names in nested properties."""
    _TS_SUFFIXES = ("_at", "_timestamp", "_time")
    properties = schema.get("properties", {})

    def _walk(obj_def: dict[str, Any]) -> None:
        if not isinstance(obj_def, dict):
            return
        sub_props = obj_def.get("properties", {})
        if isinstance(sub_props, dict):
            for key, sub_def in sub_props.items():
                # A search timestamp attests that an external search occurred.
                # It is scientific provenance, not a mechanical write-time
                # default, so the harness must require the producer to state it.
                if key != "searched_at" and isinstance(key, str) and any(
                    key.endswith(s) for s in _TS_SUFFIXES
                ):
                    found.add(key)
                if isinstance(sub_def, dict):
                    _walk(sub_def)

    for prop_def in properties.values():
        _walk(prop_def)


def _empty_schema_info() -> dict[str, Any]:
    return {
        "timestamps": set(),
        "properties": set(),
        "no_additional": False,
        "required": set(),
        "nested_required": set(),
        "nested_timestamps": set(),
    }


def _sanitize_id(val: str) -> str:
    """Force a stableId to match ^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$."""
    sane = val.lower()
    sane = re.sub(r"[^a-z0-9._-]", "_", sane)
    sane = re.sub(r"^[^a-z]+", "", sane) or "id"
    sane = re.sub(r"\.{2,}", ".", sane)
    return sane


# Schema file name → which timestamp fields are declared properties
_TIMESTAMP_FIELDS = ("created_at", "updated_at")


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

    def load_existing(
        self, *, stage: ResolvedStage, role: str
    ) -> RoleClosureResult | None:
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
        )
        task_payload = task_text.encode("utf-8")
        _immutable_write(task_path, task_payload)

        # Materialize frozen inputs into the role workspace via the
        # capability broker, verifying digests and logging every access.
        access_log_path = role_root / "access.jsonl"
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
            "format": "method-hub.role-invocation-start",
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
        sealed_outputs: tuple[SealedRoleOutput, ...] = ()
        findings: list[dict[str, Any]] = []
        if self.repository.cancellation_requested(str(self.context.run_id)):
            status = RoleExecutionStatus.CANCELLED
        elif status is RoleExecutionStatus.SUCCEEDED:
            _apply_disclosed_mechanical_repairs(
                run_root=self.workspace.for_read(f"runs/{self.context.run_id}"),
                output_plan=self.context.output_plan,
                stage=stage,
                role=role,
                run_id=str(self.context.run_id),
            )
            validation = validate_role_outputs(
                schema_catalog=self.schemas,
                run_root=self.workspace.for_read(f"runs/{self.context.run_id}"),
                output_plan=self.context.output_plan,
                stage=stage,
                role=role,
            )
            findings = [item.to_dict() for item in validation.findings]
            if not validation.passed:
                status = RoleExecutionStatus.FAILED
                failure_code = "output.structural_validation_failed"
            sealed_outputs = tuple(
                self._seal_output(item.spec, item.path, item.sha256)
                for item in validation.outputs
            )
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
            try:
                from .output_adapters import preserve_raw_output
                preserve_raw_output(
                    workspace=invocation.workspace,
                    run_id=invocation.run_id,
                    role=role,
                    artifacts=self.artifacts,
                )
            except Exception:
                pass

        if status is RoleExecutionStatus.CANCELLED:
            failure_code = None
        closed_at = isoformat_utc(utc_now())
        closure_document: dict[str, Any] = {
            "format": "method-hub.role-invocation-closure",
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
        return SealedRoleOutput(
            contract_output_id=spec.contract_output_id,
            output_id=spec.output_id,
            artifact_id=artifact_id,
            sha256=str(stored.sha256),
            size=stored.size,
            media_type="application/json",
            storage_relative_path=stored.relative_path,
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
        if status is RoleExecutionStatus.SUCCEEDED and actual_outputs != expected_outputs:
            raise RoleLifecycleError(
                f"Successful closure {closure_id} does not bind every declared output."
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
    "RoleExecutionPending",
    "RoleLifecycleError",
    "RoleLifecycleService",
    "SealedRoleOutput",
    "deterministic_id",
    "document_sha256",
]
