from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from model_forge.orchestration import StageStatus

from test_stage_execution_service import Fixture


def test_nested_frozen_method_choice_renders_in_role_brief(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    plan = replace(
        fixture.plan,
        choice_values=MappingProxyType(
            {
                "p4.selected_method": MappingProxyType(
                    {
                        "stable_id": "method.fixture",
                        "version": 1,
                        "definition_sha256": "a" * 64,
                    }
                ),
                "p4.instructions": "Use the exact selected method.",
            }
        ),
    )
    fixture.context = replace(fixture.context, plan=plan)
    fixture.plan = plan
    fixture.services = fixture.new_services(fixture.executor)

    outcome = fixture.execute_stage(0)

    assert outcome.status is StageStatus.SUCCEEDED
    brief = fixture.executor.invocations[0].task_brief.read_text(encoding="utf-8")
    assert '"stable_id": "method.fixture"' in brief
