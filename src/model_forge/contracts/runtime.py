"""Runtime-facing phase metadata omitted from the compact execution plan.

The executable phase repository remains the source of truth. This view exposes
input resolution, prerequisites, downstream effects, and UI metadata without
asking the harness or frontend to infer them from prose.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .phases import PhaseContractRepository, ResolvedPhasePlan


@dataclass(frozen=True, slots=True)
class RuntimePhaseContract:
    plan: ResolvedPhasePlan
    name: str
    scientific_purpose: str
    prerequisites: tuple[Mapping[str, Any], ...]
    required_inputs: tuple[Mapping[str, Any], ...]
    supplementary_inputs: tuple[Mapping[str, Any], ...]
    downstream_effects: tuple[Mapping[str, Any], ...]
    ui_projection: Mapping[str, Any]


def _applies_to_mode(item: Mapping[str, Any], mode_id: str) -> bool:
    modes = item.get("applicable_modes")
    return modes is None or mode_id in modes


def resolve_runtime_contract(
    repository: PhaseContractRepository,
    plan: ResolvedPhasePlan,
) -> RuntimePhaseContract:
    document = repository.contract_document(plan.identity.phase_id)
    return RuntimePhaseContract(
        plan=plan,
        name=str(document["name"]),
        scientific_purpose=str(document["scientific_purpose"]),
        prerequisites=tuple(copy.deepcopy(document["prerequisites"])),
        required_inputs=tuple(
            copy.deepcopy(item)
            for item in document["required_inputs"]
            if _applies_to_mode(item, plan.mode_id)
        ),
        supplementary_inputs=tuple(
            copy.deepcopy(item)
            for item in document.get("supplementary_inputs", ())
            if _applies_to_mode(item, plan.mode_id)
        ),
        downstream_effects=tuple(copy.deepcopy(document["downstream_effects"])),
        ui_projection=copy.deepcopy(document["ui_projection"]),
    )


__all__ = ["RuntimePhaseContract", "resolve_runtime_contract"]
