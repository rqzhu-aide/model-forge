"""Verify an immutable submission before any formal publication is planned."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..contracts import ResolvedPhasePlan
from ..domain.identities import MethodIdentity
from ..domain.validation import ValidationFinding, ValidationSeverity, make_finding
from ..json_io import JsonLoadError, loads_json
from ..schemas import SchemaCatalog
from ..storage import ArtifactStore
from ..storage.repository import HubRepository
from .execution_records import document_sha256
from .outputs import OutputPlan, OutputSpec
from .envelope import reclassify_harness_owned_finding
from .publication import RegisteredArtifactMetadata, RegisteredValidatedOutput
from .scientific_validators import validate_phase_scientific


@dataclass(frozen=True, slots=True)
class SubmissionValidationResult:
    submission: Mapping[str, Any]
    outputs: Mapping[str, RegisteredValidatedOutput]
    findings: tuple[ValidationFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(
            item.blocks_publication for item in self.findings
        )


def validate_submission(
    *,
    repository: HubRepository,
    artifacts: ArtifactStore,
    schemas: SchemaCatalog,
    project_id: str,
    run_id: str,
    plan: ResolvedPhasePlan,
    output_plan: OutputPlan,
    selected_method: MethodIdentity | None,
) -> SubmissionValidationResult:
    """Recheck exact bytes, provenance, schemas, and method identity."""

    findings: list[ValidationFinding] = []
    # Correction attempts supersede the base submission (HV-5 revision A1).
    row = repository.get_latest_submission_attempt(run_id)
    if row is None:
        row = repository.get_submission(run_id)
    if row is None:
        return SubmissionValidationResult(
            {},
            {},
            (
                _finding(
                    "submission.missing",
                    "The immutable run submission is unavailable.",
                    run_id,
                ),
            ),
        )
    try:
        submission = loads_json(row["payload_json"], source=f"submission {run_id}")
    except JsonLoadError as error:
        return SubmissionValidationResult(
            {}, {}, (_finding(error.code, error.message, run_id),)
        )
    if type(submission) is not dict:
        return SubmissionValidationResult(
            {},
            {},
            (_finding("submission.invalid_document", "Submission must be an object.", run_id),),
        )

    submitted_digest = submission.get("submission_sha256")
    unhashed = dict(submission)
    unhashed.pop("submission_sha256", None)
    if (
        submitted_digest != row["submission_sha256"]
        or document_sha256(unhashed) != submitted_digest
    ):
        findings.append(
            _finding(
                "submission.digest_mismatch",
                "Submission content does not match its sealed digest.",
                run_id,
            )
        )
    for issue in schemas.validate("run-submission.schema.json", submission):
        findings.append(
            _finding(issue.code, issue.message, run_id, issue.json_pointer)
        )
    if submission.get("project_id") != project_id:
        findings.append(
            _finding(
                "submission.project_mismatch",
                "Submission belongs to another project.",
                run_id,
            )
        )
    if submission.get("phase") != plan.identity.phase_id or submission.get(
        "mode"
    ) != plan.mode_id:
        findings.append(
            _finding(
                "submission.phase_mismatch",
                "Submission phase or mode differs from the frozen plan.",
                run_id,
            )
        )

    closure_basis = {
        str(item.get("invocation_closure_id")): (
            str(item.get("stage_id")),
            str(item.get("role")),
        )
        for item in submission.get("closure_chain", ())
        if type(item) is dict
    }
    specs = output_plan.by_contract_id()
    submitted_items = submission.get("submitted_artifacts", ())
    if type(submitted_items) is not list:
        submitted_items = []
    supplied_ids = [
        str(item.get("contract_output_id"))
        for item in submitted_items
        if type(item) is dict
    ]
    required_ids = {key for key, spec in specs.items() if spec.required}
    missing = sorted(required_ids - set(supplied_ids))
    unexpected = sorted(set(supplied_ids) - set(specs))
    duplicate = sorted(
        output_id for output_id in set(supplied_ids) if supplied_ids.count(output_id) > 1
    )
    for output_id in missing:
        findings.append(
            _finding(
                "submission.required_output_missing",
                f"Required output {output_id!r} is absent from the submission.",
                output_id,
            )
        )
    for output_id in unexpected:
        findings.append(
            _finding(
                "submission.unexpected_output",
                f"Undeclared output {output_id!r} is present in the submission.",
                output_id,
            )
        )
    for output_id in duplicate:
        findings.append(
            _finding(
                "submission.duplicate_output",
                f"Output {output_id!r} occurs more than once.",
                output_id,
            )
        )

    accepted: dict[str, RegisteredValidatedOutput] = {}
    for item in submitted_items:
        if type(item) is not dict:
            findings.append(
                _finding(
                    "submission.invalid_output_entry",
                    "Submitted output entries must be objects.",
                    run_id,
                )
            )
            continue
        output_id = str(item.get("contract_output_id"))
        spec = specs.get(output_id)
        if spec is None or output_id in accepted:
            continue
        result = _verify_output(
            repository=repository,
            artifacts=artifacts,
            schemas=schemas,
            project_id=project_id,
            item=item,
            spec=spec,
            closure_basis=closure_basis,
        )
        findings.extend(result[1])
        if result[0] is not None:
            accepted[output_id] = result[0]

    _validate_phase_semantics(
        plan=plan,
        outputs=accepted,
        selected_method=selected_method,
        findings=findings,
    )
    validate_phase_scientific(
        plan=plan,
        outputs=accepted,
        selected_method=selected_method,
        findings=findings,
    )
    return SubmissionValidationResult(submission, accepted, tuple(findings))


def _verify_output(
    *,
    repository: HubRepository,
    artifacts: ArtifactStore,
    schemas: SchemaCatalog,
    project_id: str,
    item: Mapping[str, Any],
    spec: OutputSpec,
    closure_basis: Mapping[str, tuple[str, str]],
) -> tuple[RegisteredValidatedOutput | None, tuple[ValidationFinding, ...]]:
    findings: list[ValidationFinding] = []
    closure_id = str(item.get("source_invocation_closure_id"))
    if closure_basis.get(closure_id) != (spec.stage_id, spec.producer):
        findings.append(
            _finding(
                "submission.output_provenance_mismatch",
                f"Output {spec.contract_output_id!r} is not bound to its declared producer.",
                spec.contract_output_id,
            )
        )
    if item.get("output_id") != spec.output_id:
        findings.append(
            _finding(
                "submission.output_identity_mismatch",
                f"Output {spec.contract_output_id!r} has the wrong output identity.",
                spec.contract_output_id,
            )
        )
    pointer = item.get("artifact")
    if type(pointer) is not dict or type(pointer.get("artifact_id")) is not str:
        return None, tuple(
            findings
            + [
                _finding(
                    "submission.artifact_pointer_missing",
                    f"Output {spec.contract_output_id!r} lacks an artifact pointer.",
                    spec.contract_output_id,
                )
            ]
        )
    artifact_id = str(pointer["artifact_id"])
    try:
        row = repository.get_artifact(artifact_id)
    except Exception as error:
        return None, tuple(
            findings
            + [
                _finding(
                    "submission.artifact_unavailable",
                    f"Artifact {artifact_id!r} is unavailable: {error}.",
                    spec.contract_output_id,
                )
            ]
        )
    if row["project_id"] != project_id or pointer.get("sha256") != row["sha256"]:
        findings.append(
            _finding(
                "submission.artifact_identity_mismatch",
                f"Artifact {artifact_id!r} does not match the submitted project and digest.",
                spec.contract_output_id,
            )
        )
    try:
        payload = artifacts.read_bytes(str(row["sha256"]))
        document = loads_json(payload, source=f"artifact {artifact_id}")
    except Exception as error:
        return None, tuple(
            findings
            + [
                _finding(
                    "submission.artifact_invalid",
                    f"Artifact {artifact_id!r} cannot be verified: {error}.",
                    spec.contract_output_id,
                )
            ]
        )
    documents: tuple[Any, ...]
    if spec.schema_application == "object" and type(document) is dict:
        documents = (document,)
    elif spec.schema_application == "each_item" and type(document) is list:
        documents = tuple(document)
    else:
        findings.append(
            _finding(
                "submission.output_shape_mismatch",
                f"Output {spec.contract_output_id!r} has the wrong JSON shape.",
                spec.contract_output_id,
            )
        )
        return None, tuple(findings)
    for offset, child in enumerate(documents):
        for issue in schemas.validate(spec.schema_file, child):
            prefix = f"/{offset}" if spec.schema_application == "each_item" else ""
            findings.append(
                _finding(
                    issue.code,
                    issue.message,
                    spec.contract_output_id,
                    prefix + issue.json_pointer,
                    schema_file=spec.schema_file,
                    failing_property=issue.failing_property,
                )
            )
    if findings:
        return None, tuple(findings)
    metadata = RegisteredArtifactMetadata(
        artifact_id=artifact_id,
        sha256=str(row["sha256"]),
        byte_length=int(row["size"]),
        media_type=str(row["media_type"]),
        storage_uri=str(row["storage_uri"]),
    )
    return (
        RegisteredValidatedOutput(spec.contract_output_id, document, metadata),
        (),
    )


def _validate_phase_semantics(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None:
    if plan.identity.phase_id == "P1":
        source_output = outputs.get("p1.source_changes")
        if source_output is not None and type(source_output.document) is list:
            keys = [_literature_key(item) for item in source_output.document]
            if len(keys) != len(set(keys)):
                findings.append(
                    _finding(
                        "p1.duplicate_source_identity",
                        "Phase 1 source changes repeat a stable literature identity.",
                        "p1.source_changes",
                    )
                )
    if plan.identity.phase_id not in {"P3", "P4", "P5"}:
        return
    if selected_method is None:
        findings.append(
            _finding(
                "submission.method_identity_missing",
                "A method-bound submission requires one exact selected method.",
                plan.identity.phase_id,
            )
        )
        return
    expected = selected_method.to_dict()
    identity_required_types = {
        "theory_record",
        "empirical_evidence_index",
        "empirical_synthesis",
        "implementation_record",
    }
    for binding in plan.publication_bindings:
        target = binding["target"]
        identity_required = str(target.get("record_type", "")) in identity_required_types
        for raw_output_id in binding["output_ids"]:
            output_id = str(raw_output_id)
            output = outputs.get(output_id)
            if output is None or type(output.document) is not dict:
                continue
            declared = output.document.get("method_identity") or output.document.get("identity")
            if identity_required and declared is None:
                findings.append(
                    _finding(
                        "submission.method_identity_missing",
                        f"Published output {output_id!r} must state the exact method identity.",
                        output_id,
                    )
                )
            elif declared is not None and (
                declared.get("stable_id") != expected.get("stable_id")
                or declared.get("version") != expected.get("version")
                or declared.get("definition_sha256") != expected.get("definition_sha256")
            ):
                findings.append(
                    _finding(
                        "submission.method_identity_mismatch",
                        f"Published output {output_id!r} does not match the exact selected method.",
                        output_id,
                    )
                )

def _literature_key(document: Any) -> str:
    if type(document) is not dict:
        return "invalid"
    identifiers = document.get("identifiers", ())
    if type(identifiers) is list:
        normalized = sorted(
            f"{str(item.get('kind', '')).casefold()}:{str(item.get('value', '')).casefold()}"
            for item in identifiers
            if type(item) is dict and item.get("kind") and item.get("value")
        )
        if normalized:
            return normalized[0]
    for field in ("source_id", "record_id"):
        if type(document.get(field)) is str:
            return str(document[field]).casefold()
    return document_sha256(document)


def _finding(
    code: str,
    message: str,
    object_id: str,
    pointer: str = "",
    schema_file: str | None = None,
    failing_property: str | None = None,
) -> ValidationFinding:
    finding = make_finding(
        code=code,
        message=message,
        object_id=object_id,
        pointer=pointer,
    )
    if schema_file is not None:
        return reclassify_harness_owned_finding(
            finding,
            schema_file=schema_file,
            failing_property=failing_property,
        )
    return finding


__all__ = ["SubmissionValidationResult", "validate_submission"]
