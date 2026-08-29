"""Direct scientific task briefs rendered from frozen contract data."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..schemas import SchemaCatalog
from .envelope import agent_authored_fields, harness_owned_fields
from .outputs import OutputPlan


def _resolve_ref(
    ref: str, catalog: SchemaCatalog, current_file: str = ""
) -> tuple[dict[str, Any], str]:
    """Resolve a ``$ref`` and return ``(resolved_schema, source_file)``."""
    if "#" in ref:
        file_part, pointer = ref.split("#", 1)
    else:
        file_part, pointer = ref, ""
    if not file_part:
        file_part = current_file
    if not file_part:
        return {}, current_file
    parts = [p for p in pointer.strip("/").split("/") if p]
    schema: Any = catalog.get(file_part)
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
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


def _load_fixture_example(schema_file: str) -> str | None:
    """Load a neutralized fixture only for callers without a schema catalog.

    Runtime task briefs use schema-derived skeletons instead.
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
                compact = _json.dumps(data, indent=2, ensure_ascii=False)
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


_STRUCTURAL_SCHEMA_KEYS = frozenset({
    "$ref",
    "allOf",
    "anyOf",
    "const",
    "contains",
    "enum",
    "items",
    "oneOf",
    "prefixItems",
    "properties",
    "required",
    "type",
})
_CONDITIONAL_SCHEMA_KEYS = frozenset({"if", "then", "else"})


def _has_structure(schema: Mapping[str, Any]) -> bool:
    return bool(_STRUCTURAL_SCHEMA_KEYS.intersection(schema))


def _is_conditional_schema(schema: Mapping[str, Any]) -> bool:
    return bool(_CONDITIONAL_SCHEMA_KEYS.intersection(schema))


def _contains_literal_structure(schema: Any) -> bool:
    """Return whether a property carries a const/enum structural cue."""
    if not isinstance(schema, Mapping):
        return False
    if "const" in schema or "enum" in schema:
        return True
    for key in ("contains", "allOf", "anyOf", "oneOf"):
        value = schema.get(key)
        if isinstance(value, Mapping) and _contains_literal_structure(value):
            return True
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if any(_contains_literal_structure(item) for item in value):
                return True
    return False


def _combine_skeletons(base: Any, overlay: Any) -> Any:
    if base is None:
        return overlay
    if overlay is None:
        return base
    if isinstance(base, dict) and isinstance(overlay, dict):
        combined = dict(base)
        for key, value in overlay.items():
            combined[key] = _combine_skeletons(combined.get(key), value)
        return combined
    return overlay


def _enum_placeholder(values: Sequence[Any]) -> str:
    rendered = [
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for value in values
    ]
    return f"<one of: {' | '.join(rendered)}>"


def _scalar_placeholder(name: str, schema: Mapping[str, Any]) -> str:
    value_format = schema.get("format")
    if isinstance(value_format, str) and value_format:
        return f"<{value_format}>"
    pattern = schema.get("pattern")
    if pattern == "^[a-f0-9]{64}$":
        return "<64-character hexadecimal digest>"
    return f"<{name or 'string'}>"


def _schema_skeleton(
    schema: Mapping[str, Any],
    catalog: SchemaCatalog,
    *,
    current_file: str,
    field_name: str = "",
    seen_refs: frozenset[tuple[str, str]] = frozenset(),
    depth: int = 0,
) -> Any:
    """Build parseable, scientifically neutral JSON guidance from a schema."""
    if depth > 32:
        return f"<{field_name or 'value'}>"
    if not isinstance(schema, Mapping):
        return f"<{field_name or 'value'}>"

    reference = schema.get("$ref")
    if isinstance(reference, str):
        ref_key = (current_file, reference)
        if ref_key in seen_refs:
            return {}
        resolved, source_file = _resolve_ref(reference, catalog, current_file)
        if not resolved:
            return f"<{field_name or 'value'}>"
        base = _schema_skeleton(
            resolved,
            catalog,
            current_file=source_file,
            field_name=field_name,
            seen_refs=seen_refs | {ref_key},
            depth=depth + 1,
        )
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        if _has_structure(siblings):
            overlay = _schema_skeleton(
                siblings,
                catalog,
                current_file=current_file,
                field_name=field_name,
                seen_refs=seen_refs,
                depth=depth + 1,
            )
            return _combine_skeletons(base, overlay)
        return base

    if "const" in schema:
        return schema["const"]
    enum_values = schema.get("enum")
    if isinstance(enum_values, Sequence) and not isinstance(enum_values, (str, bytes)):
        return _enum_placeholder(enum_values)

    for union_key in ("oneOf", "anyOf"):
        variants = schema.get(union_key)
        if isinstance(variants, Sequence) and not isinstance(variants, (str, bytes)):
            candidates = [item for item in variants if isinstance(item, Mapping)]
            preferred = next(
                (item for item in candidates if item.get("type") != "null"),
                candidates[0] if candidates else None,
            )
            if preferred is not None:
                return _schema_skeleton(
                    preferred,
                    catalog,
                    current_file=current_file,
                    field_name=field_name,
                    seen_refs=seen_refs,
                    depth=depth + 1,
                )

    schema_type = schema.get("type")
    if isinstance(schema_type, Sequence) and not isinstance(schema_type, (str, bytes)):
        schema_type = next((item for item in schema_type if item != "null"), "null")
    if not isinstance(schema_type, str):
        if isinstance(schema.get("properties"), Mapping) or "required" in schema:
            schema_type = "object"
        elif "items" in schema or "prefixItems" in schema:
            schema_type = "array"

    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            properties = {}
        required = [
            item for item in schema.get("required", ()) if isinstance(item, str)
        ]
        selected = list(required)
        if not selected:
            selected.extend(str(name) for name in properties)
        else:
            selected.extend(
                str(name)
                for name, prop in properties.items()
                if name not in selected and _contains_literal_structure(prop)
            )
        own = {
            name: _schema_skeleton(
                properties.get(name, {}),
                catalog,
                current_file=current_file,
                field_name=name,
                seen_refs=seen_refs,
                depth=depth + 1,
            )
            for name in selected
        }
        result: Any = {}
        for branch in schema.get("allOf", ()):
            if (
                not isinstance(branch, Mapping)
                or _is_conditional_schema(branch)
                or not _has_structure(branch)
            ):
                continue
            result = _combine_skeletons(
                result,
                _schema_skeleton(
                    branch,
                    catalog,
                    current_file=current_file,
                    field_name=field_name,
                    seen_refs=seen_refs,
                    depth=depth + 1,
                ),
            )
        return _combine_skeletons(result, own)

    if schema_type == "array":
        contained: list[Any] = []
        containers = [schema]
        containers.extend(
            branch
            for branch in schema.get("allOf", ())
            if isinstance(branch, Mapping) and not _is_conditional_schema(branch)
        )
        for container in containers:
            contains = container.get("contains")
            if isinstance(contains, Mapping):
                item = _schema_skeleton(
                    contains,
                    catalog,
                    current_file=current_file,
                    field_name=f"{field_name}_item" if field_name else "item",
                    seen_refs=seen_refs,
                    depth=depth + 1,
                )
                if item not in contained:
                    contained.append(item)
        if contained:
            return contained
        prefix_items = schema.get("prefixItems")
        if isinstance(prefix_items, Sequence) and not isinstance(prefix_items, (str, bytes)):
            return [
                _schema_skeleton(
                    item,
                    catalog,
                    current_file=current_file,
                    field_name=f"{field_name}_item" if field_name else "item",
                    seen_refs=seen_refs,
                    depth=depth + 1,
                )
                for item in prefix_items
                if isinstance(item, Mapping)
            ]
        minimum = schema.get("minItems", 0)
        if isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0:
            items = schema.get("items", {})
            return [
                _schema_skeleton(
                    items if isinstance(items, Mapping) else {},
                    catalog,
                    current_file=current_file,
                    field_name=f"{field_name}_item" if field_name else "item",
                    seen_refs=seen_refs,
                    depth=depth + 1,
                )
            ]
        return []

    combined: Any = None
    for branch in schema.get("allOf", ()):
        if (
            not isinstance(branch, Mapping)
            or _is_conditional_schema(branch)
            or not _has_structure(branch)
        ):
            continue
        combined = _combine_skeletons(
            combined,
            _schema_skeleton(
                branch,
                catalog,
                current_file=current_file,
                field_name=field_name,
                seen_refs=seen_refs,
                depth=depth + 1,
            ),
        )
    if combined is not None:
        return combined

    if schema_type == "boolean":
        return "<boolean>"
    if schema_type == "integer":
        return "<integer>"
    if schema_type == "number":
        return "<number>"
    if schema_type == "null":
        return None
    if schema_type == "string" or schema_type is None:
        return _scalar_placeholder(field_name, schema)
    return f"<{field_name or 'value'}>"


def _load_schema_example(
    schema_file: str,
    catalog: SchemaCatalog | None = None,
) -> str | None:
    """Render a neutral schema skeleton, with fixture fallback for compatibility."""
    if catalog is None:
        return _load_fixture_example(schema_file)
    try:
        skeleton = _schema_skeleton(
            catalog.get(schema_file),
            catalog,
            current_file=schema_file,
        )
        return json.dumps(
            _neutralize_identities(skeleton),
            indent=2,
            ensure_ascii=False,
        )
    except Exception:
        # A runtime brief must never fall back to domain-bearing golden content.
        return None


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
    mode_instruction: str = "",
    stage_role_instruction: str = "",
    researcher_instruction: str = "",
    scientific_stance: str = "",
    same_group_roles: Sequence[str] = (),
    schema_catalog: SchemaCatalog | None = None,
    researcher_method_spec: str = "",
    compact_views: Mapping[str, str] | None = None,
) -> str:
    """Render one bounded role assignment without software-manual prose."""

    role_step = stage.step_for(role)
    specs = output_plan.for_stage_role(stage.stage_id, role)
    missing = set(role_step.input_ids) - set(input_paths)
    if missing:
        raise ValueError(
            f"Task brief is missing resolved inputs for {sorted(missing)}."
        )
    mode_text = (mode_instruction or phase_instruction).strip()
    lines = [
        f"# {stage.stage_id}: {role}",
        "",
        f"Run: `{run_id}`",
        f"Project: `{project_id}`",
        f"Phase and mode: `{plan.identity.phase_id}` / `{plan.mode_id}`",
        "",
        "Envelope fields (`schema_version`, `content_sha256`, `created_at`, "
        "`updated_at`, `finalized_at`, `published_at`) and identity fields "
        "(`record_id`, `generation_id`, `generation_number`, `record_type`, "
        "`source_run_id`, `authority_at_creation`) are populated by the "
        "harness from sealed run facts — do not write them.",
        "",
        "## Immutable instruction boundary",
        "",
        "The frozen phase and mode, selected method identity, inputs, role, "
        "output contract, parallel-isolation rule, and execution boundary are "
        "immutable. Follow every applicable layer below. Researcher direction "
        "has highest priority among scientific directions within those "
        "boundaries, but it cannot change the mode, expand the authorized "
        "method scope, or alter declared outputs.",
        "",
        "## Scientific objective",
        "",
        stage.objective.strip(),
        "",
        "## Mode directive",
        "",
        mode_text,
    ]
    if stage_role_instruction.strip():
        lines.extend([
            "",
            "## Stage-role assignment",
            "",
            stage_role_instruction.strip(),
        ])
    if researcher_instruction.strip():
        lines.extend([
            "",
            "## Researcher direction (highest scientific priority within this mode)",
            "",
            "Apply the following text exactly within the immutable scope above:",
            "",
            researcher_instruction,
        ])
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
        line = f"- `{input_id}`: `{input_paths[input_id]}`"
        if compact_views and input_id in compact_views:
            line += f" (compact decision view: `{compact_views[input_id]}`)"
        lines.append(line)
    if compact_views:
        lines.extend([
            "",
            "Inputs with a compact decision view: read the compact view FIRST; "
            "open the full record only where you need the underlying detail.",
        ])
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
    lines.append(
        "Mathematical notation in any text field must use delimited LaTeX: "
        "`$...$` for inline math and `$$...$$` for display equations. Never "
        "write bare LaTeX commands (such as \\exp or \\sigma) outside math "
        "delimiters; undelimited commands are displayed literally."
    )
    lines.append("")
    for spec in specs:
        shape = "JSON array" if spec.schema_application == "each_item" else "JSON object"
        output_filename = Path(spec.relative_path).name
        lines.append(
            f"- `{spec.contract_output_id}`: `{output_filename}`; {shape}; "
            f"schema `{spec.schema_file}`."
        )
        if schema_catalog is not None and hasattr(schema_catalog, "get"):
            schema = schema_catalog.get(spec.schema_file)
            schema_props = frozenset(schema.get("properties", {}))
            harness_owned = sorted(harness_owned_fields(spec.schema_file) & schema_props)
            agent_authored = sorted(agent_authored_fields(spec.schema_file, schema_props))
            lines.append("")
            lines.append(
                "The harness will populate: "
                + ", ".join(f"`{name}`" for name in harness_owned)
                + ". These fields are filled automatically from sealed run "
                "facts — do not attempt to write them."
            )
            if agent_authored:
                lines.append(
                    "Agent-authored fields (your responsibility): "
                    + ", ".join(f"`{name}`" for name in agent_authored)
                    + ". Focus your scientific writing on these fields."
                )
            constraints = _render_schema_constraints(spec.schema_file, schema_catalog)
            if constraints:
                lines.append("")
                lines.append(constraints)
            example = _load_schema_example(spec.schema_file, schema_catalog)
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
