"""Operational run projections for the Web UI and remote operators."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..api.models import (
    ActionDescriptor,
    FindingGroupView,
    MethodIdentity,
    PublicationReceiptView,
    RunContract,
    RunDetail,
    RunEvent,
    RunLifecycleProjection,
    RunStage,
    RunSummary,
    TerminalReason,
    ValidationReportView,
)


CANCELLABLE = {"created", "preparing", "prepared", "running"}

# Correction type -> advertised action type (K-1).  Lane A (revalidate,
# normalize) needs no model call; Lane B (packaging, scientific) re-invokes
# the role with a correction instruction.
CORRECTION_ACTION_TYPES = {
    "revalidate": "revalidate_run",
    "normalize": "normalize_run_outputs",
    "packaging": "package_run_outputs",
    "scientific": "revise_scientific_content",
}

# States whose detail/summary advertises the correction descriptors: the
# correctable failed/rejected surface, the authorized retry surface, and
# the correcting D6 retry surface (a failed Lane B attempt leaves the run
# in correcting; the retry is a new command from there).
_CORRECTION_SURFACE_STATES = ("correction_authorized", "correcting")


def run_event_view(row: sqlite3.Row) -> RunEvent:
    payload = _payload(row)
    return RunEvent(
        sequence=int(row["sequence"]),
        event_id=str(row["event_id"]),
        event_type=str(payload.get("event_type", f"run.{row['status']}")),
        state=str(row["status"]),
        stage_id=_optional(payload.get("stage_id")),
        role=_optional(payload.get("role")),
        message=str(payload.get("message", row["status"])),
        occurred_at=str(row["recorded_at"]),
    )


def run_summary_view(
    row: sqlite3.Row,
    *,
    has_publication: bool = False,
) -> RunSummary:
    payload = _payload(row)
    state = str(row["status"])
    action_enabled = state in CANCELLABLE
    action = ActionDescriptor(
        descriptor_id=_action_id(str(row["run_id"]), "cancel", str(row["head_sequence"])),
        action_type="cancel_run",
        execution_kind="research_run",
        enabled=action_enabled,
        reason_code=None if action_enabled else "run.not_cancellable",
        researcher_message=(
            None
            if action_enabled
            else "This run is already submitted or terminal and cannot be cancelled."
        ),
        consequence_summary=(
            "Stop this run before immutable submission. Formal project records remain unchanged."
        ),
        run_id=str(row["run_id"]),
        requires_reason=True,
    )
    method = payload.get("method_identity")
    projection = _compute_projection(state, payload, has_publication=has_publication)
    actions = [action]
    if (
        state in ("failed", "rejected")
        and projection.recovery_summary == "needs_output_correction"
    ) or state in _CORRECTION_SURFACE_STATES:
        projection = projection.model_copy(
            update={
                "available_recovery_controls": [
                    "revalidate",
                    "normalize",
                    "packaging",
                    "scientific",
                ]
            }
        )
        actions.append(
            ActionDescriptor(
                descriptor_id=_action_id(
                    str(row["run_id"]),
                    "correction:revalidate",
                    str(row["head_sequence"]),
                ),
                action_type="revalidate_run",
                execution_kind="control_transaction",
                enabled=True,
                consequence_summary=(
                    "Re-check the sealed outputs against the current schemas; "
                    "on success the run re-enters submission."
                ),
                run_id=str(row["run_id"]),
            )
        )
        actions.append(
            ActionDescriptor(
                descriptor_id=_action_id(
                    str(row["run_id"]),
                    "correction:normalize",
                    str(row["head_sequence"]),
                ),
                action_type="normalize_run_outputs",
                execution_kind="control_transaction",
                enabled=True,
                consequence_summary=(
                    "Apply allowlisted mechanical transformations to the "
                    "sealed outputs; on success the run re-enters submission."
                ),
                run_id=str(row["run_id"]),
            )
        )
        actions.append(
            ActionDescriptor(
                descriptor_id=_action_id(
                    str(row["run_id"]),
                    "correction:packaging",
                    str(row["head_sequence"]),
                ),
                action_type="package_run_outputs",
                execution_kind="control_transaction",
                enabled=True,
                consequence_summary=(
                    "Re-invoke the role to fix envelope/format issues only; "
                    "one bounded attempt."
                ),
                run_id=str(row["run_id"]),
            )
        )
        actions.append(
            ActionDescriptor(
                descriptor_id=_action_id(
                    str(row["run_id"]),
                    "correction:scientific",
                    str(row["head_sequence"]),
                ),
                action_type="revise_scientific_content",
                execution_kind="control_transaction",
                enabled=True,
                consequence_summary=(
                    "Re-invoke the role to revise the scientific content "
                    "within the frozen scope; one bounded attempt."
                ),
                run_id=str(row["run_id"]),
            )
        )
    return RunSummary(
        run_id=str(row["run_id"]),
        phase=str(payload["phase"]),
        mode=str(payload["mode"]),
        state=state,
        method_identity=(
            MethodIdentity.model_validate(method) if type(method) is dict else None
        ),
        requested_at=str(payload["requested_at"]),
        updated_at=str(row["updated_at"]),
        current_stage_label=_optional(payload.get("current_stage_label")),
        actions=actions,
        lifecycle_projection=projection,
    )


def run_detail_view(
    row: sqlite3.Row,
    *,
    event_rows: tuple[sqlite3.Row, ...],
    manifest_row: sqlite3.Row | None,
    publication_row: sqlite3.Row | None = None,
    execution_activity: tuple[sqlite3.Row, ...] = (),
) -> RunDetail:
    payload = _payload(row)
    receipt_present = publication_row is not None
    summary = run_summary_view(row, has_publication=receipt_present)
    manifest = _payload(manifest_row) if manifest_row is not None else {}
    events = [run_event_view(item) for item in event_rows]
    stage_states = payload.get("stage_states", {})
    stage_source = manifest.get("stages") or payload.get("stage_plan", [])
    # Build a {stage_id: latest_heartbeat_at} map from execution activity.
    # Each row in latest_execution_activity joins role_execution_intents
    # with the most recent heartbeat; the intent's payload_json carries
    # the stage_id.  This lets the UI show liveness during long stages.
    heartbeat_by_stage: dict[str, str] = {}
    heartbeat_activity: dict[str, str] = {}
    for act_row in execution_activity:
        intent_payload = json.loads(act_row["payload_json"]) if act_row["payload_json"] else {}
        stage_id = intent_payload.get("stage_id")
        hb_at = act_row["heartbeat_at"]
        if stage_id and hb_at:
            hb_str = str(hb_at)
            # activity rows are ordered by created_at, so the last entry
            # per stage_id wins (most recent intent for that stage).
            heartbeat_by_stage[str(stage_id)] = hb_str
            hb_payload = json.loads(act_row["heartbeat_payload_json"]) if act_row["heartbeat_payload_json"] else {}
            hb_activity = hb_payload.get("activity")
            if hb_activity:
                heartbeat_activity[str(stage_id)] = str(hb_activity)
    stages: list[RunStage] = []
    for item in stage_source:
        stage_id = str(item["stage_id"])
        stage_state = stage_states.get(stage_id, {})
        role_items = item.get("roles", [])
        roles = [
            str(role["role"]) if type(role) is dict else str(role)
            for role in role_items
        ]
        # Enrich running stages with the latest heartbeat data so the
        # UI can distinguish a live agent from a wedged one.
        latest_heartbeat = heartbeat_by_stage.get(stage_id)
        latest_activity = heartbeat_activity.get(stage_id)
        stages.append(
            RunStage(
                sequence=int(item["sequence"]),
                stage_id=stage_id,
                label=str(item.get("objective", item.get("label", stage_id))),
                roles=roles,
                execution=str(item["execution"]),
                status=str(stage_state.get("status", "pending")),
                started_at=_optional(stage_state.get("started_at")),
                completed_at=_optional(stage_state.get("completed_at")),
                activity=_optional(latest_activity or stage_state.get("activity")),
                last_heartbeat_at=_optional(latest_heartbeat or stage_state.get("last_heartbeat_at")),
                stale_after_seconds=stage_state.get("stale_after_seconds"),
            )
        )
    terminal = payload.get("terminal_reason")
    validation = payload.get("validation_report")
    receipt = None
    if publication_row is not None:
        receipt = PublicationReceiptView(
            publication_id=str(publication_row["receipt_id"]),
            published_at=str(publication_row["committed_at"]),
            href=(
                f"/api/v1/projects/{row['project_id']}/publications/"
                f"{publication_row['receipt_id']}"
            ),
        )
    return RunDetail(
        **summary.model_dump(),
        requested_by=str(payload["requested_by"]),
        instructions=str(payload.get("instructions", "")),
        contract=RunContract(
            phase_contract_version=str(payload["phase_contract_version"]),
            phase_contract_sha256=str(payload["phase_contract_sha256"]),
        ),
        frozen_basis=[
            {
                "label": str(item["label"]),
                "identity": str(item["identity"]),
                "digest": str(item["digest"]),
            }
            for item in payload.get("frozen_basis", [])
        ],
        stage_plan=stages,
        last_event_sequence=int(row["head_sequence"]),
        last_event_at=events[-1].occurred_at if events else None,
        stale_after_seconds=300 if str(row["status"]) == "running" else None,
        terminal_reason=(
            TerminalReason.model_validate(terminal) if type(terminal) is dict else None
        ),
        validation_report=(
            ValidationReportView.model_validate(validation)
            if type(validation) is dict
            else None
        ),
        publication_receipt=receipt,
    )


def _payload(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    value = json.loads(row["payload_json"])
    if type(value) is not dict:
        raise ValueError("Run repository payload must be a JSON object.")
    return value


def _optional(value: Any) -> str | None:
    return str(value) if value is not None else None


def _action_id(*parts: str) -> str:
    return "action." + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Lifecycle projection (HV-3.1/HV-3.2)                                        #
# --------------------------------------------------------------------------- #

_NON_TERMINAL = {
    "created", "preparing", "prepared", "running",
    "cancellation_requested", "submitted", "validating", "promoting",
    "correction_authorized", "correcting",
}

# Failure-code prefixes that indicate executor/process failures, as opposed
# to output-conformance failures. Keying on the failure_code string is an
# interim bridge until closure findings carry HV-2 finding classes in the
# run payload. See HV-3 plan §3.2.
_EXECUTOR_FAILURE_PREFIXES = (
    "executor.",
    "orchestration.",
    "run.coordination_failed",
    "run.naive_datetime",
)

_OUTPUT_VALIDATION_FAILURE_CODES = frozenset({
    "output.structural_validation_failed",
    "submission.validation_failed",
})


def _classify_findings(
    findings: list[dict[str, Any]],
) -> tuple[int, int, list[FindingGroupView]]:
    """Count blocking vs correctable findings and group by class.

    Returns (blocking_count, correctable_count, finding_groups).
    """
    blocking = 0
    correctable = 0
    by_class: dict[str, dict[str, Any]] = {}

    for f in findings:
        fc = f.get("finding_class", "integrity_blocker")
        blocks = f.get("blocks_publication", True)
        code = f.get("code", "unknown")
        if blocks:
            blocking += 1
            if fc in ("correctable_contract_error",):
                correctable += 1
        if fc not in by_class:
            by_class[fc] = {"count": 0, "codes": []}
        by_class[fc]["count"] += 1
        if len(by_class[fc]["codes"]) < 3:
            by_class[fc]["codes"].append(code)

    groups = [
        FindingGroupView(
            finding_class=fc,  # type: ignore[arg-type]
            count=data["count"],
            sample_codes=data["codes"],
        )
        for fc, data in sorted(by_class.items())
    ]
    return blocking, correctable, groups


def _compute_projection(
    status: str,
    payload: dict[str, Any],
    *,
    has_publication: bool = False,
) -> RunLifecycleProjection:
    """Derive the 4-axis lifecycle projection from run status and payload.

    This is a pure function over existing data — no new state-machine states
    are introduced. The mapping is defined by HV-3 plan §3.2.
    """
    terminal_reason = payload.get("terminal_reason")
    failure_code = ""
    if isinstance(terminal_reason, dict):
        failure_code = str(terminal_reason.get("code", ""))

    # Extract closure findings if present in the payload
    closure_findings: list[dict[str, Any]] = []
    closure = payload.get("closure_findings")
    if isinstance(closure, list):
        closure_findings = closure

    blocking_count, correctable_count, finding_groups = _classify_findings(
        closure_findings
    )

    # --- execution_state ---
    if status in ("created", "preparing", "prepared"):
        execution_state = "not_started"
    elif status in ("running", "cancellation_requested", "submitted",
                     "validating", "promoting", "correcting"):
        execution_state = "running"
    elif status in ("correction_authorized", "correction_exhausted"):
        execution_state = "completed"
    elif status == "cancelled":
        execution_state = "cancelled"
    elif status in ("failed", "rejected", "conflicted", "published"):
        execution_state = "completed"
    else:
        execution_state = "not_started"

    # Override: if status is failed and failure_code is executor-related,
    # execution genuinely failed.
    if status == "failed" and _is_executor_failure(failure_code):
        execution_state = "failed"

    # --- conformance_state ---
    if status in ("published", "promoting"):
        conformance_state = "passed"
    elif status == "validating":
        conformance_state = "not_checked"
    elif status in ("rejected", "failed"):
        if correctable_count > 0 and not _has_integrity_blocker(finding_groups):
            conformance_state = "correction_required"
        elif _is_output_validation_failure(failure_code) and not _has_integrity_blocker(finding_groups):
            conformance_state = "correction_required"
        else:
            conformance_state = "integrity_rejected"
    elif status == "correction_exhausted":
        conformance_state = "correction_required"
    else:
        conformance_state = "not_checked"

    # --- publication_state ---
    if status == "published" or has_publication:
        publication_state = "published"
    elif status == "conflicted":
        publication_state = "conflicted"
    elif status in ("rejected", "failed", "cancelled", "correction_exhausted"):
        publication_state = "withheld"
    else:
        publication_state = "not_attempted"

    # --- recovery_summary ---
    if status == "published":
        recovery = "ok"
    elif status == "cancelled":
        recovery = "cancelled"
    elif status == "conflicted":
        recovery = "conflicted"
    elif status == "correction_exhausted":
        recovery = "correction_exhausted"
    elif status in _NON_TERMINAL:
        recovery = "in_progress"
    elif status == "failed":
        if _is_executor_failure(failure_code):
            recovery = "failed"
        elif conformance_state == "correction_required":
            recovery = "needs_output_correction"
        else:
            recovery = "failed"
    elif status == "rejected":
        if conformance_state == "correction_required":
            recovery = "needs_output_correction"
        else:
            recovery = "rejected"
    else:
        recovery = "in_progress"

    # Recovery controls — empty until HV-5 correction endpoints land.
    # The projection identifies what recovery is possible, but must not
    # advertise controls that have no backing API handler.
    recovery_controls: list[str] = []

    return RunLifecycleProjection(
        execution_state=execution_state,  # type: ignore[arg-type]
        conformance_state=conformance_state,  # type: ignore[arg-type]
        publication_state=publication_state,  # type: ignore[arg-type]
        recovery_summary=recovery,  # type: ignore[arg-type]
        blocking_finding_count=blocking_count,
        correctable_finding_count=correctable_count,
        scientific_outcome=payload.get("scientific_outcome"),
        finding_groups=finding_groups,
        available_recovery_controls=recovery_controls,  # type: ignore[arg-type]
    )


def _is_executor_failure(code: str) -> bool:
    """Check if a failure code indicates an executor/process failure."""
    return any(
        code.startswith(prefix) or code == prefix
        for prefix in _EXECUTOR_FAILURE_PREFIXES
    )


def _is_output_validation_failure(code: str) -> bool:
    """Check if a failure code is an output validation failure."""
    return code in _OUTPUT_VALIDATION_FAILURE_CODES


def _has_integrity_blocker(groups: list[FindingGroupView]) -> bool:
    """Check if any finding group is an integrity blocker."""
    return any(
        g.finding_class in ("integrity_blocker", "operational_failure")
        for g in groups
    )


__all__ = ["CANCELLABLE", "run_detail_view", "run_event_view", "run_summary_view"]
