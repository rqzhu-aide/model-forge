"""Operational run projections for the Web UI and remote operators."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..api.models import (
    ActionDescriptor,
    MethodIdentity,
    PublicationReceiptView,
    RunContract,
    RunDetail,
    RunEvent,
    RunStage,
    RunSummary,
    TerminalReason,
    ValidationReportView,
)


CANCELLABLE = {"created", "preparing", "prepared", "running"}


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


def run_summary_view(row: sqlite3.Row) -> RunSummary:
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
        actions=[action],
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
    summary = run_summary_view(row)
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


__all__ = ["CANCELLABLE", "run_detail_view", "run_event_view", "run_summary_view"]
