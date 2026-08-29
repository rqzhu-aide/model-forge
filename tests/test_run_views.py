from __future__ import annotations

import hashlib
import json

from model_forge.application.run_views import run_detail_view
from model_forge.storage.repository import HubRepository


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def test_created_run_has_one_explicit_cancel_action(tmp_path) -> None:
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project("project.example", {"name": "Example"})
    raw = repository.record_raw_command(
        "request.example", "project.example", "a" * 64, {"artifact": "raw"}
    )
    command = {
        "command_id": "command.example",
        "phase": "P1",
        "mode": "p1.literature_update",
    }
    repository.seal_command(
        "command.example",
        "project.example",
        raw.row["request_id"],
        "request-example",
        "b" * 64,
        command,
    )
    payload = {
        "phase": "P1",
        "mode": "p1.literature_update",
        "requested_at": "2026-08-02T12:00:00Z",
        "requested_by": "researcher.local",
        "instructions": "Update the literature.",
        "phase_contract_version": "1.0.0",
        "phase_contract_sha256": "c" * 64,
        "stage_plan": [
            {
                "sequence": 1,
                "stage_id": "p1.discovery",
                "label": "Independent discovery",
                "roles": ["research_lead", "theorist", "data_analyst"],
                "execution": "parallel",
            }
        ],
    }
    event = {"event_type": "run.created", "message": "Run accepted."}
    repository.create_run(
        "run.example",
        "project.example",
        "command.example",
        "created",
        payload,
        "event.example",
        _digest(event),
        event,
    )
    row = repository.get_run("run.example")

    view = run_detail_view(
        row,
        event_rows=repository.list_run_events("run.example"),
        manifest_row=None,
    )

    assert view.state == "created"
    assert view.actions[0].action_type == "cancel_run"
    assert view.actions[0].enabled is True
    assert view.stage_plan[0].execution == "parallel"


def _correcting_run(repository):
    repository.create_project("project.example", {"name": "Example"})
    raw = repository.record_raw_command(
        "request.example", "project.example", "a" * 64, {"artifact": "raw"}
    )
    command = {"command_id": "command.example", "phase": "P4", "mode": "p4.preliminary"}
    repository.seal_command(
        "command.example", "project.example", raw.row["request_id"],
        "request-example", "b" * 64, command,
    )
    payload = {
        "phase": "P4",
        "mode": "p4.preliminary",
        "requested_at": "2026-08-26T02:00:00Z",
        "requested_by": "researcher.local",
        "instructions": "Run preliminary empirical work.",
        "phase_contract_version": "2.3.0",
        "phase_contract_sha256": "c" * 64,
        "stage_plan": [],
        "findings": [
            {
                "code": "output.required_missing",
                "message": "Required output was not produced.",
                "blocks_publication": True,
                "finding_class": "correctable_contract_error",
            }
        ],
    }
    event = {"event_type": "run.failed", "message": "Run failed."}
    repository.create_run(
        "run.example", "project.example", "command.example", "correcting",
        payload, "event.example", _digest(event), event,
    )
    return "run.example"


def test_spent_scientific_lane_disables_descriptor(tmp_path) -> None:
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    run_id = _correcting_run(repository)
    row = repository.get_run(run_id)

    from model_forge.application.run_views import run_summary_view

    fresh = run_summary_view(row, correction_attempts=(0, 0))
    scientific = next(a for a in fresh.actions if a.action_type == "revise_scientific_content")
    assert scientific.enabled

    spent = run_summary_view(row, correction_attempts=(0, 1))
    scientific = next(a for a in spent.actions if a.action_type == "revise_scientific_content")
    assert not scientific.enabled
    assert scientific.reason_code == "correction.attempt_spent"
    assert "already spent" in (scientific.researcher_message or "")
    packaging = next(a for a in spent.actions if a.action_type == "package_run_outputs")
    assert packaging.enabled  # the packaging lane is independent


def _detail_for(status, correction_attempts=None):
    from model_forge.application.run_views import run_detail_view
    import sqlite3 as _sq

    class _Row(dict):
        def __getitem__(self, k):
            return super().__getitem__(k)

    payload = {
        "phase": "P4",
        "mode": "p4.preliminary",
        "requested_at": "2026-08-26T02:00:00Z",
        "requested_by": "researcher.local",
        "instructions": "Run preliminary empirical work.",
        "phase_contract_version": "2.3.0",
        "phase_contract_sha256": "c" * 64,
        "choice_values": {"p4.instructions": "Run preliminary empirical work."},
        "context_policy": "current_only",
        "stage_plan": [],
        "frozen_basis": [],
    }
    row = _Row(
        run_id="run.example",
        project_id="project.example",
        status=status,
        head_sequence=3,
        created_at="2026-08-26T02:00:00Z",
        updated_at="2026-08-26T03:00:00Z",
        payload_json=json.dumps(payload),
    )
    return run_detail_view(
        row,
        event_rows=(),
        manifest_row=None,
        correction_attempts=correction_attempts,
    )


def test_rerun_prefill_present_for_terminal_failed_run() -> None:
    detail = _detail_for("failed")
    assert detail.rerun_prefill is not None
    assert detail.rerun_prefill.phase == "P4"
    assert detail.rerun_prefill.mode == "p4.preliminary"
    assert detail.rerun_prefill.context_policy == "current_only"
    assert "p4.instructions" in detail.rerun_prefill.choice_values


def test_rerun_prefill_absent_while_scientific_lane_remains() -> None:
    detail = _detail_for("correcting", correction_attempts=(1, 0))
    assert detail.rerun_prefill is None


def test_rerun_prefill_present_when_scientific_lane_spent() -> None:
    # Packaging only reshapes sealed bytes; with the scientific lane spent a
    # full rerun is the substantive next step even if packaging is free.
    detail = _detail_for("correcting", correction_attempts=(0, 1))
    assert detail.rerun_prefill is not None
