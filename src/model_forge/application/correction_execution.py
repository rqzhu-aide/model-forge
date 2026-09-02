"""Revalidation core and closure write for the correction command path.

Revalidates the sealed outputs of one role closure against the CURRENT
schema catalog and policy registry (K-1a3):

1. Load the run's frozen recipe and re-resolve the phase plan.
2. Load the sealed role closure and materialize its outputs into a fresh
   temporary run root, digest-verified byte for byte (tamper evidence).
3. Re-run ``validate_role_outputs`` against the current schemas.
4. Record an immutable ``run_validation_attempts`` row chained to the prior
   attempt and the authorizing correction command.

K-1a4 adds ``record_revalidation_closure``: after a revalidation PASSES,
the correction-family intent/acknowledgement/closure triple is written so
that the family-aware ``RoleLifecycleService.load_existing`` (K-1a2) finds
a SUCCEEDED closure under the correction identity.  The closure document is
a deep copy of the source payload with only the identity/status fields
overridden (schema shape stays exact); its digest is recomputed.  The
source (failed) closure is never mutated.

K-1a5 Lane A adds ``seal_correction_submission``: the synchronous
submission re-entry for a run in CORRECTING, delegating to the
attempt-aware ``SubmissionAssembler`` correction branch.

K-1b adds the normalize execution core: ``normalize_closure_outputs``
applies the allowlisted mechanical transformations
(``ALLOWED_NORMALIZE_CODES``) to a copy of the sealed output bytes,
persists transformed bytes as new artifacts, and records the attempt
with an embedded per-output transformation record;
``record_normalize_closure`` writes the correction-family closure for a
PASSED normalization, overriding the output digests to the transformed
bytes; ``preview_normalize`` is the read-only dry run (zero writes of
any kind) that reports which current findings the transformations would
fix and which would remain.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import ResolvedPhasePlan
from ..digests.jcs import canonicalize
from ..domain import StableId
from ..domain.runs import isoformat_utc, utc_now
from ..domain.validation import (
    FindingClass,
    OutputTransformationRecord,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    finding_from_dict,
    make_finding,
    registry_version,
)
from ..executors import RoleExecutionStatus
from ..harness.execution_records import (
    RoleExecutionInfrastructureError,
    closure_artifact_id,
    correction_role_identity,
    deterministic_id,
    document_sha256,
)
from ..harness.envelope import harness_owned_fields
from ..harness.outputs import build_output_plan, validate_role_outputs
from ..harness.preparation import PreparedRunRecipe
from ..harness.role_execution import (
    _classify_transformations,
    _primary_artifact_unchanged,
    apply_normalize_transformations,
)
from ..harness.stage_execution import HarnessExecutionServices
from ..harness.submissions import SubmissionAssemblyError
from ..json_io import loads_json
from ..orchestration import StageOutcome, StageStatus, SubmissionStatus
from ..schemas import SchemaCatalog
from ..specification import SpecificationPackage
from ..storage.artifacts import ArtifactStore
from ..storage.repository import HubRepository, RepositoryConflictError
from .correction import (
    ALLOWED_NORMALIZE_CODES,
    CorrectionResult,
    ValidationAttempt,
    _derive_attempt_id,
    build_correction_instruction,
)


def _plan_method_bound(plan: ResolvedPhasePlan) -> bool:
    """True when the frozen plan selected a method (any
    ``*.selected_method`` choice carrying a Mapping value)."""
    return any(
        str(key).endswith(".selected_method") and isinstance(value, Mapping)
        for key, value in plan.choice_values.items()
    )


def _recipe_for_run(repository: HubRepository, run_id: str) -> PreparedRunRecipe:
    row = repository.get_manifest(run_id)
    if row is None:
        raise ValueError("Run manifest is unavailable.")
    document = loads_json(row["payload_json"], source=f"manifest {run_id}")
    if type(document) is not dict:
        raise ValueError("Run manifest must be an object.")
    return PreparedRunRecipe.load(document, str(row["manifest_sha256"]))


def _recover_frozen_contract(
    specification: SpecificationPackage,
    repository: HubRepository,
    artifacts: ArtifactStore,
    project_id: str,
    pinned_sha256: str,
) -> dict[str, Any] | None:
    """Load frozen contract bytes preserved at seal time.

    Runs sealed under a superseded contract version pin the contract by
    digest; the bytes are content-addressed into the artifact store at
    preparation so corrections can always resolve the exact frozen plan.
    The recovered document is accepted only when its registry digest equals
    the run's pinned digest.
    """
    for row in repository.find_artifacts_by_purpose(project_id, "phase_contract_frozen"):
        document = loads_json(
            artifacts.read_bytes(str(row["sha256"])),
            source=f"artifact {row['artifact_id']}",
        )
        if type(document) is not dict:
            continue
        digest = specification.digests.compute("phase_contract.content", document)
        if str(digest) == pinned_sha256:
            return document
    return None


def _plan_from_recipe(
    specification: SpecificationPackage,
    recipe: PreparedRunRecipe,
    *,
    repository: HubRepository | None = None,
    artifacts: ArtifactStore | None = None,
    project_id: str | None = None,
):
    identity = specification.phases.identity(str(recipe.document["phase"]))
    if (
        str(identity.contract_version)
        == str(recipe.document["phase_contract_version"])
        and str(identity.phase_contract_sha256)
        == str(recipe.document["phase_contract_sha256"])
    ):
        request = recipe.document["user_request"]
        return specification.resolve_phase(
            identity,
            str(recipe.document["mode"]),
            dict(request["choice_values"]),
            str(request["context_policy"]),
        )
    # The run was sealed under a superseded contract version. Recover the
    # exact frozen contract bytes preserved at seal time and resolve the plan
    # from them, re-pinned through the digest registry.
    if repository is not None and artifacts is not None and project_id is not None:
        document = _recover_frozen_contract(
            specification,
            repository,
            artifacts,
            project_id,
            str(recipe.document["phase_contract_sha256"]),
        )
        if document is not None:
            request = recipe.document["user_request"]
            return specification.resolve_phase_frozen(
                document,
                str(recipe.document["mode"]),
                dict(request["choice_values"]),
                str(request["context_policy"]),
            )
    raise ValueError("Frozen phase contract is unavailable.")


def _closure_payload(repository: HubRepository, closure_id: str) -> dict[str, Any]:
    row = repository.get_role_closure(closure_id)
    if row is None:
        raise ValueError(f"Role closure {closure_id!r} is unavailable.")
    document = loads_json(row["payload_json"], source=f"role closure {closure_id}")
    if type(document) is not dict:
        raise ValueError("Role closure payload must be an object.")
    return document

def _parse_findings(items: Any) -> tuple[ValidationFinding, ...]:
    """Rehydrate serialized finding dicts into ValidationFinding records."""
    return tuple(
        finding
        for item in items or ()
        if (finding := finding_from_dict(item)) is not None
    )


def revalidate_closure_outputs(
    *,
    repository: HubRepository,
    specification: SpecificationPackage,
    artifacts: ArtifactStore,
    schemas: SchemaCatalog,
    run_id: str,
    role_closure_id: str,
    correction_command_id: str,
) -> CorrectionResult:
    """Re-validate one sealed role closure's outputs against current schemas.

    The sealed bytes are materialized digest-verified into a temporary run
    root; any digest mismatch is tamper evidence and raises ``ValueError``.
    Exactly one ``run_validation_attempts`` row is recorded per call.
    """
    recipe = _recipe_for_run(repository, run_id)
    plan = _plan_from_recipe(
        specification,
        recipe,
        repository=repository,
        artifacts=artifacts,
        project_id=str(recipe.document["project_id"]),
    )
    output_plan = build_output_plan(plan)

    payload = _closure_payload(repository, role_closure_id)
    stage_id = str(payload.get("stage_id", ""))
    role = str(payload.get("role", ""))
    stage = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(
            f"Closure stage {stage_id!r} is not part of the frozen phase plan."
        )
    specs = {
        spec.contract_output_id: spec
        for spec in output_plan.for_stage_role(stage.stage_id, role)
    }

    sealed: list[str] = []
    with tempfile.TemporaryDirectory() as temporary:
        run_root = Path(temporary)
        for entry in payload.get("outputs", ()):
            contract_output_id = str(entry["contract_output_id"])
            sha256 = str(entry["sha256"])
            spec = specs.get(contract_output_id)
            if spec is None:
                raise ValueError(
                    f"Closure output {contract_output_id!r} is not declared for "
                    f"stage {stage_id!r} role {role!r}."
                )
            data = artifacts.read_bytes(sha256)
            if hashlib.sha256(data).hexdigest() != sha256:
                raise ValueError(
                    f"Sealed output {contract_output_id!r} does not match its "
                    "recorded SHA-256 digest."
                )
            target = run_root.joinpath(*spec.relative_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            sealed.append(sha256)
        result = validate_role_outputs(
            schema_catalog=schemas,
            run_root=run_root,
            output_plan=output_plan,
            stage=stage,
            role=role,
            method_bound=_plan_method_bound(plan),
        )

    ordinal = repository.count_validation_attempts(run_id) + 1
    attempt_id = _derive_attempt_id(run_id, ordinal)
    policy_version = registry_version()
    report = ValidationReport.from_findings(
        f"report.{attempt_id}", run_id, "revalidate", result.findings
    )
    digest_input = "revalidate:" + "".join(sorted(sealed))
    source_sha256 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    prior = repository.get_latest_validation_attempt(run_id)
    prior_attempt_id = str(prior["attempt_id"]) if prior is not None else None
    stored = repository.record_validation_attempt(
        attempt_id,
        run_id,
        ordinal,
        policy_version,
        json.dumps(report.to_dict(), sort_keys=True),
        source_sha256,
        correction_type="revalidate",
        prior_attempt_id=prior_attempt_id,
        correction_command_id=correction_command_id,
    )
    attempt = ValidationAttempt(
        attempt_id=attempt_id,
        run_id=run_id,
        policy_version=policy_version,
        report=report,
        source_sha256=source_sha256,
        correction_type="revalidate",
        prior_attempt_id=prior_attempt_id,
        correction_command_id=correction_command_id,
        attempted_at=str(stored["attempted_at"]),
    )
    return CorrectionResult(attempt=attempt, findings=tuple(result.findings))


def record_revalidation_closure(
    *,
    repository: HubRepository,
    artifacts: ArtifactStore,
    specification: SpecificationPackage,
    run_id: str,
    role_closure_id: str,
    correction_command_id: str,
    invocation_sha256: str,
    findings: tuple[ValidationFinding, ...] = (),
) -> str:
    """Write the correction-family closure for a PASSED revalidation.

    The closure document is a deep copy of the source closure payload with
    the identity/status fields overridden (no new fields; the correction
    linkage lives in the attempts table, the identity derivation, and the
    intent payload).  ``invocation_sha256`` is the digest of the sealed
    correction command, binding the closure to its authorization.

    Idempotent: an exact replay short-circuits on the already-sealed
    closure and returns the same closure id; a DIFFERENT second write for
    the same correction identity surfaces ``RepositoryConflictError`` from
    the repository (never caught here).  The source closure is immutable
    and never mutated.  Returns the correction closure id.
    """
    recipe = _recipe_for_run(repository, run_id)
    plan = _plan_from_recipe(
        specification,
        recipe,
        repository=repository,
        artifacts=artifacts,
        project_id=str(recipe.document["project_id"]),
    )
    payload = _closure_payload(repository, role_closure_id)
    stage_id = str(payload.get("stage_id", ""))
    role = str(payload.get("role", ""))
    stage = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(
            f"Closure stage {stage_id!r} is not part of the frozen phase plan."
        )

    c_invocation_id, c_execution_id, c_closure_id = correction_role_identity(
        run_id, recipe.sha256, stage, role, correction_command_id
    )
    external_execution_id = f"correction:{correction_command_id}"
    linkage = {
        "kind": "correction_revalidate",
        "correction_command_id": correction_command_id,
        "source_closure_id": role_closure_id,
    }
    repository.get_or_create_execution(
        c_execution_id,
        c_invocation_id,
        run_id,
        invocation_sha256,
        dict(linkage),
    )
    repository.acknowledge_execution(
        c_execution_id,
        external_execution_id,
        dict(linkage),
    )

    def _document(closed_at: str) -> dict[str, Any]:
        document = copy.deepcopy(payload)
        document.pop("closure_sha256", None)
        document["closure_id"] = c_closure_id
        document["execution_id"] = c_execution_id
        document["invocation_id"] = c_invocation_id
        document["invocation_sha256"] = invocation_sha256
        document["status"] = "succeeded"
        document["failure_code"] = None
        document["exit_code"] = 0
        document["external_execution_id"] = external_execution_id
        document["summary"] = (
            "Revalidation converged: the sealed outputs conform to the "
            f"current schema catalog under correction {correction_command_id}."
        )
        document["findings"] = [finding.to_dict() for finding in findings]
        document["closed_at"] = closed_at
        return document

    existing = repository.get_role_closure(c_closure_id)
    if existing is not None:
        existing_document = loads_json(
            existing["payload_json"], source=f"role closure {c_closure_id}"
        )
        closed_at = (
            str(existing_document.get("closed_at", ""))
            if type(existing_document) is dict
            else ""
        )
        probe = _document(closed_at)
        probe_sha256 = document_sha256(probe)
        probe["closure_sha256"] = probe_sha256
        if (
            type(existing_document) is dict
            and str(existing["closure_sha256"]) == probe_sha256
            and existing_document == probe
        ):
            return c_closure_id
        # A different write for the same correction identity: fall through
        # to the write path so the repository surfaces the conflict.

    document = _document(isoformat_utc(utc_now()))
    closure_sha256 = document_sha256(document)
    document["closure_sha256"] = closure_sha256
    closure_bytes = canonicalize(document)
    stored = artifacts.put_bytes(
        closure_bytes, expected_sha256=hashlib.sha256(closure_bytes).hexdigest()
    )
    # F4 (audit 2026-09-02): the correction-family close path runs under the
    # same non-sealing infrastructure-error semantics as the harness close
    # path - a transient repository failure here marks the bookkeeping
    # failure as retryable instead of surfacing as an opaque generic error.
    # Conflicts keep their integrity/concurrency semantics (an exact replay
    # short-circuits above; a DIFFERENT write must surface the conflict) and
    # are never converted.
    try:
        repository.record_artifact(
            closure_artifact_id(c_closure_id),
            str(payload["project_id"]),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "role_invocation_closure",
                "run_id": run_id,
                "closure_id": c_closure_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        repository.close_execution(
            c_execution_id, c_closure_id, closure_sha256, document
        )
    except RoleExecutionInfrastructureError:
        raise
    except RepositoryConflictError:
        raise
    except Exception as error:
        raise RoleExecutionInfrastructureError(
            f"Harness bookkeeping for correction closure "
            f"{c_closure_id} failed: "
            f"{type(error).__name__}: {error}"
        ) from error
    return c_closure_id

@dataclass(frozen=True, slots=True)
class NormalizeExecution:
    """Outcome of one normalize execution (K-1b)."""

    attempt: ValidationAttempt
    findings: tuple[ValidationFinding, ...]
    transformation_records: dict[str, OutputTransformationRecord]
    # contract_output_id -> result sha256, for CHANGED outputs only.
    result_digests: dict[str, str]

def _check_normalize_allowlist(transformation_codes: Iterable[str]) -> set[str]:
    codes = set(transformation_codes)
    disallowed = codes - ALLOWED_NORMALIZE_CODES
    if disallowed:
        raise ValueError(
            "Transformation codes outside the normalize allowlist: "
            f"{sorted(disallowed)}."
        )
    return codes

def normalize_closure_outputs(
    *,
    repository: HubRepository,
    specification: SpecificationPackage,
    artifacts: ArtifactStore,
    schemas: SchemaCatalog,
    run_id: str,
    role_closure_id: str,
    correction_command_id: str,
    transformation_codes: Iterable[str],
) -> NormalizeExecution:
    """Apply allowlisted transformations to sealed outputs and re-validate.

    Mirrors ``revalidate_closure_outputs``: the sealed bytes are
    materialized digest-verified into a temporary run root, the
    transformations mutate parsed copies in place, transformed bytes are
    persisted as new artifacts (the sealed source bytes are never
    mutated), and the transformed tree is validated against the current
    schema catalog.  Exactly one ``run_validation_attempts`` row is
    recorded per call, with the per-output transformation records embedded
    in the report.  Disallowed transformation codes raise ``ValueError``
    before any write.
    """
    codes = _check_normalize_allowlist(transformation_codes)
    recipe = _recipe_for_run(repository, run_id)
    plan = _plan_from_recipe(
        specification,
        recipe,
        repository=repository,
        artifacts=artifacts,
        project_id=str(recipe.document["project_id"]),
    )
    output_plan = build_output_plan(plan)

    payload = _closure_payload(repository, role_closure_id)
    project_id = str(payload.get("project_id", ""))
    stage_id = str(payload.get("stage_id", ""))
    role = str(payload.get("role", ""))
    stage = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(
            f"Closure stage {stage_id!r} is not part of the frozen phase plan."
        )
    specs = {
        spec.contract_output_id: spec
        for spec in output_plan.for_stage_role(stage.stage_id, role)
    }

    transformation_records: dict[str, OutputTransformationRecord] = {}
    result_digests: dict[str, str] = {}
    sealed_results: list[str] = []
    with tempfile.TemporaryDirectory() as temporary:
        run_root = Path(temporary)
        for entry in payload.get("outputs", ()):
            contract_output_id = str(entry["contract_output_id"])
            sha256 = str(entry["sha256"])
            spec = specs.get(contract_output_id)
            if spec is None:
                raise ValueError(
                    f"Closure output {contract_output_id!r} is not declared for "
                    f"stage {stage_id!r} role {role!r}."
                )
            sealed_bytes = artifacts.read_bytes(sha256)
            if hashlib.sha256(sealed_bytes).hexdigest() != sha256:
                raise ValueError(
                    f"Sealed output {contract_output_id!r} does not match its "
                    "recorded SHA-256 digest."
                )
            target = run_root.joinpath(*spec.relative_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            document = json.loads(sealed_bytes.decode("utf-8"))
            snapshot = copy.deepcopy(document)
            renames: dict[str, str] = {}
            changed = apply_normalize_transformations(
                document,
                spec=spec,
                codes=codes,
                ts=isoformat_utc(utc_now()),
                path=target,
                renames=renames,
                schemas_dir=schemas.directory,
            )
            if changed:
                result_bytes = json.dumps(
                    document, indent=2, ensure_ascii=False
                ).encode("utf-8")
                result_sha256 = hashlib.sha256(result_bytes).hexdigest()
                target.write_bytes(result_bytes)
                stored_output = artifacts.put_bytes(
                    result_bytes, expected_sha256=result_sha256
                )
                repository.record_artifact(
                    deterministic_id(
                        "artifact",
                        project_id,
                        run_id,
                        spec.contract_output_id,
                        result_sha256,
                    ),
                    project_id,
                    str(stored_output.sha256),
                    stored_output.size,
                    "application/json",
                    f"artifact://sha256/{stored_output.sha256}",
                    {
                        "kind": "normalized_role_output",
                        "run_id": run_id,
                        "contract_output_id": spec.contract_output_id,
                        "output_id": spec.output_id,
                        "storage_relative_path": stored_output.relative_path,
                    },
                )
                result_digests[contract_output_id] = result_sha256
            else:
                result_sha256 = sha256
                target.write_bytes(sealed_bytes)
            entries = _classify_transformations(snapshot, document, renames=renames)
            transformation_records[contract_output_id] = OutputTransformationRecord(
                contract_output_id=contract_output_id,
                source_sha256=sha256,
                result_sha256=result_sha256,
                entries=tuple(entries),
                primary_artifact_unchanged=_primary_artifact_unchanged(entries),
            )
            sealed_results.append(result_sha256)
        result = validate_role_outputs(
            schema_catalog=schemas,
            run_root=run_root,
            output_plan=output_plan,
            stage=stage,
            role=role,
            method_bound=_plan_method_bound(plan),
        )

    ordinal = repository.count_validation_attempts(run_id) + 1
    attempt_id = _derive_attempt_id(run_id, ordinal)
    policy_version = registry_version()
    report = ValidationReport.from_findings(
        f"report.{attempt_id}", run_id, "normalize", result.findings
    )
    report_dict = report.to_dict()
    report_dict["output_transformations"] = [
        record.to_dict() for record in transformation_records.values()
    ]
    digest_input = "normalize:" + "".join(sorted(sealed_results))
    source_sha256 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    prior = repository.get_latest_validation_attempt(run_id)
    prior_attempt_id = str(prior["attempt_id"]) if prior is not None else None
    stored = repository.record_validation_attempt(
        attempt_id,
        run_id,
        ordinal,
        policy_version,
        json.dumps(report_dict, sort_keys=True),
        source_sha256,
        correction_type="normalize",
        prior_attempt_id=prior_attempt_id,
        correction_command_id=correction_command_id,
    )
    attempt = ValidationAttempt(
        attempt_id=attempt_id,
        run_id=run_id,
        policy_version=policy_version,
        report=report,
        source_sha256=source_sha256,
        correction_type="normalize",
        prior_attempt_id=prior_attempt_id,
        correction_command_id=correction_command_id,
        attempted_at=str(stored["attempted_at"]),
    )
    return NormalizeExecution(
        attempt=attempt,
        findings=tuple(result.findings),
        transformation_records=transformation_records,
        result_digests=result_digests,
    )

def record_normalize_closure(
    *,
    repository: HubRepository,
    artifacts: ArtifactStore,
    specification: SpecificationPackage,
    run_id: str,
    role_closure_id: str,
    correction_command_id: str,
    invocation_sha256: str,
    result_digests: dict[str, str],
    transformation_records: dict[str, OutputTransformationRecord],
    findings: tuple[ValidationFinding, ...] = (),
) -> str:
    """Write the correction-family closure for a PASSED normalization.

    Mirrors ``record_revalidation_closure``, except the closure document's
    output entries are rebound to the transformed bytes: every occurrence
    of the original digest string (the ``sha256`` field and any
    digest-carrying storage path or URI field) is replaced by the
    override from ``result_digests``, and the entry's ``size`` and
    ``artifact_id`` are updated to the persisted normalized artifact so
    the correction closure passes the full ``_load_closure``
    verification.  The transformation records are embedded as
    ``output_transformations``.

    Idempotent: an exact replay short-circuits on the already-sealed
    closure and returns the same closure id; a DIFFERENT second write for
    the same correction identity surfaces ``RepositoryConflictError`` from
    the repository (never caught here).  The source closure is immutable
    and never mutated.  Returns the correction closure id.
    """
    recipe = _recipe_for_run(repository, run_id)
    plan = _plan_from_recipe(
        specification,
        recipe,
        repository=repository,
        artifacts=artifacts,
        project_id=str(recipe.document["project_id"]),
    )
    payload = _closure_payload(repository, role_closure_id)
    stage_id = str(payload.get("stage_id", ""))
    role = str(payload.get("role", ""))
    stage = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(
            f"Closure stage {stage_id!r} is not part of the frozen phase plan."
        )

    c_invocation_id, c_execution_id, c_closure_id = correction_role_identity(
        run_id, recipe.sha256, stage, role, correction_command_id
    )
    external_execution_id = f"correction:{correction_command_id}"
    linkage = {
        "kind": "correction_normalize",
        "correction_command_id": correction_command_id,
        "source_closure_id": role_closure_id,
    }
    repository.get_or_create_execution(
        c_execution_id,
        c_invocation_id,
        run_id,
        invocation_sha256,
        dict(linkage),
    )
    repository.acknowledge_execution(
        c_execution_id,
        external_execution_id,
        dict(linkage),
    )

    def _document(closed_at: str) -> dict[str, Any]:
        document = copy.deepcopy(payload)
        document.pop("closure_sha256", None)
        document["closure_id"] = c_closure_id
        document["execution_id"] = c_execution_id
        document["invocation_id"] = c_invocation_id
        document["invocation_sha256"] = invocation_sha256
        document["status"] = "succeeded"
        document["failure_code"] = None
        document["exit_code"] = 0
        document["external_execution_id"] = external_execution_id
        for output_entry in document.get("outputs", ()):
            if type(output_entry) is not dict:
                continue
            contract_output_id = str(output_entry.get("contract_output_id", ""))
            override = result_digests.get(contract_output_id)
            if override is None:
                continue
            original = str(output_entry.get("sha256", ""))
            for key, value in output_entry.items():
                if isinstance(value, str) and original and original in value:
                    output_entry[key] = value.replace(original, override)
            stored_output = artifacts.verify(override)
            # The artifact store shards the digest in its relative path
            # (``.../sha256/<2>/<rest>``), so the contiguous-digest
            # replacement above cannot reach it; rebind it explicitly with
            # the size and artifact id of the normalized artifact.
            output_entry["storage_relative_path"] = stored_output.relative_path
            output_entry["size"] = stored_output.size
            output_entry["artifact_id"] = deterministic_id(
                "artifact",
                str(document["project_id"]),
                run_id,
                contract_output_id,
                override,
            )
        document["output_transformations"] = [
            record.to_dict() for record in transformation_records.values()
        ]
        document["summary"] = (
            "Normalization converged: the transformed outputs conform to the "
            f"current schema catalog under correction {correction_command_id}."
        )
        document["findings"] = [finding.to_dict() for finding in findings]
        document["closed_at"] = closed_at
        return document

    existing = repository.get_role_closure(c_closure_id)
    if existing is not None:
        existing_document = loads_json(
            existing["payload_json"], source=f"role closure {c_closure_id}"
        )
        closed_at = (
            str(existing_document.get("closed_at", ""))
            if type(existing_document) is dict
            else ""
        )
        probe = _document(closed_at)
        probe_sha256 = document_sha256(probe)
        probe["closure_sha256"] = probe_sha256
        if (
            type(existing_document) is dict
            and str(existing["closure_sha256"]) == probe_sha256
            and existing_document == probe
        ):
            return c_closure_id
        # A different write for the same correction identity: fall through
        # to the write path so the repository surfaces the conflict.

    document = _document(isoformat_utc(utc_now()))
    closure_sha256 = document_sha256(document)
    document["closure_sha256"] = closure_sha256
    closure_bytes = canonicalize(document)
    stored = artifacts.put_bytes(
        closure_bytes, expected_sha256=hashlib.sha256(closure_bytes).hexdigest()
    )
    # F4 (audit 2026-09-02): the correction-family close path runs under the
    # same non-sealing infrastructure-error semantics as the harness close
    # path - a transient repository failure here marks the bookkeeping
    # failure as retryable instead of surfacing as an opaque generic error.
    # Conflicts keep their integrity/concurrency semantics (an exact replay
    # short-circuits above; a DIFFERENT write must surface the conflict) and
    # are never converted.
    try:
        repository.record_artifact(
            closure_artifact_id(c_closure_id),
            str(payload["project_id"]),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "role_invocation_closure",
                "run_id": run_id,
                "closure_id": c_closure_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        repository.close_execution(
            c_execution_id, c_closure_id, closure_sha256, document
        )
    except RoleExecutionInfrastructureError:
        raise
    except RepositoryConflictError:
        raise
    except Exception as error:
        raise RoleExecutionInfrastructureError(
            f"Harness bookkeeping for correction closure "
            f"{c_closure_id} failed: "
            f"{type(error).__name__}: {error}"
        ) from error
    return c_closure_id

def preview_normalize(
    *,
    repository: HubRepository,
    specification: SpecificationPackage,
    artifacts: ArtifactStore,
    schemas: SchemaCatalog,
    run_id: str,
    role_closure_id: str,
    transformation_codes: Iterable[str],
) -> dict[str, Any]:
    """Dry-run normalization against one sealed role closure (read-only).

    Materializes the sealed bytes digest-verified into a temporary root,
    validates the ORIGINAL bytes (the current failing findings), applies
    the allowlisted transformations to parsed copies in a second
    temporary root, and validates the transformed tree.  Writes nothing:
    no artifacts, no attempt rows, no state transitions.  Returns a plain
    dict with the current findings, the remaining findings, the
    per-output transformation records, the findings the transformations
    would fix (matched on ``(code, json_pointer)``), and whether the
    transformed tree would pass.
    """
    codes = _check_normalize_allowlist(transformation_codes)
    recipe = _recipe_for_run(repository, run_id)
    plan = _plan_from_recipe(
        specification,
        recipe,
        repository=repository,
        artifacts=artifacts,
        project_id=str(recipe.document["project_id"]),
    )
    output_plan = build_output_plan(plan)

    payload = _closure_payload(repository, role_closure_id)
    stage_id = str(payload.get("stage_id", ""))
    role = str(payload.get("role", ""))
    stage = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(
            f"Closure stage {stage_id!r} is not part of the frozen phase plan."
        )
    specs = {
        spec.contract_output_id: spec
        for spec in output_plan.for_stage_role(stage.stage_id, role)
    }

    transformations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temporary:
        current_root = Path(temporary) / "current"
        candidate_root = Path(temporary) / "candidate"
        for entry in payload.get("outputs", ()):
            contract_output_id = str(entry["contract_output_id"])
            sha256 = str(entry["sha256"])
            spec = specs.get(contract_output_id)
            if spec is None:
                raise ValueError(
                    f"Closure output {contract_output_id!r} is not declared for "
                    f"stage {stage_id!r} role {role!r}."
                )
            sealed_bytes = artifacts.read_bytes(sha256)
            if hashlib.sha256(sealed_bytes).hexdigest() != sha256:
                raise ValueError(
                    f"Sealed output {contract_output_id!r} does not match its "
                    "recorded SHA-256 digest."
                )
            current_target = current_root.joinpath(*spec.relative_path.split("/"))
            current_target.parent.mkdir(parents=True, exist_ok=True)
            current_target.write_bytes(sealed_bytes)
            candidate_target = candidate_root.joinpath(
                *spec.relative_path.split("/")
            )
            candidate_target.parent.mkdir(parents=True, exist_ok=True)
            document = json.loads(sealed_bytes.decode("utf-8"))
            snapshot = copy.deepcopy(document)
            renames: dict[str, str] = {}
            changed = apply_normalize_transformations(
                document,
                spec=spec,
                codes=codes,
                ts=isoformat_utc(utc_now()),
                path=candidate_target,
                renames=renames,
                schemas_dir=schemas.directory,
            )
            if changed:
                result_bytes = json.dumps(
                    document, indent=2, ensure_ascii=False
                ).encode("utf-8")
                candidate_target.write_bytes(result_bytes)
                result_sha256 = hashlib.sha256(result_bytes).hexdigest()
            else:
                candidate_target.write_bytes(sealed_bytes)
                result_sha256 = sha256
            entries = _classify_transformations(snapshot, document, renames=renames)
            transformations.append(
                OutputTransformationRecord(
                    contract_output_id=contract_output_id,
                    source_sha256=sha256,
                    result_sha256=result_sha256,
                    entries=tuple(entries),
                    primary_artifact_unchanged=_primary_artifact_unchanged(entries),
                ).to_dict()
            )
        current = validate_role_outputs(
            schema_catalog=schemas,
            run_root=current_root,
            output_plan=output_plan,
            stage=stage,
            role=role,
            method_bound=_plan_method_bound(plan),
        )
        remaining = validate_role_outputs(
            schema_catalog=schemas,
            run_root=candidate_root,
            output_plan=output_plan,
            stage=stage,
            role=role,
            method_bound=_plan_method_bound(plan),
        )

    remaining_keys = {
        (finding.code, finding.json_pointer) for finding in remaining.findings
    }
    fixed = [
        finding
        for finding in current.findings
        if (finding.code, finding.json_pointer) not in remaining_keys
    ]
    return {
        "current_findings": [finding.to_dict() for finding in current.findings],
        "remaining_findings": [finding.to_dict() for finding in remaining.findings],
        "transformations": transformations,
        "fixed_findings": [finding.to_dict() for finding in fixed],
        "passing": not any(
            finding.blocks_publication for finding in remaining.findings
        ),
    }

def _changed_paths(old: Any, new: Any, ptr: str = "") -> set[str]:
    """Return the JSON-pointer paths whose values differ between two trees."""
    if old == new:
        return set()
    if type(old) is dict and type(new) is dict:
        paths: set[str] = set()
        for key in sorted(set(old) | set(new)):
            child = f"{ptr}/{key}"
            if key not in old or key not in new:
                paths.add(child)
            else:
                paths |= _changed_paths(old[key], new[key], child)
        return paths
    if type(old) is list and type(new) is list:
        paths = set()
        for index in range(max(len(old), len(new))):
            child = f"{ptr}/{index}"
            if index >= len(old) or index >= len(new):
                paths.add(child)
            else:
                paths |= _changed_paths(old[index], new[index], child)
        return paths
    return {ptr}


def verify_correction_blast_radius(
    *,
    source_outputs: dict[str, Any],
    corrected_outputs: dict[str, Any],
    correction_type: str,
    permitted_pointers: frozenset[str],
    output_scope: frozenset[str],
) -> tuple[ValidationFinding, ...]:
    """Verify a Lane B correction stayed inside its authorized blast radius.

    Design 4a.  ``source_outputs`` and ``corrected_outputs`` map contract
    output ids to the PARSED source and corrected candidate documents.
    Out-of-scope outputs must be identical under both correction types.
    PACKAGING in-scope outputs may change only at or below the permitted
    JSON pointers; SCIENTIFIC in-scope outputs may change freely.
    Returns the violation findings (empty tuple = clean).
    """
    violations: list[ValidationFinding] = []
    for output_id in sorted(set(source_outputs) | set(corrected_outputs)):
        source = source_outputs.get(output_id)
        corrected = corrected_outputs.get(output_id)
        if source == corrected:
            continue
        if output_id not in output_scope:
            violations.append(
                make_finding(
                    "correction.blast_radius_violated",
                    f"The {correction_type} correction changed out-of-scope "
                    f"output {output_id!r}.",
                    object_id=output_id,
                )
            )
            continue
        if correction_type != "packaging":
            continue
        if source is None:
            # K5-3: the source closure sealed no bytes for this output
            # (validation failed before sealing), so there is nothing to
            # edit in place — creating it wholesale IS the correction.
            # The output is scope-gated above and the corrected document is
            # fully validated afterwards; pointer-level blast control is
            # vacuous against an absent source.
            continue
        for path in sorted(_changed_paths(source, corrected)):
            if any(
                path == pointer or path.startswith(pointer + "/")
                for pointer in permitted_pointers
            ):
                continue
            violations.append(
                make_finding(
                    "correction.blast_radius_violated",
                    f"The packaging correction changed {output_id!r} at "
                    f"{path or '/'} outside the permitted change locations.",
                    object_id=output_id,
                    pointer=path,
                )
            )
    return tuple(violations)


def incomplete_correction_chain(
    *, services: HarnessExecutionServices
) -> tuple[str, ...]:
    """Stage-role labels lacking a SUCCEEDED closure (K5-4, ADR-016).

    Mirrors ``seal_correction_submission``'s family-aware walk.  An empty
    result means the complete-chain submission path is legal; a non-empty
    result means the correction pass must take the resume-execution edge
    because the run's pipeline did not complete.
    """
    gaps: list[str] = []
    for stage in services.context.plan.stages:
        for step in stage.role_steps:
            closure = services.roles.load_existing(stage=stage, role=step.role)
            if closure is None or closure.status is not RoleExecutionStatus.SUCCEEDED:
                gaps.append(f"{stage.stage_id}/{step.role}")
    return tuple(gaps)


def seal_correction_submission(
    *,
    services: HarnessExecutionServices,
    correction_command_id: str,
    correction_type: str,
) -> str:
    """Seal the corrected submission for a run in CORRECTING (K-1a5 Lane A).

    Every stage role must already hold a SUCCEEDED closure through the
    family-aware ``RoleLifecycleService.load_existing`` (base closures plus
    any correction-family closures); a gap raises ``SubmissionAssemblyError``
    before a single write happens.  The assembler then re-enters the
    submission gate: a run with no base submission seals one (FAILED-run
    re-entry), while a run with a base submission appends a
    ``run_submission_attempts`` row and CASes correcting -> submitted
    (REJECTED-run re-entry).

    The caller builds ``services`` with a context whose
    ``submission_from_status`` is ``"correcting"`` and whose correction
    fields are set; this function stays harness-pure and synchronous.
    Returns the sealed submission id.
    """
    if services.context.submission_from_status != "correcting":
        raise ValueError(
            "seal_correction_submission requires a correcting execution context."
        )
    outcomes: list[StageOutcome] = []
    for stage in services.context.plan.stages:
        closure_ids: list[StableId] = []
        for step in stage.role_steps:
            closure = services.roles.load_existing(stage=stage, role=step.role)
            if (
                closure is None
                or closure.status is not RoleExecutionStatus.SUCCEEDED
            ):
                raise SubmissionAssemblyError(
                    f"Role {step.role!r} in {stage.stage_id!r} lacks a "
                    "successful closure."
                )
            assert closure.closure_id is not None
            closure_ids.append(StableId(closure.closure_id))
        outcomes.append(
            StageOutcome(
                sequence=stage.sequence,
                stage_id=StableId(stage.stage_id),
                status=StageStatus.SUCCEEDED,
                invocation_closure_ids=tuple(closure_ids),
                reconciled=True,
            )
        )
    result = services.submissions.submit_or_reconcile(
        stage_outcomes=tuple(outcomes)
    )
    if result.status is not SubmissionStatus.SUBMITTED or result.reference is None:
        raise SubmissionAssemblyError(
            f"Correction submission did not seal: {result.status.value}."
        )
    return str(result.reference.submission_id)


@dataclass(frozen=True, slots=True)
class TargetedCorrectionOutcome:
    """Result of one Lane B targeted correction re-invocation (K-1c)."""

    closure_id: str
    passed: bool
    findings: tuple[ValidationFinding, ...]


async def execute_targeted_correction(
    *,
    services: HarnessExecutionServices,
    repository: HubRepository,
    specification: SpecificationPackage,
    artifacts: ArtifactStore,
    run_id: str,
    role_closure_id: str,
    correction_command_id: str,
    correction_type: str,
    permitted_output_scope: tuple[str, ...],
    user_instruction: str | None,
) -> TargetedCorrectionOutcome:
    """Drive one Lane B correction re-invocation of a failed role closure.

    Loads the source closure, re-derives the frozen stage from the run's
    recipe, builds the correction instruction (with the derived permitted
    JSON pointers for packaging corrections), materializes the source
    closure's sealed output bytes digest-verified, and hands off to
    ``RoleLifecycleService.execute_correction`` under the correction
    identity.  The correction runs synchronously (Lane A precedent); the
    returned outcome reports the sealed correction closure's status and
    findings.
    """
    recipe = _recipe_for_run(repository, run_id)
    plan = _plan_from_recipe(
        specification,
        recipe,
        repository=repository,
        artifacts=artifacts,
        project_id=str(recipe.document["project_id"]),
    )
    payload = _closure_payload(repository, role_closure_id)
    stage_id = str(payload.get("stage_id", ""))
    role = str(payload.get("role", ""))
    stage = next((item for item in plan.stages if item.stage_id == stage_id), None)
    if stage is None:
        raise ValueError(
            f"Closure stage {stage_id!r} is not part of the frozen phase plan."
        )
    specs = build_output_plan(plan).for_stage_role(stage.stage_id, role)

    findings = _parse_findings(payload.get("findings", ()))
    if not findings:
        latest = repository.get_latest_validation_attempt(run_id)
        if latest is not None:
            report = loads_json(
                latest["report_json"],
                source=f"validation attempt {latest['attempt_id']}",
            )
            if type(report) is dict:
                findings = _parse_findings(report.get("findings", ()))

    # DEVIATION A: packaging corrections may touch the non-empty finding
    # json_pointers plus every harness-owned field of each corrected output
    # spec; the root pointer "" itself is never permitted.
    permitted_pointers: set[str] = set()
    if correction_type == "packaging":
        permitted_pointers.update(
            item.json_pointer for item in findings if item.json_pointer
        )
        for spec in specs:
            permitted_pointers.update(
                f"/{field}" for field in harness_owned_fields(spec.schema_file)
            )
        permitted_pointers.discard("")

    instruction = build_correction_instruction(
        correction_type=correction_type,  # type: ignore[arg-type]
        findings=findings,
        output_scope=permitted_output_scope,
        user_instruction=user_instruction,
        permitted_pointers=tuple(sorted(permitted_pointers)),
    )

    source_output_bytes: dict[str, bytes] = {}
    for entry in payload.get("outputs", ()):
        contract_output_id = str(entry["contract_output_id"])
        sha256 = str(entry["sha256"])
        data = artifacts.read_bytes(sha256)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError(
                f"Sealed output {contract_output_id!r} does not match its "
                "recorded SHA-256 digest."
            )
        source_output_bytes[contract_output_id] = data

    # DEVIATION C: the role step's frozen inputs come from the stage basis.
    basis = services._basis_before(stage)
    step = stage.step_for(role)
    inputs = {input_id: basis[input_id] for input_id in step.input_ids}

    outcome = await services.roles.execute_correction(
        stage=stage,
        role=role,
        inputs=inputs,
        correction_instruction=instruction,
        source_output_bytes=source_output_bytes,
        permitted_pointers=frozenset(permitted_pointers),
        output_scope=frozenset(permitted_output_scope),
        source_closure_id=role_closure_id,
    )
    if outcome.closure_id is None:
        raise ValueError("The correction re-invocation did not seal a closure.")
    closure_payload = _closure_payload(repository, outcome.closure_id)
    return TargetedCorrectionOutcome(
        closure_id=str(outcome.closure_id),
        passed=outcome.status.value == "succeeded",
        findings=_parse_findings(closure_payload.get("findings", ())),
    )


__all__ = [
    "NormalizeExecution",
    "TargetedCorrectionOutcome",
    "execute_targeted_correction",
    "incomplete_correction_chain",
    "normalize_closure_outputs",
    "preview_normalize",
    "record_normalize_closure",
    "record_revalidation_closure",
    "revalidate_closure_outputs",
    "seal_correction_submission",
    "verify_correction_blast_radius",
]
