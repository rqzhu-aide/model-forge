from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from method_hub.api.models import CreateProjectRequest, StartRunRequest
from method_hub.api.ports import RawRequestBody
from method_hub.application.bootstrap import build_service
from method_hub.application.settings import ApplicationSettings


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def _raw(
    body: bytes,
    *,
    family: str,
    key: str,
    project_id: str | None = None,
) -> RawRequestBody:
    return RawRequestBody(
        body=body,
        byte_length=len(body),
        media_type="application/json",
        content_sha256=hashlib.sha256(body).hexdigest(),
        method="POST",
        path="/api/v1/projects",
        command_family=family,  # type: ignore[arg-type]
        project_id=project_id,
        idempotency_key=key,
    )


def test_fake_phase_one_run_preserves_payload_and_publishes(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = build_service(
            ApplicationSettings(
                data_root=tmp_path / "data",
                architecture_root=ARCHITECTURE,
                executor_kind="fake",
                development_mode=True,
                frontend_dist=tmp_path / "missing-web",
            )
        )
        create = CreateProjectRequest(
            name="Coordinator test",
            research_question="Which method remains reliable under weak overlap?",
            domains=["statistics", "machine learning"],
            intended_use="Develop and assess a statistical method.",
        )
        create_bytes = json.dumps(create.model_dump()).encode("utf-8")
        create_receipt = await service.preserve_raw_request(
            _raw(create_bytes, family="create_project", key="create-project-e2e")
        )
        project = await service.create_project(create, raw_request=create_receipt)
        phase = await service.get_phase_view(
            project.project_id,
            "P1",
            mode="p1.literature_update",
            method_id=None,
        )
        action = next(item for item in phase.actions if item.action_type == "start_run")
        assert action.enabled is True
        selected = [
            item.option_id for item in phase.run_configuration.current_inputs
        ]
        command = StartRunRequest(
            action_descriptor_id=action.descriptor_id,
            phase="P1",
            mode="p1.literature_update",
            choice_values={
                "p1.scope": "broad_update",
                "p1.instructions": "Update the literature basis and state coverage limits.",
                "p1.selected_history": [],
            },
            context_policy="current_only",
            selected_context_option_ids=selected,
        )
        command_bytes = json.dumps(command.model_dump()).encode("utf-8")
        command_receipt = await service.preserve_raw_request(
            _raw(
                command_bytes,
                family="start_run",
                key="start-p1-e2e",
                project_id=project.project_id,
            )
        )
        started = await service.start_run(
            project.project_id, command, raw_request=command_receipt
        )
        detail = started
        for _ in range(200):
            detail = await service.get_run(project.project_id, started.run_id)
            if detail.state in {
                "published",
                "failed",
                "rejected",
                "conflicted",
                "cancelled",
            }:
                break
            await asyncio.sleep(0.025)

        assert detail.state == "published", detail.terminal_reason
        assert detail.phase == "P1"
        assert detail.mode == "p1.literature_update"
        assert detail.requested_by == "researcher.local"
        assert detail.publication_receipt is not None
        record_types = {
            str(row["record_type"])
            for row in service.repository.list_current_records(project.project_id)
        }
        assert {
            "project_brief",
            "literature_library",
            "literature_synthesis",
            "literature_coverage",
            "phase_decision",
        }.issubset(record_types)

    asyncio.run(scenario())


def test_fake_pipeline_requires_explicit_runs_and_parallel_phase_completion(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        service = build_service(
            ApplicationSettings(
                data_root=tmp_path / "data",
                architecture_root=ARCHITECTURE,
                executor_kind="fake",
                development_mode=True,
                frontend_dist=tmp_path / "missing-web",
            )
        )
        create = CreateProjectRequest(
            name="Complete fake pipeline",
            research_question="Which method remains reliable under weak overlap?",
            domains=["statistics", "machine learning"],
            intended_use="Develop, assess, and report a statistical method.",
        )
        create_bytes = json.dumps(create.model_dump()).encode("utf-8")
        create_receipt = await service.preserve_raw_request(
            _raw(create_bytes, family="create_project", key="create-full-e2e")
        )
        project = await service.create_project(create, raw_request=create_receipt)

        async def launch(
            *,
            phase: str,
            mode: str,
            choices: dict[str, object],
            key: str,
            method_id: str | None = None,
        ):
            view = await service.get_phase_view(
                project.project_id,
                phase,  # type: ignore[arg-type]
                mode=mode,
                method_id=method_id,
            )
            action = next(
                item for item in view.actions if item.action_type == "start_run"
            )
            assert action.enabled is True, action.researcher_message
            command = StartRunRequest(
                action_descriptor_id=action.descriptor_id,
                phase=phase,  # type: ignore[arg-type]
                mode=mode,
                choice_values=choices,
                context_policy="current_only",
                selected_context_option_ids=[
                    item.option_id for item in view.run_configuration.current_inputs
                ],
            )
            command_bytes = json.dumps(command.model_dump()).encode("utf-8")
            receipt = await service.preserve_raw_request(
                _raw(
                    command_bytes,
                    family="start_run",
                    key=key,
                    project_id=project.project_id,
                )
            )
            started = await service.start_run(
                project.project_id, command, raw_request=receipt
            )
            detail = started
            for _ in range(400):
                detail = await service.get_run(project.project_id, started.run_id)
                if detail.state in {
                    "published",
                    "failed",
                    "rejected",
                    "conflicted",
                    "cancelled",
                }:
                    break
                await asyncio.sleep(0.025)
            assert detail.state == "published", detail.terminal_reason
            return detail

        await launch(
            phase="P1",
            mode="p1.literature_update",
            choices={
                "p1.scope": "broad_update",
                "p1.instructions": "Establish the literature basis and its limits.",
                "p1.selected_history": [],
            },
            key="start-full-p1",
        )
        assert await service.list_runs(project.project_id, phase=None)
        assert not await service.list_methods(project.project_id)

        await launch(
            phase="P1",
            mode="p1.literature_update",
            choices={
                "p1.scope": "focused_update",
                "p1.instructions": "Reassess the most decision-relevant literature gap.",
                "p1.selected_history": [],
            },
            key="start-full-p1-rerun",
        )
        phase_one_after_rerun = await service.get_phase_view(
            project.project_id,
            "P1",
            mode="p1.literature_update",
            method_id=None,
        )
        assert phase_one_after_rerun.run_configuration.history_options
        assert all(
            not item.selected_by_default
            for item in phase_one_after_rerun.run_configuration.history_options
        )
        assert phase_one_after_rerun.assessment.attention_count

        await launch(
            phase="P2",
            mode="p2.full_catalog",
            choices={
                "p2.instructions": "Develop the feasible method catalog.",
                "p2.selected_history": [],
            },
            key="start-full-p2",
        )
        methods = await service.list_methods(project.project_id)
        assert len(methods) == 1
        method = methods[0]
        method_choice = method.identity.model_dump()
        method_id = method.identity.stable_id

        phase_three = await service.get_phase_view(
            project.project_id,
            "P3",
            mode="p3.theory_establishment",
            method_id=method_id,
        )
        phase_four = await service.get_phase_view(
            project.project_id,
            "P4",
            mode="p4.preliminary",
            method_id=method_id,
        )
        assert next(
            item for item in phase_three.actions if item.action_type == "start_run"
        ).enabled is True
        assert next(
            item for item in phase_four.actions if item.action_type == "start_run"
        ).enabled is True

        await launch(
            phase="P4",
            mode="p4.preliminary",
            choices={
                "p4.selected_method": method_choice,
                "p4.instructions": "Run the preliminary empirical assessment.",
                "p4.selected_history": [],
            },
            key="start-full-p4",
            method_id=method_id,
        )
        phase_four_current = await service.get_phase_view(
            project.project_id,
            "P4",
            mode="p4.preliminary",
            method_id=method_id,
        )
        assert phase_four_current.current_record is not None
        assert phase_four_current.decision_brief is not None
        assert phase_four_current.evidence
        assert len(phase_four_current.artifacts) == 4
        overview_after_p4 = await service.get_project_overview(project.project_id)
        phase_four_summary = next(
            item for item in overview_after_p4.phases if item.phase_id == "P4"
        )
        assert phase_four_summary.formal_record_count == 4
        assert phase_four_summary.method_scoped_record_count == 1
        assert overview_after_p4.attention_items

        phase_five_before_theory = await service.get_phase_view(
            project.project_id,
            "P5",
            mode="p5.assembly",
            method_id=method_id,
        )
        p5_action = next(
            item
            for item in phase_five_before_theory.actions
            if item.action_type == "start_run"
        )
        assert p5_action.enabled is False
        assert p5_action.reason_code == "input.required_current_record_missing"
        assert "theory_record" in str(p5_action.researcher_message)

        await launch(
            phase="P3",
            mode="p3.theory_establishment",
            choices={
                "p3.selected_method": method_choice,
                "p3.instructions": "Develop and check the current theoretical argument.",
                "p3.selected_history": [],
            },
            key="start-full-p3",
            method_id=method_id,
        )
        phase_five = await service.get_phase_view(
            project.project_id,
            "P5",
            mode="p5.assembly",
            method_id=method_id,
        )
        assert next(
            item for item in phase_five.actions if item.action_type == "start_run"
        ).enabled is True

        phase_five_run = await launch(
            phase="P5",
            mode="p5.assembly",
            choices={
                "p5.selected_method": method_choice,
                "p5.instructions": "Assemble the current formal research record.",
                "p5.selected_history": [],
            },
            key="start-full-p5",
            method_id=method_id,
        )
        assert phase_five_run.publication_receipt is not None
        assert [
            item.phase
            for item in await service.list_runs(project.project_id, phase=None)
        ] == ["P5", "P3", "P4", "P2", "P1", "P1"]

    asyncio.run(scenario())
