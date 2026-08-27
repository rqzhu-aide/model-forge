#!/usr/bin/env python3
"""Validate the Model Forge greenfield architecture specification package."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from jcs import (
    JCSCanonicalizationError,
    JCSInvalidUnicode,
    JCSUnsupportedNumber,
    canonicalize,
)


ARCHITECTURE = Path(__file__).resolve().parents[1]
REPOSITORY = ARCHITECTURE.parent
SCHEMAS = ARCHITECTURE / "schemas"
EXAMPLES = ARCHITECTURE / "examples"
CONTRACTS = ARCHITECTURE / "contracts"

VALID_EXAMPLES = {
    "action-cancel-run.example.json": "action-descriptor.schema.json",
    "action-reactivate-method.example.json": "action-descriptor.schema.json",
    "action-retire-method.example.json": "action-descriptor.schema.json",
    "action-start-run.example.json": "action-descriptor.schema.json",
    "action-withdraw-formal-generation.example.json": "action-descriptor.schema.json",
    "attention-item.example.json": "attention-item.schema.json",
    "authority-event-record-published.example.json": "authority-event.schema.json",
    "authority-event-synthesis-published.example.json": "authority-event.schema.json",
    "authority-event-implementation-published.example.json": "authority-event.schema.json",
    "authority-event-decision-published.example.json": "authority-event.schema.json",
    "authority-event.example.json": "authority-event.schema.json",
    "authority-event-attention-published.example.json": "authority-event.schema.json",
    "authority-event-replay-published.example.json": "authority-event.schema.json",
    "authority-event-replay-alignment.example.json": "authority-event.schema.json",
    "command-attempt-audit-cancellation-accepted.example.json": "command-attempt-audit-event.schema.json",
    "command-attempt-audit-method-accepted.example.json": "command-attempt-audit-event.schema.json",
    "command-attempt-audit-start-accepted.example.json": "command-attempt-audit-event.schema.json",
    "command-attempt-audit-unauthenticated-rejected.example.json": "command-attempt-audit-event.schema.json",
    "command-attempt-audit-withdrawal-rejected.example.json": "command-attempt-audit-event.schema.json",
    "command-error-delegation-not-active.example.json": "command-error.schema.json",
    "command-error.example.json": "command-error.schema.json",
    "compact-view.example.json": "compact-view.schema.json",
    "current-index.example.json": "current-index.schema.json",
    "current-index-replay.example.json": "current-index.schema.json",
    "decision-record.example.json": "decision-record.schema.json",
    "delegation-grant.example.json": "delegation-grant.schema.json",
    "delegation-revocation.example.json": "delegation-revocation.schema.json",
    "evidence.example.json": "evidence.schema.json",
    "empirical-protocol.example.json": "empirical-protocol.schema.json",
    "theory-record.example.json": "theory-record.schema.json",
    "manuscript-package.example.json": "manuscript-package.schema.json",
    "handoff.example.json": "handoff.schema.json",
    "literature-source.example.json": "literature-source.schema.json",
    "method.example.json": "method.schema.json",
    "method-exposition-revision.example.json": "method-exposition-revision.schema.json",
    "digest-vectors.example.json": "digest-vectors.schema.json",
    "method-lifecycle-command.example.json": "method-lifecycle-command.schema.json",
    "formal-generation-withdrawal-command.example.json": "formal-generation-withdrawal-command.schema.json",
    "prepared-role-context.example.json": "prepared-role-context.schema.json",
    "publication-receipt.example.json": "publication-receipt.schema.json",
    "publication-receipt-replay.example.json": "publication-receipt.schema.json",
    "record-state-empirical.example.json": "record-state.schema.json",
    "record-state-empirical-synthesis.example.json": "record-state.schema.json",
    "record-state-implementation.example.json": "record-state.schema.json",
    "record-state-decision.example.json": "record-state.schema.json",
    "record-state.example.json": "record-state.schema.json",
    "record-state-replay.example.json": "record-state.schema.json",
    "review-finding.example.json": "review-finding.schema.json",
    "review-issue.example.json": "review-issue.schema.json",
    "review-report.example.json": "review-report.schema.json",
    "role-context-snapshot.example.json": "role-context-snapshot.schema.json",
    "role-invocation-closure.example.json": "role-invocation-closure.schema.json",
    "role-invocation-downstream-start.example.json": "role-invocation-start.schema.json",
    "role-invocation-start.example.json": "role-invocation-start.schema.json",
    "role-profile.example.json": "role-profile.schema.json",
    "run-cancellation-command.example.json": "run-cancellation-command.schema.json",
    "run-command.example.json": "run-command.schema.json",
    "run-command-with-sealed-basis.example.json": "run-command.schema.json",
    "run-manifest.example.json": "run-manifest.schema.json",
    "run-state.example.json": "run-state.schema.json",
    "run-submission.example.json": "run-submission.schema.json",
    "run-state-cancellation-requested.example.json": "run-state.schema.json",
    "scientific-record.example.json": "scientific-record.schema.json",
    "statement.example.json": "statement.schema.json",
}

INVALID_EXAMPLES = {
    "authority-replay-existing-evidence-reset.invalid.json": "semantic:authority_prior_state",
    "authority-event-alignment-missing-prior-state.invalid.json": "authority-event.schema.json",
    "authority-event-withdraw-current.invalid.json": "authority-event.schema.json",
    "authority-event-cross-family.invalid.json": "authority-event.schema.json",
    "authority-event-evidence-reclassification-missing-prior-state.invalid.json": "authority-event.schema.json",
    "decision-auto-action.invalid.json": "decision-record.schema.json",
    "method-lifecycle-no-op.invalid.json": "method-lifecycle-command.schema.json",
    "formal-withdrawal-nonformal.invalid.json": "formal-generation-withdrawal-command.schema.json",
    "publication-receipt-research-run-withdraw.invalid.json": "publication-receipt.schema.json",
    "record-state-old-method-included.invalid.json": "record-state.schema.json",
    "run-manifest-current-only-history.invalid.json": "run-manifest.schema.json",
    "scientific-record-mutable-position.invalid.json": "scientific-record.schema.json",
    "action-descriptor-cross-family.invalid.json": "action-descriptor.schema.json",
    "method-lifecycle-malformed-digest.invalid.json": "method-lifecycle-command.schema.json",
    "run-cancellation-submitted.invalid.json": "run-cancellation-command.schema.json",
    "run-state-cancellation-after-submission.invalid.json": "run-state.schema.json",
}

INVALID_EXPECTED_SCHEMA_ERRORS = {
    "authority-event-alignment-missing-prior-state.invalid.json": [
        ("<root>", "required"),
    ],
    "authority-event-withdraw-current.invalid.json": [
        ("changes/record_position", "enum"),
    ],
    "authority-event-cross-family.invalid.json": [
        ("changes", "maxProperties"),
    ],
    "authority-event-evidence-reclassification-missing-prior-state.invalid.json": [
        ("<root>", "required"),
    ],
    "decision-auto-action.invalid.json": [
        ("available_actions/0/requires_user_action", "const"),
    ],
    "method-lifecycle-no-op.invalid.json": [
        ("target_lifecycle_state", "const"),
    ],
    "formal-withdrawal-nonformal.invalid.json": [
        ("expected_target_state/publication_state", "const"),
    ],
    "publication-receipt-research-run-withdraw.invalid.json": [
        ("record_changes/0/change_kind", "not"),
    ],
    "record-state-old-method-included.invalid.json": [
        ("alignment/state", "const"),
        ("evidence_eligibility/method_match", "const"),
        ("evidence_eligibility/status", "const"),
    ],
    "run-manifest-current-only-history.invalid.json": [
        ("user_request/choice_values/p4.selected_history", "maxItems"),
    ],
    "scientific-record-mutable-position.invalid.json": [
        ("<root>", "not"),
    ],
    "action-descriptor-cross-family.invalid.json": [
        ("<root>", "oneOf"),
    ],
    "method-lifecycle-malformed-digest.invalid.json": [
        ("content_sha256", "pattern"),
    ],
    "run-cancellation-submitted.invalid.json": [
        ("expected_run_head/current_state", "enum"),
    ],
    "run-state-cancellation-after-submission.invalid.json": [
        ("events/5/from", "enum"),
    ],
}

EXPECTED_RUN_STATES = [
    "created",
    "preparing",
    "prepared",
    "running",
    "cancellation_requested",
    "submitted",
    "validating",
    "promoting",
    "published",
    "cancelled",
    "failed",
    "rejected",
    "conflicted",
]

LEGAL_RUN_TRANSITIONS = {
    "created": {"preparing", "cancellation_requested"},
    "preparing": {"prepared", "cancellation_requested", "failed"},
    "prepared": {"running", "cancellation_requested", "failed"},
    "running": {"submitted", "cancellation_requested", "failed"},
    "cancellation_requested": {"cancelled"},
    "submitted": {"validating"},
    "validating": {"promoting", "rejected", "conflicted", "failed"},
    "promoting": {"published", "conflicted", "failed"},
    "published": set(),
    "cancelled": set(),
    "failed": set(),
    "rejected": set(),
    "conflicted": set(),
}
EXPECTED_NETWORK_POLICIES = ["none", "approved_resources", "user_authorized"]

EXPECTED_PHASE_ROLES = {
    "P1": [
        ("parallel", ["research_lead", "theorist", "data_analyst"]),
        ("serial", ["research_lead"]),
    ],
    "P2": [
        ("parallel", ["theorist", "data_analyst"]),
        ("parallel", ["theorist", "data_analyst"]),
        ("serial", ["research_lead"]),
    ],
    "P3": [
        ("serial", ["theorist"]),
        ("serial", ["data_analyst"]),
        ("serial", ["research_lead"]),
    ],
    "P4": [
        ("serial", ["data_analyst"]),
        ("serial", ["theorist"]),
        ("serial", ["research_lead"]),
    ],
}


def load_json(path: Path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON property {key!r} in {path}")
            result[key] = value
        return result

    def reject_nonfinite(value):
        raise ValueError(f"non-finite JSON number {value} in {path}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_nonfinite,
    )


def canonical_bytes(value) -> bytes:
    return canonicalize(value)


def canonical_sha256(value, omitted_fields: set[str] | None = None) -> str:
    omitted = omitted_fields or set()
    if not isinstance(value, dict):
        raise TypeError("canonical_sha256 expects an object")
    payload = {key: item for key, item in value.items() if key not in omitted}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_digest_contract_registry(schemas, registry) -> list[str]:
    """Validate the machine-readable payload and digest construction registry."""
    errors: list[str] = []
    path = CONTRACTS / "digest-contracts.json"
    digest_registry = load_json(path)
    validator = Draft202012Validator(
        schemas["digest-contract-registry.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    for error in sorted(
        validator.iter_errors(digest_registry),
        key=lambda item: list(item.absolute_path),
    ):
        errors.append(
            f"{path.relative_to(REPOSITORY)} at {pointer(error)}: {error.message}"
        )

    expected_ids = {
        "attention_item.content",
        "authority_event.content",
        "authority_event.root",
        "current_index.content",
        "decision_record.content",
        "evidence_item.content",
        "empirical_protocol.content",
        "manuscript_package.content",
        "review_finding.content",
        "review_report.content",
        "theory_record.content",
        "formal_generation_withdrawal_command.content",
        "literature_source.content",
        "method_lifecycle_command.content",
        "method_record.definition",
        "method_record.content",
        "phase_contract.content",
        "record_state.content",
        "review_issue.content",
        "role_profile.content",
        "run_command.content",
        "run_manifest.content",
        "run_state.event",
        "run_state.journal_root",
        "scientific_record.content",
        "run_cancellation_command.content",
        "delegation_grant.content",
        "delegation_revocation.content",
        "role_context.prepared",
        "role_context.access_event",
        "role_context.access_ledger_head",
        "role_context.snapshot",
        "run_manifest.role_plan_entry",
        "prepared_role_context.prepared",
        "prepared_role_context.content",
        "role_invocation_start.content",
        "role_invocation_closure.content",
        "run_submission.content",
        "command_attempt_audit.raw_request",
        "command_attempt_audit.content",
        "command_attempt_audit.root",
        "publication_receipt.content",
        "validation_attempt.content",
        "output_transformation_record.content",
        "run_submission_attempt.content",
    }
    contracts = digest_registry.get("contracts", [])
    contract_ids = [item.get("contract_id") for item in contracts]
    if len(contract_ids) != len(set(contract_ids)):
        errors.append("digest contract IDs must be unique")
    if set(contract_ids) != expected_ids:
        errors.append(
            "digest registry coverage differs from the required persisted JSON objects: "
            f"missing={sorted(expected_ids - set(contract_ids))}, "
            f"unexpected={sorted(set(contract_ids) - expected_ids)}"
        )

    by_id = {item.get("contract_id"): item for item in contracts}
    exact_specialized_content_contracts = {
        "empirical_protocol.content": (
            "empirical_protocol",
            "empirical-protocol.schema.json",
        ),
        "manuscript_package.content": (
            "manuscript_package",
            "manuscript-package.schema.json",
        ),
        "review_finding.content": (
            "review_finding",
            "review-finding.schema.json",
        ),
        "review_report.content": (
            "review_report",
            "review-report.schema.json",
        ),
        "theory_record.content": (
            "theory_record",
            "theory-record.schema.json",
        ),
    }
    for contract_id, (object_kind, schema_file) in (
        exact_specialized_content_contracts.items()
    ):
        expected = {
            "contract_id": contract_id,
            "object_kind": object_kind,
            "schema_file": schema_file,
            "instance_pointer": "",
            "digest_location": {
                "kind": "embedded",
                "json_pointer": "/content_sha256",
            },
            "construction": "rfc8785_sha256",
            "payload_pointer": "",
            "excluded_json_pointers": ["/content_sha256"],
        }
        if by_id.get(contract_id) != expected:
            errors.append(
                f"digest contract {contract_id} is not the exact whole-record "
                "content construction"
            )

    for contract in contracts:
        schema_file = contract.get("schema_file")
        if schema_file not in schemas:
            errors.append(
                f"digest contract {contract.get('contract_id')} names unknown schema {schema_file}"
            )
        if contract.get("construction") != "rfc8785_sha256":
            continue
        exclusions = contract.get("excluded_json_pointers", [])
        if len(exclusions) != len(set(exclusions)):
            errors.append(
                f"digest contract {contract.get('contract_id')} repeats an excluded pointer"
            )
        location = contract.get("digest_location", {})
        if (
            location.get("kind") == "embedded"
            and contract.get("payload_pointer") == ""
            and location.get("json_pointer") not in exclusions
        ):
            errors.append(
                f"digest contract {contract.get('contract_id')} hashes its own digest field"
            )

    owner_specific_root_digests = {
        "run-manifest.schema.json": {"manifest_sha256"},
        "prepared-role-context.schema.json": {"prepared_context_sha256"},
        "role-context-snapshot.schema.json": {
            "prepared_context_sha256",
            "snapshot_sha256",
        },
        "role-invocation-start.schema.json": {"start_sha256"},
        "role-invocation-closure.schema.json": {"closure_sha256"},
        "run-submission.schema.json": {"submission_sha256"},
        "authority-event.schema.json": {"event_root_sha256"},
        "run-state.schema.json": {"journal_root_sha256"},
        "command-attempt-audit-event.schema.json": {"audit_root_sha256"},
    }
    for schema_name, schema in schemas.items():
        root_properties = schema.get("properties", {})
        produced_fields = set()
        if "content_sha256" in root_properties:
            produced_fields.add("content_sha256")
        produced_fields.update(
            owner_specific_root_digests.get(schema_name, set()) & set(root_properties)
        )
        for field in produced_fields:
            matches = [
                item for item in contracts
                if item.get("schema_file") == schema_name
                and item.get("instance_pointer") == ""
                and item.get("digest_location", {}).get("kind") == "embedded"
                and item.get("digest_location", {}).get("json_pointer")
                == f"/{field}"
            ]
            if len(matches) != 1:
                errors.append(
                    f"root digest field {schema_name}/{field} must have one registry contract"
                )
    method_definition = by_id.get("method_record.definition", {})
    if (
        method_definition.get("payload_pointer")
        != "/mathematical_definition/canonical_definition"
        or method_definition.get("excluded_json_pointers") != []
        or method_definition.get("digest_location", {}).get("json_pointer")
        != "/identity/definition_sha256"
    ):
        errors.append("method identity must hash only the exact canonical definition payload")

    authority_content = by_id.get("authority_event.content", {})
    if authority_content.get("excluded_json_pointers") != [
        "/content_sha256",
        "/event_root_sha256",
    ]:
        errors.append("authority-event content digest exclusions are not exact")
    authority_root = by_id.get("authority_event.root", {})
    if authority_root.get("binary_inputs") != [
        {
            "json_pointer": "/prior_event_root_sha256",
            "decoding": "lowercase_hex_32_bytes",
        },
        {
            "json_pointer": "/content_sha256",
            "decoding": "lowercase_hex_32_bytes",
        },
    ]:
        errors.append("authority-event root must hash prior-root bytes followed by content bytes")

    phase_contract = by_id.get("phase_contract.content", {})
    if phase_contract.get("digest_location") != {
        "kind": "referenced",
        "json_pointer": "/phase_contract_sha256",
        "reference_schema_files": [
            "run-command.schema.json",
            "run-manifest.schema.json",
        ],
    }:
        errors.append("phase-contract digest storage references are incomplete")

    role_context_prepared = by_id.get("role_context.prepared", {})
    if role_context_prepared.get("construction") != "rfc8785_projection_sha256" or role_context_prepared.get(
        "included_json_pointers"
    ) != [
        "/phase_contract",
        "/role_profile",
        "/model_capacity",
        "/packing_policy",
        "/preference_memory_binding",
        "/prepared_context",
    ]:
        errors.append("prepared-context digest must use the exact six-field projection")

    role_context_head = by_id.get("role_context.access_ledger_head", {})
    if (
        role_context_head.get("source_json_pointer") != "/events/*/event_sha256"
        or role_context_head.get("empty_source_value") != "0" * 64
    ):
        errors.append("role-context access-ledger head contract is incomplete")

    for contract_id, exclusions in (
        ("run_cancellation_command.content", ["/content_sha256"]),
        ("delegation_grant.content", ["/content_sha256", "/signature"]),
        ("delegation_revocation.content", ["/content_sha256", "/signature"]),
        ("role_context.access_event", ["/event_sha256"]),
        ("role_context.snapshot", ["/snapshot_sha256"]),
    ):
        if by_id.get(contract_id, {}).get("excluded_json_pointers") != exclusions:
            errors.append(f"digest contract {contract_id} has incorrect exclusions")
    audit_raw = by_id.get("command_attempt_audit.raw_request", {})
    if (
        audit_raw.get("construction") != "sha256_referenced_bytes"
        or audit_raw.get("instance_pointer") != "/raw_request"
        or audit_raw.get("source_json_pointer") != "/uri"
        or audit_raw.get("digest_location", {}).get("json_pointer") != "/sha256"
    ):
        errors.append("command-attempt raw requests must hash the exact referenced bytes")
    audit_content = by_id.get("command_attempt_audit.content", {})
    if audit_content.get("excluded_json_pointers") != [
        "/content_sha256",
        "/audit_root_sha256",
    ]:
        errors.append("command-attempt content digest exclusions are not exact")
    audit_root = by_id.get("command_attempt_audit.root", {})
    if audit_root.get("binary_inputs") != [
        {
            "json_pointer": "/prior_audit_root_sha256",
            "decoding": "lowercase_hex_32_bytes",
        },
        {
            "json_pointer": "/content_sha256",
            "decoding": "lowercase_hex_32_bytes",
        },
    ]:
        errors.append("command-attempt root must hash prior-root bytes followed by content bytes")
    if by_id.get("publication_receipt.content", {}).get(
        "excluded_json_pointers"
    ) != ["/content_sha256"]:
        errors.append("publication-receipt self-digest exclusion is not exact")
    if digest_registry.get("canonicalization") != "RFC8785":
        errors.append("all registered JSON digest contracts must use RFC 8785")
    if digest_registry.get("hash_algorithm") != "SHA-256":
        errors.append("all registered digest contracts must use SHA-256")
    return errors


def validate_digest_vectors() -> list[str]:
    """Check fixed canonical bytes, hashes, and fail-closed numeric behavior."""
    errors: list[str] = []
    vectors = load_json(EXAMPLES / "digest-vectors.example.json")
    accepted_ids: set[str] = set()
    for vector in vectors["accepted_vectors"]:
        vector_id = vector["vector_id"]
        if vector_id in accepted_ids:
            errors.append(f"digest vector {vector_id} is duplicated")
        accepted_ids.add(vector_id)
        try:
            encoded = canonical_bytes(vector["input"])
        except JCSCanonicalizationError as exc:
            errors.append(f"digest vector {vector_id} was rejected: {exc}")
            continue
        if encoded.decode("utf-8") != vector["canonical_json"]:
            errors.append(f"digest vector {vector_id} has different canonical bytes")
        if hashlib.sha256(encoded).hexdigest() != vector["sha256"]:
            errors.append(f"digest vector {vector_id} has a different SHA-256 digest")

    error_types = {
        "unsupported_number": JCSUnsupportedNumber,
        "invalid_unicode": JCSInvalidUnicode,
        "invalid_json_value": JCSCanonicalizationError,
    }
    rejected_ids: set[str] = set()
    for vector in vectors["rejected_vectors"]:
        vector_id = vector["vector_id"]
        if vector_id in rejected_ids:
            errors.append(f"rejected digest vector {vector_id} is duplicated")
        rejected_ids.add(vector_id)
        expected_type = error_types[vector["error_code"]]
        try:
            canonical_bytes(vector["input"])
        except expected_type:
            pass
        except JCSCanonicalizationError as exc:
            errors.append(
                f"digest vector {vector_id} raised {type(exc).__name__}, "
                f"expected {expected_type.__name__}"
            )
        else:
            errors.append(f"digest vector {vector_id} did not fail closed")

    try:
        canonical_bytes({"invalid": "\ud800"})
    except JCSInvalidUnicode:
        pass
    else:
        errors.append("the bundled JCS reference accepted a lone UTF-16 surrogate")
    return errors


def validate_method_identity_vector(schemas, registry) -> list[str]:
    """Prove that editorial revision preserves mathematical identity only."""
    errors: list[str] = []
    method = load_json(EXAMPLES / "method.example.json")
    vector = load_json(EXAMPLES / "method-exposition-revision.example.json")
    definition = method["mathematical_definition"]["canonical_definition"]
    expected_definition_sha256 = hashlib.sha256(canonical_bytes(definition)).hexdigest()
    if method["identity"]["definition_sha256"] != expected_definition_sha256:
        errors.append("method identity does not hash its exact canonical definition")

    exact_components = [
        "target_or_estimand",
        "objective_or_estimating_equation",
        "algorithm_or_update_rule",
        "constraints_and_normalization",
        "tuning_definition",
        "calculation_defining_assumptions",
    ]
    if method["mathematical_definition"]["defining_components"] != exact_components:
        errors.append("method definition does not enumerate all six canonical components")
    step_orders = [item["order"] for item in definition["algorithm_or_update_rule"]]
    if step_orders != list(range(1, len(step_orders) + 1)):
        errors.append("canonical method algorithm steps must use contiguous order values")
    structured_assumption_ids = {item["assumption_id"] for item in method["assumptions"]}
    defining_assumption_ids = {
        item["assumption_id"]
        for item in definition["calculation_defining_assumptions"]
    }
    if not defining_assumption_ids.issubset(structured_assumption_ids):
        errors.append("canonical method definition cites an undeclared structured assumption")

    expected = vector["expected_relation"]
    if expected["definition_sha256"] != expected_definition_sha256:
        errors.append("exposition vector records the wrong definition digest")
    if expected["base_content_sha256"] != method["content_sha256"]:
        errors.append("exposition vector is not bound to the base method generation")
    if method["content_sha256"] != canonical_sha256(method, {"content_sha256"}):
        errors.append("base method generation has an invalid whole-record digest")

    exact_identity = method["identity"]
    selected_stable_id = exact_identity["stable_id"]
    selected_version = exact_identity["version"]

    def audit_identity_references(value, location):
        if isinstance(value, dict):
            if (
                value.get("stable_id") == selected_stable_id
                and value.get("version") == selected_version
                and "definition_sha256" in value
                and value != exact_identity
            ):
                errors.append(
                    f"{location} uses a conflicting digest for the selected method identity"
                )
            if (
                value.get("record_id") == method["record_id"]
                and value.get("generation_id") == method["generation_id"]
                and value.get("content_sha256") != method["content_sha256"]
            ):
                errors.append(
                    f"{location} uses a conflicting digest for the selected method generation"
                )
            for key, item in value.items():
                audit_identity_references(item, f"{location}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                audit_identity_references(item, f"{location}/{index}")

    for example_path in sorted(EXAMPLES.glob("*.example.json")):
        audit_identity_references(load_json(example_path), example_path.name)

    manifest = load_json(EXAMPLES / "run-manifest.example.json")
    method_input = next(
        item for item in manifest["frozen_inputs"] if item["input_id"] == "input.current_method"
    )
    if (
        method_input["record_basis"]["method_identity"] != exact_identity
        or method_input["record_basis"]["content_sha256"] != method["content_sha256"]
        or method_input["artifact"]["sha256"] != method["content_sha256"]
    ):
        errors.append("run manifest does not freeze the exact selected method generation")

    revised = copy.deepcopy(method)
    replacements = vector["replacement_fields"]
    for field in (
        "generation_id",
        "summary",
        "lineage",
        "created_at",
        "updated_at",
        "publication_receipt_id",
        "published_at",
    ):
        revised[field] = copy.deepcopy(replacements[field])
    revised["mathematical_definition"]["canonical_artifact"] = copy.deepcopy(
        replacements["canonical_artifact"]
    )
    revised["mathematical_definition"]["definition_locator"] = replacements[
        "definition_locator"
    ]
    revised["content_sha256"] = expected["revised_content_sha256"]

    method_validator = Draft202012Validator(
        schemas["method.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    for error in method_validator.iter_errors(revised):
        errors.append(
            "constructed exposition revision fails method.schema.json at "
            f"{pointer(error)}: {error.message}"
        )

    revised_definition = revised["mathematical_definition"]["canonical_definition"]
    revised_definition_sha256 = hashlib.sha256(
        canonical_bytes(revised_definition)
    ).hexdigest()
    revised_content_sha256 = canonical_sha256(revised, {"content_sha256"})
    if revised_definition != definition:
        errors.append("exposition revision changed the canonical mathematical payload")
    if revised["identity"] != method["identity"]:
        errors.append("exposition revision changed the exact method identity")
    if revised_definition_sha256 != expected_definition_sha256:
        errors.append("exposition revision changed the definition digest")
    if revised_content_sha256 != expected["revised_content_sha256"]:
        errors.append("exposition revision records the wrong whole-record digest")
    if revised_content_sha256 == method["content_sha256"]:
        errors.append("exposition revision did not change the whole-record digest")
    if (
        revised["mathematical_definition"]["canonical_artifact"]["sha256"]
        == method["mathematical_definition"]["canonical_artifact"]["sha256"]
    ):
        errors.append("exposition revision did not change the artifact digest")
    if revised["lineage"]["predecessor"] != method["identity"]:
        errors.append("exposition revision does not name its unchanged predecessor identity")
    return errors


def validate_shared_digest_examples() -> list[str]:
    """Verify digests introduced by cancellation, delegation, and role context."""
    errors: list[str] = []
    for example_name, omitted_fields in (
        ("run-cancellation-command.example.json", {"content_sha256"}),
        (
            "delegation-grant.example.json",
            {"content_sha256", "signature"},
        ),
        (
            "delegation-revocation.example.json",
            {"content_sha256", "signature"},
        ),
    ):
        item = load_json(EXAMPLES / example_name)
        if item["content_sha256"] != canonical_sha256(item, omitted_fields):
            errors.append(f"{example_name} has an invalid registered content digest")

    snapshot = load_json(EXAMPLES / "role-context-snapshot.example.json")
    prepared_fields = (
        "phase_contract",
        "role_profile",
        "model_capacity",
        "packing_policy",
        "preference_memory_binding",
        "prepared_context",
    )
    prepared_payload = {field: snapshot[field] for field in prepared_fields}
    prepared_digest = hashlib.sha256(canonical_bytes(prepared_payload)).hexdigest()
    if snapshot["prepared_context_sha256"] != prepared_digest:
        errors.append("role-context prepared digest does not match its six-field projection")

    prior_event_digest = "0" * 64
    events = snapshot["access_ledger"]["events"]
    for expected_sequence, event in enumerate(events, start=1):
        if event["sequence"] != expected_sequence:
            errors.append("role-context access events must have contiguous sequence values")
        if event["prior_event_sha256"] != prior_event_digest:
            errors.append(
                f"role-context access event {event['event_id']} breaks the digest chain"
            )
        event_digest = canonical_sha256(event, {"event_sha256"})
        if event["event_sha256"] != event_digest:
            errors.append(
                f"role-context access event {event['event_id']} has an invalid digest"
            )
        prior_event_digest = event_digest
    if snapshot["access_ledger"]["head_sha256"] != prior_event_digest:
        errors.append(
            "role-context access-ledger head must be zero for an empty ledger or the final event digest"
        )
    if snapshot["snapshot_sha256"] != canonical_sha256(
        snapshot, {"snapshot_sha256"}
    ):
        errors.append("role-context snapshot has an invalid whole-snapshot digest")
    return errors

def _artifact_identity(artifact: dict) -> tuple:
    """Return immutable artifact identity while ignoring optional physical locators."""
    return tuple(
        artifact.get(field)
        for field in ("artifact_id", "uri", "sha256", "media_type", "locator")
    )

def _role_start_diagnostics(
    start: dict,
    manifest: dict,
    upstream_closures: dict[str, dict],
) -> list[str]:
    """Return stable cross-object diagnostics for one immutable role start."""
    errors: list[str] = []
    identity_fields = ("run_id", "project_id", "phase", "mode")
    for field in identity_fields:
        if start[field] != manifest[field]:
            errors.append(f"role start changed manifest {field}")
    if start["manifest_binding"]["manifest_sha256"] != manifest["manifest_sha256"]:
        errors.append("role start changed the sealed manifest digest")

    sequence = start["role_plan_step"]["sequence"]
    matching_steps = [step for step in manifest["role_plan"] if step["sequence"] == sequence]
    if len(matching_steps) != 1:
        errors.append("role start does not resolve one manifest role-plan entry")
        return errors
    manifest_step = matching_steps[0]
    copied_step = copy.deepcopy(start["role_plan_step"])
    recorded_step_digest = copied_step.pop("role_plan_entry_sha256")
    if copied_step != manifest_step:
        errors.append("role start changed the copied manifest role-plan entry")
    if recorded_step_digest != canonical_sha256(manifest_step):
        errors.append("role start has the wrong role-plan-entry digest")
    if start["role_write_root"] != manifest_step["role_write_root"]:
        errors.append("role start changed the role write root")

    manifest_inputs = {item["input_id"]: item for item in manifest["frozen_inputs"]}
    profile = manifest_inputs.get(manifest_step["profile_input_id"])
    if profile is None or start["resolved_profile_artifact"] != profile["artifact"]:
        errors.append("role start changed the resolved profile artifact")

    actual_inputs = start["actual_input_bindings"]
    if [item["input_id"] for item in actual_inputs] != manifest_step["input_ids"]:
        errors.append("role start actual input order differs from the role-plan recipe")
    for binding in actual_inputs:
        input_id = binding["input_id"]
        if binding["source_kind"] == "manifest_frozen_input":
            frozen = manifest_inputs.get(input_id)
            if frozen is None or binding["artifact"] != frozen["artifact"]:
                errors.append(f"role start changed frozen input {input_id}")
        else:
            source = binding["upstream_closure"]
            closure = upstream_closures.get(source["invocation_closure_id"])
            if closure is None or closure["terminal_status"] != "succeeded":
                errors.append(f"role start uses unclosed upstream input {input_id}")
                continue
            if source["closure_sha256"] != closure["closure_sha256"]:
                errors.append(f"role start changed upstream closure digest for {input_id}")
            outputs = {
                item["output_id"]: item for item in closure["verified_outputs"]
            }
            output = outputs.get(source["output_id"])
            if output is None or source["output_id"] != input_id:
                errors.append(f"role start uses undeclared upstream output {input_id}")
            elif _artifact_identity(binding["artifact"]) != _artifact_identity(
                output["accepted_artifact"]
            ):
                errors.append(f"role start changed accepted upstream artifact for {input_id}")

    expected_outputs = {item["output_id"]: item for item in manifest["expected_outputs"]}
    output_bindings = start["output_contract_bindings"]
    if [item["output_id"] for item in output_bindings] != manifest_step["output_ids"]:
        errors.append("role start output contracts differ from the role-plan recipe")
    copied_output_fields = (
        "output_id",
        "contract_output_id",
        "output_kind",
        "relative_path",
        "schema_uri",
        "required",
    )
    for binding in output_bindings:
        expected = expected_outputs.get(binding["output_id"])
        if expected is None or any(
            binding[field] != expected[field] for field in copied_output_fields
        ):
            errors.append(f"role start changed output contract {binding['output_id']}")

    grants = start["capability_grants"]
    if grants["read_input_ids"] != manifest_step["input_ids"]:
        errors.append("role start read grants differ from actual inputs")
    if grants["write_output_ids"] != manifest_step["output_ids"]:
        errors.append("role start write grants differ from output contracts")
    if parse_time(grants["expires_at"]) <= parse_time(start["started_at"]):
        errors.append("role start capability grants expire before execution")
    if parse_time(start["prepared_context_binding"]["prepared_at"]) > parse_time(
        start["started_at"]
    ):
        errors.append("role start predates its prepared context")
    if start["start_sha256"] != canonical_sha256(start, {"start_sha256"}):
        errors.append("role start has an invalid whole-record digest")
    return errors


def _submission_chain_diagnostics(submission: dict, manifest: dict) -> list[str]:
    """Check ordered successful closures and complete submitted outputs."""
    errors: list[str] = []
    chain = submission["closure_chain"]
    expected_steps = [
        (step["sequence"], step["stage_id"], step["role"])
        for step in manifest["role_plan"]
    ]
    actual_steps = [
        (item["sequence"], item["stage_id"], item["role"]) for item in chain
    ]
    if actual_steps != expected_steps:
        errors.append("submission closure chain does not cover the selected role plan")
    if any(item["terminal_status"] != "succeeded" for item in chain):
        errors.append("submission closure chain contains an unsuccessful role")
    closure_ids = [item["invocation_closure_id"] for item in chain]
    if len(closure_ids) != len(set(closure_ids)):
        errors.append("submission closure chain repeats a role closure")
    if not chain or submission["lead_closure"] != {
        "invocation_closure_id": chain[-1]["invocation_closure_id"],
        "closure_sha256": chain[-1]["closure_sha256"],
    } or chain[-1]["role"] != "research_lead":
        errors.append("submission does not bind the final research-lead closure")

    expected_outputs = {item["output_id"]: item for item in manifest["expected_outputs"]}
    submitted = {item["output_id"]: item for item in submission["submitted_artifacts"]}
    if len(submitted) != len(submission["submitted_artifacts"]):
        errors.append("submission repeats an output artifact")
    if set(submitted) != set(expected_outputs):
        errors.append("submission does not contain every expected role output")
    chain_digests = {
        item["invocation_closure_id"]: item["closure_sha256"] for item in chain
    }
    for output_id, item in submitted.items():
        expected = expected_outputs.get(output_id)
        if expected is None:
            continue
        if item["contract_output_id"] != expected["contract_output_id"]:
            errors.append(f"submission changed output contract {output_id}")
        if chain_digests.get(item["source_invocation_closure_id"]) != item[
            "source_closure_sha256"
        ]:
            errors.append(f"submission changed source closure for {output_id}")
    return errors


def validate_role_invocation_lifecycle() -> list[str]:
    """Validate prepared context, dynamic role starts, closures, and submission."""
    errors: list[str] = []
    manifest = load_json(EXAMPLES / "run-manifest.example.json")
    prepared = load_json(EXAMPLES / "prepared-role-context.example.json")
    snapshot = load_json(EXAMPLES / "role-context-snapshot.example.json")
    start = load_json(EXAMPLES / "role-invocation-start.example.json")
    closure = load_json(EXAMPLES / "role-invocation-closure.example.json")
    downstream = load_json(EXAMPLES / "role-invocation-downstream-start.example.json")
    submission = load_json(EXAMPLES / "run-submission.example.json")

    for invocation in (start, downstream):
        executor = invocation["executor_binding"]
        if executor["backend"] != "trusted_local":
            errors.append("role start executor backend is not trusted_local")
        process_control = executor["process_control"]
        if process_control["supervision"] != "local_process_group":
            errors.append("role start process supervision is not local_process_group")
        if process_control["termination"] != "sigterm_then_sigkill":
            errors.append("role start process termination is not sigterm_then_sigkill")
        if process_control["quiescence_required"] is not True:
            errors.append("role start does not require verified quiescence")
        working_roots = executor["working_roots"]
        run_profile = working_roots["run_profile"]
        workspace = working_roots["workspace"]
        if not isinstance(run_profile, str) or not run_profile.strip():
            errors.append("role start run profile working root is missing or empty")
        if not isinstance(workspace, str) or not workspace.strip():
            errors.append("role start workspace working root is missing or empty")
        if run_profile == workspace:
            errors.append("role start run profile is also the workspace")
    pinned_executor_fields = {
        "executor_profile_id",
        "executor_profile_artifact",
        "hermes_executable",
        "backend",
    }
    if any(
        start["executor_binding"][field] != downstream["executor_binding"][field]
        for field in pinned_executor_fields
    ):
        errors.append("example role starts do not share the pinned version 1 executor")

    projection_fields = (
        "phase_contract",
        "role_profile",
        "model_capacity",
        "packing_policy",
        "preference_memory_binding",
        "prepared_context",
    )
    projection = {field: prepared[field] for field in projection_fields}
    if prepared["prepared_context_sha256"] != hashlib.sha256(
        canonical_bytes(projection)
    ).hexdigest():
        errors.append("PreparedRoleContext has an invalid projection digest")
    if prepared["content_sha256"] != canonical_sha256(
        prepared, {"content_sha256"}
    ):
        errors.append("PreparedRoleContext has an invalid whole-record digest")

    errors.extend(_role_start_diagnostics(start, manifest, {}))
    prepared_binding = start["prepared_context_binding"]
    expected_prepared_source = {
        "prepared_context_id": prepared["prepared_context_id"],
        "artifact": prepared_binding["prepared_context_artifact"],
        "content_sha256": prepared["content_sha256"],
        "prepared_context_sha256": prepared["prepared_context_sha256"],
    }
    if prepared_binding["prepared_context_id"] != prepared["prepared_context_id"]:
        errors.append("role start changed the PreparedRoleContext identity")
    if prepared_binding["prepared_context_content_sha256"] != prepared["content_sha256"]:
        errors.append("role start changed the PreparedRoleContext content digest")
    if prepared_binding["prepared_context_sha256"] != prepared["prepared_context_sha256"]:
        errors.append("role start changed the prepared-context projection digest")

    prepared_input_ids = {
        item["input_id"]
        for item in start["actual_input_bindings"]
        if item["delivery"] == "prepared_context"
    }
    context_items = {
        item["item_id"]: item for item in prepared["prepared_context"]["context_items"]
    }
    if set(context_items) != prepared_input_ids:
        errors.append("prepared context contains missing or undeclared actual inputs")
    input_artifacts = {
        item["input_id"]: item["artifact"] for item in start["actual_input_bindings"]
    }
    for input_id, context_item in context_items.items():
        if context_item["source_artifacts"] != [input_artifacts[input_id]]:
            errors.append(f"prepared context changed source artifact for {input_id}")
    if prepared["prepared_context"]["execution_metadata"]["role_write_root"] != start[
        "role_write_root"
    ]:
        errors.append("prepared context changed the exact role write root")

    for field in (
        "run_id",
        "project_id",
        "phase",
        "mode",
        "stage_id",
        "execution_group_id",
        "role",
    ) + projection_fields:
        if snapshot[field] != prepared[field]:
            errors.append(f"RoleContextSnapshot changed prepared field {field}")
    if snapshot["prepared_context_source"] != expected_prepared_source:
        errors.append("RoleContextSnapshot cites a different PreparedRoleContext source")

    start_identity = {
        "run_id": start["run_id"],
        "project_id": start["project_id"],
        "phase": start["phase"],
        "mode": start["mode"],
        "sequence": start["role_plan_step"]["sequence"],
        "stage_id": start["role_plan_step"]["stage_id"],
        "execution_group_id": start["role_plan_step"]["execution_group_id"],
        "role": start["role_plan_step"]["role"],
    }
    for field, expected in start_identity.items():
        if closure[field] != expected:
            errors.append(f"role closure changed invocation field {field}")
    if closure["invocation_start_binding"]["start_sha256"] != start["start_sha256"]:
        errors.append("role closure changed its invocation-start digest")
    context_binding = closure["context_snapshot_binding"]
    if context_binding["prepared_context_source"] != expected_prepared_source:
        errors.append("role closure changed the PreparedRoleContext source")
    if context_binding["snapshot_sha256"] != snapshot["snapshot_sha256"]:
        errors.append("role closure changed the final context snapshot digest")
    if context_binding["access_ledger_head_sha256"] != snapshot["access_ledger"][
        "head_sha256"
    ] or context_binding["access_event_count"] != len(snapshot["access_ledger"]["events"]):
        errors.append("role closure changed the sealed access ledger")
    if closure["closure_sha256"] != canonical_sha256(closure, {"closure_sha256"}):
        errors.append("role closure has an invalid whole-record digest")

    output_contracts = {item["output_id"]: item for item in start["output_contract_bindings"]}
    verified = {item["output_id"]: item for item in closure["verified_outputs"]}
    if set(verified) != set(output_contracts):
        errors.append("successful role closure omits a declared output")
    for output_id, output in verified.items():
        contract = output_contracts.get(output_id)
        if contract is None:
            continue
        for field in ("contract_output_id", "output_kind", "schema_uri"):
            if output[field] != contract[field]:
                errors.append(f"role closure changed output metadata for {output_id}")
        if output["source_artifact"]["sha256"] != output["accepted_artifact"]["sha256"]:
            errors.append(f"accepted role output changed bytes for {output_id}")
    for handoff in closure["accepted_handoffs"]:
        output = verified.get(handoff["output_id"])
        if output is None or handoff["accepted_artifact"] != output["accepted_artifact"]:
            errors.append("accepted handoff does not resolve to a verified role output")

    upstream = {closure["invocation_closure_id"]: closure}
    errors.extend(_role_start_diagnostics(downstream, manifest, upstream))
    if parse_time(downstream["started_at"]) <= parse_time(closure["closed_at"]):
        errors.append("downstream role started before the upstream closure fixed its outputs")
    mismatch_probe = copy.deepcopy(downstream)
    upstream_binding = next(
        item for item in mismatch_probe["actual_input_bindings"]
        if item["source_kind"] == "accepted_upstream_output"
    )
    upstream_binding["artifact"]["sha256"] = "0" * 64
    if not any(
        "changed accepted upstream artifact" in item
        for item in _role_start_diagnostics(mismatch_probe, manifest, upstream)
    ):
        errors.append("downstream artifact-mismatch probe was not rejected")

    if submission["submission_sha256"] != canonical_sha256(
        submission, {"submission_sha256"}
    ):
        errors.append("RunSubmission has an invalid whole-record digest")
    if submission["manifest_binding"]["manifest_sha256"] != manifest["manifest_sha256"]:
        errors.append("RunSubmission changed the sealed manifest digest")
    errors.extend(_submission_chain_diagnostics(submission, manifest))
    omitted_probe = copy.deepcopy(submission)
    omitted_probe["closure_chain"].pop(1)
    if not any(
        "does not cover the selected role plan" in item
        for item in _submission_chain_diagnostics(omitted_probe, manifest)
    ):
        errors.append("incomplete submission closure-chain probe was not rejected")

    analyst_chain = submission["closure_chain"][0]
    if analyst_chain["start_sha256"] != start["start_sha256"] or analyst_chain[
        "closure_sha256"
    ] != closure["closure_sha256"]:
        errors.append("RunSubmission changed the analyst start or closure digest")
    if submission["closure_chain"][1]["start_sha256"] != downstream["start_sha256"]:
        errors.append("RunSubmission changed the downstream role-start digest")
    analyst_submitted = {
        item["output_id"]: item for item in submission["submitted_artifacts"]
        if item["source_invocation_closure_id"] == closure["invocation_closure_id"]
    }
    for output_id, output in verified.items():
        submitted = analyst_submitted.get(output_id)
        if submitted is None or _artifact_identity(submitted["artifact"]) != _artifact_identity(
            output["accepted_artifact"]
        ):
            errors.append(f"RunSubmission changed accepted analyst output {output_id}")

    run_state = load_json(EXAMPLES / "run-state.example.json")
    submitted_event = next(event for event in run_state["events"] if event["to"] == "submitted")
    if (
        run_state.get("submission_id") != submission["submission_id"]
        or run_state.get("submission_sha256") != submission["submission_sha256"]
        or submitted_event.get("evidence_artifact", {}).get("sha256")
        != submission["submission_sha256"]
    ):
        errors.append("RunState does not bind the exact immutable RunSubmission")
    cancellation_state = load_json(EXAMPLES / "run-state-cancellation-requested.example.json")
    if "submission_id" in cancellation_state or "submission_sha256" in cancellation_state:
        errors.append("pre-submission cancellation must not claim a RunSubmission")
    return errors

def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def pointer(error) -> str:
    location = "/".join(str(part) for part in error.absolute_path)
    return location or "<root>"


def validate_run_state_journal(run_state: dict, label: str) -> list[str]:
    """Validate one run journal against the canonical lifecycle and hash chain."""
    errors: list[str] = []
    prior_event_sha = "0" * 64
    prior_state = None
    prior_time = None
    event_ids: set[str] = set()
    for expected_sequence, event in enumerate(run_state["events"], start=1):
        if event["sequence"] != expected_sequence:
            errors.append(f"{label}: event sequences must start at one and remain contiguous")
        if event["event_id"] in event_ids:
            errors.append(f"{label}: event IDs must be unique")
        event_ids.add(event["event_id"])
        if event["prior_event_sha256"] != prior_event_sha:
            errors.append(f"{label}: event {event['event_id']} breaks the hash chain")
        expected_event_sha = canonical_sha256(event, {"event_sha256"})
        if event["event_sha256"] != expected_event_sha:
            errors.append(f"{label}: event {event['event_id']} has an invalid digest")
        event_time = parse_time(event["at"])
        if prior_time is not None and event_time < prior_time:
            errors.append(f"{label}: event timestamps must be nondecreasing")
        if prior_state is None:
            if "from" in event or event["to"] != "created":
                errors.append(f"{label}: first event must create the run")
        else:
            if event.get("from") != prior_state:
                errors.append(f"{label}: event {event['event_id']} has the wrong from state")
            if event["to"] not in LEGAL_RUN_TRANSITIONS[prior_state]:
                errors.append(f"{label}: event {event['event_id']} uses an illegal transition")
        prior_event_sha = event["event_sha256"]
        prior_state = event["to"]
        prior_time = event_time
    if run_state["journal_root_sha256"] != prior_event_sha:
        errors.append(f"{label}: journal root must equal the final event digest")
    if run_state["current_state"] != prior_state:
        errors.append(f"{label}: current state must equal the final event state")
    if prior_time is None or parse_time(run_state["updated_at"]) != prior_time:
        errors.append(f"{label}: updated time must equal the final event time")
    return errors


def validate_command_attempt_audit(schemas, registry) -> list[str]:
    """Validate the operational audit chain, commands, errors, and effects."""
    errors: list[str] = []
    names = [
        "command-attempt-audit-start-accepted.example.json",
        "command-attempt-audit-method-accepted.example.json",
        "command-attempt-audit-withdrawal-rejected.example.json",
        "command-attempt-audit-cancellation-accepted.example.json",
        "command-attempt-audit-unauthenticated-rejected.example.json",
    ]
    events = [load_json(EXAMPLES / name) for name in names]
    events.sort(key=lambda item: item["audit_sequence"])
    event_ids: set[str] = set()
    prior_root = "0" * 64
    prior_time = None
    for expected_sequence, event in enumerate(events, start=1):
        if event["audit_sequence"] != expected_sequence:
            errors.append("command-attempt audit sequences must start at one and remain contiguous")
        if event["audit_event_id"] in event_ids:
            errors.append("command-attempt audit event IDs must be unique")
        event_ids.add(event["audit_event_id"])
        if event["prior_audit_root_sha256"] != prior_root:
            errors.append(f"audit event {event['audit_event_id']} breaks the root chain")
        content = canonical_sha256(
            event, {"content_sha256", "audit_root_sha256"}
        )
        if event["content_sha256"] != content:
            errors.append(f"audit event {event['audit_event_id']} has an invalid content digest")
        root_digest = hashlib.sha256(
            bytes.fromhex(prior_root) + bytes.fromhex(content)
        ).hexdigest()
        if event["audit_root_sha256"] != root_digest:
            errors.append(f"audit event {event['audit_event_id']} has an invalid audit root")
        occurred_at = parse_time(event["occurred_at"])
        if prior_time is not None and occurred_at < prior_time:
            errors.append("command-attempt audit times must be nondecreasing")
        prior_root = root_digest
        prior_time = occurred_at

    command_names = [
        "run-command.example.json",
        "method-lifecycle-command.example.json",
        "formal-generation-withdrawal-command.example.json",
        "run-cancellation-command.example.json",
    ]
    commands = [load_json(EXAMPLES / name) for name in command_names]
    commands_by_id = {item["command_id"]: item for item in commands}
    grant = load_json(EXAMPLES / "delegation-grant.example.json")

    def target_for(command: dict) -> dict:
        if "phase" in command:
            method = command.get("choice_values", {}).get("p4.selected_method")
            result = {
                "target_type": "run_start",
                "phase": command["phase"],
                "mode": command["mode"],
            }
            if method is not None:
                result["method_id"] = method["stable_id"]
            return result
        if command.get("command_type") == "method_lifecycle_change":
            return {
                "target_type": "method_lifecycle",
                "method_id": command["method_id"],
                "expected_generation_id": command["expected_method"]["generation_id"],
                "expected_content_sha256": command["expected_method"]["content_sha256"],
                "target_lifecycle_state": command["target_lifecycle_state"],
            }
        if command.get("command_type") == "formal_generation_withdrawal":
            return {
                "target_type": "formal_generation",
                **command["target"],
                "expected_record_state_sha256": command["expected_target_state"][
                    "record_state_sha256"
                ],
            }
        return {
            "target_type": "run_cancellation",
            "run_id": command["run_id"],
            "expected_state": command["expected_run_head"]["current_state"],
            "expected_last_event_sequence": command["expected_run_head"][
                "last_event_sequence"
            ],
            "expected_journal_root_sha256": command["expected_run_head"][
                "journal_root_sha256"
            ],
        }

    for event in events:
        validated = event.get("validated_command")
        if validated is None:
            continue
        command = commands_by_id.get(validated["command_id"])
        if command is None:
            errors.append(f"audit event {event['audit_event_id']} cites an unknown command")
            continue
        if validated["command_sha256"] != command["content_sha256"]:
            errors.append(f"audit event {event['audit_event_id']} changed the command digest")
        if event["project_id"] != command["project_id"]:
            errors.append(f"audit event {event['audit_event_id']} changed the command project")
        if event["target"] != target_for(command):
            errors.append(f"audit event {event['audit_event_id']} changed the exact command target")
        audit_requester = event["requested_by"]
        command_requester = command["requested_by"]
        for field in ("user_id", "operating_actor_type", "operator_id"):
            if audit_requester.get(field) != command_requester.get(field):
                errors.append(
                    f"audit event {event['audit_event_id']} changed requester field {field}"
                )
        if command_requester["operating_actor_type"] == "authorized_remote_operator":
            delegation = event["authorization"].get("delegation_check", {})
            if delegation.get("grant_id") != command_requester.get("delegation_id"):
                errors.append(f"audit event {event['audit_event_id']} changed delegation identity")
            if delegation.get("grant_id") == grant["grant_id"] and delegation.get(
                "grant_sha256"
            ) != grant["content_sha256"]:
                errors.append(f"audit event {event['audit_event_id']} changed delegation digest")

        if event["result"]["status"] == "rejected":
            command_error = event["result"]["command_error"]
            if command_error["occurred_at"] != event["occurred_at"]:
                errors.append(f"audit event {event['audit_event_id']} changed error time")

    withdrawal_event = next(
        item for item in events if item["action_type"] == "withdraw_formal_generation"
    )
    standalone_error = load_json(
        EXAMPLES / "command-error-delegation-not-active.example.json"
    )
    if withdrawal_event["result"]["command_error"] != standalone_error:
        errors.append("withdrawal audit does not embed the complete canonical CommandError")

    error_policies = {
        "AUTHENTICATION_REQUIRED": ("authentication", 401, True, "MF-59"),
        "DELEGATION_NOT_ACTIVE": ("authorization", 403, True, "MF-55"),
        "COMMAND_SCHEMA_INVALID": ("schema", 422, True, "MF-59"),
        "COMMAND_DIGEST_MISMATCH": ("digest", 422, True, "MF-57"),
        "IDEMPOTENCY_KEY_REUSED": ("idempotency", 409, True, "MF-49"),
        "INVALID_TRANSITION": ("transition", 409, False, "MF-59"),
        "RUN_ALREADY_SUBMITTED": ("transition", 409, False, "MF-59"),
        "CANCELLATION_REQUESTED": ("concurrency", 409, False, "MF-59"),
        "CONTROL_HEAD_STALE": ("concurrency", 409, True, "MF-49"),
        "TARGET_STATE_MISMATCH": ("concurrency", 409, True, "MF-49"),
        "TARGET_NOT_FOUND": ("dependency", 404, False, "MF-59"),
        "DEPENDENCY_CLOSURE_INCOMPLETE": ("dependency", 422, True, "MF-59"),
        "NO_STATE_CHANGE": ("transition", 409, False, "MF-47"),
        "PUBLICATION_CONFLICT": ("concurrency", 409, True, "MF-56"),
        "CORRECTION_NOT_APPLICABLE": ("transition", 409, False, "MF-73"),
        "CORRECTION_SCOPE_INVALID": ("schema", 400, True, "MF-74"),
        "CORRECTION_EXHAUSTED": ("transition", 409, False, "MF-75"),
    }
    error_validator = Draft202012Validator(
        schemas["command-error.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    for code, policy in error_policies.items():
        category, http_status, retryable, rule_id = policy
        probe = copy.deepcopy(standalone_error)
        probe.update(
            {
                "code": code,
                "category": category,
                "http_status": http_status,
                "retryable": retryable,
                "rule_id": rule_id,
            }
        )
        if list(error_validator.iter_errors(probe)):
            errors.append(f"command-error schema rejected canonical policy for {code}")
        wrong_policy = copy.deepcopy(probe)
        wrong_policy["category"] = "schema" if category != "schema" else "digest"
        if not list(error_validator.iter_errors(wrong_policy)):
            errors.append(f"command-error schema accepted a wrong policy for {code}")

    control_text = (ARCHITECTURE / "09-control-commands.md").read_text(encoding="utf-8")
    catalog_rows = re.findall(
        r"^\| `([A-Z_]+)` \| `([a-z]+)` \| ([0-9]+) \| (yes|no) \| `([^`]+)` \|$",
        control_text,
        flags=re.MULTILINE,
    )
    documented_policies = {
        code: (category, int(status), retryable == "yes", rule_id)
        for code, category, status, retryable, rule_id in catalog_rows
    }
    if documented_policies != error_policies:
        errors.append("control-command error catalog differs from the schema policy")
    malformed = next(item for item in events if item["target"]["target_type"] == "unresolved")
    malformed_bytes = (EXAMPLES / "raw-command-request-malformed.txt").read_bytes()
    if (
        malformed["raw_request"]["uri"]
        != "artifact://architecture/examples/raw-command-request-malformed.txt"
        or malformed["raw_request"]["byte_length"] != len(malformed_bytes)
        or malformed["raw_request"]["sha256"]
        != hashlib.sha256(malformed_bytes).hexdigest()
    ):
        errors.append("malformed audit request does not bind its exact raw bytes")

    cancellation_event = next(
        item
        for item in events
        if item["action_type"] == "cancel_run"
        and item["result"]["status"] == "accepted"
    )
    cancellation_state = load_json(
        EXAMPLES / "run-state-cancellation-requested.example.json"
    )
    fence = next(
        item for item in cancellation_state["events"]
        if item["to"] == "cancellation_requested"
    )
    source = fence["command_source"]
    expected_effect = {
        "effect_kind": "run_state_event",
        "effect_id": fence["event_id"],
        "effect_sha256": fence["event_sha256"],
    }
    if cancellation_event["result"].get("effect_ref") != expected_effect:
        errors.append("accepted cancellation audit does not bind the exact RunState effect")
    if (
        source["command_id"] != cancellation_event["validated_command"]["command_id"]
        or source["command_sha256"]
        != cancellation_event["validated_command"]["command_sha256"]
        or source["requested_by"]["user_id"]
        != cancellation_event["requested_by"]["user_id"]
        or source["requested_by"].get("operator_id")
        != cancellation_event["requested_by"].get("operator_id")
        or source["requested_by"].get("delegation_id")
        != cancellation_event["authorization"]["delegation_check"]["grant_id"]
    ):
        errors.append("cancellation RunState source differs from its accepted command audit")

    audit_validator = Draft202012Validator(
        schemas["command-attempt-audit-event.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )

    def schema_valid(instance: dict) -> bool:
        return not list(audit_validator.iter_errors(instance))

    unresolved_precommit = copy.deepcopy(malformed)
    unresolved_precommit["check_stage"] = "pre_commit"
    if schema_valid(unresolved_precommit):
        errors.append("audit schema accepted an unresolved pre-commit target")
    unauthenticated_accept = copy.deepcopy(malformed)
    unauthenticated_accept["result"] = {"status": "accepted"}
    if schema_valid(unauthenticated_accept):
        errors.append("audit schema accepted an unauthenticated request")
    missing_effect = copy.deepcopy(cancellation_event)
    missing_effect["result"].pop("effect_ref", None)
    if schema_valid(missing_effect):
        errors.append("audit schema accepted a pre-commit success without a durable effect")
    wrong_target = copy.deepcopy(cancellation_event)
    wrong_target["action_type"] = "start_run"
    if schema_valid(wrong_target):
        errors.append("audit schema accepted a cross-family action target")
    reactivate = copy.deepcopy(
        next(item for item in events if item["action_type"] == "retire_method")
    )
    reactivate["action_type"] = "reactivate_method"
    reactivate["target"]["target_lifecycle_state"] = "active"
    if not schema_valid(reactivate):
        errors.append("audit schema rejected a valid reactivate-method branch")
    zero_byte = copy.deepcopy(malformed)
    zero_byte["raw_request"]["byte_length"] = 0
    zero_byte["raw_request"]["sha256"] = hashlib.sha256(b"").hexdigest()
    if not schema_valid(zero_byte):
        errors.append("audit schema rejected a zero-byte malformed request")
    return errors

def validate_control_and_context_semantics() -> list[str]:
    """Validate action, cancellation, delegation, and role-context relationships."""
    errors: list[str] = []
    action_files = {
        "cancel_run": "action-cancel-run.example.json",
        "reactivate_method": "action-reactivate-method.example.json",
        "retire_method": "action-retire-method.example.json",
        "start_run": "action-start-run.example.json",
        "withdraw_formal_generation": "action-withdraw-formal-generation.example.json",
    }
    actions = {
        action_type: load_json(EXAMPLES / example_name)
        for action_type, example_name in action_files.items()
    }
    if {item["action_type"] for item in actions.values()} != set(action_files):
        errors.append("typed action examples do not cover the five action branches exactly")
    descriptor_ids = [item["descriptor_id"] for item in actions.values()]
    if len(descriptor_ids) != len(set(descriptor_ids)):
        errors.append("typed action descriptor IDs must be unique")
    expected_execution_kind = {
        "start_run": "research_run",
        "cancel_run": "run_cancellation",
        "retire_method": "formal_control_transaction",
        "reactivate_method": "formal_control_transaction",
        "withdraw_formal_generation": "formal_control_transaction",
    }
    for action_type, action in actions.items():
        if action["action_type"] != action_type:
            errors.append(f"{action_files[action_type]} has the wrong action branch")
        if action["execution_kind"] != expected_execution_kind[action_type]:
            errors.append(f"{action_files[action_type]} has the wrong execution kind")
        authorization_status = action["authorization"]["status"]
        if action["enabled"]:
            if authorization_status not in {"direct_user", "active_delegation"}:
                errors.append(f"enabled action {action_type} lacks live user authority")
            if "reason_code" in action:
                errors.append(f"enabled action {action_type} must not expose an unavailable reason")
        else:
            if authorization_status in {"direct_user", "active_delegation"}:
                errors.append(f"disabled action {action_type} claims live authority")
            if not action.get("reason_code"):
                errors.append(f"disabled action {action_type} lacks a stable reason code")

    for action_type, expected_prior, expected_target in (
        ("retire_method", "active", "retired"),
        ("reactivate_method", "retired", "active"),
    ):
        action = actions[action_type]
        if (
            action["method_id"]
            != action["expected_method"]["method_identity"]["stable_id"]
            or action["expected_method"]["lifecycle_state"] != expected_prior
            or action["target_lifecycle_state"] != expected_target
        ):
            errors.append(f"{action_type} descriptor does not freeze the exact lifecycle transition")

    grant = load_json(EXAMPLES / "delegation-grant.example.json")
    revocation = load_json(EXAMPLES / "delegation-revocation.example.json")
    permission_types = [item["action_type"] for item in grant["permissions"]]
    if len(permission_types) != len(set(permission_types)) or set(permission_types) != set(
        action_files
    ):
        errors.append("delegation grant must cover each typed action branch exactly once")
    issued_at = parse_time(grant["issued_at"])
    not_before = parse_time(grant["not_before"])
    expires_at = parse_time(grant["expires_at"])
    revoked_at = parse_time(revocation["revoked_at"])
    if not issued_at <= not_before < expires_at:
        errors.append("delegation grant has an invalid authority interval")
    if revoked_at < issued_at:
        errors.append("delegation revocation predates its grant")
    for field in ("grant_id", "revocation_handle", "project_id", "user_id"):
        grant_field = "grant_id" if field == "grant_id" else field
        if revocation[field] != grant[grant_field]:
            errors.append(f"delegation revocation changed {field}")
    if revocation["revocation_sequence"] != 1:
        errors.append("first delegation revocation must use sequence one")

    cancel_action = actions["cancel_run"]
    cancel_auth = cancel_action["authorization"]
    if (
        cancel_auth.get("user_id") != grant["user_id"]
        or cancel_auth.get("operator_id") != grant["operator_id"]
        or cancel_auth.get("delegation_id") != grant["grant_id"]
        or cancel_auth.get("grant_sha256") != grant["content_sha256"]
        or cancel_auth.get("expires_at") != grant["expires_at"]
    ):
        errors.append("cancel action does not bind the exact active delegation")
    checked_at = parse_time(cancel_auth["checked_at"])
    if not not_before <= checked_at < min(expires_at, revoked_at):
        errors.append("cancel action was not checked inside the live delegation interval")

    withdraw_action = actions["withdraw_formal_generation"]
    withdraw_auth = withdraw_action["authorization"]
    if (
        withdraw_auth.get("delegation_id") != grant["grant_id"]
        or withdraw_auth.get("operator_id") != grant["operator_id"]
        or withdraw_auth.get("user_id") != grant["user_id"]
        or withdraw_auth.get("reason") != "revoked"
        or parse_time(withdraw_action["issued_at"]) < revoked_at
    ):
        errors.append("disabled withdrawal action does not project the exact revocation")

    cancellation = load_json(EXAMPLES / "run-cancellation-command.example.json")
    cancellation_state = load_json(
        EXAMPLES / "run-state-cancellation-requested.example.json"
    )
    errors.extend(
        validate_run_state_journal(cancellation_state, "cancellation run-state")
    )
    if (
        cancellation["project_id"] != cancellation_state["project_id"]
        or cancellation["run_id"] != cancellation_state["run_id"]
        or cancellation["project_id"] != cancel_action["project_id"]
        or cancellation["run_id"] != cancel_action["run_id"]
    ):
        errors.append("cancellation command, action, and run journal target different runs")
    if cancellation["expected_run_head"] != cancel_action["expected_run_head"]:
        errors.append("cancel action and command freeze different run heads")
    expected_head = cancellation["expected_run_head"]
    head_sequence = expected_head["last_event_sequence"]
    if not 1 <= head_sequence < len(cancellation_state["events"]):
        errors.append("cancellation command names a nonexistent pre-cancellation run head")
    else:
        head_event = cancellation_state["events"][head_sequence - 1]
        cancellation_event = cancellation_state["events"][head_sequence]
        if (
            head_event["sequence"] != head_sequence
            or head_event["to"] != expected_head["current_state"]
            or head_event["event_sha256"] != expected_head["journal_root_sha256"]
        ):
            errors.append("cancellation command does not freeze the exact pre-cancellation head")
        if (
            cancellation_event["from"] != expected_head["current_state"]
            or cancellation_event["to"] != "cancellation_requested"
            or cancellation_event["prior_event_sha256"]
            != expected_head["journal_root_sha256"]
            or cancellation_event["at"] != cancellation["requested_at"]
        ):
            errors.append("cancellation request event does not consume the authorized run head")
    if cancellation_state["current_state"] != "cancellation_requested":
        errors.append("cancellation example must stop at cancellation_requested")

    snapshot = load_json(EXAMPLES / "role-context-snapshot.example.json")
    prepared = snapshot["prepared_context"]
    metadata = prepared["execution_metadata"]
    for field in ("run_id", "phase", "mode", "stage_id", "execution_group_id", "role"):
        if metadata[field] != snapshot[field]:
            errors.append(f"role-context execution metadata changed {field}")
    artifact_bindings = (
        ("phase_contract", "phase_contract_artifact"),
        ("role_profile", "role_profile_artifact"),
    )
    for binding_field, metadata_field in artifact_bindings:
        if snapshot[binding_field]["artifact"] != metadata[metadata_field]:
            errors.append(f"role-context metadata changed {binding_field} artifact")
    if snapshot["model_capacity"]["tokenizer"]["artifact"] != metadata[
        "tokenizer_artifact"
    ]:
        errors.append("role-context metadata changed tokenizer artifact")
    capacity = snapshot["model_capacity"]
    expected_usable = (
        capacity["context_window_tokens"]
        - capacity["reserved_output_tokens"]
        - capacity["reserved_runtime_tokens"]
    )
    if capacity["usable_input_tokens"] != expected_usable:
        errors.append("role-context usable token capacity is arithmetically inconsistent")
    if (
        metadata["input_budget_tokens"] != capacity["usable_input_tokens"]
        or metadata["input_budget_bytes"] != capacity["input_byte_limit"]
        or prepared["supplied_input_tokens"] + prepared["remaining_input_tokens"]
        != capacity["usable_input_tokens"]
        or prepared["supplied_input_bytes"] + prepared["remaining_input_bytes"]
        != capacity["input_byte_limit"]
    ):
        errors.append("role-context prepared budgets do not reconcile with model capacity")
    if (
        metadata["project_storage_credentials_exposed"] is not False
        or metadata["formal_storage_credentials_exposed"] is not False
    ):
        errors.append("role-context execution metadata exposes formal storage credentials")

    context_items = prepared["context_items"]
    context_ids = [item["item_id"] for item in context_items]
    omitted_ids = [item["item_id"] for item in prepared["omitted_optional_items"]]
    if len(context_ids) != len(set(context_ids)) or len(omitted_ids) != len(
        set(omitted_ids)
    ):
        errors.append("role-context item IDs must be unique")
    if set(context_ids) & set(omitted_ids):
        errors.append("role-context item cannot be both supplied and omitted")
    class_rank = {
        name: rank
        for rank, name in enumerate(
            (
                "system_and_phase_contract",
                "user_command",
                "current_formal_record",
                "structured_summary_or_attention",
                "user_selected_optional_context",
                "accepted_same_run_handoff",
                "primary_artifact_reference",
                "role_profile_skill_tool_resource",
                "review_packet",
            ),
            start=1,
        )
    }
    actual_order = [
        (class_rank[item["context_class"]], item["contract_order"], item["item_id"])
        for item in context_items
    ]
    if actual_order != sorted(actual_order):
        errors.append("role-context supplied items do not follow the frozen ordering rule")
    compactions = [
        item for item in context_items if item["representation"] == "frozen_compaction"
    ]
    if bool(compactions) != (prepared["capacity_result"] == "frozen_compaction_used"):
        errors.append("role-context capacity result disagrees with frozen compaction use")
    if sum(item["supplied_tokens"] for item in context_items) > prepared[
        "supplied_input_tokens"
    ] or sum(item["supplied_bytes"] for item in context_items) > prepared[
        "supplied_input_bytes"
    ]:
        errors.append("role-context rendered totals are smaller than their supplied items")

    capabilities = {
        item["capability_id"]: item for item in prepared["on_demand_capabilities"]
    }
    if len(capabilities) != len(prepared["on_demand_capabilities"]):
        errors.append("role-context on-demand capability IDs must be unique")
    successful_reads: dict[str, int] = {}
    read_tokens = 0
    read_bytes = 0
    prior_read_at = None
    for event in snapshot["access_ledger"]["events"]:
        capability = capabilities.get(event["capability_id"])
        if capability is None:
            errors.append(f"role-context read {event['event_id']} uses an unknown capability")
            continue
        successful_reads[event["capability_id"]] = (
            successful_reads.get(event["capability_id"], 0) + 1
        )
        read_at = parse_time(event["read_at"])
        if prior_read_at is not None and read_at < prior_read_at:
            errors.append("role-context read times must be nondecreasing")
        prior_read_at = read_at
        if (
            event["artifact"] != capability["artifact"]
            or event["supplied_tokens"] > capability["maximum_returned_tokens"]
            or event["supplied_bytes"] > capability["maximum_returned_bytes"]
            or not parse_time(prepared["prepared_at"])
            <= read_at
            <= parse_time(capability["expires_at"])
        ):
            errors.append(f"role-context read {event['event_id']} violates its capability")
        read_tokens += event["supplied_tokens"]
        read_bytes += event["supplied_bytes"]
    for capability_id, count in successful_reads.items():
        if count > capabilities[capability_id]["maximum_successful_reads"]:
            errors.append(f"role-context capability {capability_id} exceeds its read limit")
    if (
        prepared["supplied_input_tokens"] + read_tokens
        > capacity["usable_input_tokens"]
        or prepared["supplied_input_bytes"] + read_bytes > capacity["input_byte_limit"]
    ):
        errors.append("role-context successful reads exceed the frozen capacity")
    if (
        snapshot["closed_at"] != snapshot["access_ledger"]["sealed_at"]
        or parse_time(snapshot["closed_at"]) < parse_time(prepared["prepared_at"])
        or any(
            parse_time(event["read_at"]) > parse_time(snapshot["closed_at"])
            for event in snapshot["access_ledger"]["events"]
        )
    ):
        errors.append("role-context closure does not seal the complete access ledger")

    if snapshot["role"] == "outside_reviewer":
        if (
            len(context_items) != 1
            or context_items[0]["context_class"] != "review_packet"
            or context_items[0]["contract_input_id"] != "p5.review_packet"
            or snapshot["preference_memory_binding"]["status"] != "disabled"
            or prepared["on_demand_capabilities"]
            or snapshot["access_ledger"]["events"]
            or snapshot["access_ledger"]["head_sha256"] != "0" * 64
        ):
            errors.append("outside-reviewer context is not closed to the review packet")
    return errors

def choice_value_error(choice: dict, value) -> str | None:
    value_kind = choice["value_kind"]
    if value_kind == "enum_string":
        if not isinstance(value, str) or value not in choice["allowed_values"]:
            return f"must be one of {choice['allowed_values']}"
    elif value_kind == "text":
        if not isinstance(value, str) or not value.strip():
            return "must be nonempty text"
    elif value_kind == "method_identity":
        if not isinstance(value, dict) or set(value) != {
            "stable_id",
            "version",
            "definition_sha256",
        }:
            return "must be an exact method identity"
        if (
            not isinstance(value["stable_id"], str)
            or not value["stable_id"]
            or not isinstance(value["version"], int)
            or isinstance(value["version"], bool)
            or value["version"] < 1
            or re.fullmatch(r"[0-9a-f]{64}", value["definition_sha256"]) is None
        ):
            return "contains an invalid method identity"
    elif value_kind == "artifact_pointer_list":
        if not isinstance(value, list):
            return "must be a list of artifact pointers"
        for item in value:
            if not isinstance(item, dict) or not {
                "artifact_id",
                "uri",
                "sha256",
            }.issubset(item):
                return "contains an invalid artifact pointer"
    else:
        return f"uses unknown value kind {value_kind}"
    return None


def validate_command_against_contract(
    command: dict, contract: dict, contract_sha256: str
) -> list[str]:
    """Resolve one immutable user command against one exact phase contract."""
    errors: list[str] = []
    if command.get("phase") != contract["phase_id"]:
        errors.append("command phase does not match the selected phase contract")
    if command.get("phase_contract_version") != contract["contract_version"]:
        errors.append("command phase-contract version does not match")
    if command.get("phase_contract_sha256") != contract_sha256:
        errors.append("command phase-contract digest does not match")

    matching_modes = [
        mode for mode in contract["run_modes"] if mode["mode_id"] == command.get("mode")
    ]
    if len(matching_modes) != 1:
        errors.append("command mode does not resolve exactly once in the phase contract")
        return errors

    mode = matching_modes[0]
    definitions = {
        choice["choice_id"]: choice for choice in contract["user_choices"]
    }
    supplied = command.get("choice_values")
    if not isinstance(supplied, dict):
        errors.append("command choice_values must be an object")
        return errors

    supplied_ids = set(supplied)
    required_ids = set(mode["required_choice_ids"])
    optional_ids = set(mode["optional_choice_ids"])
    missing = required_ids - supplied_ids
    unknown = supplied_ids - required_ids - optional_ids
    if missing:
        errors.append(f"command omits required choices {sorted(missing)}")
    if unknown:
        errors.append(f"command supplies choices outside the selected mode {sorted(unknown)}")

    for choice_id in sorted(supplied_ids & set(definitions)):
        problem = choice_value_error(definitions[choice_id], supplied[choice_id])
        if problem is not None:
            errors.append(f"command choice {choice_id} {problem}")

    history_choice_id = contract["optional_context_policy"]["history_choice_id"]
    selected_history = supplied.get(history_choice_id, [])
    if command.get("context_policy") == "current_only" and selected_history:
        errors.append("current-only command may not select historical artifacts")
    if command.get("context_policy") == "current_plus_selected_history" and not selected_history:
        errors.append("history-enabled command must identify selected historical artifacts")

    method_choice_id = mode.get("method_choice_id")
    if mode["requires_method"] and method_choice_id not in supplied_ids:
        errors.append("method-bound mode lacks its exact selected method")
    if not mode["requires_method"] and method_choice_id is not None:
        errors.append("method-free mode declares a method choice")
    return errors

STATE_FIELDS = (
    "publication_state",
    "record_position",
    "alignment",
    "research_attention",
    "evidence_eligibility",
)


def authority_subject_key(subject: dict) -> tuple | None:
    if subject["kind"] == "record_generation":
        return (
            "record_generation",
            subject["subject_id"],
            subject["generation_id"],
        )
    if subject["kind"] == "evidence_item":
        return ("evidence_item", subject["subject_id"])
    return None


def validate_subject_prior_state_bindings(
    events: list[dict], existing_subjects: list[dict] | None = None
) -> list[str]:
    """Reject a no-prior event when its authority subject already has state."""
    errors: list[str] = []
    seen = {
        key
        for subject in existing_subjects or []
        if (key := authority_subject_key(subject)) is not None
    }
    for event in sorted(events, key=lambda item: item["event_sequence"]):
        key = authority_subject_key(event["subject"])
        if key is None:
            continue
        if key in seen and "prior_state_sha256" not in event:
            errors.append(
                f"authority event {event['event_id']} revisits subject {key} "
                "without prior_state_sha256"
            )
        seen.add(key)
    return errors


def fold_authority_events(events: list[dict]) -> tuple[dict, list[str]]:
    """Fold ordered authority events with whole-field, later-event precedence."""
    errors = validate_subject_prior_state_bindings(events)
    folded: dict[tuple, dict] = {}
    for event in sorted(events, key=lambda item: item["event_sequence"]):
        key = authority_subject_key(event["subject"])
        if key is None:
            continue
        projection = folded.get(key)
        if projection is None:
            values = {}
            if event["subject"]["kind"] == "record_generation":
                values["evidence_eligibility"] = {
                    "status": "not_applicable",
                    "method_match": "not_applicable",
                    "reasons": [],
                }
            else:
                values["record_position"] = "none"
            projection = {
                "project_id": event["project_id"],
                "subject": event["subject"],
                "values": values,
                "source_event_ids": [],
            }
            folded[key] = projection
        else:
            if projection["project_id"] != event["project_id"]:
                errors.append(f"authority subject {key} changes project during replay")
            if projection["subject"] != event["subject"]:
                errors.append(f"authority subject {key} changes identity during replay")

        for field in STATE_FIELDS:
            if field in event["changes"]:
                projection["values"][field] = event["changes"][field]
        projection["source_event_ids"].append(event["event_id"])

    for key, projection in folded.items():
        missing = set(STATE_FIELDS) - set(projection["values"])
        if missing:
            errors.append(
                f"authority subject {key} lacks final replay fields {sorted(missing)}"
            )
    return folded, errors


def validate_folded_record_states(
    states: list[dict],
    events: list[dict],
    checkpoint_sequence: int,
    checkpoint_root: str,
    checkpoint_time: str,
    label: str,
) -> list[str]:
    errors: list[str] = []
    folded, fold_errors = fold_authority_events(events)
    errors.extend(f"{label}: {problem}" for problem in fold_errors)
    state_keys = [authority_subject_key(state["subject"]) for state in states]
    if len(state_keys) != len(set(state_keys)):
        errors.append(f"{label}: record-state subjects must be unique")

    for state in states:
        key = authority_subject_key(state["subject"])
        projection = folded.get(key)
        if projection is None:
            errors.append(f"{label}: state {state['state_projection_id']} has no replay events")
            continue
        expected_fields = {
            "project_id": projection["project_id"],
            "subject": projection["subject"],
            **projection["values"],
            "source_event_ids": projection["source_event_ids"],
            "last_event_sequence": checkpoint_sequence,
            "event_root_sha256": checkpoint_root,
            "computed_at": checkpoint_time,
        }
        for field, expected in expected_fields.items():
            if state.get(field) != expected:
                errors.append(
                    f"{label}: state {state['state_projection_id']} has {field} "
                    f"{state.get(field)!r}, expected {expected!r}"
                )
        expected_digest = canonical_sha256(state, {"content_sha256"})
        if state["content_sha256"] != expected_digest:
            errors.append(
                f"{label}: state {state['state_projection_id']} has an invalid content digest"
            )
    return errors

def build_schema_registry():
    errors: list[str] = []
    schemas = {}
    registry = Registry()
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        try:
            schema = load_json(path)
            Draft202012Validator.check_schema(schema)
            schemas[path.name] = schema
            resource = Resource.from_contents(schema)
            registry = registry.with_resource(schema["$id"], resource)
            registry = registry.with_resource(path.name, resource)
        except Exception as exc:
            errors.append(f"{path.relative_to(REPOSITORY)}: {exc}")
    return schemas, registry, errors


def validate_examples(schemas, registry) -> list[str]:
    errors: list[str] = []
    checker = FormatChecker()
    actual_valid = {path.name for path in EXAMPLES.glob("*.example.json")}
    registered_valid = set(VALID_EXAMPLES)
    if actual_valid != registered_valid:
        errors.append(
            "valid example registry mismatch: "
            f"unregistered={sorted(actual_valid - registered_valid)}, "
            f"missing={sorted(registered_valid - actual_valid)}"
        )
    actual_invalid = {
        path.name for path in (EXAMPLES / "invalid").glob("*.invalid.json")
    }
    registered_invalid = set(INVALID_EXAMPLES)
    if actual_invalid != registered_invalid:
        errors.append(
            "negative fixture registry mismatch: "
            f"unregistered={sorted(actual_invalid - registered_invalid)}, "
            f"missing={sorted(registered_invalid - actual_invalid)}"
        )
    schema_negative_fixtures = {
        name
        for name, schema_name in INVALID_EXAMPLES.items()
        if not schema_name.startswith("semantic:")
    }
    if set(INVALID_EXPECTED_SCHEMA_ERRORS) != schema_negative_fixtures:
        errors.append(
            "negative diagnostic registry mismatch: "
            f"unregistered={sorted(schema_negative_fixtures - set(INVALID_EXPECTED_SCHEMA_ERRORS))}, "
            f"unexpected={sorted(set(INVALID_EXPECTED_SCHEMA_ERRORS) - schema_negative_fixtures)}"
        )
    for example_name, schema_name in VALID_EXAMPLES.items():
        path = EXAMPLES / example_name
        if not path.exists():
            errors.append(f"missing valid example: {path.relative_to(REPOSITORY)}")
            continue
        instance = load_json(path)
        validator = Draft202012Validator(
            schemas[schema_name], registry=registry, format_checker=checker
        )
        found = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
        for error in found:
            errors.append(
                f"{path.relative_to(REPOSITORY)} at {pointer(error)}: {error.message}"
            )

    control_examples = {
        "method-lifecycle-command.example.json": load_json(
            EXAMPLES / "method-lifecycle-command.example.json"
        ),
        "formal-generation-withdrawal-command.example.json": load_json(
            EXAMPLES / "formal-generation-withdrawal-command.example.json"
        ),
    }
    control_union_validator = Draft202012Validator(
        schemas["control-command.schema.json"],
        registry=registry,
        format_checker=checker,
    )
    for example_name, command in control_examples.items():
        for error in control_union_validator.iter_errors(command):
            errors.append(
                f"{EXAMPLES / example_name} fails the ControlCommand union at "
                f"{pointer(error)}: {error.message}"
            )

    receipt_validator = Draft202012Validator(
        schemas["publication-receipt.schema.json"],
        registry=registry,
        format_checker=checker,
    )
    receipt_template = load_json(EXAMPLES / "publication-receipt.example.json")
    method_command = control_examples["method-lifecycle-command.example.json"]
    method_receipt = json.loads(json.dumps(receipt_template))
    method_receipt["publication_id"] = "publication.method.retire.001"
    method_receipt["transaction_id"] = "transaction.method.retire.001"
    method_receipt["source"] = {
        "kind": "method_lifecycle_command",
        "command_id": method_command["command_id"],
        "command_sha256": method_command["content_sha256"],
    }
    method_receipt["prior_current_index_generation_id"] = method_command[
        "expected_control_head"
    ]["current_index_generation_id"]
    method_receipt["prior_current_index_sha256"] = method_command["expected_control_head"][
        "current_index_sha256"
    ]
    method_receipt["committed_event_range"] = {
        "first_sequence": method_command["expected_control_head"]["last_event_sequence"] + 1,
        "last_sequence": method_command["expected_control_head"]["last_event_sequence"] + 4,
        "event_ids": [
            "event.method.new.published.probe",
            "event.method.prior.superseded.probe",
            "event.catalog.new.published.probe",
            "event.catalog.prior.superseded.probe",
        ],
        "prior_event_root_sha256": method_command["expected_control_head"][
            "event_root_sha256"
        ],
        "new_event_root_sha256": "1" * 64,
    }
    method_receipt["record_changes"] = [
        {
            "record_id": method_command["expected_method"]["record_id"],
            "record_type": "method_record",
            "prior_generation_id": method_command["expected_method"]["generation_id"],
            "new_generation_id": "generation.method.lifecycle.probe",
            "new_position": "current",
            "change_kind": "replace",
            "authority_event_ids": [
                "event.method.new.published.probe",
                "event.method.prior.superseded.probe",
            ],
        },
        {
            "record_id": method_command["expected_catalog"]["record_id"],
            "record_type": "method_catalog",
            "prior_generation_id": method_command["expected_catalog"]["generation_id"],
            "new_generation_id": "generation.method_catalog.lifecycle.probe",
            "new_position": "current",
            "change_kind": "replace",
            "authority_event_ids": [
                "event.catalog.new.published.probe",
                "event.catalog.prior.superseded.probe",
            ],
        },
    ]
    method_receipt["cumulative_object_changes"] = []
    method_receipt["state_changes"] = []
    method_receipt["alignment_impacts"] = []
    method_receipt["attention_impacts"] = []
    method_receipt["content_sha256"] = canonical_sha256(
        method_receipt, {"content_sha256"}
    )

    method_audit = load_json(
        EXAMPLES / "command-attempt-audit-method-accepted.example.json"
    )
    if method_audit["result"].get("effect_ref") != {
        "effect_kind": "publication_receipt",
        "effect_id": method_receipt["publication_id"],
        "effect_sha256": method_receipt["content_sha256"],
    }:
        errors.append("accepted method audit does not bind its exact publication receipt")
    withdrawal_command = control_examples[
        "formal-generation-withdrawal-command.example.json"
    ]
    withdrawal_receipt = json.loads(json.dumps(receipt_template))
    withdrawal_receipt["publication_id"] = "publication.generation.withdraw.001"
    withdrawal_receipt["transaction_id"] = "transaction.generation.withdraw.001"
    withdrawal_receipt["source"] = {
        "kind": "generation_withdrawal_command",
        "command_id": withdrawal_command["command_id"],
        "command_sha256": withdrawal_command["content_sha256"],
    }
    withdrawal_receipt["prior_current_index_generation_id"] = withdrawal_command[
        "expected_control_head"
    ]["current_index_generation_id"]
    withdrawal_receipt["prior_current_index_sha256"] = withdrawal_command[
        "expected_control_head"
    ]["current_index_sha256"]
    withdrawal_receipt["committed_event_range"] = {
        "first_sequence": withdrawal_command["expected_control_head"]["last_event_sequence"]
        + 1,
        "last_sequence": withdrawal_command["expected_control_head"]["last_event_sequence"]
        + 1,
        "event_ids": ["event.generation.withdrawn.probe"],
        "prior_event_root_sha256": withdrawal_command["expected_control_head"][
            "event_root_sha256"
        ],
        "new_event_root_sha256": "2" * 64,
    }
    withdrawal_receipt["record_changes"] = [
        {
            "record_id": withdrawal_command["target"]["record_id"],
            "record_type": withdrawal_command["target"]["record_type"],
            "subject_generation_id": withdrawal_command["target"]["generation_id"],
            "new_position": "none",
            "change_kind": "withdraw",
            "authority_event_ids": ["event.generation.withdrawn.probe"],
        }
    ]
    withdrawal_receipt["cumulative_object_changes"] = []
    withdrawal_receipt["state_changes"] = []
    withdrawal_receipt["content_sha256"] = canonical_sha256(
        withdrawal_receipt, {"content_sha256"}
    )

    for label, probe in (
        ("method lifecycle receipt probe", method_receipt),
        ("generation withdrawal receipt probe", withdrawal_receipt),
    ):
        found = list(receipt_validator.iter_errors(probe))
        for error in found:
            errors.append(f"{label} at {pointer(error)}: {error.message}")
    prior_method = load_json(EXAMPLES / "method.example.json")
    lifecycle_method = json.loads(json.dumps(prior_method))
    lifecycle_method["generation_id"] = "generation.method.lifecycle.probe"
    lifecycle_method["lifecycle_state"] = method_command["target_lifecycle_state"]
    lifecycle_method["lineage"] = {
        "predecessor": prior_method["identity"],
        "predecessor_generation_id": prior_method["generation_id"],
        "change_class": "lifecycle",
        "change_summary": "Lifecycle-only retirement with no scientific change.",
        "change_source": {
            "kind": "method_lifecycle_command",
            "command_id": method_command["command_id"],
            "command_sha256": method_command["content_sha256"],
        },
    }
    lifecycle_method["content_sha256"] = "3" * 64
    lifecycle_method_validator = Draft202012Validator(
        schemas["method.schema.json"], registry=registry, format_checker=checker
    )
    for error in lifecycle_method_validator.iter_errors(lifecycle_method):
        errors.append(f"lifecycle method probe at {pointer(error)}: {error.message}")
    preserved_scientific_fields = {
        "identity",
        "title",
        "scientific_question",
        "rationale",
        "summary",
        "mathematical_definition",
        "assumptions",
        "literature_provenance",
        "limitations",
    }
    if any(
        lifecycle_method[field] != prior_method[field]
        for field in preserved_scientific_fields
    ):
        errors.append("lifecycle method probe changed scientific or mathematical content")
    if (
        lifecycle_method["lineage"]["predecessor"] != lifecycle_method["identity"]
        or lifecycle_method["lineage"]["predecessor_generation_id"]
        != prior_method["generation_id"]
    ):
        errors.append("lifecycle method probe lost exact identity or generation lineage")
    invalid_dir = EXAMPLES / "invalid"
    for example_name, schema_name in INVALID_EXAMPLES.items():
        path = invalid_dir / example_name
        if not path.exists():
            errors.append(f"missing invalid example: {path.relative_to(REPOSITORY)}")
            continue
        instance = load_json(path)
        if schema_name == "semantic:authority_prior_state":
            event_names = instance.get("event_example_names", [])
            existing_subjects = instance.get("existing_subjects", [])
            if (
                set(instance) != {"fixture_id", "existing_subjects", "event_example_names"}
                or not isinstance(event_names, list)
                or not event_names
                or len(event_names) != len(set(event_names))
                or not isinstance(existing_subjects, list)
                or not existing_subjects
            ):
                errors.append(
                    f"{path.relative_to(REPOSITORY)} has an invalid semantic-fixture shape"
                )
                continue
            semantic_events = []
            authority_validator = Draft202012Validator(
                schemas["authority-event.schema.json"],
                registry=registry,
                format_checker=checker,
            )
            for event_name in event_names:
                if VALID_EXAMPLES.get(event_name) != "authority-event.schema.json":
                    errors.append(
                        f"{path.relative_to(REPOSITORY)} cites unknown authority event {event_name}"
                    )
                    continue
                event = load_json(EXAMPLES / event_name)
                if list(authority_validator.iter_errors(event)):
                    errors.append(
                        f"{path.relative_to(REPOSITORY)} cites a schema-invalid authority event {event_name}"
                    )
                    continue
                semantic_events.append(event)
            if semantic_events and not validate_subject_prior_state_bindings(
                semantic_events, existing_subjects
            ):
                errors.append(
                    f"{path.relative_to(REPOSITORY)} unexpectedly passed checkpoint-seeded prior-state validation"
                )
            continue
        validator = Draft202012Validator(
            schemas[schema_name], registry=registry, format_checker=checker
        )
        found = sorted(
            validator.iter_errors(instance),
            key=lambda item: (list(item.absolute_path), item.validator),
        )
        observed = [(pointer(error), error.validator) for error in found]
        expected = INVALID_EXPECTED_SCHEMA_ERRORS[example_name]
        if observed != expected:
            errors.append(
                f"{path.relative_to(REPOSITORY)} diagnostics {observed}, expected {expected}"
            )
    return errors


def validate_contracts(schemas, registry) -> tuple[list[str], dict]:
    errors: list[str] = []
    registry_path = CONTRACTS / "phases.json"
    complete = load_json(registry_path)
    validator = Draft202012Validator(
        schemas["phase-contract.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    for error in sorted(
        validator.iter_errors(complete), key=lambda item: list(item.absolute_path)
    ):
        errors.append(
            f"{registry_path.relative_to(REPOSITORY)} at {pointer(error)}: {error.message}"
        )

    expected_ids = ["P1", "P2", "P3", "P4", "P5"]
    fragments = [
        load_json(CONTRACTS / "phases" / f"{phase_id}.json")
        for phase_id in expected_ids
    ]
    if complete.get("contracts") != fragments:
        errors.append("contracts/phases.json does not exactly match its five phase files")
    fragment_validator = Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": (
                "https://model-forge.local/architecture/schemas/"
                "phase-contract.schema.json#/$defs/phaseContract"
            ),
        },
        registry=registry,
        format_checker=FormatChecker(),
    )
    for phase_id, fragment in zip(expected_ids, fragments):
        fragment_path = CONTRACTS / "phases" / f"{phase_id}.json"
        for error in sorted(
            fragment_validator.iter_errors(fragment),
            key=lambda item: list(item.absolute_path),
        ):
            errors.append(
                f"{fragment_path.relative_to(REPOSITORY)} at {pointer(error)}: "
                f"{error.message}"
            )

    contracts = {item["phase_id"]: item for item in complete.get("contracts", [])}
    if list(contracts) != expected_ids:
        errors.append(f"phase registry order must be {expected_ids}, found {list(contracts)}")

    for phase_id, expected in EXPECTED_PHASE_ROLES.items():
        actual = [
            (stage["execution"], stage["roles"])
            for stage in contracts.get(phase_id, {}).get("role_stages", [])
        ]
        if actual != expected:
            errors.append(f"{phase_id} role order is {actual}, expected {expected}")

    p5 = contracts.get("P5", {})
    review_stage = next(
        (item for item in p5.get("role_stages", []) if item["stage_id"] == "p5.parallel_reviews"),
        None,
    )
    revision_stage = next(
        (item for item in p5.get("role_stages", []) if item["stage_id"] == "p5.revision_lead"),
        None,
    )
    if not review_stage or review_stage["execution"] != "parallel" or review_stage["roles"] != [
        "theorist",
        "data_analyst",
        "outside_reviewer",
    ]:
        errors.append("P5 review stage must run theorist, data analyst, and outside reviewer in parallel")
    if not review_stage or "never" not in review_stage.get("isolation_rule", "").lower():
        errors.append("P5 review stage must state the outside-reviewer isolation rule")
    if not revision_stage or revision_stage["sequence"] != 2 or revision_stage["roles"] != [
        "research_lead"
    ]:
        errors.append("P5 lead revision must follow the fixed parallel reviews")

    p5_review_target = next(
        (item for item in p5.get("required_inputs", []) if item["input_id"] == "p5.review_target_manuscript"),
        None,
    )
    if not p5_review_target or p5_review_target["method_match"] != "same_stable_method":
        errors.append("P5 review target must belong to the selected stable method lineage")
    if (
        p5_review_target
        and (
            p5_review_target.get("presence") != "required_in_modes"
            or p5_review_target.get("required_in_modes") != ["p5.review_revision"]
        )
    ):
        errors.append("P5 review target must be required in review-revision mode only")
    p5_current_manuscript = next(
        (item for item in p5.get("required_inputs", []) if item["input_id"] == "p5.current_manuscript"),
        None,
    )
    if not p5_current_manuscript or p5_current_manuscript.get("presence") != "required_on_rerun":
        errors.append("P5 current manuscript must be situation-aware (required_on_rerun)")

    role_reads = {
        item["role"]: item["input_ids"]
        for item in (review_stage or {}).get("role_reads", [])
    }
    if (review_stage or {}).get("reads"):
        errors.append("P5 parallel review stage may not grant one shared read set to all roles")
    if set(role_reads) != {"theorist", "data_analyst", "outside_reviewer"}:
        errors.append("P5 review stage must declare one explicit read set for each reviewer role")
    expected_review_reads = {
        "theorist": [
            "p5.review_packet",
            "p5.review_target_manuscript",
            "p5.method",
            "p5.theory",
            "p5.implementation_record",
            "p5.literature_synthesis",
        ],
        "data_analyst": [
            "p5.review_packet",
            "p5.review_target_manuscript",
            "p5.method",
            "p5.theory",
            "p5.empirical_index",
            "p5.empirical",
            "p5.implementation_record",
            "p5.literature_synthesis",
        ],
        "outside_reviewer": ["p5.review_packet"],
    }
    if role_reads != expected_review_reads:
        errors.append("P5 reviewer roles must use their exact frozen role-specific read sets")
    review_packet = next(
        (item for item in p5.get("prepared_contexts", []) if item["context_id"] == "p5.review_packet"),
        None,
    )
    if not review_packet or review_packet["applicable_modes"] != ["p5.review_revision"]:
        errors.append("P5 must construct one immutable review packet during review-revision preparation")
    elif set(review_packet["source_input_ids"]) != {"p5.review_target_manuscript", "p5.literature_library"}:
        errors.append("P5 review packet must derive from the manuscript and reviewer-visible literature")
    elif review_packet["source_choice_ids"] != ["p5.instructions"]:
        errors.append("P5 review packet must freeze the reviewer-facing user and venue instructions")
    forbidden_reviewer_inputs = {
        "p5.theory_audit",
        "p5.empirical_audit",
        "p5.outside_review",
        "p5.revision_account",
        "p5.review_issues",
    }
    if forbidden_reviewer_inputs & set(role_reads.get("outside_reviewer", [])):
        errors.append("P5 outside reviewer read set contains internal or later role output")

    expected_effects = {
        ("P1", "new_current_record"): ("preserve", None, "record_if_identified"),
        ("P2", "mathematical_method_change"): ("set", "outdated", "create_required"),
        ("P3", "theory_basis_change"): ("preserve", None, "record_if_identified"),
        ("P3", "new_current_record"): ("set", "outdated", "create_required"),
        ("P4", "empirical_basis_change"): ("preserve", None, "record_if_identified"),
        ("P4", "new_current_record"): ("set", "outdated", "create_required"),
        ("P5", "manuscript_change"): ("preserve", None, "record_if_identified"),
    }
    seen_effects: set[tuple[str, str]] = set()

    for phase_id, contract in contracts.items():
        choices = {item["choice_id"] for item in contract["user_choices"]}
        contract_modes = {item["mode_id"] for item in contract["run_modes"]}
        declared_outputs = {item["output_id"] for item in contract["run_local_outputs"]}
        written_outputs = {
            output_id for stage in contract["role_stages"] for output_id in stage["writes"]
        }
        writer_modes: dict[str, set[str]] = {}
        for stage in contract["role_stages"]:
            for output_id in stage["writes"]:
                writer_modes.setdefault(output_id, set()).update(stage["applicable_modes"])

        declared_inputs = {item["input_id"] for item in contract["required_inputs"]}
        prepared_contexts = contract["prepared_contexts"]
        prepared_ids = [item["context_id"] for item in prepared_contexts]
        if len(prepared_ids) != len(set(prepared_ids)):
            errors.append(f"{phase_id} prepared-context IDs must be unique")
        for context in prepared_contexts:
            context_modes = set(context["applicable_modes"])
            if not context_modes.issubset(contract_modes):
                errors.append(
                    f"{phase_id} prepared context {context['context_id']} uses unknown modes: "
                    f"{sorted(context_modes - contract_modes)}"
                )
            unknown_sources = set(context["source_input_ids"]) - declared_inputs
            if unknown_sources:
                errors.append(
                    f"{phase_id} prepared context {context['context_id']} uses unknown inputs: "
                    f"{sorted(unknown_sources)}"
                )
            unknown_choices = set(context["source_choice_ids"]) - choices
            if unknown_choices:
                errors.append(
                    f"{phase_id} prepared context {context['context_id']} uses unknown choices: "
                    f"{sorted(unknown_choices)}"
                )

        stage_ids = [item["stage_id"] for item in contract["role_stages"]]
        if len(stage_ids) != len(set(stage_ids)):
            errors.append(f"{phase_id} role-stage IDs must be unique")
        for mode_id in sorted(contract_modes):
            mode_sequences = sorted(
                item["sequence"] for item in contract["role_stages"]
                if mode_id in item["applicable_modes"]
            )
            expected_sequences = list(range(1, len(mode_sequences) + 1))
            if mode_sequences != expected_sequences:
                errors.append(
                    f"{phase_id} mode {mode_id} role-stage sequences must be "
                    f"contiguous from one, found {mode_sequences}"
                )
        for mode_id in contract_modes:
            available_ids = set(declared_inputs)
            available_ids.update(
                item["context_id"]
                for item in prepared_contexts
                if mode_id in item["applicable_modes"]
            )
            selected_stages = sorted(
                (
                    stage
                    for stage in contract["role_stages"]
                    if mode_id in stage["applicable_modes"]
                ),
                key=lambda stage: stage["sequence"],
            )
            for stage in selected_stages:
                role_reads = stage.get("role_reads", [])
                if role_reads:
                    if stage["reads"]:
                        errors.append(
                            f"{phase_id} stage {stage['stage_id']} mixes shared reads with role-specific reads"
                        )
                    declared_roles = [item["role"] for item in role_reads]
                    if len(declared_roles) != len(set(declared_roles)):
                        errors.append(
                            f"{phase_id} stage {stage['stage_id']} repeats a role-specific read set"
                        )
                    if set(declared_roles) != set(stage["roles"]):
                        errors.append(
                            f"{phase_id} stage {stage['stage_id']} must define reads for every stage role"
                        )
                    reads_by_role = {
                        item["role"]: set(item["input_ids"])
                        for item in role_reads
                    }
                else:
                    reads_by_role = {
                        role: set(stage["reads"])
                        for role in stage["roles"]
                    }
                for role, read_ids in reads_by_role.items():
                    unknown_reads = read_ids - available_ids
                    if unknown_reads:
                        errors.append(
                            f"{phase_id} stage {stage['stage_id']} role {role} reads undeclared or unavailable IDs: "
                            f"{sorted(unknown_reads)}"
                        )
                available_ids.update(stage["writes"])

        for item in contract["required_inputs"]:
            required_modes = set(item.get("required_in_modes", []))
            if item["presence"] == "required_in_modes":
                if not required_modes or not required_modes.issubset(contract_modes):
                    errors.append(
                        f"{phase_id} input {item['input_id']} has invalid required modes: {sorted(required_modes)}"
                    )
            elif required_modes:
                errors.append(
                    f"{phase_id} input {item['input_id']} declares modes without required_in_modes presence"
                )

        for item in contract["run_local_outputs"]:
            required_modes = set(item.get("required_in_modes", []))
            if item["requirement"] == "always":
                if item["required"] is not True or required_modes:
                    errors.append(
                        f"{phase_id} output {item['output_id']} has inconsistent always requirement"
                    )
            else:
                if item["required"] is not False or not required_modes:
                    errors.append(
                        f"{phase_id} output {item['output_id']} has inconsistent mode requirement"
                    )
                if not required_modes.issubset(contract_modes):
                    errors.append(
                        f"{phase_id} output {item['output_id']} uses unknown modes: {sorted(required_modes)}"
                    )
                if not required_modes.issubset(writer_modes.get(item["output_id"], set())):
                    errors.append(
                        f"{phase_id} output {item['output_id']} is not written in every required mode"
                    )
        collection_output_kinds = {
            "statement_set",
            "evidence_set",
            "method_set",
            "review_issue_set",
            "attention_item_set",
        }
        outputs_by_id = {item["output_id"]: item for item in contract["run_local_outputs"]}
        for output in contract["run_local_outputs"]:
            if (
                output["output_kind"] in collection_output_kinds
                and output.get("schema_application") != "each_item"
            ):
                errors.append(
                    f"{phase_id} collection output {output['output_id']} must validate each item"
                )

        bindings = contract["publication_bindings"]
        binding_ids = [item["binding_id"] for item in bindings]
        if len(binding_ids) != len(set(binding_ids)):
            errors.append(f"{phase_id} publication-binding IDs must be unique")
        bound_canonical_types: set[str] = set()
        bound_cumulative_types: set[str] = set()
        for binding in bindings:
            binding_modes = set(binding["applicable_modes"])
            if not binding_modes.issubset(contract_modes):
                errors.append(
                    f"{phase_id} binding {binding['binding_id']} uses unknown modes: "
                    f"{sorted(binding_modes - contract_modes)}"
                )
            unknown_outputs = set(binding["output_ids"]) - declared_outputs
            if unknown_outputs:
                errors.append(
                    f"{phase_id} binding {binding['binding_id']} uses unknown outputs: "
                    f"{sorted(unknown_outputs)}"
                )
            for output_id in set(binding["output_ids"]) & declared_outputs:
                if not binding_modes.issubset(writer_modes.get(output_id, set())):
                    errors.append(
                        f"{phase_id} binding {binding['binding_id']} can publish {output_id} "
                        "in a mode where it is not produced"
                    )
            unknown_inputs = set(binding.get("source_input_ids", [])) - declared_inputs
            if unknown_inputs:
                errors.append(
                    f"{phase_id} binding {binding['binding_id']} uses unknown formal inputs: "
                    f"{sorted(unknown_inputs)}"
                )
            if binding["publisher_transform"] == "deterministic_index" and not binding.get(
                "source_input_ids"
            ):
                errors.append(
                    f"{phase_id} deterministic index {binding['binding_id']} must bind its prior formal input"
                )
            components = binding.get("components", [])
            if components:
                names = [item["component_name"] for item in components]
                component_outputs = [item["output_id"] for item in components]
                if len(names) != len(set(names)):
                    errors.append(
                        f"{phase_id} bundle {binding['binding_id']} repeats a component name"
                    )
                if set(component_outputs) != set(binding["output_ids"]):
                    errors.append(
                        f"{phase_id} bundle {binding['binding_id']} components must name every and only bound output"
                    )
            target = binding["target"]
            if target["kind"] in {"current_slot", "keyed_current_slots"}:
                bound_canonical_types.add(target["record_type"])
            elif target["kind"] == "cumulative_collection":
                bound_cumulative_types.add(target["object_type"])
            if binding["may_create_scientific_content"] is not False:
                errors.append(
                    f"{phase_id} publisher {binding['binding_id']} may not create scientific content"
                )

        promoted_canonical = set(contract["promotion"]["canonical_record_types"])
        promoted_cumulative = set(contract["promotion"]["cumulative_object_types"])
        if bound_canonical_types != promoted_canonical:
            errors.append(
                f"{phase_id} canonical publication coverage {sorted(bound_canonical_types)} "
                f"does not match promotion {sorted(promoted_canonical)}"
            )
        if bound_cumulative_types != promoted_cumulative:
            errors.append(
                f"{phase_id} cumulative publication coverage {sorted(bound_cumulative_types)} "
                f"does not match promotion {sorted(promoted_cumulative)}"
            )
        if promoted_canonical & promoted_cumulative:
            errors.append(f"{phase_id} canonical and cumulative publication types must be disjoint")

        attention_outputs = [
            item
            for item in contract["run_local_outputs"]
            if item["output_kind"] == "attention_item_set"
        ]
        if len(attention_outputs) != 1:
            errors.append(f"{phase_id} must declare one final lead attention collection")
        else:
            attention_output = attention_outputs[0]
            if (
                attention_output["producer"] != "research_lead"
                or attention_output.get("schema_application") != "each_item"
                or not attention_output["schema_uri"].endswith("attention-item.schema.json")
            ):
                errors.append(
                    f"{phase_id} attention collection must be a lead-produced itemwise attention artifact"
                )
            attention_bindings = [
                item
                for item in bindings
                if item["operation"] == "append"
                and item["target"].get("object_type") == "attention_item"
                and attention_output["output_id"] in item["output_ids"]
            ]
            if len(attention_bindings) != 1:
                errors.append(f"{phase_id} must append its lead attention collection exactly once")

        expected_reducer_sources = {
            ("P1", "p1.rebuild_literature_library"): {"p1.current_library"},
            ("P2", "p2.rebuild_method_catalog"): {"p2.current_catalog"},
            ("P5", "p5.replace_review_issue_ledger"): {"p5.review_issue_ledger"},
        }
        for (source_phase, binding_id), expected_sources in expected_reducer_sources.items():
            if phase_id != source_phase:
                continue
            reducer = next((item for item in bindings if item["binding_id"] == binding_id), None)
            if reducer is None or set(reducer.get("source_input_ids", [])) != expected_sources:
                errors.append(
                    f"{phase_id} deterministic reducer {binding_id} must bind {sorted(expected_sources)}"
                )

        if phase_id == "P1" and not any(
            item["operation"] == "append"
            and item["target"].get("object_type") == "literature_source"
            for item in bindings
        ):
            errors.append("P1 must append immutable literature sources")
        if phase_id == "P2" and not any(
            item["operation"] == "upsert_each"
            and item["target"].get("record_type") == "method_record"
            for item in bindings
        ):
            errors.append("P2 must upsert each lead-consolidated method record")
        if phase_id == "P4" and not any(
            item["operation"] == "append"
            and item["target"].get("object_type") == "evidence_item"
            for item in bindings
        ):
            errors.append("P4 must append immutable evidence items")
        if phase_id == "P5":
            review_append = [
                item
                for item in bindings
                if item["operation"] == "append"
                and item["target"].get("object_type") == "review_issue"
            ]
            if len(review_append) != 1:
                errors.append("P5 must append lead-consolidated immutable review issues")
            if not any(item["operation"] == "bundle" for item in bindings):
                errors.append("P5 must publish manuscript generations as named deterministic bundles")
        missing_outputs = written_outputs - declared_outputs
        if missing_outputs:
            errors.append(
                f"{phase_id} stage writes lack output declarations: {sorted(missing_outputs)}"
            )
        choice_definitions = {
            item["choice_id"]: item for item in contract["user_choices"]
        }
        choice_values = {
            choice_id: set(item["allowed_values"])
            for choice_id, item in choice_definitions.items()
        }
        required_by_mode: list[set[str]] = []
        for mode in contract["run_modes"]:
            required_choices = set(mode["required_choice_ids"])
            optional_choices = set(mode["optional_choice_ids"])
            required_by_mode.append(required_choices)
            unknown = (required_choices | optional_choices) - choices
            if unknown:
                errors.append(f"{phase_id} mode {mode['mode_id']} uses unknown choices: {sorted(unknown)}")
            overlap = required_choices & optional_choices
            if overlap:
                errors.append(f"{phase_id} mode {mode['mode_id']} marks choices both required and optional: {sorted(overlap)}")

            method_choice_id = mode.get("method_choice_id")
            if mode["requires_method"]:
                if method_choice_id not in required_choices:
                    errors.append(
                        f"{phase_id} mode {mode['mode_id']} must require its method_choice_id"
                    )
                elif choice_definitions.get(method_choice_id, {}).get("value_kind") != "method_identity":
                    errors.append(
                        f"{phase_id} mode {mode['mode_id']} method_choice_id must identify a method_identity choice"
                    )
            elif method_choice_id is not None:
                errors.append(
                    f"{phase_id} mode {mode['mode_id']} may not name a method_choice_id"
                )

        globally_required = {
            item["choice_id"] for item in contract["user_choices"] if item["required"]
        }
        required_in_every_mode = set.intersection(*required_by_mode)
        if globally_required != required_in_every_mode:
            errors.append(
                f"{phase_id} global required choices {sorted(globally_required)} do not match every-mode requirements {sorted(required_in_every_mode)}"
            )

        history_choice_id = contract["optional_context_policy"]["history_choice_id"]
        history_choice = choice_definitions.get(history_choice_id)
        if history_choice is None or history_choice.get("value_kind") != "artifact_pointer_list":
            errors.append(f"{phase_id} history_choice_id must identify an artifact_pointer_list choice")
        for mode in contract["run_modes"]:
            if history_choice_id not in mode["optional_choice_ids"]:
                errors.append(
                    f"{phase_id} mode {mode['mode_id']} must expose history only as an optional choice"
                )

        unknown_ui = set(contract["ui_projection"]["user_action_choice_ids"]) - choices
        if unknown_ui:
            errors.append(f"{phase_id} UI uses unknown choices: {sorted(unknown_ui)}")
        validator_ids = {item["validator_id"] for item in contract["validation_rules"]}
        unknown_validators = set(contract["promotion"]["blocking_validator_ids"]) - validator_ids
        if unknown_validators:
            errors.append(
                f"{phase_id} promotion uses unknown validators: {sorted(unknown_validators)}"
            )
        if contract["optional_context_policy"]["default"] != "current_only":
            errors.append(f"{phase_id} must use current_only context by default")
        if not contract["optional_context_policy"]["history_selection_user_controlled"]:
            errors.append(f"{phase_id} history selection must remain user-controlled")
        for effect in contract["downstream_effects"]:
            if effect["automatic_run"] is not False:
                errors.append(f"{phase_id} downstream effect may not launch a run")
            key = (phase_id, effect["trigger"])
            seen_effects.add(key)
            expected = expected_effects.get(key)
            actual = (
                effect["alignment_effect"]["action"],
                effect["alignment_effect"].get("state"),
                effect["attention_effect"]["action"],
            )
            if expected is None:
                errors.append(f"{phase_id} has an undeclared downstream effect: {effect['trigger']}")
            elif actual != expected:
                errors.append(f"{phase_id} downstream effect {effect['trigger']} is {actual}, expected {expected}")

        for value in [contract["prose_contract"]] + [
            output["schema_uri"] for output in contract["run_local_outputs"]
        ]:
            target = REPOSITORY / value
            if not target.is_file():
                errors.append(f"{phase_id} references missing project file: {value}")

        scenario_prefixes = {path.stem.split("-")[0].lower() for path in (ARCHITECTURE / "scenarios").glob("S*.md")}
        for scenario_id in contract["acceptance_scenarios"]:
            if scenario_id.split(".")[0] not in scenario_prefixes:
                errors.append(f"{phase_id} references unknown scenario: {scenario_id}")

    if seen_effects != set(expected_effects):
        errors.append(
            f"downstream effect registry mismatch: missing {sorted(set(expected_effects) - seen_effects)}, extra {sorted(seen_effects - set(expected_effects))}"
        )

    p3_prereq_phases = {item.get("phase") for item in contracts["P3"]["prerequisites"]}
    p4_prereq_phases = {item.get("phase") for item in contracts["P4"]["prerequisites"]}
    if "P4" in p3_prereq_phases:
        errors.append("P3 may not require P4")
    if "P3" in p4_prereq_phases:
        errors.append("P4 may not require P3")
    if not {"P1", "P2"}.issubset(p3_prereq_phases):
        errors.append("P3 must require current P1 and P2")
    if not {"P1", "P2"}.issubset(p4_prereq_phases):
        errors.append("P4 must require current P1 and P2")

    p5_exact = {
        (item.get("phase"), item["kind"])
        for item in contracts["P5"]["prerequisites"]
    }
    if ("P3", "exact_alignment") not in p5_exact or ("P4", "exact_alignment") not in p5_exact:
        errors.append("P5 must require exact current P3 and P4 alignment")

    mode_ids = {
        phase_id: {item["mode_id"] for item in contract["run_modes"]}
        for phase_id, contract in contracts.items()
    }
    if mode_ids.get("P2") != {
        "p2.full_catalog",
        "p2.focused_method",
        "p2.researcher_proposal",
    }:
        errors.append(
            "P2 must expose full-catalog, focused-method, and researcher-proposal modes"
        )
    if mode_ids.get("P4") != {"p4.preliminary", "p4.comprehensive"}:
        errors.append("P4 must expose preliminary and comprehensive modes on every run")
    if mode_ids.get("P5") != {"p5.assembly", "p5.review_revision"}:
        errors.append("P5 must expose assembly and review-revision modes")

    return errors, complete


def validate_traceability_registry(schemas, registry, complete: dict) -> list[str]:
    """Cross-check the machine traceability graph against every narrative source."""
    errors: list[str] = []
    path = CONTRACTS / "traceability.json"
    traceability = load_json(path)
    validator = Draft202012Validator(
        schemas["traceability-registry.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    for error in sorted(
        validator.iter_errors(traceability),
        key=lambda item: list(item.absolute_path),
    ):
        errors.append(
            f"{path.relative_to(REPOSITORY)} at {pointer(error)}: {error.message}"
        )

    principles_text = (ARCHITECTURE / "00-system-principles.md").read_text(
        encoding="utf-8"
    )
    test_text = (ARCHITECTURE / "05-validation-strategy.md").read_text(
        encoding="utf-8"
    )
    requirement_text = (ARCHITECTURE / "07-contract-traceability.md").read_text(
        encoding="utf-8"
    )
    roadmap_text = (ARCHITECTURE / "06-implementation-roadmap.md").read_text(
        encoding="utf-8"
    )
    principle_ids = re.findall(r"^### (INV-[0-9]{3}):", principles_text, re.MULTILINE)
    test_pairs = re.findall(
        r"^\| (IT-[0-9]{3}) \| (INV-[0-9]{3}) \|", test_text, re.MULTILINE
    )
    requirement_ids = re.findall(
        r"^\| (MF-[0-9]{2}) \|", requirement_text, re.MULTILINE
    )
    milestone_numbers = [
        int(item)
        for item in re.findall(
            r"^## Milestone ([0-9]+):", roadmap_text, re.MULTILINE
        )
    ]
    expected_invariants = [f"INV-{number:03d}" for number in range(1, 23)]
    expected_tests = [f"IT-{number:03d}" for number in range(1, 23)]
    expected_requirements = {f"MF-{number:02d}" for number in range(1, 76)}
    if principle_ids != expected_invariants:
        errors.append(
            f"principle invariant IDs are {principle_ids}, expected {expected_invariants}"
        )
    test_ids = [test_id for test_id, _ in test_pairs]
    if test_ids != expected_tests:
        errors.append(f"integration test IDs are {test_ids}, expected {expected_tests}")
    if len(requirement_ids) != len(set(requirement_ids)) or set(
        requirement_ids
    ) != expected_requirements:
        errors.append("narrative requirement IDs must cover MF-01 through MF-75 exactly once")
    if milestone_numbers != list(range(10)):
        errors.append("roadmap milestones must cover M0 through M9 exactly once and in order")

    coverage_items = traceability["invariant_coverage"]
    coverage_ids = [item["invariant_id"] for item in coverage_items]
    if coverage_ids != expected_invariants:
        errors.append("traceability invariant coverage must follow INV-001 through INV-022")
    coverage_by_id = {item["invariant_id"]: item for item in coverage_items}
    narrative_tests_by_invariant: dict[str, list[str]] = {}
    for test_id, invariant_id in test_pairs:
        narrative_tests_by_invariant.setdefault(invariant_id, []).append(test_id)
    for invariant_id, item in coverage_by_id.items():
        if item["test_ids"] != narrative_tests_by_invariant.get(invariant_id, []):
            errors.append(
                f"traceability {invariant_id} test IDs differ from the validation table"
            )
        unknown_requirements = set(item["requirement_ids"]) - expected_requirements
        if unknown_requirements:
            errors.append(
                f"traceability {invariant_id} uses unknown requirements {sorted(unknown_requirements)}"
            )

    registered_scenarios = traceability["scenarios"]
    scenario_ids = [item["scenario_id"] for item in registered_scenarios]
    scenario_codes = [item["scenario_code"] for item in registered_scenarios]
    expected_codes = [f"S{number:02d}" for number in range(1, 31)]
    if scenario_codes != expected_codes or len(scenario_ids) != len(set(scenario_ids)):
        errors.append("traceability scenarios must register S01 through S30 exactly once and in order")
    scenario_by_id = {item["scenario_id"]: item for item in registered_scenarios}
    registered_documents = {item["document"] for item in registered_scenarios}
    actual_documents = {
        (Path("architecture") / "scenarios" / item.name).as_posix()
        for item in (ARCHITECTURE / "scenarios").glob("S*.md")
    }
    if registered_documents != actual_documents:
        errors.append(
            "traceability scenario documents differ from the scenario directory: "
            f"unregistered={sorted(actual_documents - registered_documents)}, "
            f"missing={sorted(registered_documents - actual_documents)}"
        )

    milestone_ids = {f"M{number}" for number in milestone_numbers}
    for scenario in registered_scenarios:
        scenario_id = scenario["scenario_id"]
        document = (REPOSITORY / scenario["document"]).resolve()
        try:
            document.relative_to((ARCHITECTURE / "scenarios").resolve())
        except ValueError:
            errors.append(f"traceability scenario {scenario_id} points outside scenarios")
            continue
        if not document.exists():
            errors.append(f"traceability scenario {scenario_id} has no document")
            continue
        first_line = document.read_text(encoding="utf-8").splitlines()[0]
        if not first_line.startswith(f"# {scenario['scenario_code']}:"):
            errors.append(
                f"traceability scenario {scenario_id} document has the wrong heading"
            )
        unknown_invariants = set(scenario["invariant_ids"]) - set(coverage_by_id)
        if unknown_invariants:
            errors.append(
                f"traceability scenario {scenario_id} uses unknown invariants {sorted(unknown_invariants)}"
            )
            continue
        expected_scenario_tests = [
            test_id
            for invariant_id in scenario["invariant_ids"]
            for test_id in coverage_by_id[invariant_id]["test_ids"]
        ]
        if scenario["test_ids"] != expected_scenario_tests:
            errors.append(
                f"traceability scenario {scenario_id} test IDs do not match its invariants"
            )
        linked_requirements = {
            requirement_id
            for invariant_id in scenario["invariant_ids"]
            for requirement_id in coverage_by_id[invariant_id]["requirement_ids"]
        }
        if not set(scenario["requirement_ids"]).issubset(linked_requirements):
            errors.append(
                f"traceability scenario {scenario_id} cites a requirement outside its invariants"
            )
        unknown_milestones = set(scenario["milestones"]) - milestone_ids
        if unknown_milestones:
            errors.append(
                f"traceability scenario {scenario_id} uses unknown milestones {sorted(unknown_milestones)}"
            )
        for invariant_id in scenario["invariant_ids"]:
            if scenario_id not in coverage_by_id[invariant_id]["scenario_ids"]:
                errors.append(
                    f"traceability scenario {scenario_id} is missing from {invariant_id} back-links"
                )

    for invariant_id, coverage in coverage_by_id.items():
        expected_back_links = [
            scenario["scenario_id"]
            for scenario in registered_scenarios
            if invariant_id in scenario["invariant_ids"]
        ]
        if coverage["scenario_ids"] != expected_back_links:
            errors.append(
                f"traceability {invariant_id} scenario links are not bidirectional"
            )

    contracts_by_phase = {
        contract["phase_id"]: contract for contract in complete["contracts"]
    }
    for phase_id, contract in contracts_by_phase.items():
        expected_phase_scenarios = [
            scenario["scenario_id"]
            for scenario in registered_scenarios
            if phase_id in scenario["phase_contracts"]
        ]
        if contract["acceptance_scenarios"] != expected_phase_scenarios:
            errors.append(
                f"{phase_id} acceptance scenarios differ from machine traceability: "
                f"{contract['acceptance_scenarios']} versus {expected_phase_scenarios}"
            )
    for scenario_id, scenario in scenario_by_id.items():
        contract_membership = [
            phase_id
            for phase_id, contract in contracts_by_phase.items()
            if scenario_id in contract["acceptance_scenarios"]
        ]
        if scenario["phase_contracts"] != contract_membership:
            errors.append(
                f"traceability scenario {scenario_id} phase links are not bidirectional"
            )
    return errors

def validate_package_indexes(schemas: dict[str, dict]) -> list[str]:
    """Reject stale human-facing package counts and incomplete inventories."""
    errors: list[str] = []
    schema_count = len(schemas)
    valid_count = len(VALID_EXAMPLES)
    invalid_count = len(INVALID_EXAMPLES)

    advertised_counts = [
        (
            ARCHITECTURE / "README.md",
            re.compile(
                r"`schemas/` contains (\d+) machine-validatable schemas, while "
                r"`examples/` contains (\d+) valid examples and (\d+) focused "
                r"invalid fixtures\."
            ),
            (schema_count, valid_count, invalid_count),
            "architecture package counts",
        ),
        (
            SCHEMAS / "README.md",
            re.compile(r"contains (\d+) valid examples covering every"),
            (valid_count,),
            "schema-guide example count",
        ),
        (
            EXAMPLES / "README.md",
            re.compile(r"This directory contains (\d+) valid examples\."),
            (valid_count,),
            "example-guide count",
        ),
        (
            ARCHITECTURE / "tools" / "README.md",
            re.compile(
                r"- (\d+) valid JSON Schema Draft 2020-12 definitions;\s*"
                r"- (\d+) complete valid examples and (\d+) rejected negative fixtures;"
            ),
            (schema_count, valid_count, invalid_count),
            "validator-guide counts",
        ),
    ]
    for path, pattern, expected, label in advertised_counts:
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match is None:
            errors.append(f"{label} are missing or not machine-readable")
            continue
        actual = tuple(int(value) for value in match.groups())
        if actual != expected:
            errors.append(f"{label} are stale: {actual} versus {expected}")

    schema_index_text = (SCHEMAS / "README.md").read_text(encoding="utf-8")
    indexed_schema_names = re.findall(
        r"^\| `([^`]+\.schema\.json)` \|", schema_index_text, flags=re.MULTILINE
    )
    if len(indexed_schema_names) != len(set(indexed_schema_names)):
        errors.append("schemas/README.md contains duplicate schema inventory entries")
    indexed_schema_set = set(indexed_schema_names)
    schema_set = set(schemas)
    for name in sorted(schema_set - indexed_schema_set):
        errors.append(f"schemas/README.md does not inventory {name}")
    for name in sorted(indexed_schema_set - schema_set):
        errors.append(f"schemas/README.md inventories unknown schema {name}")

    decisions = ARCHITECTURE / "decisions"
    decision_files = {
        path.name
        for path in decisions.glob("ADR-*.md")
        if path.name != "ADR-000-template.md"
    }
    decision_index_text = (decisions / "README.md").read_text(encoding="utf-8")
    indexed_decisions = re.findall(
        r"^- \[ADR-\d{3}:[^\]]+\]\((ADR-\d{3}[^)]+\.md)\)$",
        decision_index_text,
        flags=re.MULTILINE,
    )
    if len(indexed_decisions) != len(set(indexed_decisions)):
        errors.append("decisions/README.md contains duplicate accepted-decision entries")
    indexed_decision_set = set(indexed_decisions)
    for name in sorted(decision_files - indexed_decision_set):
        errors.append(f"decisions/README.md does not index accepted decision {name}")
    for name in sorted(indexed_decision_set - decision_files):
        errors.append(f"decisions/README.md indexes missing decision {name}")

    return errors

def validate_text_and_links() -> list[str]:
    errors: list[str] = []
    forbidden = {chr(0x2013): "en dash", chr(0x2014): "em dash", chr(0xFFFD): "replacement character"}
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    checked_suffixes = {".md", ".json", ".py"}

    for path in sorted(ARCHITECTURE.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in checked_suffixes:
            continue
        text = path.read_text(encoding="utf-8")
        for character, label in forbidden.items():
            if character in text:
                line = text[: text.index(character)].count("\n") + 1
                errors.append(f"{path.relative_to(REPOSITORY)}:{line} contains {label}")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.endswith(" ") or line.endswith("\t"):
                errors.append(f"{path.relative_to(REPOSITORY)}:{number} has trailing whitespace")

        if path.suffix.lower() != ".md":
            continue
        for match in link_pattern.finditer(text):
            raw = match.group(1).strip().strip("<>")
            if raw.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = unquote(raw.split("#", 1)[0])
            if not local:
                continue
            target = (path.parent / local).resolve()
            try:
                target.relative_to(REPOSITORY.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(REPOSITORY)} links outside repository: {raw}")
                continue
            if not target.exists():
                line = text[: match.start()].count("\n") + 1
                errors.append(f"{path.relative_to(REPOSITORY)}:{line} has broken link: {raw}")
    return errors


def publication_binding_diagnostics(
    contract: dict,
    mode: str,
    publication_plan: list[dict],
    outputs_by_contract_id: dict[str, set[str]],
    bound_inputs: dict[str, str],
    expected_targets_by_id: dict[str, dict],
) -> list[str]:
    """Return stable pre-commit diagnostics for one resolved publication plan."""
    diagnostics: list[str] = []
    all_bindings = {
        item["binding_id"]: item for item in contract["publication_bindings"]
    }
    applicable_bindings = {
        binding_id: item
        for binding_id, item in all_bindings.items()
        if mode in item["applicable_modes"]
    }
    plans_by_id: dict[str, list[dict]] = {}
    for item in publication_plan:
        plans_by_id.setdefault(item["publication_binding_id"], []).append(item)
    for binding_id, plans in sorted(plans_by_id.items()):
        if len(plans) > 1:
            diagnostics.append(f"PUB_BINDING_DUPLICATE:{binding_id}")
    for binding_id in sorted(set(applicable_bindings) - set(plans_by_id)):
        diagnostics.append(f"PUB_BINDING_MISSING:{binding_id}")
    for binding_id in sorted(set(plans_by_id) - set(applicable_bindings)):
        code = (
            "PUB_BINDING_MODE_INAPPLICABLE"
            if binding_id in all_bindings
            else "PUB_BINDING_UNKNOWN"
        )
        diagnostics.append(f"{code}:{binding_id}")

    for binding_id in sorted(set(plans_by_id) & set(applicable_bindings)):
        binding = applicable_bindings[binding_id]
        plan = plans_by_id[binding_id][0]
        for field in (
            "operation",
            "prior_target_policy",
            "publisher_transform",
            "may_create_scientific_content",
        ):
            if plan[field] != binding[field]:
                diagnostics.append(f"PUB_BINDING_FIELD_MISMATCH:{binding_id}:{field}")

        component_name_by_output = {
            item["output_id"]: item["component_name"]
            for item in binding.get("components", [])
        }
        expected_output_mappings = {
            (
                contract_output_id,
                output_id,
                component_name_by_output.get(contract_output_id),
            )
            for contract_output_id in binding["output_ids"]
            for output_id in outputs_by_contract_id.get(contract_output_id, set())
        }
        actual_output_mappings = {
            (
                item["contract_output_id"],
                item["output_id"],
                item.get("component_name"),
            )
            for item in plan["source_output_mappings"]
        }
        if actual_output_mappings != expected_output_mappings:
            diagnostics.append(f"PUB_BINDING_OUTPUT_MAPPING_MISMATCH:{binding_id}")

        source_items = plan.get("source_input_mappings", [])
        source_mappings = {
            item["contract_input_id"]: item for item in source_items
        }
        if len(source_mappings) != len(source_items):
            diagnostics.append(f"PUB_BINDING_SOURCE_INPUT_DUPLICATE:{binding_id}")
        if set(source_mappings) != set(binding.get("source_input_ids", [])):
            diagnostics.append(f"PUB_BINDING_SOURCE_INPUT_SET_MISMATCH:{binding_id}")
        for contract_input_id, source_mapping in source_mappings.items():
            frozen_input_id = bound_inputs.get(contract_input_id)
            if frozen_input_id is None:
                if source_mapping["resolution"] != "absent":
                    diagnostics.append(
                        f"PUB_BINDING_SOURCE_RESOLUTION_MISMATCH:{binding_id}:{contract_input_id}"
                    )
            elif (
                source_mapping["resolution"] != "frozen_input"
                or source_mapping.get("input_id") != frozen_input_id
            ):
                diagnostics.append(
                    f"PUB_BINDING_SOURCE_RESOLUTION_MISMATCH:{binding_id}:{contract_input_id}"
                )

        contract_target = binding["target"]
        plan_target = plan["target"]
        if contract_target["kind"] == "current_slot":
            expected_target = expected_targets_by_id.get(
                plan_target.get("expected_target_id")
            )
            if (
                plan_target.get("kind") != "current_slot"
                or expected_target is None
                or expected_target["slot_id"] != contract_target["slot_id"]
                or expected_target["record_type"] != contract_target["record_type"]
            ):
                diagnostics.append(f"PUB_BINDING_CURRENT_TARGET_MISMATCH:{binding_id}")
        else:
            comparable_keys = set(contract_target)
            if any(
                plan_target.get(key) != contract_target[key]
                for key in comparable_keys
            ):
                diagnostics.append(f"PUB_BINDING_COLLECTION_TARGET_MISMATCH:{binding_id}")
    return diagnostics

def validate_global_invariants(schemas) -> list[str]:
    errors: list[str] = []
    run_states = schemas["common-definitions.schema.json"]["$defs"]["runLifecycleState"]["enum"]
    if run_states != EXPECTED_RUN_STATES:
        errors.append(f"canonical run states are {run_states}, expected {EXPECTED_RUN_STATES}")
    command_network = schemas["run-command.schema.json"]["properties"][
        "resource_constraints"
    ]["properties"]["network_policy"]["enum"]
    manifest_authorized_network = schemas["run-manifest.schema.json"]["properties"][
        "user_request"
    ]["properties"]["authorized_resource_constraints"]["properties"][
        "network_policy"
    ]["enum"]
    manifest_effective_network = schemas["run-manifest.schema.json"]["properties"][
        "resource_policy"
    ]["properties"]["network_policy"]["enum"]
    for label, values in (
        ("run command", command_network),
        ("authorized manifest request", manifest_authorized_network),
        ("effective manifest policy", manifest_effective_network),
    ):
        if values != EXPECTED_NETWORK_POLICIES:
            errors.append(
                f"{label} network policies are {values}, expected {EXPECTED_NETWORK_POLICIES}"
            )

    schema_text = "\n".join(
        path.read_text(encoding="utf-8") for path in SCHEMAS.glob("*.schema.json")
    )
    if "authority_state" in schema_text:
        errors.append("schemas must not reintroduce a generic authority_state field")

    def schema_strings(value, location=()):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from schema_strings(item, location + (key,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from schema_strings(item, location + (str(index),))
        elif isinstance(value, str):
            yield location, value

    for schema_name, schema in schemas.items():
        for location, value in schema_strings(schema):
            lowered = value.lower()
            if (
                location[-1] in {"description", "$comment"}
                and "canonical" in lowered
                and "json" in lowered
                and "rfc 8785" not in lowered
            ):
                errors.append(
                    f"{schema_name} at {'/'.join(location)} uses ambiguous canonical JSON wording"
                )

    method = load_json(EXAMPLES / "method.example.json")
    version = method["identity"]["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append("method example version must be a positive integer")
    if method["content_sha256"] != canonical_sha256(method, {"content_sha256"}):
        errors.append("method example content digest does not match its immutable generation")
    lineage = method["lineage"]
    if lineage["change_class"] == "lifecycle":
        if (
            lineage.get("change_source", {}).get("kind") != "method_lifecycle_command"
            or "predecessor_generation_id" not in lineage
            or lineage.get("predecessor") != method["identity"]
        ):
            errors.append(
                "lifecycle-only method replacement must name its command, predecessor generation, "
                "and unchanged mathematical identity"
            )
    elif lineage.get("change_source", {}).get("kind") != "research_run":
        errors.append("scientific method generations must identify their producing research run")

    method_control = load_json(EXAMPLES / "method-lifecycle-command.example.json")
    withdrawal_control = load_json(
        EXAMPLES / "formal-generation-withdrawal-command.example.json"
    )
    for name, control in (
        ("method-lifecycle-command.example.json", method_control),
        ("formal-generation-withdrawal-command.example.json", withdrawal_control),
    ):
        if control["content_sha256"] != canonical_sha256(control, {"content_sha256"}):
            errors.append(f"{name} content digest does not match its authorized payload")
        if control["requested_by"]["operating_actor_type"] not in {
            "user",
            "authorized_remote_operator",
        }:
            errors.append(f"{name} lacks explicit user authority")
        if any(field in control for field in ("run_id", "phase", "mode", "manifest_sha256")):
            errors.append(f"{name} must not create or identify a research run")
        if set(control["expected_control_head"]) != {
            "current_index_generation_id",
            "current_index_sha256",
            "last_event_sequence",
            "event_root_sha256",
        }:
            errors.append(f"{name} must freeze the complete optimistic-concurrency head")
    if method_control["method_id"] != method_control["expected_method"]["method_identity"][
        "stable_id"
    ]:
        errors.append("method lifecycle command targets a different stable method identity")
    if method_control["target_lifecycle_state"] == method_control["expected_method"][
        "lifecycle_state"
    ]:
        errors.append("method lifecycle command must request a real active-retired transition")
    if withdrawal_control["expected_target_state"]["publication_state"] != "formal":
        errors.append("generation withdrawal command must freeze a currently formal target")


    command = load_json(EXAMPLES / "run-command.example.json")
    manifest = load_json(EXAMPLES / "run-manifest.example.json")
    complete = load_json(CONTRACTS / "phases.json")
    contracts_by_phase = {
        contract["phase_id"]: contract for contract in complete["contracts"]
    }
    modes_by_phase = {
        contract["phase_id"]: {mode["mode_id"] for mode in contract["run_modes"]}
        for contract in complete["contracts"]
    }

    if command["requested_by"]["operating_actor_type"] != "user":
        errors.append("run-command example must show explicit user authorization")
    expected_command_sha = canonical_sha256(command, {"content_sha256"})
    if command["content_sha256"] != expected_command_sha:
        errors.append("run-command content digest does not match its canonical authorized payload")
    if manifest["command_sha256"] != command["content_sha256"]:
        errors.append("run-manifest must bind the exact authorized run-command digest")

    exact_command_bindings = {
        "project_id": (command["project_id"], manifest["project_id"]),
        "command_id": (command["command_id"], manifest["command_id"]),
        "idempotency_key": (
            command["idempotency_key"],
            manifest["command_idempotency_key"],
        ),
        "phase": (command["phase"], manifest["phase"]),
        "phase_contract_version": (
            command["phase_contract_version"],
            manifest["phase_contract_version"],
        ),
        "phase_contract_sha256": (
            command["phase_contract_sha256"],
            manifest["phase_contract_sha256"],
        ),
        "mode": (command["mode"], manifest["mode"]),
        "requested_by": (command["requested_by"], manifest["initiated_by"]),
        "choice_values": (
            command["choice_values"],
            manifest["user_request"]["choice_values"],
        ),
        "context_policy": (
            command["context_policy"],
            manifest["user_request"]["context_policy"],
        ),
        "resource_constraints": (
            command.get("resource_constraints"),
            manifest["user_request"].get("authorized_resource_constraints"),
        ),
    }
    for label, (authorized, sealed) in exact_command_bindings.items():
        if sealed != authorized:
            errors.append(f"run-manifest changed authorized command field {label}")

    command_constraints = command.get("resource_constraints", {})
    manifest_policy = manifest["resource_policy"]
    if (
        "wall_time_limit_seconds" in command_constraints
        and manifest_policy["wall_time_limit_seconds"]
        > command_constraints["wall_time_limit_seconds"]
    ):
        errors.append("run-manifest broadens the authorized wall-time limit")
    network_rank = {
        value: rank for rank, value in enumerate(EXPECTED_NETWORK_POLICIES)
    }
    authorized_network = command_constraints.get("network_policy", "none")
    if manifest_policy["network_policy"] not in network_rank:
        errors.append("run-manifest uses an unknown network policy")
    elif authorized_network not in network_rank:
        errors.append("run-command uses an unknown network policy")
    elif network_rank[manifest_policy["network_policy"]] > network_rank[authorized_network]:
        errors.append("run-manifest broadens the authorized network policy")
    if parse_time(manifest["prepared_at"]) < parse_time(command["requested_at"]):
        errors.append("run-manifest cannot be prepared before its authorizing command")

    if command["mode"] not in modes_by_phase.get(command["phase"], set()):
        errors.append("run-command example mode must resolve in its executable phase contract")
    if manifest["mode"] not in modes_by_phase.get(manifest["phase"], set()):
        errors.append("run-manifest example mode must resolve in its executable phase contract")
    if (command["phase"], command["mode"]) != (manifest["phase"], manifest["mode"]):
        errors.append("run-command and run-manifest examples must use the same phase and mode")

    command_contract = contracts_by_phase[command["phase"]]
    command_contract_path = CONTRACTS / "phases" / f"{command['phase']}.json"
    command_contract_sha = canonical_sha256(load_json(command_contract_path))
    for problem in validate_command_against_contract(
        command, command_contract, command_contract_sha
    ):
        errors.append(f"run-command example: {problem}")

    history_choice_id = command_contract["optional_context_policy"]["history_choice_id"]
    manifest_history = manifest["user_request"]["choice_values"].get(
        history_choice_id, []
    )
    if manifest["user_request"]["context_policy"] == "current_only" and manifest_history:
        errors.append("current-only run-manifest example may not contain selected history")

    def probe_value(choice: dict):
        if choice["value_kind"] == "enum_string":
            return choice["allowed_values"][0]
        if choice["value_kind"] == "text":
            return "Probe instruction."
        if choice["value_kind"] == "method_identity":
            return {
                "stable_id": "method.probe",
                "version": 1,
                "definition_sha256": "1" * 64,
            }
        if choice["value_kind"] == "artifact_pointer_list":
            return []
        raise ValueError(f"unsupported probe choice kind {choice['value_kind']}")

    validated_mode_count = 0
    probe_by_mode: dict[tuple[str, str], tuple[dict, dict, str]] = {}
    for contract in complete["contracts"]:
        contract_path = CONTRACTS / "phases" / f"{contract['phase_id']}.json"
        contract_sha = canonical_sha256(load_json(contract_path))
        definitions = {
            choice["choice_id"]: choice for choice in contract["user_choices"]
        }
        for mode in contract["run_modes"]:
            choice_values = {
                choice_id: probe_value(definitions[choice_id])
                for choice_id in mode["required_choice_ids"]
            }
            probe = {
                "phase": contract["phase_id"],
                "phase_contract_version": contract["contract_version"],
                "phase_contract_sha256": contract_sha,
                "mode": mode["mode_id"],
                "choice_values": choice_values,
                "context_policy": "current_only",
            }
            problems = validate_command_against_contract(probe, contract, contract_sha)
            if problems:
                errors.append(
                    f"{contract['phase_id']} mode {mode['mode_id']} cannot be represented by RunCommand: {problems}"
                )
            validated_mode_count += 1
            probe_by_mode[(contract["phase_id"], mode["mode_id"])] = (
                probe,
                contract,
                contract_sha,
            )
    if validated_mode_count != 10:
        errors.append(f"RunCommand coverage found {validated_mode_count} modes, expected 10")

    p1_probe, p1_contract, p1_sha = probe_by_mode[("P1", "p1.literature_update")]
    for scope_value in ("broad_update", "focused_update"):
        scope_probe = json.loads(json.dumps(p1_probe))
        scope_probe["choice_values"]["p1.scope"] = scope_value
        if validate_command_against_contract(scope_probe, p1_contract, p1_sha):
            errors.append(f"P1 scope {scope_value} cannot be represented by RunCommand")

    p4_probe, p4_contract, p4_sha = probe_by_mode[("P4", "p4.preliminary")]
    history_probe = json.loads(json.dumps(p4_probe))
    history_choice_id = p4_contract["optional_context_policy"]["history_choice_id"]
    history_probe["context_policy"] = "current_plus_selected_history"
    history_probe["choice_values"][history_choice_id] = [
        {
            "artifact_id": "artifact.history.probe",
            "uri": "artifact://history/probe",
            "sha256": "2" * 64,
        }
    ]
    if validate_command_against_contract(history_probe, p4_contract, p4_sha):
        errors.append(
            "RunCommand rejected a schema-valid history pointer without optional media_type"
        )

    negative_probes = []
    missing = json.loads(json.dumps(p4_probe))
    missing["choice_values"].pop("p4.instructions")
    negative_probes.append(("missing required choice", missing, p4_contract, p4_sha))
    unknown = json.loads(json.dumps(p4_probe))
    unknown["choice_values"]["p4.unknown"] = "unsupported"
    negative_probes.append(("unknown choice", unknown, p4_contract, p4_sha))
    wrong_type = json.loads(json.dumps(p4_probe))
    wrong_type["choice_values"]["p4.instructions"] = {}
    negative_probes.append(("wrong choice type", wrong_type, p4_contract, p4_sha))
    stale_contract = json.loads(json.dumps(p4_probe))
    stale_contract["phase_contract_sha256"] = "f" * 64
    negative_probes.append(("contract digest mismatch", stale_contract, p4_contract, p4_sha))
    p2_probe, p2_contract, p2_sha = probe_by_mode[("P2", "p2.focused_method")]
    missing_method = json.loads(json.dumps(p2_probe))
    missing_method["choice_values"].pop("p2.selected_method")
    negative_probes.append(
        ("focused P2 without method", missing_method, p2_contract, p2_sha)
    )
    for label, probe, contract, contract_sha in negative_probes:
        if not validate_command_against_contract(probe, contract, contract_sha):
            errors.append(f"RunCommand semantic probe failed to reject {label}")
    profile = load_json(EXAMPLES / "role-profile.example.json")
    profile_modes = set(profile["applicable_modes"])
    allowed_profile_modes = set().union(
        *(modes_by_phase.get(phase, set()) for phase in profile["applicable_phases"])
    )
    if not profile_modes.issubset(allowed_profile_modes):
        errors.append("role-profile example contains a mode absent from its executable phase contracts")

    contracts_by_phase = {
        contract["phase_id"]: contract for contract in complete["contracts"]
    }
    manifest_contract = contracts_by_phase[manifest["phase"]]
    split_contract_path = CONTRACTS / "phases" / f"{manifest['phase']}.json"
    split_contract = load_json(split_contract_path)
    split_contract_sha = canonical_sha256(split_contract)
    if manifest["phase_contract_sha256"] != split_contract_sha:
        errors.append("run-manifest phase-contract digest does not match the split executable contract")
    expected_manifest_sha = canonical_sha256(manifest, {"manifest_sha256"})
    if manifest["manifest_sha256"] != expected_manifest_sha:
        errors.append("run-manifest digest does not match its canonical sealed payload")
    canonical_publication_types = set(manifest_contract["promotion"]["canonical_record_types"])
    target_types = {item["record_type"] for item in manifest["expected_target_generations"]}
    if target_types != canonical_publication_types:
        errors.append(
            f"run-manifest publication target types {sorted(target_types)} do not match contract "
            f"{sorted(canonical_publication_types)}"
        )
    if manifest["phase_contract_version"] != manifest_contract["contract_version"]:
        errors.append("run-manifest contract version must match its executable phase contract")
    if "phase_contract_sha256" not in manifest:
        errors.append("run-manifest must freeze the exact phase-contract digest")

    selected_stages = [
        stage
        for stage in manifest_contract["role_stages"]
        if manifest["mode"] in stage["applicable_modes"]
    ]
    contract_input_ids = {
        item["input_id"] for item in manifest_contract["required_inputs"]
    }
    contract_contexts_by_id = {
        item["context_id"]: item for item in manifest_contract["prepared_contexts"]
    }
    declared_contract_bindings = contract_input_ids | set(contract_contexts_by_id)
    manifest_inputs_by_id = {
        item["input_id"]: item for item in manifest["frozen_inputs"]
    }
    bound_inputs: dict[str, str] = {}
    for item in manifest["frozen_inputs"]:
        binding_id = item.get("contract_binding_id")
        if binding_id is None:
            continue
        if binding_id not in declared_contract_bindings:
            errors.append(f"run-manifest input {item['input_id']} uses unknown contract binding {binding_id}")
        if binding_id in bound_inputs:
            errors.append(f"run-manifest repeats contract input binding {binding_id}")
        bound_inputs[binding_id] = item["input_id"]
        if item["input_kind"] == "prepared_context" and binding_id in contract_contexts_by_id:
            context = contract_contexts_by_id[binding_id]
            actual_source_bindings = {
                manifest_inputs_by_id[source_id].get("contract_binding_id")
                for source_id in item["derived_from_input_ids"]
                if source_id in manifest_inputs_by_id
            }
            if actual_source_bindings != set(context["source_input_ids"]):
                errors.append(f"prepared context {binding_id} does not freeze its declared formal sources")
            if set(item["derived_from_choice_ids"]) != set(context["source_choice_ids"]):
                errors.append(f"prepared context {binding_id} does not freeze its declared user choices")
    required_contract_inputs = {
        item["input_id"]
        for item in manifest_contract["required_inputs"]
        if item["presence"] == "always"
        or (
            item["presence"] == "required_in_modes"
            and manifest["mode"] in item.get("required_in_modes", [])
        )
    }
    required_contract_contexts = {
        item["context_id"]
        for item in manifest_contract["prepared_contexts"]
        if manifest["mode"] in item["applicable_modes"]
    }
    missing_bindings = (required_contract_inputs | required_contract_contexts) - set(bound_inputs)
    if missing_bindings:
        errors.append(f"run-manifest omits required contract input bindings: {sorted(missing_bindings)}")

    manifest_outputs_by_id = {
        item["output_id"]: item for item in manifest["expected_outputs"]
    }
    outputs_by_contract_id: dict[str, set[str]] = {}
    declared_contract_outputs = {
        item["output_id"] for item in manifest_contract["run_local_outputs"]
    }
    for item in manifest["expected_outputs"]:
        contract_output_id = item["contract_output_id"]
        if contract_output_id not in declared_contract_outputs:
            errors.append(
                f"run-manifest output {item['output_id']} uses unknown contract output {contract_output_id}"
            )
        outputs_by_contract_id.setdefault(contract_output_id, set()).add(item["output_id"])
    required_contract_outputs = {
        item["output_id"]
        for item in manifest_contract["run_local_outputs"]
        if item["requirement"] == "always"
        or manifest["mode"] in item.get("required_in_modes", [])
    }
    missing_output_bindings = required_contract_outputs - set(outputs_by_contract_id)
    if missing_output_bindings:
        errors.append(
            f"run-manifest omits required contract output bindings: {sorted(missing_output_bindings)}"
        )

    expected_targets_by_id = {
        item["target_id"]: item for item in manifest["expected_target_generations"]
    }
    publication_diagnostics = publication_binding_diagnostics(
        manifest_contract,
        manifest["mode"],
        manifest["publication_plan"],
        outputs_by_contract_id,
        bound_inputs,
        expected_targets_by_id,
    )
    errors.extend(
        f"run-manifest publication diagnostic {diagnostic}"
        for diagnostic in publication_diagnostics
    )

    first_binding_id = manifest["publication_plan"][0]["publication_binding_id"]
    missing_probe = copy.deepcopy(manifest["publication_plan"])
    missing_probe = [
        item
        for item in missing_probe
        if item["publication_binding_id"] != first_binding_id
    ]
    missing_diagnostics = publication_binding_diagnostics(
        manifest_contract,
        manifest["mode"],
        missing_probe,
        outputs_by_contract_id,
        bound_inputs,
        expected_targets_by_id,
    )
    if f"PUB_BINDING_MISSING:{first_binding_id}" not in missing_diagnostics:
        errors.append("publication-binding mutation probe did not reject a missing binding")

    duplicate_probe = copy.deepcopy(manifest["publication_plan"])
    duplicate_probe.append(copy.deepcopy(duplicate_probe[0]))
    duplicate_diagnostics = publication_binding_diagnostics(
        manifest_contract,
        manifest["mode"],
        duplicate_probe,
        outputs_by_contract_id,
        bound_inputs,
        expected_targets_by_id,
    )
    if f"PUB_BINDING_DUPLICATE:{first_binding_id}" not in duplicate_diagnostics:
        errors.append("publication-binding mutation probe did not reject a duplicate binding")

    p5_contract = contracts_by_phase["P5"]
    p5_review_only_binding = next(
        item
        for item in p5_contract["publication_bindings"]
        if "p5.review_revision" in item["applicable_modes"]
        and "p5.assembly" not in item["applicable_modes"]
    )
    p5_mode_diagnostics = publication_binding_diagnostics(
        p5_contract,
        "p5.assembly",
        [{"publication_binding_id": p5_review_only_binding["binding_id"]}],
        {},
        {},
        {},
    )
    if (
        f"PUB_BINDING_MODE_INAPPLICABLE:{p5_review_only_binding['binding_id']}"
        not in p5_mode_diagnostics
    ):
        errors.append(
            "publication-binding mutation probe did not reject a mode-inapplicable binding"
        )

    current_binding = next(
        item
        for item in manifest_contract["publication_bindings"]
        if manifest["mode"] in item["applicable_modes"]
        and item["target"]["kind"] == "current_slot"
    )
    current_target_probe = copy.deepcopy(manifest["publication_plan"])
    current_plan = next(
        item
        for item in current_target_probe
        if item["publication_binding_id"] == current_binding["binding_id"]
    )
    current_plan["target"]["expected_target_id"] = "target.mutation.nonexistent"
    target_diagnostics = publication_binding_diagnostics(
        manifest_contract,
        manifest["mode"],
        current_target_probe,
        outputs_by_contract_id,
        bound_inputs,
        expected_targets_by_id,
    )
    if (
        f"PUB_BINDING_CURRENT_TARGET_MISMATCH:{current_binding['binding_id']}"
        not in target_diagnostics
    ):
        errors.append(
            "publication-binding mutation probe did not reject a current-slot target mutation"
        )
    expected_steps = [
        (stage["sequence"], stage["stage_id"], stage["execution"], role)
        for stage in selected_stages
        for role in stage["roles"]
    ]
    actual_steps = [
        (step["sequence"], step["stage_id"], step["execution"], step["role"])
        for step in manifest["role_plan"]
    ]
    if actual_steps != expected_steps:
        errors.append(f"run-manifest role plan {actual_steps} does not match contract {expected_steps}")

    frozen_ids = {item["input_id"] for item in manifest["frozen_inputs"]}
    expected_output_ids = {item["output_id"] for item in manifest["expected_outputs"]}
    expected_outputs_by_id = {
        item["output_id"]: item for item in manifest["expected_outputs"]
    }
    available_ids = set(frozen_ids)
    write_roots: set[str] = set()
    execution_groups: set[str] = set()
    selected_stages_by_id = {stage["stage_id"]: stage for stage in selected_stages}
    contract_outputs_by_id = {
        item["output_id"]: item for item in manifest_contract["run_local_outputs"]
    }
    for step in manifest["role_plan"]:
        if step["profile_input_id"] not in frozen_ids:
            errors.append(f"role step {step['stage_id']} uses an unfrozen profile")
        elif manifest_inputs_by_id[step["profile_input_id"]]["input_kind"] != "profile":
            errors.append(f"role step {step['stage_id']} profile input is not a frozen profile artifact")
        contract_stage = selected_stages_by_id[step["stage_id"]]
        stage_role_reads = {
            item["role"]: set(item["input_ids"])
            for item in contract_stage.get("role_reads", [])
        }
        contract_read_ids = stage_role_reads.get(step["role"], set(contract_stage["reads"]))
        expected_bound_reads = {
            contract_id
            for contract_id in contract_read_ids
            if contract_id in bound_inputs or contract_id in outputs_by_contract_id
        }
        actual_bound_reads: set[str] = set()
        for input_id in step["input_ids"]:
            frozen_input = manifest_inputs_by_id.get(input_id)
            if frozen_input and frozen_input.get("contract_binding_id"):
                actual_bound_reads.add(frozen_input["contract_binding_id"])
            output = manifest_outputs_by_id.get(input_id)
            if output:
                actual_bound_reads.add(output["contract_output_id"])
        if actual_bound_reads != expected_bound_reads:
            errors.append(
                f"role step {step['stage_id']} materializes contract reads {sorted(actual_bound_reads)}, "
                f"expected {sorted(expected_bound_reads)}"
            )
        expected_role_writes = {
            output_id
            for output_id in contract_stage["writes"]
            if contract_outputs_by_id[output_id]["producer"] == step["role"]
        }
        actual_role_writes = {
            manifest_outputs_by_id[output_id]["contract_output_id"]
            for output_id in step["output_ids"]
            if output_id in manifest_outputs_by_id
        }
        if actual_role_writes != expected_role_writes:
            errors.append(
                f"role step {step['stage_id']} materializes contract writes {sorted(actual_role_writes)}, "
                f"expected {sorted(expected_role_writes)}"
            )
        unknown_inputs = set(step["input_ids"]) - available_ids
        if unknown_inputs:
            errors.append(f"role step {step['stage_id']} reads unavailable inputs: {sorted(unknown_inputs)}")
        unknown_outputs = set(step["output_ids"]) - expected_output_ids
        if unknown_outputs:
            errors.append(f"role step {step['stage_id']} writes undeclared outputs: {sorted(unknown_outputs)}")
        if not step["role_write_root"].startswith(manifest["allowed_write_root"]):
            errors.append(f"role step {step['stage_id']} write root escapes the run root")
        else:
            role_relative_root = step["role_write_root"][len(manifest["allowed_write_root"]):]
            for output_id in step["output_ids"]:
                output = expected_outputs_by_id.get(output_id)
                if output and not output["relative_path"].startswith(role_relative_root):
                    errors.append(
                        f"role step {step['stage_id']} assigns {output_id} outside its role-specific root"
                    )
        if step["role_write_root"] in write_roots:
            errors.append(f"role step {step['stage_id']} reuses another role write root")
        write_roots.add(step["role_write_root"])
        if step["execution"] == "serial" and step["execution_group_id"] in execution_groups:
            errors.append(f"serial role step {step['stage_id']} reuses an execution group")
        execution_groups.add(step["execution_group_id"])
        available_ids.update(step["output_ids"])

    allowed_profile_stages = {
        stage["stage_id"]
        for phase in profile["applicable_phases"]
        for stage in contracts_by_phase[phase]["role_stages"]
        if profile["role"] in stage["roles"]
        and set(stage["applicable_modes"]) & profile_modes
    }
    if not set(profile["applicable_stage_ids"]).issubset(allowed_profile_stages):
        errors.append("role-profile stage IDs do not match its role, phase, and mode contracts")
    output_contract = profile.get("output_contract")
    if not output_contract or not output_contract.get("sha256"):
        errors.append("every role profile must freeze its output contract by artifact digest")
    for resource in profile["skills"] + profile["knowledge_resources"] + profile["tools"]:
        artifact = resource.get("artifact")
        if not artifact or not artifact.get("sha256"):
            errors.append("every role-profile skill, knowledge resource, and tool must have an immutable artifact digest")
    profile_steps = [step for step in manifest["role_plan"] if step["role"] == profile["role"]]
    if len(profile_steps) != 1:
        errors.append("run-manifest example must contain one role step for the role-profile example")
    else:
        profile_step = profile_steps[0]
        frozen_profile = manifest_inputs_by_id[profile_step["profile_input_id"]]
        if frozen_profile["artifact"]["sha256"] != profile["content_sha256"]:
            errors.append("run-manifest role profile digest must match the frozen profile content digest")
        role_resource_hashes = {
            manifest_inputs_by_id[input_id]["artifact"]["sha256"]
            for input_id in profile_step["input_ids"]
            if input_id in manifest_inputs_by_id
        }
        required_resource_hashes = {
            item["artifact"]["sha256"]
            for item in profile["skills"] + profile["knowledge_resources"] + profile["tools"]
            if item["required"]
        }
        if not required_resource_hashes.issubset(role_resource_hashes):
            errors.append("run-manifest role step omits a required role-profile resource artifact")

    forbidden_state_by_schema = {
        "scientific-record.schema.json": {
            "publication_state", "record_position", "alignment", "research_attention",
            "withdrawal_reason", "withdrawal_receipt_id", "invalid_reason",
        },
        "evidence.schema.json": {
            "publication_state", "record_position", "alignment", "research_attention",
            "eligible_for_current_index", "withdrawal_reason", "invalid_reason",
        },
        "method.schema.json": {"publication_state", "record_position"},
        "literature-source.schema.json": {"publication_state", "record_position"},
        "statement.schema.json": {
            "publication_state", "record_position", "alignment", "research_attention",
        },
        "handoff.schema.json": {"publication_state"},
        "decision-record.schema.json": {
            "publication_state", "record_position", "alignment", "research_attention",
        },
        "attention-item.schema.json": {"publication_state"},
        "review-issue.schema.json": {"publication_state"},
    }
    for schema_name, forbidden_fields in forbidden_state_by_schema.items():
        present = set(schemas[schema_name]["properties"]) & forbidden_fields
        if present:
            errors.append(
                f"immutable {schema_name} contains mutable derived-state fields: "
                f"{sorted(present)}"
            )
    for schema_name in ("authority-event.schema.json", "record-state.schema.json"):
        if schema_name not in schemas:
            errors.append(f"missing required derived-state schema: {schema_name}")

    current_index_slot = schemas["current-index.schema.json"]["properties"]["slots"]["items"]
    required_slot_fields = set(current_index_slot["required"])
    if not {"alignment", "research_attention", "source_event_ids"}.issubset(required_slot_fields):
        errors.append("current-index slots must expose rebuildable derived alignment and attention state")

    receipt = load_json(EXAMPLES / "publication-receipt.example.json")
    submission = load_json(EXAMPLES / "run-submission.example.json")
    current_index = load_json(EXAMPLES / "current-index.example.json")
    expected_receipt_source = {
        "kind": "research_run",
        "command_id": command["command_id"],
        "run_id": manifest["run_id"],
        "phase": manifest["phase"],
        "manifest_sha256": manifest["manifest_sha256"],
        "submission_id": submission["submission_id"],
        "submission_sha256": submission["submission_sha256"],
    }
    if receipt["source"] != expected_receipt_source:
        errors.append("P4 receipt source does not exactly identify its command, run, manifest, and submission")
    if receipt["content_sha256"] != canonical_sha256(receipt, {"content_sha256"}):
        errors.append("P4 publication receipt has an invalid self-digest")

    immutable_content_examples = [
        "attention-item.example.json",
        "review-issue.example.json",
        "scientific-record.example.json",
        "evidence.example.json",
        "decision-record.example.json",
    ]
    for example_name in immutable_content_examples:
        item = load_json(EXAMPLES / example_name)
        if item["content_sha256"] != canonical_sha256(item, {"content_sha256"}):
            errors.append(f"{example_name} content digest does not match its immutable payload")

    event_example_names = [
        "authority-event-record-published.example.json",
        "authority-event-synthesis-published.example.json",
        "authority-event-implementation-published.example.json",
        "authority-event-decision-published.example.json",
        "authority-event.example.json",
        "authority-event-attention-published.example.json",
    ]
    authority_events = [load_json(EXAMPLES / name) for name in event_example_names]
    events_by_id = {event["event_id"]: event for event in authority_events}
    if len(events_by_id) != len(authority_events):
        errors.append("authority-event fixture IDs must be unique")

    event_range = receipt["committed_event_range"]
    committed_ids = event_range["event_ids"]
    expected_sequences = list(
        range(event_range["first_sequence"], event_range["last_sequence"] + 1)
    )
    if len(committed_ids) != len(expected_sequences):
        errors.append("publication receipt event range must be contiguous")
    if set(committed_ids) != set(events_by_id):
        errors.append("publication receipt must include every and only replay fixture event")

    prior_root = event_range["prior_event_root_sha256"]
    prior_time = None
    for expected_sequence, event_id in zip(expected_sequences, committed_ids):
        event = events_by_id.get(event_id)
        if event is None:
            continue
        if event["event_sequence"] != expected_sequence:
            errors.append(f"authority event {event_id} has a noncontiguous sequence")
        if event["project_id"] != receipt["project_id"]:
            errors.append(f"authority event {event_id} belongs to the wrong project")
        if event["trigger"] != {
            "kind": "publication_receipt",
            "source_id": receipt["publication_id"],
        }:
            errors.append(f"authority event {event_id} is not bound to the receipt")
        expected_content = canonical_sha256(
            event, {"content_sha256", "event_root_sha256"}
        )
        if event["content_sha256"] != expected_content:
            errors.append(f"authority event {event_id} has an invalid content digest")
        if event["prior_event_root_sha256"] != prior_root:
            errors.append(f"authority event {event_id} breaks the prior-root chain")
        expected_root = hashlib.sha256(
            bytes.fromhex(prior_root) + bytes.fromhex(expected_content)
        ).hexdigest()
        if event["event_root_sha256"] != expected_root:
            errors.append(f"authority event {event_id} has an invalid event root")
        event_time = parse_time(event["created_at"])
        if prior_time is not None and event_time < prior_time:
            errors.append("authority-event timestamps must be nondecreasing")
        prior_time = event_time
        prior_root = event["event_root_sha256"]
    if prior_root != event_range["new_event_root_sha256"]:
        errors.append("publication receipt does not commit the final authority-event root")

    record_event_ids: list[str] = []
    for change in receipt["record_changes"]:
        for event_id in change["authority_event_ids"]:
            record_event_ids.append(event_id)
            event = events_by_id.get(event_id)
            if event is None:
                errors.append(f"record change cites unknown authority event {event_id}")
                continue
            if event["event_type"] == "superseded":
                expected_generation_id = change.get("prior_generation_id")
            elif event["event_type"] in {"withdrawn", "invalidated"}:
                expected_generation_id = change.get("subject_generation_id")
            else:
                expected_generation_id = change.get("new_generation_id")
            subject = event["subject"]
            if (
                subject["kind"] != "record_generation"
                or subject["subject_id"] != change["record_id"]
                or subject["generation_id"] != expected_generation_id
            ):
                errors.append(
                    f"record change and authority event {event_id} name different generations"
                )
        if change["change_kind"] not in {"withdraw", "invalidate"}:
            matching = [events_by_id[item] for item in change["authority_event_ids"] if item in events_by_id]
            if not any(
                event["changes"].get("publication_state") == "formal"
                and event["changes"].get("record_position") == "current"
                for event in matching
            ):
                errors.append(f"record change {change['record_id']} lacks a formal-current event")

    evidence = load_json(EXAMPLES / "evidence.example.json")
    attention = load_json(EXAMPLES / "attention-item.example.json")
    cumulative_objects = {
        ("evidence_item", evidence["evidence_id"]): evidence,
        ("attention_item", attention["attention_version_id"]): attention,
    }
    cumulative_event_ids: list[str] = []
    for change in receipt["cumulative_object_changes"]:
        key = (change["object_type"], change["object_id"])
        item = cumulative_objects.get(key)
        if item is None:
            errors.append(f"receipt cites unresolved cumulative object {key}")
        elif item["content_sha256"] != change["content_sha256"]:
            errors.append(f"receipt cumulative digest does not match {change['object_id']}")
        for event_id in change["authority_event_ids"]:
            cumulative_event_ids.append(event_id)
            event = events_by_id.get(event_id)
            if event is None:
                errors.append(f"cumulative change cites unknown authority event {event_id}")
                continue
            subject = event["subject"]
            if change["object_type"] == "evidence_item":
                matches_subject = (
                    subject["kind"] == "evidence_item"
                    and subject["subject_id"] == change["object_id"]
                )
            else:
                matches_subject = (
                    subject["kind"] == "cumulative_object"
                    and subject.get("object_type") == change["object_type"]
                    and subject["subject_id"] == change["object_id"]
                )
            if not matches_subject:
                errors.append(f"cumulative change and event {event_id} name different subjects")
        if change["change_kind"] == "publish" and not any(
            events_by_id[event_id]["changes"].get("publication_state") == "formal"
            for event_id in change["authority_event_ids"]
            if event_id in events_by_id
        ):
            errors.append(f"cumulative publication {change['object_id']} lacks a formal event")

    state_event_ids: list[str] = []
    for change in receipt["state_changes"]:
        for event_id in change["authority_event_ids"]:
            state_event_ids.append(event_id)
            event = events_by_id.get(event_id)
            if event is None:
                errors.append(f"state change cites unknown authority event {event_id}")
                continue
            if event["subject"] != change["subject"]:
                errors.append(
                    f"state change and authority event {event_id} name different subjects"
                )
            if event["event_type"] != change["change_kind"]:
                errors.append(
                    f"state change {change['change_kind']} cites {event['event_type']} event {event_id}"
                )

    accounted_event_ids = record_event_ids + cumulative_event_ids + state_event_ids
    if (
        len(accounted_event_ids) != len(committed_ids)
        or sorted(accounted_event_ids) != sorted(committed_ids)
    ):
        errors.append(
            "receipt change categories must account for every committed authority event exactly once"
        )

    for item_name in (
        "scientific-record.example.json",
        "evidence.example.json",
        "decision-record.example.json",
        "attention-item.example.json",
    ):
        item = load_json(EXAMPLES / item_name)
        if item["publication_receipt_id"] != receipt["publication_id"]:
            errors.append(f"formal {item_name} does not cite its publication receipt")
        if item["published_at"] != receipt["published_at"]:
            errors.append(f"formal {item_name} has a publication time outside its receipt")

    state_example_names = [
        "record-state-empirical.example.json",
        "record-state-empirical-synthesis.example.json",
        "record-state-implementation.example.json",
        "record-state-decision.example.json",
        "record-state.example.json",
    ]
    states = [load_json(EXAMPLES / name) for name in state_example_names]
    states_by_projection_id = {state["state_projection_id"]: state for state in states}
    if len(states_by_projection_id) != len(states):
        errors.append("record-state projection IDs must be unique")
    errors.extend(
        validate_folded_record_states(
            states,
            authority_events,
            event_range["last_sequence"],
            event_range["new_event_root_sha256"],
            authority_events[-1]["created_at"],
            "P4 receipt replay",
        )
    )
    if current_index["content_sha256"] != canonical_sha256(
        current_index, {"content_sha256"}
    ):
        errors.append("current-index digest does not match its canonical projection")
    if (
        current_index["index_generation_id"] != receipt["new_current_index_generation_id"]
        or current_index["content_sha256"] != receipt["new_current_index_sha256"]
        or current_index["publication_receipt_id"] != receipt["publication_id"]
    ):
        errors.append("publication receipt does not identify the committed current index")
    if (
        current_index["last_event_sequence"] != event_range["last_sequence"]
        or current_index["event_root_sha256"] != event_range["new_event_root_sha256"]
    ):
        errors.append("current index is not checkpointed at the receipt's final event root")

    receipt_changes = {
        (item["record_id"], item["record_type"], item.get("new_generation_id"))
        for item in receipt["record_changes"]
        if item["change_kind"] not in {"withdraw", "invalidate"}
    }
    index_changes = {
        (item["record_id"], item["record_type"], item["current_generation_id"])
        for item in current_index["slots"]
    }
    if receipt_changes != index_changes:
        errors.append("receipt record changes must exactly match committed current-index slots")

    record_states_by_subject = {
        (
            state["subject"]["subject_id"],
            state["subject"].get("generation_id"),
        ): state
        for state in states
        if state["subject"]["kind"] == "record_generation"
    }
    formal_attention_ids = {attention["attention_id"]}
    referenced_attention_ids: set[str] = set()
    for slot in current_index["slots"]:
        state = record_states_by_subject.get(
            (slot["record_id"], slot["current_generation_id"])
        )
        if state is None:
            errors.append(f"current slot {slot['slot_id']} lacks a replayed record-state projection")
            continue
        for field in (
            "publication_state",
            "record_position",
            "alignment",
            "research_attention",
            "source_event_ids",
        ):
            if slot[field] != state[field]:
                errors.append(f"current slot {slot['slot_id']} disagrees with replayed {field}")
        referenced_attention_ids.update(slot["research_attention"]["open_item_ids"])
    for state in states:
        referenced_attention_ids.update(state["research_attention"]["open_item_ids"])
    for impact in receipt["attention_impacts"]:
        referenced_attention_ids.update(impact.get("open_item_ids", []))
    if not referenced_attention_ids.issubset(formal_attention_ids):
        errors.append("formal state references an attention ID not published by the receipt")

    projection_digests = {
        (item["projection_kind"], item["projection_id"]): item["content_sha256"]
        for item in receipt["derived_projection_digests"]
    }
    expected_projection_digests = {
        ("record_state", state["state_projection_id"]): state["content_sha256"]
        for state in states
    }
    expected_projection_digests[("current_index", current_index["index_generation_id"])] = current_index[
        "content_sha256"
    ]
    if projection_digests != expected_projection_digests:
        errors.append("publication receipt projection digests are not replay-complete")

    empirical_record = load_json(EXAMPLES / "scientific-record.example.json")
    decision_record = load_json(EXAMPLES / "decision-record.example.json")
    generation_digests = {
        (empirical_record["record_id"], empirical_record["generation_id"]): empirical_record[
            "content_sha256"
        ],
        (decision_record["decision_id"], decision_record["generation_id"]): decision_record[
            "content_sha256"
        ],
    }
    for slot in current_index["slots"]:
        expected_digest = generation_digests.get(
            (slot["record_id"], slot["current_generation_id"])
        )
        if expected_digest is not None and slot["content_sha256"] != expected_digest:
            errors.append(f"current slot {slot['slot_id']} changed the generation content digest")

    replay_event_names = [
        "authority-event-replay-published.example.json",
        "authority-event-replay-alignment.example.json",
    ]
    replay_events = [load_json(EXAMPLES / name) for name in replay_event_names]
    replay_state = load_json(EXAMPLES / "record-state-replay.example.json")
    replay_index = load_json(EXAMPLES / "current-index-replay.example.json")
    replay_receipt = load_json(EXAMPLES / "publication-receipt-replay.example.json")
    if replay_receipt["content_sha256"] != canonical_sha256(
        replay_receipt, {"content_sha256"}
    ):
        errors.append("replay publication receipt has an invalid self-digest")
    replay_range = replay_receipt["committed_event_range"]
    replay_ids = [event["event_id"] for event in replay_events]

    if replay_range["event_ids"] != replay_ids:
        errors.append("replay receipt must preserve exact authority-event order")
    if (
        replay_range["first_sequence"] != 1
        or replay_range["last_sequence"] != len(replay_events)
    ):
        errors.append("replay receipt must commit the complete genesis event range")

    replay_prior_root = replay_range["prior_event_root_sha256"]
    replay_prior_time = None
    for expected_sequence, event in enumerate(replay_events, start=1):
        if event["event_sequence"] != expected_sequence:
            errors.append("replay-vector event sequences must be contiguous")
        if event["project_id"] != replay_receipt["project_id"]:
            errors.append("replay-vector event belongs to the wrong project")
        if event["trigger"] != {
            "kind": "publication_receipt",
            "source_id": replay_receipt["publication_id"],
        }:
            errors.append("replay-vector event is not bound to its receipt")
        expected_content = canonical_sha256(
            event, {"content_sha256", "event_root_sha256"}
        )
        if event["content_sha256"] != expected_content:
            errors.append(f"replay event {event['event_id']} has an invalid digest")
        if event["prior_event_root_sha256"] != replay_prior_root:
            errors.append(f"replay event {event['event_id']} breaks the root chain")
        expected_root = hashlib.sha256(
            bytes.fromhex(replay_prior_root) + bytes.fromhex(expected_content)
        ).hexdigest()
        if event["event_root_sha256"] != expected_root:
            errors.append(f"replay event {event['event_id']} has an invalid root")
        event_time = parse_time(event["created_at"])
        if replay_prior_time is not None and event_time < replay_prior_time:
            errors.append("replay-vector event timestamps must be nondecreasing")
        replay_prior_time = event_time
        replay_prior_root = event["event_root_sha256"]
    if replay_prior_root != replay_range["new_event_root_sha256"]:
        errors.append("replay receipt does not commit the final event root")

    first_fold, first_fold_errors = fold_authority_events(replay_events[:1])
    errors.extend(f"replay intermediate: {problem}" for problem in first_fold_errors)
    replay_key = authority_subject_key(replay_state["subject"])
    first_projection = first_fold.get(replay_key)
    if first_projection is None:
        errors.append("replay vector cannot build its intermediate state")
    else:
        intermediate_state = json.loads(json.dumps(replay_state))
        intermediate_state.update(first_projection["values"])
        intermediate_state["project_id"] = first_projection["project_id"]
        intermediate_state["subject"] = first_projection["subject"]
        intermediate_state["source_event_ids"] = first_projection["source_event_ids"]
        intermediate_state["last_event_sequence"] = replay_events[0]["event_sequence"]
        intermediate_state["event_root_sha256"] = replay_events[0]["event_root_sha256"]
        intermediate_state["computed_at"] = replay_events[0]["created_at"]
        intermediate_state["content_sha256"] = canonical_sha256(
            intermediate_state, {"content_sha256"}
        )
        if (
            replay_events[1].get("prior_state_sha256")
            != intermediate_state["content_sha256"]
        ):
            errors.append(
                "second replay event does not bind the deterministic intermediate state"
            )

    errors.extend(
        validate_folded_record_states(
            [replay_state],
            replay_events,
            replay_range["last_sequence"],
            replay_range["new_event_root_sha256"],
            replay_events[-1]["created_at"],
            "two-event replay vector",
        )
    )
    if (
        len(replay_state["source_event_ids"]) < 2
        or replay_events[0]["subject"] != replay_events[1]["subject"]
        or replay_events[0]["changes"].get("alignment")
        == replay_events[1]["changes"].get("alignment")
    ):
        errors.append(
            "replay vector must contain two ordered events that replace one state field"
        )

    replay_record_event_ids = [
        event_id
        for change in replay_receipt["record_changes"]
        for event_id in change["authority_event_ids"]
    ]
    replay_state_event_ids = [
        event_id
        for change in replay_receipt["state_changes"]
        for event_id in change["authority_event_ids"]
    ]
    replay_cumulative_event_ids = [
        event_id
        for change in replay_receipt["cumulative_object_changes"]
        for event_id in change["authority_event_ids"]
    ]
    replay_accounted = (
        replay_record_event_ids
        + replay_state_event_ids
        + replay_cumulative_event_ids
    )
    if (
        len(replay_accounted) != len(replay_ids)
        or sorted(replay_accounted) != sorted(replay_ids)
    ):
        errors.append("replay receipt must categorize every event exactly once")
    replay_events_by_id = {event["event_id"]: event for event in replay_events}
    for change in replay_receipt["state_changes"]:
        for event_id in change["authority_event_ids"]:
            event = replay_events_by_id.get(event_id)
            if event is None:
                errors.append("replay state change cites an unknown event")
            elif (
                event["event_type"] != change["change_kind"]
                or event["subject"] != change["subject"]
            ):
                errors.append("replay state change does not match its authority event")

    if replay_index["content_sha256"] != canonical_sha256(
        replay_index, {"content_sha256"}
    ):
        errors.append("replay current index has an invalid content digest")
    if (
        replay_index["publication_receipt_id"] != replay_receipt["publication_id"]
        or replay_index["index_generation_id"]
        != replay_receipt["new_current_index_generation_id"]
        or replay_index["content_sha256"]
        != replay_receipt["new_current_index_sha256"]
        or replay_index["last_event_sequence"] != replay_range["last_sequence"]
        or replay_index["event_root_sha256"] != replay_range["new_event_root_sha256"]
    ):
        errors.append("replay current index is not bound to the final receipt state")
    if len(replay_index["slots"]) != 1:
        errors.append("replay current index must contain one exact theory slot")
    else:
        replay_slot = replay_index["slots"][0]
        if (
            replay_slot["record_id"] != replay_state["subject"]["subject_id"]
            or replay_slot["current_generation_id"]
            != replay_state["subject"]["generation_id"]
        ):
            errors.append("replay current slot identifies a different generation")
        for field in (
            "publication_state",
            "record_position",
            "alignment",
            "research_attention",
            "source_event_ids",
        ):
            if replay_slot[field] != replay_state[field]:
                errors.append(f"replay current slot disagrees with folded {field}")

    replay_projection_digests = {
        (item["projection_kind"], item["projection_id"]): item["content_sha256"]
        for item in replay_receipt["derived_projection_digests"]
    }
    expected_replay_digests = {
        ("record_state", replay_state["state_projection_id"]): replay_state[
            "content_sha256"
        ],
        ("current_index", replay_index["index_generation_id"]): replay_index[
            "content_sha256"
        ],
    }
    if replay_projection_digests != expected_replay_digests:
        errors.append("replay receipt projection digests are incomplete")
    if replay_receipt["alignment_impacts"] != [
        {
            "affected_record_id": replay_state["subject"]["subject_id"],
            "before": "unassessed",
            "after": "exact",
            "cause": "exact_match",
            "automatic_run": False,
        }
    ]:
        errors.append("replay receipt does not expose the exact alignment change")
    run_state = load_json(EXAMPLES / "run-state.example.json")
    if (
        run_state["project_id"] != manifest["project_id"]
        or run_state["run_id"] != manifest["run_id"]
        or run_state["manifest_sha256"] != manifest["manifest_sha256"]
    ):
        errors.append("run-state journal is not bound to the sealed manifest")
    errors.extend(validate_run_state_journal(run_state, "published run-state"))
    if (
        run_state["current_state"] == "published"
        and run_state["publication_receipt_id"] != receipt["publication_id"]
    ):
        errors.append("published run-state must resolve to the committed publication receipt")
    if receipt["source"]["manifest_sha256"] != manifest["manifest_sha256"]:
        errors.append("publication receipt is not bound to the sealed run manifest")

    return errors


def main() -> int:
    schemas, registry, errors = build_schema_registry()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    errors.extend(validate_examples(schemas, registry))
    errors.extend(validate_digest_contract_registry(schemas, registry))
    errors.extend(validate_digest_vectors())
    errors.extend(validate_method_identity_vector(schemas, registry))
    errors.extend(validate_shared_digest_examples())
    errors.extend(validate_role_invocation_lifecycle())
    errors.extend(validate_control_and_context_semantics())
    errors.extend(validate_command_attempt_audit(schemas, registry))
    contract_errors, complete_contract = validate_contracts(schemas, registry)
    errors.extend(contract_errors)
    errors.extend(
        validate_traceability_registry(schemas, registry, complete_contract)
    )
    errors.extend(validate_package_indexes(schemas))
    errors.extend(validate_text_and_links())
    errors.extend(validate_global_invariants(schemas))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Architecture package validation failed with {len(errors)} error(s).")
        return 1

    print("Architecture package validation passed.")
    print(f"  Schemas: {len(schemas)}")
    print(f"  Valid examples: {len(VALID_EXAMPLES)}")
    print(f"  Rejected negative fixtures: {len(INVALID_EXAMPLES)}")
    print(f"  Phase contracts: {len(complete_contract['contracts'])}")
    print("  Phase semantics, role order, user control, links, and terminology: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
