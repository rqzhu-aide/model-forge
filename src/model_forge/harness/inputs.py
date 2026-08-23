"""Exact current-record and selected-history resolution for run preparation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..contracts.runtime import RuntimePhaseContract
from ..domain.identities import ArtifactPointer, MethodIdentity
from ..domain.validation import ValidationFinding, ValidationSeverity, make_finding


@dataclass(frozen=True, slots=True)
class CurrentRecordReference:
    record_id: str
    generation_id: str
    generation_number: int
    record_type: str
    artifact: ArtifactPointer
    method_identity: MethodIdentity | None = None
    logical_slot: str | None = None
    summary: str | None = None
    highlight_artifact_id: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedRunInput:
    contract_input_id: str
    record: CurrentRecordReference
    purpose: str
    selected_by: str = "phase_contract"


@dataclass(frozen=True, slots=True)
class InputResolutionResult:
    inputs: tuple[ResolvedRunInput, ...]
    selected_history: tuple[ArtifactPointer, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(
            finding.blocks_publication for finding in self.findings
        )


class CurrentRecordLookup(Protocol):
    def current_record(
        self,
        *,
        project_id: str,
        record_type: str,
        method_identity: MethodIdentity | None,
        match_policy: str,
    ) -> CurrentRecordReference | None: ...


def _method_from_choices(contract: RuntimePhaseContract) -> MethodIdentity | None:
    document = dict(contract.plan.choice_values)
    for key, value in document.items():
        if key.endswith(".selected_method"):
            return MethodIdentity.from_dict(value)
    return None


def resolve_run_inputs(
    *,
    project_id: str,
    contract: RuntimePhaseContract,
    lookup: CurrentRecordLookup,
    selected_context_option_ids: Sequence[str] | None = None,
) -> InputResolutionResult:
    """Resolve the exact user-selected current basis without hidden history."""

    method = _method_from_choices(contract)
    selected = (
        None
        if selected_context_option_ids is None
        else frozenset(selected_context_option_ids)
    )
    declared_ids = {
        str(item["input_id"])
        for item in contract.required_inputs
        if not (
            str(item["presence"]) == "required_in_modes"
            and contract.plan.mode_id not in item.get("required_in_modes", ())
        )
    }
    if selected is not None:
        unknown = sorted(selected - declared_ids)
        if unknown:
            return InputResolutionResult(
                (),
                (),
                tuple(
                    make_finding(
                        code="input.unknown_context_selection",
                        message=(
                            f"Selected current context {input_id!r} is not declared "
                            "for this run."
                        ),
                        object_id=input_id,
                    )
                    for input_id in unknown
                ),
            )
    applicable_inputs = tuple(
        item
        for item in contract.required_inputs
        if not (
            str(item["presence"]) == "required_in_modes"
            and contract.plan.mode_id not in item.get("required_in_modes", ())
        )
    )
    current_records: dict[str, CurrentRecordReference | None] = {}
    for input_contract in applicable_inputs:
        input_id = str(input_contract["input_id"])
        match_policy = str(input_contract["method_match"])
        query_method = (
            method if match_policy in {"exact", "same_stable_method"} else None
        )
        current_records[input_id] = lookup.current_record(
            project_id=project_id,
            record_type=str(input_contract["record_type"]),
            method_identity=query_method,
            match_policy=match_policy,
        )
    rerun_active = any(
        str(item["presence"]) == "required_on_rerun"
        and current_records[str(item["input_id"])] is not None
        for item in applicable_inputs
    )

    resolved: list[ResolvedRunInput] = []
    findings: list[ValidationFinding] = []
    for input_contract in applicable_inputs:
        presence = str(input_contract["presence"])
        match_policy = str(input_contract["method_match"])
        query_method = method if match_policy in {"exact", "same_stable_method"} else None
        input_id = str(input_contract["input_id"])
        record = current_records[input_id]
        required = presence in {"always", "required_in_modes"} or (
            presence == "required_on_rerun" and rerun_active
        )
        if not required and selected is not None and input_id not in selected:
            continue
        if required and selected is not None and input_id not in selected:
            findings.append(
                make_finding(
                    code="input.required_context_not_selected",
                    message=f"Required current context {input_id!r} must remain selected.",
                    object_id=input_id,
                )
            )
            continue
        if record is None:
            if required:
                findings.append(
                    make_finding(
                        code="input.required_current_record_missing",
                        message=(
                            f"Required current {input_contract['record_type']} is unavailable "
                            f"for {input_contract['input_id']}."
                        ),
                        object_id=str(input_contract["input_id"]),
                    )
                )
            continue
        if query_method is not None and record.method_identity is None:
            findings.append(
                make_finding(
                    code="input.method_identity_missing",
                    message=(
                        f"Current {record.record_type} does not declare the method identity "
                        "required by this run."
                    ),
                    object_id=str(input_contract["input_id"]),
                )
            )
            continue
        if query_method is not None and record.method_identity is not None:
            exact = record.method_identity == query_method
            same_stable = record.method_identity.stable_id == query_method.stable_id
            if match_policy == "exact" and not exact:
                findings.append(
                    make_finding(
                        code="input.method_identity_mismatch",
                        message=f"Current {record.record_type} is not aligned to the exact selected method.",
                        object_id=str(input_contract["input_id"]),
                    )
                )
                continue
            if match_policy == "same_stable_method" and not same_stable:
                findings.append(
                    make_finding(
                        code="input.method_lineage_mismatch",
                        message=f"Current {record.record_type} belongs to another method lineage.",
                        object_id=str(input_contract["input_id"]),
                    )
                )
                continue
        resolved.append(
            ResolvedRunInput(
                contract_input_id=str(input_contract["input_id"]),
                record=record,
                purpose=str(input_contract["purpose"]),
            )
        )

    if contract.plan.identity.phase_id == "P4":
        prior_ids = {
            "p4.current_evidence_index",
            "p4.current_empirical",
            "p4.current_implementation",
        }
        present = {item.contract_input_id for item in resolved} & prior_ids
        if present and present != prior_ids:
            findings.append(
                make_finding(
                    code="input.p4_prior_package_incomplete",
                    message=(
                        "The current Phase 4 evidence index, empirical synthesis, and "
                        "implementation record must be jointly present or jointly absent."
                    ),
                    object_id="p4.prior_package",
                )
            )

    history_id = f"{contract.plan.identity.phase_id.lower()}.selected_history"
    raw_history = dict(contract.plan.choice_values).get(history_id, ())
    history = tuple(ArtifactPointer.from_dict(item) for item in raw_history)
    return InputResolutionResult(tuple(resolved), history, tuple(findings))


__all__ = [
    "CurrentRecordLookup",
    "CurrentRecordReference",
    "InputResolutionResult",
    "ResolvedRunInput",
    "resolve_run_inputs",
]
