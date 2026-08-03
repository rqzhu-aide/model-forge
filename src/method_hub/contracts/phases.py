"""Exact executable phase-contract loading and mode resolution."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..digests import DigestContractRegistry
from ..domain import (
    ArtifactPointer,
    MethodIdentity,
    PhaseContractIdentity,
    SemanticVersion,
    Sha256Digest,
)
from ..errors import MethodHubError
from ..json_io import load_json
from ..schemas import SchemaCatalog


_PHASE_IDS = ("P1", "P2", "P3", "P4", "P5")
_CONTEXT_POLICIES = frozenset(
    {"current_only", "current_plus_selected_history"}
)
_CHOICE_KINDS = frozenset(
    {"text", "enum_string", "method_identity", "artifact_pointer_list"}
)


class PhaseContractError(MethodHubError, ValueError):
    """An executable phase contract cannot be loaded or resolved exactly."""


def _fail(code: str, message: str) -> PhaseContractError:
    return PhaseContractError(code, message)


def _freeze_json(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _freeze_json(child) for key, child in value.items()}
        )
    if type(value) is list:
        return tuple(_freeze_json(child) for child in value)
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail("phase_contract.invalid_type", f"{label} must be a JSON object.")
    if not all(type(key) is str for key in value):
        raise _fail(
            "phase_contract.invalid_key_type",
            f"{label} must contain only string keys.",
        )
    return value


def _index_unique(
    items: Any,
    id_field: str,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    if type(items) is not list:
        raise _fail("phase_contract.invalid_type", f"{label} must be an array.")
    result: dict[str, Mapping[str, Any]] = {}
    for offset, raw in enumerate(items):
        item = _require_mapping(raw, f"{label}[{offset}]")
        item_id = item.get(id_field)
        if type(item_id) is not str:
            raise _fail(
                "phase_contract.invalid_id",
                f"{label}[{offset}].{id_field} must be a string.",
            )
        if item_id in result:
            raise _fail(
                "phase_contract.duplicate_id",
                f"{label} repeats {id_field} {item_id!r}.",
            )
        result[item_id] = item
    return result


@dataclass(frozen=True, slots=True)
class ResolvedRoleStep:
    """One role's exact read and output obligations in a selected stage."""

    role: str
    input_ids: tuple[str, ...]
    output_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedStage:
    """One selected serial or parallel stage with explicit role-level I/O."""

    sequence: int
    stage_id: str
    execution: str
    objective: str
    role_steps: tuple[ResolvedRoleStep, ...]
    writes: tuple[str, ...]
    handoff_required: bool
    isolation_rule: str | None

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(step.role for step in self.role_steps)

    def step_for(self, role: str) -> ResolvedRoleStep:
        matches = tuple(step for step in self.role_steps if step.role == role)
        if len(matches) != 1:
            raise _fail(
                "phase_contract.role_not_in_stage",
                f"Stage {self.stage_id!r} does not contain role {role!r} exactly once.",
            )
        return matches[0]


@dataclass(frozen=True, slots=True)
class ResolvedPhasePlan:
    """Immutable executable plan for one exact contract mode and user choice set."""

    identity: PhaseContractIdentity
    mode_id: str
    choice_values: Mapping[str, Any]
    context_policy: str
    stages: tuple[ResolvedStage, ...]
    output_contracts: tuple[Mapping[str, Any], ...]
    prepared_contexts: tuple[Mapping[str, Any], ...]
    validation_rules: tuple[Mapping[str, Any], ...]
    publication_bindings: tuple[Mapping[str, Any], ...]
    promotion: Mapping[str, Any]

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.stages)


@dataclass(frozen=True, slots=True)
class _LoadedPhaseContract:
    identity: PhaseContractIdentity
    document: Mapping[str, Any]


class PhaseContractRepository:
    """Validated index of the five split executable phase contracts."""

    def __init__(
        self,
        *,
        architecture_root: Path,
        contracts: Sequence[_LoadedPhaseContract],
    ) -> None:
        self.architecture_root = architecture_root
        self._contracts = {item.identity.phase_id: item for item in contracts}
        modes: dict[str, str] = {}
        for loaded in contracts:
            for mode in loaded.document["run_modes"]:
                mode_id = mode["mode_id"]
                if mode_id in modes:
                    raise _fail(
                        "phase_contract.duplicate_mode_id",
                        f"Mode {mode_id!r} appears in both {modes[mode_id]} and "
                        f"{loaded.identity.phase_id}.",
                    )
                modes[mode_id] = loaded.identity.phase_id
        self._modes = MappingProxyType(modes)

    @classmethod
    def load(
        cls,
        architecture_root: str | Path,
        schemas: SchemaCatalog,
        digests: DigestContractRegistry,
    ) -> "PhaseContractRepository":
        root = Path(architecture_root).resolve()
        contract_root = root / "contracts"
        split_root = contract_root / "phases"
        expected_names = {f"{phase_id}.json" for phase_id in _PHASE_IDS}
        try:
            actual_names = {
                path.name for path in split_root.iterdir() if path.suffix == ".json"
            }
        except OSError as error:
            raise _fail(
                "phase_contract.split_directory_unreadable",
                f"Cannot read split contract directory {split_root}: {error}.",
            ) from error
        if actual_names != expected_names:
            raise _fail(
                "phase_contract.split_inventory_mismatch",
                f"Split contracts must be exactly {sorted(expected_names)}; found "
                f"{sorted(actual_names)}.",
            )

        aggregate_path = contract_root / "phases.json"
        aggregate = load_json(aggregate_path)
        if type(aggregate) is not dict:
            raise _fail(
                "phase_contract.aggregate_invalid",
                "The phase registry must be a JSON object.",
            )
        aggregate_by_phase = _index_unique(
            aggregate.get("contracts"), "phase_id", "phase registry contracts"
        )
        if set(aggregate_by_phase) != set(_PHASE_IDS):
            raise _fail(
                "phase_contract.aggregate_inventory_mismatch",
                f"Phase registry must contain exactly {_PHASE_IDS}; found "
                f"{tuple(sorted(aggregate_by_phase))}.",
            )
        schemas.require_valid("phase-contract.schema.json", aggregate)

        loaded: list[_LoadedPhaseContract] = []
        for phase_id in _PHASE_IDS:
            split_path = split_root / f"{phase_id}.json"
            document = load_json(split_path)
            if type(document) is not dict:
                raise _fail(
                    "phase_contract.split_invalid",
                    f"{split_path.name} must contain a JSON object.",
                )
            if document.get("phase_id") != phase_id:
                raise _fail(
                    "phase_contract.filename_identity_mismatch",
                    f"{split_path.name} declares phase {document.get('phase_id')!r}.",
                )
            if document != aggregate_by_phase[phase_id]:
                raise _fail(
                    "phase_contract.split_aggregate_mismatch",
                    f"{split_path.name} differs from its phases.json member.",
                )
            cls._validate_contract_semantics(document)
            digest = digests.compute("phase_contract.content", document)
            identity = PhaseContractIdentity(
                phase_id=phase_id,
                contract_version=SemanticVersion(document["contract_version"]),
                phase_contract_sha256=Sha256Digest(digest),
            )
            loaded.append(
                _LoadedPhaseContract(identity=identity, document=_freeze_json(document))
            )
        return cls(architecture_root=root, contracts=loaded)

    @staticmethod
    def _validate_contract_semantics(contract: Mapping[str, Any]) -> None:
        phase_id = contract["phase_id"]
        choices = _index_unique(contract["user_choices"], "choice_id", f"{phase_id} choices")
        modes = _index_unique(contract["run_modes"], "mode_id", f"{phase_id} modes")
        inputs = _index_unique(
            contract["required_inputs"], "input_id", f"{phase_id} inputs"
        )
        contexts = _index_unique(
            contract["prepared_contexts"], "context_id", f"{phase_id} contexts"
        )
        stages = _index_unique(
            contract["role_stages"], "stage_id", f"{phase_id} stages"
        )
        outputs = _index_unique(
            contract["run_local_outputs"], "output_id", f"{phase_id} outputs"
        )
        validators = _index_unique(
            contract["validation_rules"], "validator_id", f"{phase_id} validators"
        )
        bindings = _index_unique(
            contract["publication_bindings"],
            "binding_id",
            f"{phase_id} publication bindings",
        )
        mode_ids = set(modes)
        choice_ids = set(choices)
        input_ids = set(inputs)
        context_ids = set(contexts)
        output_ids = set(outputs)

        PhaseContractRepository._validate_choice_and_input_scopes(
            contract,
            choices=choices,
            modes=modes,
            inputs=inputs,
        )

        for choice_id, choice in choices.items():
            if choice["value_kind"] not in _CHOICE_KINDS:
                raise _fail(
                    "phase_contract.unknown_choice_kind",
                    f"Choice {choice_id!r} uses unknown kind {choice['value_kind']!r}.",
                )
        for mode_id, mode in modes.items():
            required = tuple(mode["required_choice_ids"])
            optional = tuple(mode["optional_choice_ids"])
            if len(required) != len(set(required)) or len(optional) != len(set(optional)):
                raise _fail(
                    "phase_contract.duplicate_choice_reference",
                    f"Mode {mode_id!r} repeats a choice reference.",
                )
            if set(required) & set(optional):
                raise _fail(
                    "phase_contract.ambiguous_choice_scope",
                    f"Mode {mode_id!r} declares a choice as both required and optional.",
                )
            unknown = (set(required) | set(optional)) - choice_ids
            if unknown:
                raise _fail(
                    "phase_contract.unknown_choice_reference",
                    f"Mode {mode_id!r} references unknown choices {sorted(unknown)}.",
                )
            method_choice = mode.get("method_choice_id")
            if method_choice is not None and (
                method_choice not in required
                or choices[method_choice]["value_kind"] != "method_identity"
            ):
                raise _fail(
                    "phase_contract.invalid_method_choice",
                    f"Mode {mode_id!r} has an invalid method_choice_id.",
                )

        for context_id, context in contexts.items():
            unknown_modes = set(context["applicable_modes"]) - mode_ids
            unknown_inputs = set(context["source_input_ids"]) - input_ids
            unknown_choices = set(context["source_choice_ids"]) - choice_ids
            if unknown_modes or unknown_inputs or unknown_choices:
                raise _fail(
                    "phase_contract.invalid_prepared_context_reference",
                    f"Prepared context {context_id!r} has unresolved references.",
                )

        for output_id, output in outputs.items():
            if output["requirement"] == "required_in_modes":
                required_modes = set(output.get("required_in_modes", ()))
                if not required_modes or not required_modes.issubset(mode_ids):
                    raise _fail(
                        "phase_contract.invalid_output_mode_scope",
                        f"Output {output_id!r} has invalid required modes.",
                    )

        for stage_id, stage in stages.items():
            if not set(stage["applicable_modes"]).issubset(mode_ids):
                raise _fail(
                    "phase_contract.unknown_stage_mode",
                    f"Stage {stage_id!r} names an unknown mode.",
                )
            roles = tuple(stage["roles"])
            if len(roles) != len(set(roles)):
                raise _fail(
                    "phase_contract.duplicate_stage_role",
                    f"Stage {stage_id!r} repeats a role.",
                )
            if "role_reads" in stage:
                if stage["reads"]:
                    raise _fail(
                        "phase_contract.mixed_stage_reads",
                        f"Stage {stage_id!r} cannot mix shared reads with role-specific reads.",
                    )
                role_reads = _index_unique(
                    stage["role_reads"], "role", f"{stage_id} role reads"
                )
                if set(role_reads) != set(roles):
                    raise _fail(
                        "phase_contract.incomplete_role_reads",
                        f"Stage {stage_id!r} must declare reads for every role exactly once.",
                    )
            unknown_outputs = set(stage["writes"]) - output_ids
            if unknown_outputs:
                raise _fail(
                    "phase_contract.unknown_stage_output",
                    f"Stage {stage_id!r} writes unknown outputs {sorted(unknown_outputs)}.",
                )
            for output_id in stage["writes"]:
                if outputs[output_id]["producer"] not in roles:
                    raise _fail(
                        "phase_contract.output_producer_not_in_stage",
                        f"Output {output_id!r} has no producing role in stage {stage_id!r}.",
                    )

        PhaseContractRepository._validate_publication_graph(
            contract,
            modes=modes,
            inputs=inputs,
            outputs=outputs,
            bindings=bindings,
        )
        PhaseContractRepository._validate_promotion_rules(
            contract,
            validators=validators,
        )

        for mode_id in modes:
            PhaseContractRepository._validate_selected_graph(
                contract,
                mode_id,
                inputs=inputs,
                contexts=contexts,
                outputs=outputs,
            )

    @staticmethod
    def _validate_choice_and_input_scopes(
        contract: Mapping[str, Any],
        *,
        choices: Mapping[str, Mapping[str, Any]],
        modes: Mapping[str, Mapping[str, Any]],
        inputs: Mapping[str, Mapping[str, Any]],
    ) -> None:
        phase_id = contract["phase_id"]
        mode_ids = set(modes)
        history_id = contract["optional_context_policy"]["history_choice_id"]
        history_choice = choices.get(history_id)
        if history_choice is None or history_choice["value_kind"] != "artifact_pointer_list":
            raise _fail(
                "phase_contract.invalid_history_choice",
                f"Phase {phase_id} history_choice_id must name an artifact pointer list.",
            )
        for mode_id, mode in modes.items():
            if history_id not in mode["optional_choice_ids"]:
                raise _fail(
                    "phase_contract.invalid_history_choice",
                    f"Mode {mode_id!r} must expose {history_id!r} as an optional choice.",
                )

        for input_id, input_contract in inputs.items():
            required_modes = set(input_contract.get("required_in_modes", ()))
            if input_contract["presence"] == "required_in_modes":
                if not required_modes or not required_modes.issubset(mode_ids):
                    raise _fail(
                        "phase_contract.invalid_input_mode_scope",
                        f"Input {input_id!r} has invalid required modes "
                        f"{sorted(required_modes)}.",
                    )
            elif required_modes:
                raise _fail(
                    "phase_contract.invalid_input_mode_scope",
                    f"Input {input_id!r} declares modes without required_in_modes presence.",
                )

    @staticmethod
    def _validate_publication_graph(
        contract: Mapping[str, Any],
        *,
        modes: Mapping[str, Mapping[str, Any]],
        inputs: Mapping[str, Mapping[str, Any]],
        outputs: Mapping[str, Mapping[str, Any]],
        bindings: Mapping[str, Mapping[str, Any]],
    ) -> None:
        mode_ids = set(modes)
        input_ids = set(inputs)
        output_ids = set(outputs)
        writer_modes: dict[str, set[str]] = {}
        for stage in contract["role_stages"]:
            for output_id in stage["writes"]:
                writer_modes.setdefault(output_id, set()).update(
                    stage["applicable_modes"]
                )

        bound_canonical_types: set[str] = set()
        bound_cumulative_types: set[str] = set()
        targets_by_mode: dict[tuple[str, str, str], str] = {}
        for binding_id, binding in bindings.items():
            binding_modes = set(binding["applicable_modes"])
            if not binding_modes.issubset(mode_ids):
                raise _fail(
                    "phase_contract.unknown_binding_mode",
                    f"Binding {binding_id!r} names an unknown mode.",
                )
            unknown_outputs = set(binding["output_ids"]) - output_ids
            unknown_inputs = set(binding.get("source_input_ids", ())) - input_ids
            if unknown_outputs or unknown_inputs:
                raise _fail(
                    "phase_contract.invalid_publication_reference",
                    f"Binding {binding_id!r} has unresolved input or output references.",
                )
            for output_id in binding["output_ids"]:
                unavailable_modes = binding_modes - writer_modes.get(output_id, set())
                inapplicable_modes = {
                    mode_id
                    for mode_id in binding_modes
                    if not PhaseContractRepository._output_applies(
                        outputs[output_id], mode_id
                    )
                }
                invalid_modes = unavailable_modes | inapplicable_modes
                if invalid_modes:
                    raise _fail(
                        "phase_contract.mode_inapplicable_publication_output",
                        f"Binding {binding_id!r} publishes {output_id!r} in modes "
                        f"where it is not required and produced: {sorted(invalid_modes)}.",
                    )

            components = tuple(binding.get("components", ()))
            if components:
                component_names = tuple(
                    component["component_name"] for component in components
                )
                component_outputs = tuple(
                    component["output_id"] for component in components
                )
                if (
                    len(component_names) != len(set(component_names))
                    or len(component_outputs) != len(set(component_outputs))
                    or set(component_outputs) != set(binding["output_ids"])
                ):
                    raise _fail(
                        "phase_contract.invalid_bundle_components",
                        f"Bundle {binding_id!r} components must name every and only "
                        "bound output exactly once.",
                    )

            target = binding["target"]
            target_kind = target["kind"]
            if target_kind == "current_slot":
                target_id = target["slot_id"]
                bound_canonical_types.add(target["record_type"])
            elif target_kind == "keyed_current_slots":
                target_id = target["collection_id"]
                bound_canonical_types.add(target["record_type"])
            else:
                target_id = target["collection_id"]
                bound_cumulative_types.add(target["object_type"])
            for mode_id in binding_modes:
                target_key = (mode_id, target_kind, target_id)
                previous = targets_by_mode.get(target_key)
                if previous is not None:
                    raise _fail(
                        "phase_contract.duplicate_publication_target",
                        f"Bindings {previous!r} and {binding_id!r} both resolve target "
                        f"{target_id!r} in mode {mode_id!r}.",
                    )
                targets_by_mode[target_key] = binding_id

        promotion = contract["promotion"]
        promoted_canonical_types = set(promotion["canonical_record_types"])
        promoted_cumulative_types = set(promotion["cumulative_object_types"])
        if (
            bound_canonical_types != promoted_canonical_types
            or bound_cumulative_types != promoted_cumulative_types
        ):
            raise _fail(
                "phase_contract.publication_coverage_mismatch",
                "Publication target types do not exactly match promotion coverage: "
                f"canonical {sorted(bound_canonical_types)} versus "
                f"{sorted(promoted_canonical_types)}, cumulative "
                f"{sorted(bound_cumulative_types)} versus "
                f"{sorted(promoted_cumulative_types)}.",
            )
        overlap = promoted_canonical_types & promoted_cumulative_types
        if overlap:
            raise _fail(
                "phase_contract.ambiguous_promotion_type",
                f"Promotion types cannot be both canonical and cumulative: "
                f"{sorted(overlap)}.",
            )

    @staticmethod
    def _validate_promotion_rules(
        contract: Mapping[str, Any],
        *,
        validators: Mapping[str, Mapping[str, Any]],
    ) -> None:
        blocking_ids = set(contract["promotion"]["blocking_validator_ids"])
        unknown = blocking_ids - set(validators)
        if unknown:
            raise _fail(
                "phase_contract.unknown_blocking_validator",
                f"Promotion references unknown blocking validators {sorted(unknown)}.",
            )
        nonblocking = {
            validator_id
            for validator_id in blocking_ids
            if validators[validator_id]["severity"] != "blocking"
        }
        if nonblocking:
            raise _fail(
                "phase_contract.nonblocking_promotion_validator",
                f"Promotion validators must be blocking: {sorted(nonblocking)}.",
            )

    @staticmethod
    def _output_applies(output: Mapping[str, Any], mode_id: str) -> bool:
        requirement = output["requirement"]
        if requirement == "always":
            return True
        if requirement == "required_in_modes":
            return mode_id in output.get("required_in_modes", ())
        raise _fail(
            "phase_contract.unknown_output_requirement",
            f"Output {output['output_id']!r} uses unknown requirement {requirement!r}.",
        )

    @staticmethod
    def _stage_reads(
        stage: Mapping[str, Any], role: str
    ) -> tuple[str, ...]:
        if "role_reads" not in stage:
            return tuple(stage["reads"])
        matches = tuple(
            item for item in stage["role_reads"] if item["role"] == role
        )
        if len(matches) != 1:
            raise _fail(
                "phase_contract.incomplete_role_reads",
                f"Stage {stage['stage_id']!r} does not define one read set for {role!r}.",
            )
        return tuple(matches[0]["input_ids"])

    @staticmethod
    def _validate_selected_graph(
        contract: Mapping[str, Any],
        mode_id: str,
        *,
        inputs: Mapping[str, Mapping[str, Any]],
        contexts: Mapping[str, Mapping[str, Any]],
        outputs: Mapping[str, Mapping[str, Any]],
    ) -> None:
        stages = tuple(
            stage
            for stage in contract["role_stages"]
            if mode_id in stage["applicable_modes"]
        )
        sequences = tuple(stage["sequence"] for stage in stages)
        if sequences != tuple(range(1, len(stages) + 1)):
            raise _fail(
                "phase_contract.noncontiguous_stage_sequence",
                f"Mode {mode_id!r} stages must appear in contiguous sequence order.",
            )
        available = set(inputs)
        available.update(
            context_id
            for context_id, context in contexts.items()
            if mode_id in context["applicable_modes"]
        )
        written: set[str] = set()
        for stage in stages:
            for role in stage["roles"]:
                reads = PhaseContractRepository._stage_reads(stage, role)
                unknown = set(reads) - available
                if unknown:
                    raise _fail(
                        "phase_contract.unavailable_stage_input",
                        f"Stage {stage['stage_id']!r} role {role!r} reads unavailable "
                        f"IDs {sorted(unknown)}.",
                    )
            duplicates = set(stage["writes"]) & written
            if duplicates:
                raise _fail(
                    "phase_contract.duplicate_mode_output",
                    f"Mode {mode_id!r} writes outputs more than once: {sorted(duplicates)}.",
                )
            written.update(stage["writes"])
            available.update(stage["writes"])
        expected = {
            output_id
            for output_id, output in outputs.items()
            if PhaseContractRepository._output_applies(output, mode_id)
        }
        if written != expected:
            raise _fail(
                "phase_contract.output_coverage_mismatch",
                f"Mode {mode_id!r} writes {sorted(written)}, expected {sorted(expected)}.",
            )

    @property
    def phase_ids(self) -> tuple[str, ...]:
        return tuple(phase_id for phase_id in _PHASE_IDS if phase_id in self._contracts)

    @property
    def mode_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._modes))

    @property
    def identities(self) -> tuple[PhaseContractIdentity, ...]:
        return tuple(self._contracts[phase_id].identity for phase_id in self.phase_ids)

    def __len__(self) -> int:
        return len(self._contracts)

    def identity(self, phase_id: str) -> PhaseContractIdentity:
        try:
            return self._contracts[phase_id].identity
        except KeyError as error:
            raise _fail(
                "phase_contract.not_found", f"Unknown phase contract {phase_id!r}."
            ) from error

    def contract_document(self, phase_id: str) -> dict[str, Any]:
        try:
            frozen = self._contracts[phase_id].document
        except KeyError as error:
            raise _fail(
                "phase_contract.not_found", f"Unknown phase contract {phase_id!r}."
            ) from error

        def thaw(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {key: thaw(child) for key, child in value.items()}
            if type(value) is tuple:
                return [thaw(child) for child in value]
            return copy.deepcopy(value)

        return thaw(frozen)

    def resolve(
        self,
        identity: PhaseContractIdentity,
        mode_id: str,
        choice_values: Mapping[str, Any],
        context_policy: str,
    ) -> ResolvedPhasePlan:
        if type(identity) is not PhaseContractIdentity:
            raise _fail(
                "phase_contract.invalid_identity_type",
                "identity must be a PhaseContractIdentity.",
            )
        loaded = self._contracts.get(identity.phase_id)
        if loaded is None:
            raise _fail(
                "phase_contract.not_found",
                f"Unknown phase contract {identity.phase_id!r}.",
            )
        expected = loaded.identity
        if identity.contract_version != expected.contract_version:
            raise _fail(
                "phase_contract.version_mismatch",
                f"Phase {identity.phase_id} requires contract version "
                f"{expected.contract_version}, not {identity.contract_version}.",
            )
        if identity.phase_contract_sha256 != expected.phase_contract_sha256:
            raise _fail(
                "phase_contract.digest_mismatch",
                f"Phase {identity.phase_id} contract digest does not match the loaded "
                "contract.",
            )
        contract = loaded.document
        modes = tuple(mode for mode in contract["run_modes"] if mode["mode_id"] == mode_id)
        if len(modes) != 1:
            raise _fail(
                "phase_contract.mode_not_found",
                f"Mode {mode_id!r} does not resolve exactly once in {identity.phase_id}.",
            )
        mode = modes[0]
        normalized_choices = self._validate_choices(
            contract, mode, choice_values, context_policy
        )
        outputs_by_id = {
            output["output_id"]: output for output in contract["run_local_outputs"]
        }
        selected_outputs = tuple(
            output
            for output in contract["run_local_outputs"]
            if self._output_applies(output, mode_id)
        )
        stages: list[ResolvedStage] = []
        for stage in contract["role_stages"]:
            if mode_id not in stage["applicable_modes"]:
                continue
            role_steps = []
            for role in stage["roles"]:
                role_steps.append(
                    ResolvedRoleStep(
                        role=role,
                        input_ids=self._stage_reads(stage, role),
                        output_ids=tuple(
                            output_id
                            for output_id in stage["writes"]
                            if outputs_by_id[output_id]["producer"] == role
                        ),
                    )
                )
            stages.append(
                ResolvedStage(
                    sequence=stage["sequence"],
                    stage_id=stage["stage_id"],
                    execution=stage["execution"],
                    objective=stage["objective"],
                    role_steps=tuple(role_steps),
                    writes=tuple(stage["writes"]),
                    handoff_required=stage["handoff_required"],
                    isolation_rule=stage.get("isolation_rule"),
                )
            )
        prepared_contexts = tuple(
            _freeze_json(dict(context))
            for context in contract["prepared_contexts"]
            if mode_id in context["applicable_modes"]
        )
        bindings = tuple(
            _freeze_json(dict(binding))
            for binding in contract["publication_bindings"]
            if mode_id in binding["applicable_modes"]
        )
        selected_output_ids = {output["output_id"] for output in selected_outputs}
        for binding in bindings:
            unknown = set(binding["output_ids"]) - selected_output_ids
            if unknown:
                raise _fail(
                    "phase_contract.mode_inapplicable_publication_output",
                    f"Binding {binding['binding_id']!r} uses outputs outside mode "
                    f"{mode_id!r}: {sorted(unknown)}.",
                )
        return ResolvedPhasePlan(
            identity=expected,
            mode_id=mode_id,
            choice_values=_freeze_json(normalized_choices),
            context_policy=context_policy,
            stages=tuple(stages),
            output_contracts=tuple(
                _freeze_json(dict(output)) for output in selected_outputs
            ),
            prepared_contexts=prepared_contexts,
            validation_rules=tuple(
                _freeze_json(dict(rule)) for rule in contract["validation_rules"]
            ),
            publication_bindings=bindings,
            promotion=_freeze_json(dict(contract["promotion"])),
        )

    @staticmethod
    def _validate_choices(
        contract: Mapping[str, Any],
        mode: Mapping[str, Any],
        choice_values: Mapping[str, Any],
        context_policy: str,
    ) -> dict[str, Any]:
        supplied = _require_mapping(choice_values, "choice_values")
        definitions = {
            choice["choice_id"]: choice for choice in contract["user_choices"]
        }
        required = set(mode["required_choice_ids"])
        optional = set(mode["optional_choice_ids"])
        supplied_ids = set(supplied)
        missing = required - supplied_ids
        unknown = supplied_ids - required - optional
        if missing:
            raise _fail(
                "phase_contract.missing_choice",
                f"Mode {mode['mode_id']!r} requires choices {sorted(missing)}.",
            )
        if unknown:
            raise _fail(
                "phase_contract.unknown_choice",
                f"Mode {mode['mode_id']!r} does not permit choices {sorted(unknown)}.",
            )
        normalized: dict[str, Any] = {}
        for choice_id, value in supplied.items():
            definition = definitions[choice_id]
            kind = definition["value_kind"]
            if kind == "text":
                if type(value) is not str or not value.strip():
                    raise _fail(
                        "phase_contract.invalid_choice_value",
                        f"Choice {choice_id!r} must be nonempty text.",
                    )
                normalized[choice_id] = value
            elif kind == "enum_string":
                if type(value) is not str or value not in definition["allowed_values"]:
                    raise _fail(
                        "phase_contract.invalid_choice_value",
                        f"Choice {choice_id!r} must be one of "
                        f"{tuple(definition['allowed_values'])}.",
                    )
                normalized[choice_id] = value
            elif kind == "method_identity":
                try:
                    normalized[choice_id] = MethodIdentity.from_dict(value).to_dict()
                except MethodHubError as error:
                    raise _fail(
                        "phase_contract.invalid_choice_value",
                        f"Choice {choice_id!r} is not an exact method identity: "
                        f"{error.message}",
                    ) from error
            elif kind == "artifact_pointer_list":
                if type(value) is not list:
                    raise _fail(
                        "phase_contract.invalid_choice_value",
                        f"Choice {choice_id!r} must be an artifact pointer list.",
                    )
                pointers = []
                for offset, pointer in enumerate(value):
                    try:
                        pointers.append(ArtifactPointer.from_dict(pointer).to_dict())
                    except MethodHubError as error:
                        raise _fail(
                            "phase_contract.invalid_choice_value",
                            f"Choice {choice_id!r}[{offset}] is invalid: {error.message}",
                        ) from error
                normalized[choice_id] = pointers
            else:
                raise _fail(
                    "phase_contract.unknown_choice_kind",
                    f"Choice {choice_id!r} uses unknown kind {kind!r}.",
                )

        if context_policy not in _CONTEXT_POLICIES:
            raise _fail(
                "phase_contract.invalid_context_policy",
                f"Unknown context policy {context_policy!r}.",
            )
        policy = contract["optional_context_policy"]
        history_id = policy["history_choice_id"]
        selected_history = normalized.get(history_id, [])
        if context_policy == "current_only" and selected_history:
            raise _fail(
                "phase_contract.history_forbidden",
                "current_only cannot include selected historical artifacts.",
            )
        if context_policy == "current_plus_selected_history":
            if not policy["allows_selected_history"]:
                raise _fail(
                    "phase_contract.history_unsupported",
                    f"Phase {contract['phase_id']} does not allow selected history.",
                )
            if not selected_history:
                raise _fail(
                    "phase_contract.history_required",
                    "current_plus_selected_history requires at least one artifact pointer.",
                )
        return normalized


__all__ = [
    "PhaseContractError",
    "PhaseContractRepository",
    "ResolvedPhasePlan",
    "ResolvedRoleStep",
    "ResolvedStage",
]
