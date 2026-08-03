"""Researcher-facing run configuration derived from executable contracts.

This module projects contract facts only. Eligibility findings are supplied by
the application service after it inspects formal current records. The browser
does not reconstruct either the stage plan or the launch decision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..contracts import PhaseContractRepository
from ..domain.identities import MethodIdentity


def _descriptor_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "action." + hashlib.sha256(encoded).hexdigest()


def _method_document(method: MethodIdentity | None) -> dict[str, Any] | None:
    return method.to_dict() if method is not None else None


def build_phase_configuration(
    *,
    repository: PhaseContractRepository,
    project_id: str,
    phase_id: str,
    selected_mode: str | None = None,
    selected_method: MethodIdentity | None = None,
    current_inputs: Sequence[Mapping[str, Any]] = (),
    history_options: Sequence[Mapping[str, Any]] = (),
    eligibility_findings: Sequence[Mapping[str, str]] = (),
    authority_head: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one complete backend-authored run form and launch action."""

    document = repository.contract_document(phase_id)
    modes = tuple(document["run_modes"])
    mode_ids = tuple(str(item["mode_id"]) for item in modes)
    mode_id = selected_mode or mode_ids[0]
    if mode_id not in mode_ids:
        raise ValueError(f"Mode {mode_id!r} is not declared by phase {phase_id}.")
    selected = next(item for item in modes if item["mode_id"] == mode_id)
    method_required = bool(selected["requires_method"])
    findings = tuple(dict(item) for item in eligibility_findings)
    if method_required and selected_method is None:
        findings = findings + (
            {
                "code": "run.method_required",
                "message": "Select one current active method before starting this run.",
            },
        )

    instructions = next(
        item
        for item in document["user_choices"]
        if str(item["choice_id"]).endswith(".instructions")
    )
    stages = [
        {
            "stage_id": str(stage["stage_id"]),
            "label": str(stage["objective"]),
            "roles": list(stage["roles"]),
            "execution": str(stage["execution"]),
        }
        for stage in document["role_stages"]
        if mode_id in stage["applicable_modes"]
    ]
    enabled = not findings
    researcher_message = (
        None
        if enabled
        else " ".join(str(item["message"]) for item in findings)
    )
    identity = repository.identity(phase_id)
    consequence = _launch_consequence(document, selected)
    descriptor_basis = {
        "project_id": project_id,
        "action_type": "start_run",
        "phase": phase_id,
        "mode": mode_id,
        "phase_contract_version": str(identity.contract_version),
        "phase_contract_sha256": str(identity.phase_contract_sha256),
        "method_identity": _method_document(selected_method),
        "enabled": enabled,
        "finding_codes": [item["code"] for item in findings],
        "reviewed_current_inputs": [
            {
                "option_id": str(item["option_id"]),
                "required": bool(item.get("required", False)),
                "artifact_id": (
                    item.get("artifact_pointer", {}).get("artifact_id")
                ),
                "sha256": item.get("artifact_pointer", {}).get("sha256"),
            }
            for item in current_inputs
        ],
        "authority_head": dict(authority_head or {}),
    }
    action: dict[str, Any] = {
        "descriptor_id": _descriptor_id(descriptor_basis),
        "action_type": "start_run",
        "execution_kind": "research_run",
        "enabled": enabled,
        "consequence_summary": consequence,
        "command_contract": {
            "phase": phase_id,
            "phase_contract_version": str(identity.contract_version),
            "phase_contract_sha256": str(identity.phase_contract_sha256),
            "mode": mode_id,
        },
    }
    if researcher_message is not None:
        action["reason_code"] = str(findings[0]["code"])
        action["researcher_message"] = researcher_message
    if selected_method is not None:
        action["method_identity"] = selected_method.to_dict()

    return {
        "modes": [
            {
                "mode_id": str(item["mode_id"]),
                "label": str(item["label"]),
                "description": str(item["purpose"]),
            }
            for item in modes
        ],
        "default_mode": mode_id,
        "instruction_label": str(instructions["label"]),
        "instruction_help": str(instructions["description"]),
        "instruction_placeholder": _instruction_placeholder(phase_id),
        "current_inputs": [dict(item) for item in current_inputs],
        "history_options": [dict(item) for item in history_options],
        "stage_plan": stages,
        "actions": [action],
    }


def _launch_consequence(
    document: Mapping[str, Any], mode: Mapping[str, Any]
) -> str:
    promotion = document["promotion"]
    current_types = ", ".join(promotion["canonical_record_types"])
    cumulative_types = ", ".join(promotion["cumulative_object_types"])
    effects: list[str] = []
    if current_types:
        effects.append(f"replace the complete current {current_types} record set")
    if cumulative_types:
        effects.append(f"append validated {cumulative_types} records")
    effect = " and ".join(effects) or "publish the declared phase records"
    return (
        f"Run {mode['label']} once using the displayed frozen basis. "
        f"If every required output validates and the basis is still current, {effect}. "
        "No later phase or rerun starts automatically."
    )


def _instruction_placeholder(phase_id: str) -> str:
    values = {
        "P1": "State the literature question, scope, exclusions, and source constraints.",
        "P2": "State the methodological question, scientific constraints, and priorities.",
        "P3": "State the theorem, proof, assumption, or theoretical question to examine.",
        "P4": "State the empirical question, data or simulation constraints, and comparisons.",
        "P5": "State the paper scope, venue, emphasis, and revision priorities.",
    }
    return values[phase_id]


__all__ = ["build_phase_configuration"]
