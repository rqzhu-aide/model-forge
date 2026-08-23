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
