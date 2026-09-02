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
from dataclasses import dataclass, replace
from typing import Any, Mapping

from ..domain.identities import SCHEMA_VERSION, MethodIdentity
from ..domain.validation import (
    FindingClass,
    ValidationFinding,
    ValidationSeverity,
)


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
    schema_version: str = SCHEMA_VERSION
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
    sequence: int = 0  # stage sequence (handoffs)
    to_role: str = ""  # next stage's sole role (handoffs); empty when terminal or when the next stage has multiple roles


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
    # Decision/attention/review records and handoffs: the harness knows the
    # run identity, the producing role, and the stage position.
    "decision-record.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "decision_id",
        "phase",
        "source_run_id",
        "generated_by",
        "authority_at_creation",
        # F-2: generation identity is publisher-derived at promotion;
        # candidates must not carry it (strip rule applies as for F-1).
        "generation_id",
        "generation_number",
    }),
    "attention-item.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "attention_id",
        "attention_version_id",
        "source_run_id",
        "raised_by",
        "authority_at_creation",
    }),
    "review-issue.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "issue_id",
        "issue_version_id",
        "source_run_id",
        # NOTE: raised_by is NOT harness-owned here. A review issue's raised_by
        # names the specialist who raised it (theorist/data_analyst/
        # outside_reviewer); the disposition ledger is written by the research
        # lead, so overwriting with the producing role would corrupt it (and
        # fail the schema enum, which excludes research_lead).
        "review_basis_generation_id",
        "authority_at_creation",
    }),
    "handoff.schema.json": frozenset({
        *_COMMON_HARNESS_FIELDS,
        "handoff_id",
        "run_id",
        "phase",
        "sequence",
        "from_role",
        "to_role",
    }),
}


def harness_owned_fields(schema_file: str) -> frozenset[str]:
    """Return the set of harness-owned field names for a schema file.

    Falls back to the common set if the schema is not explicitly registered.
    """
    return _HARNESS_OWNED_BY_SCHEMA.get(
        schema_file, _COMMON_HARNESS_FIELDS
    )


def reclassify_harness_owned_finding(
    finding: ValidationFinding,
    *,
    schema_file: str,
    failing_property: str | None,
    method_bound: bool = True,
) -> ValidationFinding:
    """Route a finding on a harness-owned field to operational failure.

    ADR-015: when a ``schema.*`` finding blames a top-level property the
    harness owns for this schema, no correction lane can repair it (the
    harness re-populates or omits those fields at every close), so the
    finding is an operational harness fault, not an agent-correctable
    contract error.  The message names the fault explicitly.

    The ADR-015 premise (the harness re-populates those fields at every
    close) holds for ``identity``/``lineage`` only when the run is
    method-bound; catalog modes (p2.full_catalog, p2.researcher_proposal)
    leave them agent-authored by design (populate_harness_fields
    :360-367), so ``method_bound=False`` removes them from the effective
    owned set for method.schema.json.
    """
    owned = harness_owned_fields(schema_file)
    if schema_file == "method.schema.json" and not method_bound:
        owned = owned - {"identity", "lineage"}
    if (
        failing_property is None
        or finding.finding_class is not FindingClass.CORRECTABLE_CONTRACT_ERROR
        or failing_property not in owned
    ):
        return finding
    return replace(
        finding,
        message=(
            f"The harness could not satisfy its own field "
            f"{failing_property!r}: {finding.message}"
        ),
        finding_class=FindingClass.OPERATIONAL_FAILURE,
        blocks_publication=True,
        correction_class="none",
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
    """RFC 8785 SHA-256 of content excluding content_sha256.

    ``digest-contracts.json`` registers ``construction: rfc8785_sha256`` for
    every embedded ``content_sha256``; plain ``json.dumps(sort_keys=True)`` is
    a different byte serialization and never matches the contract.
    """
    import copy

    from ..digests.jcs import canonicalize

    cleaned = copy.deepcopy(data)
    cleaned.pop("content_sha256", None)
    return hashlib.sha256(canonicalize(cleaned)).hexdigest()


# --------------------------------------------------------------------------- #
# Envelope population                                                         #
# --------------------------------------------------------------------------- #


def populate_harness_fields(
    payload: dict[str, Any],
    run_facts: SealedRunFacts,
    schema_file: str,
    *,
    item_index: int | None = None,
) -> dict[str, Any]:
    """Populate harness-owned fields in a candidate document.

    Takes the agent's scientific payload and fills harness-owned fields
    with values computed from sealed run facts.  Returns a new dict in the
    existing schema shape — the original payload is not mutated.

    Overwrite policy:
    - Run-bound fields (schema_version, timestamps, phase, mode,
      source_run_id, authority_at_creation, record_type, content_sha256, and
      method identity when a method is selected) are ALWAYS overwritten: the
      harness owns them and agent-written values are not authoritative.
    - Record-local identity fields (record_id, protocol_id,
      evidence_id, issue_id, report_id, source_id) are filled only when
      missing: agents legitimately author these to cross-reference within a
      document, and deterministic fill preserves that linkage.  Filled values
      are unique per (run, schema, item_index).
    - Generation identity (generation_id, generation_number) is assigned by
      the publisher at promotion, never by the harness at closure and never
      by an agent.  When the run-facts value is empty, any agent-supplied
      value is DELETED from the candidate; when non-empty, it is
      overwritten.
    - Provenance-class harness-owned fields (record_type, to_role,
      review_basis_generation_id) follow the generation-identity strip
      rule: when the sealed run fact is empty, any agent-supplied value is
      DELETED (fail-loud via the schema's required rule where applicable),
      because a fabricated value could otherwise pass validation.

    No model call is needed. All values are reproducible from sealed inputs.
    No scientific claim, assumption, result, citation, or provenance
    assertion is added or modified.
    """
    result: dict[str, Any] = dict(payload)
    owned = harness_owned_fields(schema_file)

    # Schema version
    if "schema_version" in owned:
        result["schema_version"] = run_facts.schema_version

    # Timestamps (harness-owned: always overwrite)
    ts = run_facts.produced_at
    if not ts:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
    if "created_at" in owned:
        result["created_at"] = ts
    if "updated_at" in owned:
        result["updated_at"] = ts
    if "finalized_at" in owned:
        result["finalized_at"] = ts

    # Run/project/phase identity (harness-owned: always overwrite)
    if "source_run_id" in owned:
        result["source_run_id"] = run_facts.run_id
    if "phase" in owned:
        result["phase"] = run_facts.phase
    if "mode" in owned:
        result["mode"] = run_facts.mode
    if "record_type" in owned:
        if run_facts.record_type:
            result["record_type"] = run_facts.record_type
        else:
            result.pop("record_type", None)

    # Method identity: populate only when the run is method-bound.  Catalog
    # modes (p2.full_catalog, p2.researcher_proposal) have no selected method;
    # new method identities there are agent-authored by design.
    if run_facts.method_identity:
        if "method_identity" in owned:
            result["method_identity"] = dict(run_facts.method_identity)
        if "identity" in owned:
            result["identity"] = dict(run_facts.method_identity)

    # Generation identifiers: assigned by the publisher at promotion, so a
    # run-local candidate never carries them.  When the run-facts value is
    # empty, strip any agent-supplied value (an agent writing one fabricates
    # generation identity); when non-empty, overwrite as before.
    if "generation_id" in owned:
        if run_facts.generation_id:
            result["generation_id"] = run_facts.generation_id
        else:
            result.pop("generation_id", None)
    if "generation_number" in owned:
        if run_facts.generation_number:
            result["generation_number"] = run_facts.generation_number
        else:
            result.pop("generation_number", None)

    # Record identifiers: fill only when missing, unique per item.
    def _fill_id(field: str, prefix: str = "") -> None:
        if field in owned and not result.get(field):
            result[field] = _derive_record_id(
                run_facts, schema_file, prefix=prefix, item_index=item_index
            )

    _fill_id("record_id")
    _fill_id("protocol_id", prefix="protocol")
    _fill_id("evidence_id", prefix="evidence")
    _fill_id("issue_id", prefix="finding")
    _fill_id("report_id", prefix="report")
    _fill_id("source_id", prefix="source")
    _fill_id("decision_id", prefix="decision")
    _fill_id("attention_id", prefix="attention")
    _fill_id("attention_version_id", prefix="attention.version")
    _fill_id("issue_version_id", prefix="issue.version")
    _fill_id("handoff_id", prefix="handoff")

    # Run-position fields the harness knows exactly
    if "run_id" in owned:
        result["run_id"] = run_facts.run_id
    if "from_role" in owned:
        result["from_role"] = run_facts.role
    if "generated_by" in owned:
        result["generated_by"] = run_facts.role
    if "sequence" in owned and run_facts.sequence:
        result["sequence"] = run_facts.sequence
    if "to_role" in owned:
        if run_facts.to_role:
            result["to_role"] = run_facts.to_role
        else:
            result.pop("to_role", None)

    # Review-specific harness fields
    if "raised_by" in owned:
        result["raised_by"] = run_facts.role
    if "reviewer_role" in owned:
        result["reviewer_role"] = run_facts.reviewer_role or run_facts.role
    if "review_basis_generation_id" in owned:
        if run_facts.review_basis_generation_id:
            result["review_basis_generation_id"] = run_facts.review_basis_generation_id
        else:
            result.pop("review_basis_generation_id", None)

    # Authority marker: a string enum per common-definitions
    # creationAuthority; role outputs are always run-local candidates.
    if "authority_at_creation" in owned:
        result["authority_at_creation"] = "run_local_candidate"
    # Run-local candidates must not carry formal-generation provenance: the
    # schemas forbid publication_receipt_id/published_at unless
    # authority_at_creation is formal_generation (scientific-record allOf
    # if/else rule).  An agent writing them fabricates publication authority,
    # so the harness strips these harness-owned fields from candidates.
    for publication_field in ("publication_receipt_id", "published_at"):
        if publication_field in owned:
            result.pop(publication_field, None)

    # Method lineage: populate only from sealed facts (focused-method runs);
    # never invent lineage.
    if "lineage" in owned and run_facts.method_lineage is not None:
        result["lineage"] = dict(run_facts.method_lineage)

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
    item_index: int | None = None,
) -> str:
    """Derive a deterministic record ID from sealed run facts.

    Format: ``{prefix}.{run_short}[.{item_index}]`` — unique per
    (run, schema, item) so array outputs never receive duplicate identities.
    """
    if not prefix:
        # Derive prefix from schema file name
        prefix = schema_file.replace(".schema.json", "").replace("-", ".")
    # Use first 12 chars of run_id for compactness
    run_short = facts.run_id.replace("-", "")[:12]
    base = f"{prefix}.{run_short}"
    if item_index is not None:
        base = f"{base}.{item_index}"
    return base


__all__ = [
    "SealedRunFacts",
    "agent_authored_fields",
    "harness_owned_fields",
    "populate_harness_fields",
]
