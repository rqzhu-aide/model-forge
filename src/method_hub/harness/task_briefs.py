"""Direct scientific task briefs rendered from frozen contract data."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..schemas import SchemaCatalog
from .outputs import OutputPlan


def _resolve_ref(
    ref: str, catalog: SchemaCatalog, current_file: str = ""
) -> tuple[dict[str, Any], str]:
    """Resolve a ``$ref`` and return ``(resolved_schema, source_file)``."""
    if "#" not in ref:
        return {}, current_file
    file_part, pointer = ref.split("#", 1)
    if not file_part:
        file_part = current_file
    if not file_part:
        return {}, current_file
    parts = [p for p in pointer.strip("/").split("/") if p]
    schema: Any = catalog.get(file_part)
    for part in parts:
        if not isinstance(schema, dict) or part not in schema:
            return {}, file_part
        schema = schema[part]
    return (schema if isinstance(schema, dict) else {}), file_part


_PATTERN_HINTS = {
    "^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$": "lowercase kebab-case (e.g. `source.garbuno_2020`)",
    "^[a-f0-9]{64}$": "64-char hex digest",
    "^(artifact|generation|run)://[^\\s]+$": "URI like `artifact://...`",
}


def _pattern_hint(pattern: str) -> str:
    return _PATTERN_HINTS.get(pattern, "")


def _summarise_property(
    name: str,
    prop: dict[str, Any],
    catalog: SchemaCatalog,
    indent: int = 2,
    current_file: str = "",
) -> list[str]:
    """Render one property's constraints, recursing into nested objects/arrays."""
    if "$ref" in prop:
        prop, current_file = _resolve_ref(prop["$ref"], catalog, current_file)

    prefix = " " * indent
    parts: list[str] = []
    lines: list[str] = []

    if "const" in prop:
        parts.append(f"must be `{json.dumps(prop['const'], ensure_ascii=False)}`")
    elif "enum" in prop:
        values = ", ".join(f"`{v}`" for v in prop["enum"])
        parts.append(f"one of {values}")

    ptype = prop.get("type")
    if ptype == "string" and "const" not in prop and "enum" not in prop:
        parts.append("string")
    elif ptype == "integer":
        parts.append("integer")
    elif ptype == "array":
        items = prop.get("items", {})
        if isinstance(items, dict):
            if "$ref" in items:
                items, current_file = _resolve_ref(items["$ref"], catalog, current_file)
            if items.get("type") == "object" and items.get("properties"):
                parts.append("array of objects, each with:")
            elif items.get("type") == "string":
                parts.append("array of strings")
                if "pattern" in items:
                    hint = _pattern_hint(items["pattern"])
                    extra = f" ({hint})" if hint else ""
                    parts.append(f"each matching `{items['pattern']}`{extra}")
            else:
                parts.append("array")
        else:
            parts.append("array")
    elif ptype == "object" and prop.get("properties"):
        parts.append("object with fields:")
    elif ptype == "object":
        parts.append("object")

    if "pattern" in prop:
        hint = _pattern_hint(prop["pattern"])
        extra = f" ({hint})" if hint else ""
        parts.append(f"pattern `{prop['pattern']}`{extra}")
    if "minLength" in prop:
        parts.append(f"min length {prop['minLength']}")
    if "maxLength" in prop:
        parts.append(f"max length {prop['maxLength']}")

    detail = "; ".join(parts) if parts else "free-form"
    lines.append(f"{prefix}- `{name}`: {detail}")

    # Recurse into nested object properties
    if ptype == "object" and prop.get("properties"):
        nested_required = set(prop.get("required", []))
        for sub_name in sorted(prop["properties"]):
            sub_marker = "required" if sub_name in nested_required else "optional"
            sub_lines = _summarise_property(
                sub_name, prop["properties"][sub_name], catalog, indent + 4, current_file
            )
            if sub_lines:
                sub_lines[0] = sub_lines[0] + f" ({sub_marker})"
            lines.extend(sub_lines)

    # Recurse into array-of-object item properties
    if ptype == "array":
        items = prop.get("items", {})
        if isinstance(items, dict):
            if "$ref" in items:
                items, current_file = _resolve_ref(items["$ref"], catalog, current_file)
            if items.get("type") == "object" and items.get("properties"):
                nested_required = set(items.get("required", []))
                for sub_name in sorted(items["properties"]):
                    sub_marker = "required" if sub_name in nested_required else "optional"
                    sub_lines = _summarise_property(
                        sub_name, items["properties"][sub_name], catalog, indent + 4, current_file
                    )
                    if sub_lines:
                        sub_lines[0] = sub_lines[0] + f" ({sub_marker})"
                    lines.extend(sub_lines)

    return lines


def _render_schema_constraints(
    schema_file: str,
    catalog: SchemaCatalog,
) -> str:
    """Render a compact field-constraint block for a JSON schema."""
    if not hasattr(catalog, "get"):
        return ""
    schema = catalog.get(schema_file)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    if not properties:
        return ""
    lines: list[str] = []
    for name in sorted(properties):
        marker = "required" if name in required else "optional"
        prop_lines = _summarise_property(name, properties[name], catalog, current_file=schema_file)
        if prop_lines:
            prop_lines[0] = prop_lines[0] + f" ({marker})"
        lines.extend(prop_lines)
    return "\n".join(lines)


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
    schema_catalog: SchemaCatalog | None = None,
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
        if schema_catalog is not None:
            constraints = _render_schema_constraints(spec.schema_file, schema_catalog)
            if constraints:
                lines.append("")
                lines.append(constraints)
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
