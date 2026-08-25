"""Deterministic operational manifest preparation for the first vertical slice.

The architecture package still tracks the richer normative RunManifest schema
as a hardening milestone. This module freezes every choice needed by the simple
sequential runtime now, including the engine-neutral orchestration binding.
Production Hermes execution remains disabled until the normative manifest and
the trusted local execution boundary (ADR-012) are complete.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..contracts.runtime import RuntimePhaseContract
from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, thaw_json, utc_now
from ..orchestration import OrchestrationBinding
from .inputs import InputResolutionResult
from .outputs import OutputPlan


@dataclass(frozen=True, slots=True)
class PreparedRunRecipe:
    document: Mapping[str, Any]
    sha256: str

    @classmethod
    def load(
        cls,
        document: Mapping[str, Any],
        expected_sha256: str,
    ) -> "PreparedRunRecipe":
        if not isinstance(document, Mapping):
            raise ValueError("Prepared run recipe must be a JSON object.")
        normalized = thaw_json(document)
        digest = hashlib.sha256(canonicalize(normalized)).hexdigest()
        if digest != expected_sha256:
            raise ValueError("Prepared run recipe digest does not match its manifest.")
        if normalized.get("format") != "model-forge.prepared-run-recipe":
            raise ValueError("Prepared run recipe format is not supported.")
        if normalized.get("format_version") != "1.0.0":
            raise ValueError("Prepared run recipe version is not supported.")
        return cls(document=normalized, sha256=digest)


def build_prepared_run_recipe(
    *,
    run_id: str,
    command: Mapping[str, Any],
    contract: RuntimePhaseContract,
    inputs: InputResolutionResult,
    output_plan: OutputPlan,
    profiles: Mapping[str, str],
    binding: OrchestrationBinding,
    publication_basis: Mapping[str, Any] | None = None,
    role_resources: Mapping[str, Mapping[str, Any]] | None = None,
    prepared_at: datetime | None = None,
) -> PreparedRunRecipe:
    """Freeze the contract-derived operational basis of one accepted run."""

    if not inputs.passed:
        raise ValueError("A run with unresolved required inputs cannot be prepared.")
    plan = contract.plan
    stages = []
    for stage in plan.stages:
        roles = []
        for step in stage.role_steps:
            if step.role not in profiles:
                raise ValueError(f"No profile is configured for role {step.role!r}.")
            roles.append(
                {
                    "role": step.role,
                    "profile": profiles[step.role],
                    "input_ids": list(step.input_ids),
                    "output_ids": list(step.output_ids),
                    "role_write_root": f"roles/{stage.sequence:02d}-{step.role}",
                }
            )
        stages.append(
            {
                "sequence": stage.sequence,
                "stage_id": stage.stage_id,
                "execution": stage.execution,
                "objective": stage.objective,
                "handoff_required": stage.handoff_required,
                "isolation_rule": stage.isolation_rule,
                "roles": roles,
            }
        )
    frozen_inputs = [
        {
            "contract_input_id": item.contract_input_id,
            "record_id": item.record.record_id,
            "generation_id": item.record.generation_id,
            "generation_number": item.record.generation_number,
            "record_type": item.record.record_type,
            "logical_slot": item.record.logical_slot,
            "method_identity": (
                item.record.method_identity.to_dict()
                if item.record.method_identity is not None
                else None
            ),
            "artifact": item.record.artifact.to_dict(),
            "purpose": item.purpose,
            "selected_by": item.selected_by,
        }
        for item in inputs.inputs
    ]
    expected_outputs = [
        {
            "contract_output_id": spec.contract_output_id,
            "output_id": spec.output_id,
            "output_kind": spec.output_kind,
            "producer": spec.producer,
            "stage_id": spec.stage_id,
            "stage_sequence": spec.stage_sequence,
            "schema_application": spec.schema_application,
            "schema_file": spec.schema_file,
            "relative_path": spec.relative_path,
            "required": spec.required,
            "record_type": spec.record_type,
        }
        for spec in output_plan.specs
    ]
    identity = plan.identity
    document: dict[str, Any] = {
        "format": "model-forge.prepared-run-recipe",
        "format_version": "1.0.0",
        "conformance_state": "vertical_slice",
        "run_id": run_id,
        "project_id": str(command["project_id"]),
        "command_id": str(command["command_id"]),
        "command_sha256": str(command["content_sha256"]),
        "command_idempotency_key": str(command["idempotency_key"]),
        "phase": identity.phase_id,
        "phase_contract_version": str(identity.contract_version),
        "phase_contract_sha256": str(identity.phase_contract_sha256),
        "mode": plan.mode_id,
        "user_request": {
            "choice_values": thaw_json(plan.choice_values),
            "context_policy": plan.context_policy,
            "selected_current_input_ids": list(command.get("selected_current_input_ids", ())),
            "resource_constraints": dict(command["resource_constraints"]),
        },
        "frozen_inputs": frozen_inputs,
        "selected_history": [item.to_dict() for item in inputs.selected_history],
        "prepared_contexts": [thaw_json(item) for item in plan.prepared_contexts],
        "stages": stages,
        "expected_outputs": expected_outputs,
        "validation_rules": [thaw_json(item) for item in plan.validation_rules],
        "publication_bindings": [thaw_json(item) for item in plan.publication_bindings],
        "promotion": thaw_json(plan.promotion),
        "orchestration_binding": _binding_document(binding),
        "prepared_at": isoformat_utc(prepared_at or utc_now()),
    }
    if publication_basis is not None:
        document["publication_basis"] = thaw_json(publication_basis)
    if role_resources is not None:
        document["role_resources"] = {
            role: thaw_json(resource) for role, resource in role_resources.items()
        }
    digest = hashlib.sha256(canonicalize(document)).hexdigest()
    return PreparedRunRecipe(document=document, sha256=digest)


def _binding_document(binding: OrchestrationBinding) -> dict[str, Any]:
    return binding.to_dict()


__all__ = ["PreparedRunRecipe", "build_prepared_run_recipe"]
