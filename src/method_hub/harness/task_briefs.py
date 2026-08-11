"""Direct scientific task briefs rendered from frozen contract data."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
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
    elif "oneOf" in prop:
        # Render discriminated unions: each variant has a const "kind" field
        variants: list[str] = []
        for v in prop["oneOf"]:
            vprops = v.get("properties", {})
            vkind = vprops.get("kind", {}).get("const", "")
            vrequired = [f for f in v.get("required", []) if f != "kind"]
            if vkind and vrequired:
                variants.append(f"{{kind: `{vkind}`, requires: {', '.join(f'`{r}`' for r in vrequired)}}}")
            elif vkind:
                variants.append(f"{{kind: `{vkind}`}}")
        if variants:
            parts.append("one of: " + "; ".join(variants))

    ptype = prop.get("type")
    if ptype == "string" and "const" not in prop and "enum" not in prop:
        parts.append("string")
    elif ptype == "integer":
        parts.append("integer")
    elif ptype == "boolean":
        parts.append("boolean")
    elif ptype == "array":
        items = prop.get("items", {})
        if isinstance(items, dict):
            if "$ref" in items:
                items, current_file = _resolve_ref(items["$ref"], catalog, current_file)
            if items.get("type") == "object" and items.get("properties"):
                parts.append("array of objects, each with:")
            elif items.get("type") == "string":
                parts.append("array of strings")
                if "enum" in items:
                    values = ", ".join(f"`{v}`" for v in items["enum"])
                    parts.append(f"each one of {values}")
                if "pattern" in items:
                    hint = _pattern_hint(items["pattern"])
                    extra = f" ({hint})" if hint else ""
                    parts.append(f"each matching `{items['pattern']}`{extra}")
            elif items.get("type") == "boolean":
                parts.append("array of booleans")
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

    # Surface conditional requirements and prohibitions from if/then/else
    # rules so agents include fields only when their trigger condition
    # actually holds, and never include fields an else branch forbids.
    conditional = _extract_conditional_requirements(schema)
    if conditional:
        lines.append("")
        lines.append("Conditional fields (include only when the stated condition holds; omit otherwise):")
        for entry in conditional:
            field = entry["field"]
            if entry["condition"] and entry["prohibited_when"]:
                lines.append(
                    f"- `{field}` — required only when: {entry['condition']}; "
                    f"do NOT include when: {entry['prohibited_when']}"
                )
            elif entry["condition"]:
                lines.append(f"- `{field}` — required only when: {entry['condition']}")
            else:
                lines.append(f"- `{field}` — do NOT include when: {entry['prohibited_when']}")

    return "\n".join(lines)


def _describe_condition(if_block: dict[str, Any]) -> str:
    """Render a human-readable description of an if-block's conditions."""
    parts: list[str] = []
    props = if_block.get("properties", {})
    for field, constraint in props.items():
        if "const" in constraint:
            parts.append(f"`{field}` is `{constraint['const']}`")
        elif "enum" in constraint:
            vals = ", ".join(f"`{v}`" for v in constraint["enum"])
            parts.append(f"`{field}` is one of ({vals})")
    return "; AND ".join(parts) if parts else "always"


def _describe_else_condition(if_block: dict[str, Any]) -> str:
    """Render the condition under which an ``else`` branch applies.

    The ``if`` block is a conjunction of property constraints, so its
    negation is the disjunction of the per-property negations (De Morgan).
    """
    parts: list[str] = []
    props = if_block.get("properties", {})
    for field, constraint in props.items():
        if "const" in constraint:
            parts.append(f"`{field}` is not `{constraint['const']}`")
        elif "enum" in constraint:
            vals = ", ".join(f"`{v}`" for v in constraint["enum"])
            parts.append(f"`{field}` is none of ({vals})")
    return "; OR ".join(parts) if parts else "never"


def _extract_prohibited_fields(block: Any) -> set[str]:
    """Collect field names an ``else`` block forbids.

    Handles the common ``not: {anyOf: [{required: [...]}, ...]}`` shape
    used to forbid fields when the ``if`` condition does not hold.
    """
    fields: set[str] = set()
    if not isinstance(block, dict):
        return fields
    required = block.get("required")
    if isinstance(required, list):
        fields.update(f for f in required if isinstance(f, str))
    for key in ("not", "anyOf", "allOf", "oneOf"):
        value = block.get(key)
        if isinstance(value, dict):
            fields |= _extract_prohibited_fields(value)
        elif isinstance(value, list):
            for item in value:
                fields |= _extract_prohibited_fields(item)
    return fields


def _load_schema_example(schema_file: str) -> str | None:
    """Load a compact JSON example for a schema, if one exists.

    Identity-bearing fields (``*_id``, ``run_id``, ``stable_id``,
    ``*_sha256``, timestamps) are replaced with ``<...>`` placeholders so
    agents do not copy concrete example identities into real outputs.
    """
    from pathlib import Path as _Path

    examples_dir = _Path(__file__).resolve().parents[3] / "architecture" / "examples"
    stem = schema_file.replace(".schema.json", "")
    # Try exact match, then stem-based match
    candidates = [
        examples_dir / f"{stem}.example.json",
        examples_dir / f"{stem}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            import json as _json

            try:
                data = _json.loads(candidate.read_text())
                # Neutralize identity-bearing fields so agents don't
                # copy concrete example values into real outputs.
                data = _neutralize_identities(data)
                # For array outputs, wrap in array
                compact = _json.dumps(data, indent=2, ensure_ascii=False)
                if len(compact) > 1500:
                    compact = compact[:1500] + "\n  ... (truncated)"
                return compact
            except Exception:
                pass
    return None


_ID_BEARING_SUFFIXES = ("_id", "_sha256")
_ID_BEARING_KEYS = frozenset({
    "run_id", "stable_id", "project_id", "artifact_id",
    "generation_id", "command_id", "request_id", "manifest_id",
    "definition_sha256", "content_sha256",
    "sha256",  # bare sha256 keys in artifact pointers, evidence artifacts
    "created_at", "updated_at", "published_at", "sealed_at",
    "assessed_at",  # nested timestamp in alignmentAssessment
})


def _neutralize_identities(obj: Any) -> Any:
    """Recursively replace identity-bearing values with ``<...>`` placeholders."""
    if isinstance(obj, dict):
        result = {}
        for key, val in obj.items():
            if (
                key in _ID_BEARING_KEYS
                or any(key.endswith(suffix) for suffix in _ID_BEARING_SUFFIXES)
            ):
                result[key] = "<...>"
            else:
                result[key] = _neutralize_identities(val)
        return result
    if isinstance(obj, list):
        return [_neutralize_identities(item) for item in obj]
    return obj


def _extract_conditional_requirements(schema: dict[str, Any]) -> list[dict[str, str | None]]:
    """Extract conditional field requirements and prohibitions from if/then/else rules.

    Each returned entry has:
    - ``field``: the field name
    - ``condition``: when the field is required (``None`` if never required)
    - ``prohibited_when``: when the field must NOT be included (``None`` if never prohibited)

    Fields named in an ``else`` branch (via ``not``/``anyOf``/``required``)
    are recorded as prohibitions so agents are never told to write fields
    the schema forbids under the same condition.
    """
    entries: dict[str, dict[str, str | None]] = {}
    for rule in schema.get("allOf", []):
        if_block = rule.get("if", {})
        if not isinstance(if_block, dict) or not if_block:
            continue
        condition = _describe_condition(if_block)
        then_block = rule.get("then", {})
        then_required = (
            then_block.get("required", []) if isinstance(then_block, dict) else []
        )
        else_block = rule.get("else")
        else_condition = (
            _describe_else_condition(if_block) if isinstance(else_block, dict) else None
        )
        prohibited = _extract_prohibited_fields(else_block)
        for field in then_required:
            entry = entries.setdefault(
                field, {"field": field, "condition": None, "prohibited_when": None}
            )
            if entry["condition"]:
                entry["condition"] = f"{entry['condition']}; OR {condition}"
            else:
                entry["condition"] = condition
            if field in prohibited and else_condition:
                if entry["prohibited_when"]:
                    entry["prohibited_when"] = (
                        f"{entry['prohibited_when']}; OR {else_condition}"
                    )
                else:
                    entry["prohibited_when"] = else_condition
        for field in sorted(prohibited - set(then_required)):
            entry = entries.setdefault(
                field, {"field": field, "condition": None, "prohibited_when": None}
            )
            if entry["prohibited_when"]:
                entry["prohibited_when"] = (
                    f"{entry['prohibited_when']}; OR {else_condition}"
                )
            else:
                entry["prohibited_when"] = else_condition
    return list(entries.values())


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
    researcher_method_spec: str = "",
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
        f"Current timestamp for `created_at`/`updated_at` fields: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Scientific objective",
        "",
        stage.objective.strip(),
        "",
        "## User direction",
        "",
        phase_instruction.strip(),
    ]
    if researcher_method_spec.strip():
        lines.extend([
            "",
            "## Researcher-proposed method specification",
            "",
            "The researcher has provided the following method for evaluation. "
            "Evaluate this proposal — do NOT propose alternative methods. "
            "Assess its mathematical soundness, computational feasibility, and "
            "scientific novelty relative to the current catalog. If the method "
            "is valid and distinct, the lead should register it in the catalog.",
            "",
            "---",
            "",
            researcher_method_spec.strip(),
            "",
            "---",
        ])
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
    lines.append(
        "For optional fields: omit the field entirely if you have no value. "
        "Do not write `null` for optional object or array fields."
    )
    lines.append("")
    for spec in specs:
        shape = "JSON array" if spec.schema_application == "each_item" else "JSON object"
        output_filename = Path(spec.relative_path).name
        lines.append(
            f"- `{spec.contract_output_id}`: `{output_filename}`; {shape}; "
            f"schema `{spec.schema_file}`."
        )
        if schema_catalog is not None:
            constraints = _render_schema_constraints(spec.schema_file, schema_catalog)
            if constraints:
                lines.append("")
                lines.append(constraints)
            # Include a compact example to anchor the agent on the correct structure
            example = _load_schema_example(spec.schema_file)
            if example:
                lines.append("")
                if spec.schema_application == "each_item":
                    lines.append(
                        "Template (the output file must be a JSON array; "
                        "each element follows this shape — fill with real values, "
                        "preserve structure):"
                    )
                    lines.append("```json")
                    lines.append("[")
                    lines.append(example)
                    lines.append("]")
                    lines.append("```")
                else:
                    lines.append("Template (fill with real values, preserve structure):")
                    lines.append("```json")
                    lines.append(example)
                    lines.append("```")
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
