"""Contract-derived output planning and structural acceptance."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..domain.validation import (
    ValidationFinding,
    ValidationSeverity,
    make_finding,
)
from ..json_io import JsonLoadError, loads_json
from ..schemas import SchemaCatalog


_SAFE_FILENAME = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class OutputSpec:
    contract_output_id: str
    output_id: str
    output_kind: str
    producer: str
    stage_id: str
    stage_sequence: int
    schema_application: str
    schema_file: str
    relative_path: str
    required: bool


@dataclass(frozen=True, slots=True)
class OutputPlan:
    specs: tuple[OutputSpec, ...]

    def for_stage_role(self, stage_id: str, role: str) -> tuple[OutputSpec, ...]:
        return tuple(
            spec
            for spec in self.specs
            if spec.stage_id == stage_id and spec.producer == role
        )

    def by_contract_id(self) -> Mapping[str, OutputSpec]:
        return {item.contract_output_id: item for item in self.specs}


@dataclass(frozen=True, slots=True)
class ValidatedOutput:
    spec: OutputSpec
    path: Path
    document: Any
    sha256: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class OutputValidationResult:
    outputs: tuple[ValidatedOutput, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(
            finding.blocks_publication for finding in self.findings
        )


def _filename(contract_output_id: str) -> str:
    suffix = contract_output_id.split(".", 1)[-1].lower()
    safe = _SAFE_FILENAME.sub("-", suffix).strip("-")
    if not safe:
        raise ValueError(f"Output ID {contract_output_id!r} has no safe filename.")
    return safe + ".json"


def _schema_file(schema_uri: str) -> str:
    value = schema_uri.replace("\\", "/").rsplit("/", 1)[-1]
    if not value.endswith(".schema.json"):
        raise ValueError(f"Output schema URI {schema_uri!r} is not a schema filename.")
    return value


def build_output_plan(plan: ResolvedPhasePlan) -> OutputPlan:
    """Derive exact role-local JSON destinations from one resolved contract."""

    outputs = {
        str(item["output_id"]): item for item in plan.output_contracts
    }
    specs: list[OutputSpec] = []
    seen_paths: set[str] = set()
    for stage in plan.stages:
        for role_step in stage.role_steps:
            for contract_output_id in role_step.output_ids:
                contract = outputs[contract_output_id]
                relative_path = (
                    f"roles/{stage.sequence:02d}-{role_step.role}/"
                    f"{_filename(contract_output_id)}"
                )
                if relative_path in seen_paths:
                    raise ValueError(f"Output path {relative_path!r} is duplicated.")
                seen_paths.add(relative_path)
                specs.append(
                    OutputSpec(
                        contract_output_id=contract_output_id,
                        output_id=f"output.{contract_output_id}",
                        output_kind=str(contract["output_kind"]),
                        producer=role_step.role,
                        stage_id=stage.stage_id,
                        stage_sequence=stage.sequence,
                        schema_application=str(contract["schema_application"]),
                        schema_file=_schema_file(str(contract["schema_uri"])),
                        relative_path=relative_path,
                        required=bool(contract["required"]),
                    )
                )
    return OutputPlan(tuple(specs))


def _finding(
    code: str,
    message: str,
    spec: OutputSpec,
    pointer: str = "",
) -> ValidationFinding:
    return make_finding(
        code=code,
        message=message,
        object_id=spec.contract_output_id,
        pointer=pointer,
    )


def validate_role_outputs(
    *,
    schema_catalog: SchemaCatalog,
    run_root: Path,
    output_plan: OutputPlan,
    stage: ResolvedStage,
    role: str,
) -> OutputValidationResult:
    """Validate the exact declared outputs for one role closure.

    This establishes structural eligibility only. It does not judge theorem
    correctness, empirical interpretation, novelty, or scientific importance.
    """

    specs = output_plan.for_stage_role(stage.stage_id, role)
    findings: list[ValidationFinding] = []
    accepted: list[ValidatedOutput] = []
    if not specs:
        findings.append(
            make_finding(
                "output.role_has_no_contract",
                f"Role {role!r} has no declared outputs in stage {stage.stage_id!r}.",
                object_id=stage.stage_id,
            )
        )
        return OutputValidationResult((), tuple(findings))

    resolved_root = run_root.resolve()
    for spec in specs:
        path = run_root.joinpath(*spec.relative_path.split("/"))
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except FileNotFoundError:
            if spec.required:
                findings.append(
                    _finding(
                        "output.required_missing",
                        f"Required output {spec.contract_output_id!r} was not produced.",
                        spec,
                    )
                )
            continue
        except (OSError, ValueError):
            findings.append(
                _finding(
                    "output.unsafe_path",
                    f"Output {spec.contract_output_id!r} does not resolve safely inside the run.",
                    spec,
                )
            )
            continue
        if resolved.is_symlink() or not resolved.is_file():
            findings.append(
                _finding(
                    "output.not_regular_file",
                    f"Output {spec.contract_output_id!r} must be a regular JSON file.",
                    spec,
                )
            )
            continue
        try:
            payload = resolved.read_bytes()
            document = loads_json(payload, source=str(resolved))
        except JsonLoadError as error:
            findings.append(
                _finding(
                    error.code,
                    f"Output {spec.contract_output_id!r} is not strict JSON: {error.message}",
                    spec,
                )
            )
            continue
        except OSError as error:
            findings.append(
                _finding(
                    "output.unreadable",
                    f"Output {spec.contract_output_id!r} cannot be read: {error}.",
                    spec,
                )
            )
            continue

        documents: tuple[Any, ...]
        if spec.schema_application == "each_item":
            if type(document) is not list:
                findings.append(
                    _finding(
                        "output.expected_array",
                        f"Output {spec.contract_output_id!r} must be a JSON array.",
                        spec,
                    )
                )
                continue
            documents = tuple(document)
        elif spec.schema_application == "object":
            if type(document) is not dict:
                findings.append(
                    _finding(
                        "output.expected_object",
                        f"Output {spec.contract_output_id!r} must be a JSON object.",
                        spec,
                    )
                )
                continue
            documents = (document,)
        else:
            findings.append(
                _finding(
                    "output.unknown_schema_application",
                    f"Output {spec.contract_output_id!r} has unsupported schema application.",
                    spec,
                )
            )
            continue

        item_findings: list[ValidationFinding] = []
        for offset, item in enumerate(documents):
            for issue in schema_catalog.validate(spec.schema_file, item):
                prefix = f"/{offset}" if spec.schema_application == "each_item" else ""
                item_findings.append(
                    _finding(
                        issue.code,
                        issue.message,
                        spec,
                        prefix + issue.json_pointer,
                    )
                )
        if item_findings:
            findings.extend(item_findings)
            continue
        accepted.append(
            ValidatedOutput(
                spec=spec,
                path=resolved,
                document=document,
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_length=len(payload),
            )
        )
    return OutputValidationResult(tuple(accepted), tuple(findings))


__all__ = [
    "OutputPlan",
    "OutputSpec",
    "OutputValidationResult",
    "ValidatedOutput",
    "build_output_plan",
    "validate_role_outputs",
]
