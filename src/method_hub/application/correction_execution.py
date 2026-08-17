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

No run-status transitions and no submission work — those land in K-1a5.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, utc_now
from ..domain.validation import ValidationFinding, ValidationReport, registry_version
from ..harness.execution_records import (
    closure_artifact_id,
    correction_role_identity,
    document_sha256,
)
from ..harness.outputs import build_output_plan, validate_role_outputs
from ..harness.preparation import PreparedRunRecipe
from ..json_io import loads_json
from ..schemas import SchemaCatalog
from ..specification import SpecificationPackage
from ..storage.artifacts import ArtifactStore
from ..storage.repository import HubRepository
from .correction import CorrectionResult, ValidationAttempt, _derive_attempt_id


def _recipe_for_run(repository: HubRepository, run_id: str) -> PreparedRunRecipe:
    row = repository.get_manifest(run_id)
    if row is None:
        raise ValueError("Run manifest is unavailable.")
    document = loads_json(row["payload_json"], source=f"manifest {run_id}")
    if type(document) is not dict:
        raise ValueError("Run manifest must be an object.")
    return PreparedRunRecipe.load(document, str(row["manifest_sha256"]))


def _plan_from_recipe(
    specification: SpecificationPackage, recipe: PreparedRunRecipe
):
    identity = specification.phases.identity(str(recipe.document["phase"]))
    if (
        str(identity.contract_version)
        != str(recipe.document["phase_contract_version"])
        or str(identity.phase_contract_sha256)
        != str(recipe.document["phase_contract_sha256"])
    ):
        raise ValueError("Frozen phase contract is unavailable.")
    request = recipe.document["user_request"]
    return specification.resolve_phase(
        identity,
        str(recipe.document["mode"]),
        dict(request["choice_values"]),
        str(request["context_policy"]),
    )


def _closure_payload(repository: HubRepository, closure_id: str) -> dict[str, Any]:
    row = repository.get_role_closure(closure_id)
    if row is None:
        raise ValueError(f"Role closure {closure_id!r} is unavailable.")
    document = loads_json(row["payload_json"], source=f"role closure {closure_id}")
    if type(document) is not dict:
        raise ValueError("Role closure payload must be an object.")
    return document


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
    plan = _plan_from_recipe(specification, recipe)
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
    plan = _plan_from_recipe(specification, recipe)
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
    return c_closure_id


__all__ = ["record_revalidation_closure", "revalidate_closure_outputs"]
