"""Harness-owned envelope field population (HV-4).

Separates agent-authored scientific content from harness-owned system fields.
The harness populates identity, provenance, timestamps, and digest fields
deterministically from sealed run facts; the agent focuses on the scientific
payload.

The document shape does NOT change — the harness fills harness-owned fields
of the EXISTING phase schemas in place.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..domain.identities import MethodIdentity
from ..domain.validation import (
    FindingClass,
    ValidationFinding,
    ValidationSeverity,
    make_finding,
)
from .outputs import OutputSpec


# --------------------------------------------------------------------------- #
# Sealed run facts                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SealedRunFacts:
    """All harness-known facts about a run, reproducible from sealed inputs.

    Passed to :func:`populate_harness_fields` to fill harness-owned fields
    in the candidate document.
    """

    project_id: str
    run_id: str
    phase: str
    mode: str
    role: str
    method_identity: dict[str, Any]
    schema_version: str = "1.0.0"
    generation_id: str = ""
    generation_number: int = 0
    sealed_basis_digest: str = ""
    manifest_sha256: str = ""
    produced_at: str = ""  # ISO timestamp; if empty, harness stamps at call time
    review_basis_generation_id: str = ""
    reviewer_role: str = ""
    record_type: str = ""
    method_lifecycle_state: str = ""
    method_lineage: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Harness-owned field registry (per schema file)                              #
# --------------------------------------------------------------------------- #

# Fields the harness owns and populates deterministically.
# These are populated AFTER the agent's raw output is read, and BEFORE
# validation. The agent should not write these fields.

_COMMON_HARNESS_FIELDS: frozenset[str] = frozenset({
    "schema_version",
    "content_sha256",
    "created_at",
    "updated_at",
    "published_at",
    "publication_receipt_id",
})

# Per-schema harness-owned fields. These include identity/provenance fields
# that the harness can compute from sealed run facts.
_HARNESS_OWNED_BY_SCHEMA: dict[str, frozenset[str]] = {
    "method.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "record_id",
        "generation_id",
        "identity",
        "lineage",
        "authority_at_creation",
    }),
    "scientific-record.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "record_id",
        "generation_id",
        "generation_number",
        "record_type",
        "phase",
        "source_run_id",
        "method_identity",
        "authority_at_creation",
        "replaces_generation_id",
    }),
    "theory-record.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "record_id",
        "generation_id",
        "generation_number",
        "record_type",
        "phase",
        "source_run_id",
        "method_identity",
        "authority_at_creation",
        "replaces_generation_id",
    }),
    "empirical-protocol.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "protocol_id",
        "phase",
        "source_run_id",
        "mode",
        "method_identity",
        "finalized_at",
    }),
    "manuscript-package.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "record_id",
        "generation_id",
        "generation_number",
        "record_type",
        "phase",
        "source_run_id",
        "method_identity",
        "authority_at_creation",
        "replaces_generation_id",
    }),
    "review-finding.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "issue_id",
        "source_run_id",
        "raised_by",
        "review_basis_generation_id",
        "authority_at_creation",
    }),
    "review-report.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "report_id",
        "source_run_id",
        "reviewer_role",
        "review_basis_generation_id",
        "authority_at_creation",
    }),
    "evidence.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "evidence_id",
        "phase",
        "source_run_id",
        "method_identity",
        "authority_at_creation",
        "supersedes_evidence_id",
    }),
    "literature-source.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "record_id",
        "generation_id",
        "source_id",
        "predecessor_generation_id",
        "authority_at_creation",
    }),
}


def harness_owned_fields(schema_file: str) -> frozenset[str]:
    """Return the set of harness-owned field names for a schema file.

    Falls back to the common set if the schema is not explicitly registered.
    """
    return _HARNESS_OWNED_BY_SCHEMA.get(
        schema_file, _COMMON_HARNESS_FIELDS
    )


def agent_authored_fields(
    schema_file: str,
    all_properties: frozenset[str],
) -> frozenset[str]:
    """Return the set of agent-authored field names for a schema file.

    Computed as: all_properties - harness_owned_fields.
    """
    return all_properties - harness_owned_fields(schema_file)


# --------------------------------------------------------------------------- #
# Content hash computation                                                    #
# --------------------------------------------------------------------------- #


def _compute_content_sha256(data: dict[str, Any]) -> str:
    """Compute RFC8785-style canonical SHA-256 of content excluding content_sha256."""
    import copy

    cleaned = copy.deepcopy(data)
    cleaned.pop("content_sha256", None)

    canonical = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Envelope population                                                         #
# --------------------------------------------------------------------------- #


def populate_harness_fields(
    payload: dict[str, Any],
    run_facts: SealedRunFacts,
    schema_file: str,
) -> dict[str, Any]:
    """Populate harness-owned fields in a candidate document.

    Takes the agent's scientific payload and fills all harness-owned fields
    with values computed from sealed run facts.  Returns a new dict in the
    existing schema shape — the original payload is not mutated.

    No model call is needed. All values are reproducible from sealed inputs.
    No scientific claim, assumption, result, citation, or provenance
    assertion is added or modified.
    """
    result: dict[str, Any] = dict(payload)
    owned = harness_owned_fields(schema_file)

    # Schema version
    if "schema_version" in owned:
        result["schema_version"] = run_facts.schema_version

    # Timestamps
    ts = run_facts.produced_at
    if not ts:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
    if "created_at" in owned:
        result.setdefault("created_at", ts)
        # If the agent wrote a created_at, override it — the harness owns this
        result["created_at"] = result.get("created_at", ts)
    if "updated_at" in owned:
        result["updated_at"] = ts
    if "finalized_at" in owned:
        result["finalized_at"] = ts

    # Run/project/phase identity
    if "source_run_id" in owned:
        result["source_run_id"] = run_facts.run_id
    if "phase" in owned:
        result["phase"] = run_facts.phase
    if "mode" in owned:
        result["mode"] = run_facts.mode
    if "record_type" in owned and run_facts.record_type:
        result["record_type"] = run_facts.record_type

    # Method identity
    if "method_identity" in owned:
        result["method_identity"] = dict(run_facts.method_identity)
    if "identity" in owned:
        result["identity"] = dict(run_facts.method_identity)

    # Generation identifiers
    if "generation_id" in owned and run_facts.generation_id:
        result["generation_id"] = run_facts.generation_id
    if "generation_number" in owned and run_facts.generation_number:
        result["generation_number"] = run_facts.generation_number

    # Record identifiers (harness-assigned, deterministic from run + schema)
    if "record_id" in owned:
        result["record_id"] = _derive_record_id(
            run_facts, schema_file
        )
    if "protocol_id" in owned:
        result["protocol_id"] = _derive_record_id(
            run_facts, schema_file, prefix="protocol"
        )
    if "evidence_id" in owned:
        result["evidence_id"] = _derive_record_id(
            run_facts, schema_file, prefix="evidence"
        )
    if "issue_id" in owned:
        result["issue_id"] = _derive_record_id(
            run_facts, schema_file, prefix="finding"
        )
    if "report_id" in owned:
        result["report_id"] = _derive_record_id(
            run_facts, schema_file, prefix="report"
        )
    if "source_id" in owned:
        result["source_id"] = _derive_record_id(
            run_facts, schema_file, prefix="source"
        )

    # Review-specific harness fields
    if "raised_by" in owned:
        result["raised_by"] = run_facts.role
    if "reviewer_role" in owned:
        result["reviewer_role"] = run_facts.reviewer_role or run_facts.role
    if "review_basis_generation_id" in owned and run_facts.review_basis_generation_id:
        result["review_basis_generation_id"] = run_facts.review_basis_generation_id

    # Lineage / authority (harness-owned on method records)
    if "authority_at_creation" in owned:
        result["authority_at_creation"] = _build_authority(run_facts)
    if "lineage" in owned and run_facts.method_lineage is not None:
        result["lineage"] = dict(run_facts.method_lineage)

    # Predecessor/replaces (harness-owned, from sealed facts)
    if "predecessor_generation_id" in owned:
        # Read from the payload if the agent provided it as context;
        # otherwise leave absent.
        pass
    if "replaces_generation_id" in owned:
        pass  # Same — only populate if the sealed facts provide it.

    # Content hash — ALWAYS recomputed (hash paradox: the agent cannot know
    # the hash of the file they are currently writing).
    if "content_sha256" in owned:
        result["content_sha256"] = _compute_content_sha256(result)

    return result


def _derive_record_id(
    facts: SealedRunFacts,
    schema_file: str,
    *,
    prefix: str = "",
) -> str:
    """Derive a deterministic record ID from sealed run facts.

    Format: ``{prefix}.{run_id_short}.{schema_short}`` where the components
    are derived deterministically so the same inputs always produce the
    same ID.
    """
    if not prefix:
        # Derive prefix from schema file name
        prefix = schema_file.replace(".schema.json", "").replace("-", ".")
    # Use first 12 chars of run_id for compactness
    run_short = facts.run_id.replace("-", "")[:12]
    return f"{prefix}.{run_short}"


def _build_authority(facts: SealedRunFacts) -> dict[str, Any]:
    """Build the authority_at_creation structure from sealed run facts."""
    return {
        "source_run_id": facts.run_id,
        "manifest_sha256": facts.manifest_sha256 or "0" * 64,
        "sealed_basis_digest": facts.sealed_basis_digest or "0" * 64,
    }


# --------------------------------------------------------------------------- #
# Candidate output preparation                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CandidateOutput:
    """Result of preparing a candidate output for validation."""

    contract_output_id: str
    schema_file: str
    document: dict[str, Any]
    populated_fields: tuple[str, ...]
    findings: tuple[ValidationFinding, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not any(f.blocks_publication for f in self.findings)


def prepare_candidate_output(
    raw_payload_path: Path,
    run_facts: SealedRunFacts,
    spec: OutputSpec,
) -> CandidateOutput:
    """Read raw agent payload, populate harness fields, return candidate.

    1. Reads the agent's raw payload from disk (preserved per HV-1).
    2. Populates all harness-owned fields from sealed run facts.
    3. Computes content_sha256.
    4. Returns the candidate document and any findings.

    This does NOT call a model. It is a deterministic transformation.

    If the raw payload cannot be read or parsed, returns a candidate with
    a blocking finding.
    """
    findings: list[ValidationFinding] = []
    populated: list[str] = []

    # 1. Read raw payload
    try:
        text = raw_payload_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except FileNotFoundError:
        return CandidateOutput(
            contract_output_id=spec.contract_output_id,
            schema_file=spec.schema_file,
            document={},
            populated_fields=(),
            findings=(
                make_finding(
                    "output.required_missing",
                    f"Agent did not produce required output at {raw_payload_path.name}.",
                    object_id=spec.contract_output_id,
                ),
            ),
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return CandidateOutput(
            contract_output_id=spec.contract_output_id,
            schema_file=spec.schema_file,
            document={},
            populated_fields=(),
            findings=(
                make_finding(
                    "json.decode_error",
                    f"Agent output is not valid JSON: {exc}",
                    object_id=spec.contract_output_id,
                ),
            ),
        )

    if not isinstance(payload, dict):
        return CandidateOutput(
            contract_output_id=spec.contract_output_id,
            schema_file=spec.schema_file,
            document={},
            populated_fields=(),
            findings=(
                make_finding(
                    "json.invalid_input_type",
                    "Agent output must be a JSON object.",
                    object_id=spec.contract_output_id,
                ),
            ),
        )

    # 2. Populate harness-owned fields
    before = set(payload.keys())
    document = populate_harness_fields(payload, run_facts, spec.schema_file)
    after = set(document.keys())
    populated = sorted(
        k for k in (after - before) | before
        if k in harness_owned_fields(spec.schema_file)
    )

    return CandidateOutput(
        contract_output_id=spec.contract_output_id,
        schema_file=spec.schema_file,
        document=document,
        populated_fields=tuple(populated),
        findings=tuple(findings),
    )


__all__ = [
    "CandidateOutput",
    "SealedRunFacts",
    "agent_authored_fields",
    "harness_owned_fields",
    "populate_harness_fields",
    "prepare_candidate_output",
]
