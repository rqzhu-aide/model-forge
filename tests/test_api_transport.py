from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient

from method_hub.api import (
    ArtifactDelivery,
    CommandRejected,
    RawRequestBody,
    RawRequestReceipt,
    create_app,
    new_command_error,
)
from method_hub.api.models import (
    ActionDescriptor,
    CorrectionPreviewRequest,
    CorrectionPreviewView,
    CorrectionRequest,
    CreateProjectRequest,
    InstallSkillRequest,
    MethodRow,
    PhaseId,
    PhaseView,
    ProfileConfigurationView,
    PublicationReceiptDocument,
    ProjectBriefView,
    ProjectOverview,
    ProjectSummary,
    ReasonedActionRequest,
    RunDetail,
    RunEvent,
    RunSummary,
    SaveProfileRequest,
    StartRunRequest,
    SystemSettingsView,
    UpdateProjectBriefRequest,
)


SHA = "a" * 64
NOW = "2026-08-02T12:00:00Z"


def project_summary() -> ProjectSummary:
    return ProjectSummary(
        project_id="project.demo",
        name="Demo",
        research_question="Which estimator is robust?",
        domains=["statistics"],
        updated_at=NOW,
        active_run_count=0,
    )


def disabled_start_action() -> ActionDescriptor:
    return ActionDescriptor(
        descriptor_id="action.start.p3",
        action_type="start_run",
        execution_kind="research_run",
        enabled=False,
        reason_code="METHOD_NOT_SELECTED",
        researcher_message="Select a current method before starting theory development.",
        consequence_summary="A valid run will replace the current theory record.",
        command_contract={
            "phase": "P3",
            "phase_contract_version": "2.0.0",
            "phase_contract_sha256": SHA,
            "mode": "p3.theory_establishment",
        },
    )


def phase_view() -> PhaseView:
    return PhaseView(
        phase_id="P3",
        name="Theory development",
        purpose="Develop complete theory for one exact method identity.",
        assessment={},
        evidence=[],
        artifacts=[],
        run_configuration={
            "modes": [
                {
                    "mode_id": "p3.theory_establishment",
                    "label": "Theory update",
                    "description": "Reassess and update the complete theory record.",
                }
            ],
            "default_mode": "p3.theory_establishment",
            "instruction_label": "Research instructions",
            "instruction_help": "Describe the questions that need attention.",
            "current_inputs": [],
            "history_options": [],
            "stage_plan": [
                {
                    "stage_id": "theorist",
                    "label": "Theorist",
                    "roles": ["theorist"],
                    "execution": "serial",
                }
            ],
        },
        actions=[disabled_start_action()],
        active_runs=[],
        recent_runs=[],
        projection={"view_revision": 4, "projected_at": NOW},
        empty_state_message="No current theory record exists for this method.",
    )


def run_detail(state: str = "created") -> RunDetail:
    return RunDetail(
        run_id="run.demo",
        phase="P3",
        mode="p3.theory_establishment",
        state=state,
        requested_at=NOW,
        updated_at=NOW,
        actions=[],
        requested_by="researcher.demo",
        instructions="Check the boundary case.",
        contract={
            "phase_contract_version": "2.0.0",
            "phase_contract_sha256": SHA,
        },
        frozen_basis=[],
        stage_plan=[
            {
                "sequence": 1,
                "stage_id": "theorist",
                "label": "Theorist",
                "roles": ["theorist"],
                "execution": "serial",
                "status": "pending",
            }
        ],
        last_event_sequence=0,
    )


def profile_view() -> ProfileConfigurationView:
    return ProfileConfigurationView(
        profiles=[
            {
                "role_id": "theorist",
                "display_name": "Theorist",
                "role_summary": "Develops mathematical arguments.",
                "profile_id": "profile.theorist",
                "profile_version": "1.0.0",
                "profile_options": [
                    {
                        "profile_id": "profile.theorist",
                        "label": "Theorist",
                        "version": "1.0.0",
                        "enabled": True,
                        "researcher_message": None,
                        "action_descriptor_id": "action.profile.theorist",
                    }
                ],
                "scientific_stance_summary": "State every assumption explicitly.",
                "model_summary": "Configured by the researcher.",
                "memory_policy_summary": "Use frozen run context.",
                "applicable_phases": ["P3", "P4"],
                "skills": [],
                "actions": [],
            }
        ],
        projection={"view_revision": 2, "projected_at": NOW},
    )


def project_brief_view() -> ProjectBriefView:
    return ProjectBriefView(
        project_id="project.demo",
        record_id="record.project_brief",
        generation_id="generation.project_brief",
        research_question="Which estimator is robust?",
        domains=["statistics"],
        intended_use="Method development",
        scope="Weak overlap.",
        decision_criteria=["Valid inference"],
        constraints=["Reproducible analysis"],
        scope_note="Changed only by an explicit command.",
        published_at=NOW,
        artifact={
            "artifact_id": "artifact.project_brief",
            "label": "Formal project brief",
            "information_layer": "structured",
            "media_type": "application/json",
            "href": "/api/v1/projects/project.demo/artifacts/artifact.project_brief",
        },
        actions=[
            {
                "descriptor_id": "action.update.brief",
                "action_type": "update_project_brief",
                "execution_kind": "configuration",
                "enabled": True,
                "consequence_summary": "Replace the formal brief without a run.",
                "target_id": "generation.project_brief",
                "requires_reason": True,
            }
        ],
        projection={"view_revision": 1, "projected_at": NOW},
    )


def system_settings_view() -> SystemSettingsView:
    return SystemSettingsView(
        service_version="1.0.0",
        bind_host="127.0.0.1",
        port=8765,
        executor_kind="disabled",
        execution_available=False,
        development_mode=False,
        data_root="C:/method-hub",
        database_path="C:/method-hub/method-hub.sqlite3",
        artifact_namespace="artifacts/objects",
        architecture_root="C:/method-hub/architecture",
        frontend_dist="C:/method-hub/web/dist",
        frontend_available=True,
        database_schema_version=3,
        project_count=1,
        settings_message="Restart the service to change these values.",
    )


def publication_receipt() -> PublicationReceiptDocument:
    return PublicationReceiptDocument(
        format="method-hub.publication-receipt",
        format_version="1.0.0",
        receipt_id="receipt.demo",
        project_id="project.demo",
        run_id="run.demo",
        command_id="command.demo",
        phase="P3",
        record_changes=[],
        cumulative_object_changes=[],
        authority_events=[],
        prior_authority_sequence=2,
        new_authority_sequence=3,
        prior_authority_root_sha256=SHA,
        new_authority_root_sha256="b" * 64,
        prior_current_revision=1,
        new_current_revision=2,
        atomic=True,
        published_at=NOW,
        content_sha256="c" * 64,
    )


class RecordingService:
    def __init__(self) -> None:
        self.raw_requests: list[RawRequestBody] = []
        self.calls: list[tuple[Any, ...]] = []
        self.reject_start = False
        self.events = [
            RunEvent(
                sequence=2,
                event_id="event.2",
                event_type="stage_started",
                state="running",
                stage_id="theorist",
                message="Theory work started.",
                occurred_at=NOW,
            ),
            RunEvent(
                sequence=3,
                event_id="event.3",
                event_type="heartbeat",
                state="running",
                stage_id="theorist",
                message="Theory work remains active.",
                occurred_at=NOW,
            ),
        ]

    async def preserve_raw_request(
        self, raw_request: RawRequestBody
    ) -> RawRequestReceipt:
        self.raw_requests.append(raw_request)
        return RawRequestReceipt(
            request_artifact_id=f"raw.{len(self.raw_requests)}",
            content_sha256=raw_request.content_sha256,
        )

    async def list_projects(self) -> list[ProjectSummary]:
        self.calls.append(("list_projects",))
        return [project_summary()]

    async def create_project(
        self, command: CreateProjectRequest, *, raw_request: RawRequestReceipt
    ) -> ProjectSummary:
        self.calls.append(("create_project", command, raw_request))
        return project_summary()

    async def get_project_brief(self, project_id: str) -> ProjectBriefView:
        self.calls.append(("get_project_brief", project_id))
        return project_brief_view()

    async def update_project_brief(
        self,
        project_id: str,
        command: UpdateProjectBriefRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProjectBriefView:
        self.calls.append(("update_project_brief", project_id, command, raw_request))
        return project_brief_view()

    async def get_system_settings(self) -> SystemSettingsView:
        self.calls.append(("get_system_settings",))
        return system_settings_view()

    async def get_project_overview(self, project_id: str) -> ProjectOverview:
        self.calls.append(("get_project_overview", project_id))
        return ProjectOverview(
            project=project_summary(),
            project_brief=project_brief_view(),
            methods=[],
            phases=[],
            active_runs=[],
            attention_items=[],
            storage={
                "storage_kind": "backend_managed",
                "open_folder_supported": False,
                "explanation": "No isolated project folder exists.",
            },
            actions=[],
            projection={"view_revision": 1, "projected_at": NOW},
        )

    async def get_phase_view(
        self,
        project_id: str,
        phase_id: PhaseId,
        *,
        mode: str | None,
        method_id: str | None,
    ) -> PhaseView:
        self.calls.append(
            ("get_phase_view", project_id, phase_id, mode, method_id)
        )
        return phase_view()

    async def list_methods(self, project_id: str) -> list[MethodRow]:
        self.calls.append(("list_methods", project_id))
        return []

    async def change_method_lifecycle(
        self,
        project_id: str,
        method_id: str,
        command: ReasonedActionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> None:
        self.calls.append(
            ("change_method_lifecycle", project_id, method_id, command, raw_request)
        )

    async def list_runs(
        self, project_id: str, *, phase: PhaseId | None
    ) -> list[RunSummary]:
        self.calls.append(("list_runs", project_id, phase))
        return []

    async def start_run(
        self,
        project_id: str,
        command: StartRunRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail:
        self.calls.append(("start_run", project_id, command, raw_request))
        if self.reject_start:
            raise CommandRejected(
                new_command_error(
                    "PUBLICATION_CONFLICT",
                    researcher_message="The selected current basis changed.",
                    smallest_correction="Refresh the phase view and prepare a new run.",
                    object_refs=[project_id],
                )
            )
        return run_detail()

    async def get_run(self, project_id: str, run_id: str) -> RunDetail:
        self.calls.append(("get_run", project_id, run_id))
        return run_detail()

    async def get_artifact(
        self, project_id: str, artifact_id: str
    ) -> ArtifactDelivery:
        self.calls.append(("get_artifact", project_id, artifact_id))
        return ArtifactDelivery(
            artifact_id=artifact_id,
            content=b'{"result":"verified"}\n',
            media_type="application/json",
            content_sha256=SHA,
            filename="artifact.demo.json",
        )

    async def get_publication_receipt(
        self, project_id: str, receipt_id: str
    ) -> PublicationReceiptDocument:
        self.calls.append(("get_publication_receipt", project_id, receipt_id))
        return publication_receipt()

    async def list_run_events(
        self, project_id: str, run_id: str, *, after_sequence: int
    ) -> list[RunEvent]:
        self.calls.append(("list_run_events", project_id, run_id, after_sequence))
        return [event for event in self.events if event.sequence > after_sequence]

    async def stream_run_events(
        self, project_id: str, run_id: str, *, after_sequence: int
    ) -> AsyncIterator[RunEvent]:
        self.calls.append(("stream_run_events", project_id, run_id, after_sequence))

        async def selected_events() -> AsyncIterator[RunEvent]:
            for event in self.events:
                if event.sequence > after_sequence:
                    yield event

        return selected_events()

    async def cancel_run(
        self,
        project_id: str,
        run_id: str,
        command: ReasonedActionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail:
        self.calls.append(("cancel_run", project_id, run_id, command, raw_request))
        return run_detail("cancellation_requested")

    async def request_output_correction(
        self,
        project_id: str,
        run_id: str,
        command: CorrectionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail:
        self.calls.append(
            ("request_output_correction", project_id, run_id, command, raw_request)
        )
        return run_detail("correcting")

    async def preview_output_correction(
        self,
        project_id: str,
        run_id: str,
        command: CorrectionPreviewRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> CorrectionPreviewView:
        self.calls.append(
            ("preview_output_correction", project_id, run_id, command, raw_request)
        )
        return CorrectionPreviewView(
            current_findings=[],
            remaining_findings=[],
            fixed_findings=[],
            transformations=[],
            passing=True,
        )

    async def get_profiles(self, project_id: str) -> ProfileConfigurationView:
        self.calls.append(("get_profiles", project_id))
        return profile_view()

    async def save_profile(
        self,
        project_id: str,
        role_id: str,
        command: SaveProfileRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProfileConfigurationView:
        self.calls.append(("save_profile", project_id, role_id, command, raw_request))
        return profile_view()

    async def install_skill(
        self,
        project_id: str,
        role_id: str,
        skill_id: str,
        command: InstallSkillRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProfileConfigurationView:
        self.calls.append(
            ("install_skill", project_id, role_id, skill_id, command, raw_request)
        )
        return profile_view()


def client_and_service() -> tuple[TestClient, RecordingService]:
    service = RecordingService()
    return TestClient(create_app(service)), service


def start_run_payload() -> dict[str, Any]:
    return {
        "action_descriptor_id": "action.start.p3",
        "phase": "P3",
        "mode": "p3.theory_establishment",
        "choice_values": {
            "method_id": "method.demo",
            "instructions": "Check the boundary case.",
        },
        "context_policy": "current_only",
        "selected_context_option_ids": [],
    }


def test_create_project_preserves_exact_bytes_before_typed_command() -> None:
    client, service = client_and_service()
    raw = (
        b'{"name":"Demo","research_question":"Which estimator is robust?",'
        b'"domains":["statistics"],"intended_use":"Method development"}'
    )

    response = client.post(
        "/api/v1/projects",
        content=raw,
        headers={"Content-Type": "application/json", "Idempotency-Key": "create-1"},
    )

    assert response.status_code == 201
    assert response.json()["project_id"] == "project.demo"
    captured = service.raw_requests[0]
    assert captured.body == raw
    assert captured.byte_length == len(raw)
    assert captured.command_family == "create_project"
    assert captured.idempotency_key == "create-1"
    assert service.calls[0][0] == "create_project"
    assert isinstance(service.calls[0][1], CreateProjectRequest)


def test_invalid_command_is_preserved_before_stable_schema_rejection() -> None:
    client, service = client_and_service()
    raw = (
        b'{"name":"Demo","research_question":"Question",'
        b'"domains":["statistics"],"intended_use":"Study","unexpected":true}'
    )

    response = client.post(
        "/api/v1/projects", content=raw, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "COMMAND_SCHEMA_INVALID"
    assert response.json()["rule_id"] == "MH-59"
    assert response.json()["retryable"] is True
    assert response.json()["field_path"] == "unexpected"
    assert service.raw_requests[0].body == raw
    assert not service.calls


def test_project_brief_and_system_settings_use_typed_shared_routes() -> None:
    client, service = client_and_service()

    settings = client.get("/api/v1/system/settings")
    brief = client.get("/api/v1/projects/project.demo/brief")
    updated = client.patch(
        "/api/v1/projects/project.demo/brief",
        json={
            "action_descriptor_id": "action.update.brief",
            "reason": "Narrow the scientific scope.",
            "scope": "Weak overlap with prespecified nuisance estimators.",
        },
    )

    assert settings.status_code == 200
    assert settings.json()["settings_editable_in_ui"] is False
    assert brief.status_code == 200
    assert brief.json()["generation_id"] == "generation.project_brief"
    assert updated.status_code == 200
    assert service.raw_requests[-1].command_family == "update_project_brief"
    assert isinstance(service.calls[-1][2], UpdateProjectBriefRequest)


def test_phase_view_returns_backend_action_without_client_eligibility_logic() -> None:
    client, service = client_and_service()

    response = client.get(
        "/api/v1/projects/project.demo/phases/P3",
        params={"mode": "p3.theory_establishment", "method_id": "method.demo"},
    )

    assert response.status_code == 200
    action = response.json()["actions"][0]
    assert action["enabled"] is False
    assert action["reason_code"] == "METHOD_NOT_SELECTED"
    assert "Select a current method" in action["researcher_message"]
    assert service.calls[-1] == (
        "get_phase_view",
        "project.demo",
        "P3",
        "p3.theory_establishment",
        "method.demo",
    )


def test_start_run_uses_typed_request_and_raw_receipt() -> None:
    client, service = client_and_service()

    response = client.post(
        "/api/v1/projects/project.demo/runs", json=start_run_payload()
    )

    assert response.status_code == 201
    assert response.json()["state"] == "created"
    assert service.raw_requests[-1].command_family == "start_run"
    call = service.calls[-1]
    assert call[0:2] == ("start_run", "project.demo")
    assert isinstance(call[2], StartRunRequest)
    assert isinstance(call[3], RawRequestReceipt)


def test_service_command_error_keeps_registered_http_mapping() -> None:
    client, service = client_and_service()
    service.reject_start = True

    response = client.post(
        "/api/v1/projects/project.demo/runs", json=start_run_payload()
    )

    payload = response.json()
    assert response.status_code == 409
    assert payload["code"] == "PUBLICATION_CONFLICT"
    assert payload["category"] == "concurrency"
    assert payload["rule_id"] == "MH-56"
    assert payload["researcher_message"] == "The selected current basis changed."


def test_polling_and_default_message_sse_use_same_event_model() -> None:
    client, service = client_and_service()

    polling = client.get(
        "/api/v1/projects/project.demo/runs/run.demo/events",
        params={"after_sequence": 2},
    )
    stream = client.get(
        "/api/v1/projects/project.demo/runs/run.demo/events/stream",
        params={"after_sequence": 1},
    )

    assert polling.status_code == 200
    assert [event["sequence"] for event in polling.json()] == [3]
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\n" in stream.text
    assert 'data: {"sequence":2' in stream.text
    assert "event:" not in stream.text
    assert ("list_run_events", "project.demo", "run.demo", 2) in service.calls
    assert ("stream_run_events", "project.demo", "run.demo", 1) in service.calls


def test_artifact_and_publication_links_deliver_immutable_resources() -> None:
    client, service = client_and_service()

    artifact = client.get(
        "/api/v1/projects/project.demo/artifacts/artifact.demo"
    )
    download = client.get(
        "/api/v1/projects/project.demo/artifacts/artifact.demo",
        params={"download": True},
    )
    receipt = client.get(
        "/api/v1/projects/project.demo/publications/receipt.demo"
    )

    assert artifact.status_code == 200
    assert artifact.content == b'{"result":"verified"}\n'
    assert artifact.headers["content-type"] == "application/json"
    assert artifact.headers["content-disposition"].startswith("inline;")
    assert artifact.headers["etag"] == f'"{SHA}"'
    assert artifact.headers["x-content-sha256"] == SHA
    assert artifact.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert receipt.status_code == 200
    assert receipt.json()["receipt_id"] == "receipt.demo"
    assert receipt.headers["etag"] == '"' + "c" * 64 + '"'
    assert ("get_artifact", "project.demo", "artifact.demo") in service.calls
    assert (
        "get_publication_receipt",
        "project.demo",
        "receipt.demo",
    ) in service.calls


def test_control_and_configuration_commands_all_preserve_raw_requests() -> None:
    client, service = client_and_service()

    lifecycle = client.post(
        "/api/v1/projects/project.demo/methods/method.demo/lifecycle",
        json={"action_descriptor_id": "action.retire", "reason": "Outside scope."},
    )
    cancellation = client.post(
        "/api/v1/projects/project.demo/runs/run.demo/cancel",
        json={"action_descriptor_id": "action.cancel", "reason": "Revise inputs."},
    )
    correction = client.post(
        "/api/v1/projects/project.demo/runs/run.demo/corrections",
        json={
            "correction_type": "revalidate",
            "permitted_output_scope": ["output.demo"],
            "action_descriptor_id": "action.correct",
        },
    )
    preview = client.post(
        "/api/v1/projects/project.demo/runs/run.demo/corrections/preview",
        json={"transformation_codes": ["timestamp_injection"]},
    )
    saved = client.patch(
        "/api/v1/projects/project.demo/configuration/profiles/theorist",
        json={
            "profile_id": "profile.theorist",
            "action_descriptor_id": "action.profile",
        },
    )
    installed = client.post(
        "/api/v1/projects/project.demo/configuration/profiles/theorist/skills/writing/install",
        json={"action_descriptor_id": "action.skill"},
    )

    assert lifecycle.status_code == 204
    assert cancellation.status_code == 200
    assert cancellation.json()["state"] == "cancellation_requested"
    assert correction.status_code == 200
    assert correction.json()["state"] == "correcting"
    assert preview.status_code == 200
    assert preview.json()["passing"] is True
    assert saved.status_code == 200
    assert installed.status_code == 200
    assert [item.command_family for item in service.raw_requests] == [
        "method_lifecycle",
        "cancel_run",
        "request_output_correction",
        "request_output_correction",
        "save_profile",
        "install_skill",
    ]


def test_openapi_lists_the_complete_frontend_route_surface() -> None:
    client, _service = client_and_service()

    paths = client.get("/openapi.json").json()["paths"]

    expected = {
        "/api/v1/projects",
        "/api/v1/system/settings",
        "/api/v1/projects/{project_id}/brief",
        "/api/v1/projects/{project_id}/overview",
        "/api/v1/projects/{project_id}/phases/{phase_id}",
        "/api/v1/projects/{project_id}/methods",
        "/api/v1/projects/{project_id}/methods/{method_id}/lifecycle",
        "/api/v1/projects/{project_id}/runs",
        "/api/v1/projects/{project_id}/runs/{run_id}",
        "/api/v1/projects/{project_id}/runs/{run_id}/events",
        "/api/v1/projects/{project_id}/runs/{run_id}/events/stream",
        "/api/v1/projects/{project_id}/runs/{run_id}/cancel",
        "/api/v1/projects/{project_id}/runs/{run_id}/corrections",
        "/api/v1/projects/{project_id}/runs/{run_id}/corrections/preview",
        "/api/v1/projects/{project_id}/artifacts/{artifact_id}",
        "/api/v1/projects/{project_id}/publications/{receipt_id}",
        "/api/v1/projects/{project_id}/configuration/profiles",
        "/api/v1/projects/{project_id}/configuration/profiles/{role_id}",
        "/api/v1/projects/{project_id}/configuration/profiles/{role_id}/skills/{skill_id}/install",
    }
    assert expected <= set(paths)
