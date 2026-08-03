"""Direct scientific task briefs rendered from frozen contract data."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from ..contracts import ResolvedPhasePlan, ResolvedStage
from .outputs import OutputPlan


def render_task_brief(
    *,
    run_id: str,
    project_id: str,
    plan: ResolvedPhasePlan,
    stage: ResolvedStage,
    role: str,
    input_paths: Mapping[str, str],
    output_plan: OutputPlan,
    phase_instruction: str,
    scientific_stance: str = "",
    same_group_roles: Sequence[str] = (),
) -> str:
    """Render one bounded role assignment without software-manual prose."""

    role_step = stage.step_for(role)
    specs = output_plan.for_stage_role(stage.stage_id, role)
    missing = set(role_step.input_ids) - set(input_paths)
    if missing:
        raise ValueError(
            f"Task brief is missing resolved inputs for {sorted(missing)}."
        )
    lines = [
        f"# {stage.stage_id}: {role}",
        "",
        f"Run: `{run_id}`",
        f"Project: `{project_id}`",
        f"Phase and mode: `{plan.identity.phase_id}` / `{plan.mode_id}`",
        "",
        "## Scientific objective",
        "",
        stage.objective.strip(),
        "",
        "## User direction",
        "",
        phase_instruction.strip(),
    ]
    if scientific_stance.strip():
        lines.extend(["", "## Role stance", "", scientific_stance.strip()])
    lines.extend(["", "## Frozen inputs", ""])
    for input_id in role_step.input_ids:
        lines.append(f"- `{input_id}`: `{input_paths[input_id]}`")
    if stage.execution == "parallel" and same_group_roles:
        peers = ", ".join(f"`{item}`" for item in same_group_roles if item != role)
        lines.extend(
            [
                "",
                "## Parallel-group boundary",
                "",
                "This stage uses a common frozen basis. Do not read outputs from "
                f"same-group roles ({peers or 'none'}). Their work is reconciled only "
                "after every role in this group closes.",
            ]
        )
    lines.extend(["", "## Required outputs", ""])
    for spec in specs:
        shape = "JSON array" if spec.schema_application == "each_item" else "JSON object"
        lines.append(
            f"- `{spec.contract_output_id}`: `{spec.relative_path}`; {shape}; "
            f"schema `{spec.schema_file}`."
        )
    lines.extend(
        [
            "",
            "## Execution boundary",
            "",
            "Work only on this role assignment. Write only the declared outputs and "
            "their explicitly referenced supporting artifacts inside this role workspace.",
            "Do not start another role, rerun, phase, or publication operation.",
            "Do not retry failed scientific work under this invocation. Report the failure "
            "and its smallest actionable cause.",
            "A negative, null, contradictory, or inconclusive scientific result is a valid "
            "result when it is accurately documented. Do not relabel it as an execution failure.",
            "",
            "The output schema establishes structure and provenance. It does not establish "
            "that a theorem is true or that an empirical interpretation is correct.",
            "",
            "Resolved choices:",
            "",
            "```json",
            json.dumps(dict(plan.choice_values), ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["render_task_brief"]
