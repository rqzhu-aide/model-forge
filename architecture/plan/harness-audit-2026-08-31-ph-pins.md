# Implementation Pins: Pkg H (R16 - task-brief conditional extraction)

Status: PINNED 2026-09-01 (coordinator). Finding re-probed against the live
tree before pinning; both halves of the audit claim reproduce exactly.
Source of truth for the finding:
[../harness-audit-2026-08-31.md](../harness-audit-2026-08-31.md) (R16).
Fix program entry:
[harness-audit-2026-08-31-fix-program.md](harness-audit-2026-08-31-fix-program.md)
(P-H).

## Probe facts (verified 2026-09-01 against the live tree, HEAD 97eba80)

1. LIVE PROBE (/tmp/ph_probe.py, driving the real
   `_extract_conditional_requirements` on the sealed schema catalog):
   - `evidence.schema.json` yields entries for `method_identity`,
     `reproducibility`, `publication_receipt_id`, `published_at` only.
     NO entry for `alignment_at_creation.state`, although
     `evidence.schema.json` `allOf[2]` pins
     `if applicability_at_creation.method_match == "older_method_version"
     then alignment_at_creation.state` must be const `"outdated"` via
     NESTED `properties`/`required`. Validation blocks on this rule while
     the brief never mentions it (the audit's correction-cycle burner).
   - `role-invocation-closure.schema.json` yields
     `{'field': 'termination', 'condition': None, 'prohibited_when':
     "'terminal_status' is not `succeeded`"}` - the live misread.
     `allOf[0].else.required: ["termination"]` is a bare (non-negated)
     `required`, which AFFIRMS the field when the condition fails; the
     extractor reports it as prohibited.
   - `method.schema.json` yields no entry for
     `lineage.change_source.kind`, although `allOf[0].else` pins it to
     const `"research_run"` via nested `properties`/`required`.
   - Synthetic probes on `_extract_prohibited_fields`:
     `{"required": ["termination"]}` -> `{'termination'}` (wrong: bare
     required collected as prohibition);
     `{"not": {"not": {"required": ["x"]}}}` -> `{'x'}` (wrong: double
     negation affirms, must not be collected);
     `{"not": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}}` ->
     `{'a', 'b'}` (correct canonical shape; MUST keep working).
2. Full-schema survey (every `architecture/schemas/*.schema.json` walked
   for if/then/else): the ONLY top-level rule whose bare `else.required`
   reaches the extractor is `role-invocation-closure.schema.json`
   `allOf[0]` (`termination`). The other bare-else-required shapes
   (method.schema.json allOf[0], phase-contract runLocalOutput,
   publication-receipt record_changes, run-manifest
   source_input_mappings, authority-event allOf[4].then.allOf[0]) are
   either nested under `properties` (the current extractor's recursion
   only descends `not`/`anyOf`/`allOf`/`oneOf`, so it never sees them)
   or not at schema-root `allOf` (the driver loop reads only
   `schema["allOf"]`). The audit's "latent" severity is confirmed for
   the prohibition half.
3. Nested-if rules with a top-level `then.required`: exactly ONE exists
   (`command-attempt-audit-event.schema.json` `allOf[7]`,
   `validated_command` when `result.status` is `accepted`); its condition
   currently renders as "always". That schema is a harness-sealed audit
   event, not an agent-authored output, so no live brief is affected;
   the `_describe_condition` recursion below fixes the rendering as a
   side effect. No test asserts on that string (grep-verified).
4. Existing rendering assertions that MUST keep passing unchanged:
   `tests/test_harness_outputs.py:147-186`
   (`test_conditional_fields_render_else_prohibitions`) pins the
   attention-item output: the `not: {anyOf: [{required: ...}]}` shape
   still yields `prohibited_when` for `publication_receipt_id` /
   `published_at`, and the rendered lines keep their exact text.

## Pinned implementation (all edits in src/model_forge/harness/task_briefs.py)

### Edit 1: `_extract_prohibited_fields` (currently :233-252) - not-depth

Replace the whole function with:

```python
def _extract_prohibited_fields(block: Any, _negated: bool = False) -> set[str]:
    """Collect field names an ``else`` block forbids.

    A ``required`` list is a prohibition only under an ODD ``not`` depth
    (the common ``not: {anyOf: [{required: [...]}, ...]}`` shape). A bare
    ``required`` affirms the field when the ``if`` condition fails, and
    double negation affirms it again - neither may be collected.
    """
    fields: set[str] = set()
    if not isinstance(block, dict):
        return fields
    if _negated:
        required = block.get("required")
        if isinstance(required, list):
            fields.update(f for f in required if isinstance(f, str))
    for key in ("not", "anyOf", "allOf", "oneOf"):
        value = block.get(key)
        child_negated = (not _negated) if key == "not" else _negated
        if isinstance(value, dict):
            fields |= _extract_prohibited_fields(value, child_negated)
        elif isinstance(value, list):
            for item in value:
                fields |= _extract_prohibited_fields(item, child_negated)
    return fields
```

### Edit 2: `_describe_condition` (:203-213) and `_describe_else_condition`
(:216-230) - recurse into nested property subobjects with dotted paths

```python
def _describe_condition(if_block: dict[str, Any]) -> str:
    """Render a human-readable description of an if-block's conditions.

    Nested ``properties`` subobjects recurse, so a condition on a nested
    leaf renders with its dotted path (`` `a.b` is `...` ``).
    """
    parts: list[str] = []
    props = if_block.get("properties", {})
    for field, constraint in props.items():
        if not isinstance(constraint, dict):
            continue
        if "const" in constraint:
            parts.append(f"`{field}` is `{constraint['const']}`")
        elif "enum" in constraint:
            vals = ", ".join(f"`{v}`" for v in constraint["enum"])
            parts.append(f"`{field}` is one of ({vals})")
        elif isinstance(constraint.get("properties"), dict):
            nested = _describe_condition(constraint)
            if nested and nested != "always":
                parts.append(nested)
    return "; AND ".join(parts) if parts else "always"
```

```python
def _describe_else_condition(if_block: dict[str, Any]) -> str:
    """Render the condition under which an ``else`` branch applies.

    The ``if`` block is a conjunction of property constraints, so its
    negation is the disjunction of the per-property negations (De Morgan).
    Nested ``properties`` subobjects recurse; because every level is a
    conjunction, the flattened leaf negations joined by OR remain the
    exact De Morgan negation.
    """
    parts: list[str] = []
    props = if_block.get("properties", {})
    for field, constraint in props.items():
        if not isinstance(constraint, dict):
            continue
        if "const" in constraint:
            parts.append(f"`{field}` is not `{constraint['const']}`")
        elif "enum" in constraint:
            vals = ", ".join(f"`{v}`" for v in constraint["enum"])
            parts.append(f"`{field}` is none of ({vals})")
        elif isinstance(constraint.get("properties"), dict):
            nested = _describe_else_condition(constraint)
            if nested and nested != "never":
                parts.append(nested)
    return "; OR ".join(parts) if parts else "never"
```

### Edit 3: new helper `_extract_nested_const_requirements` (place directly
above `_extract_conditional_requirements`)

```python
def _extract_nested_const_requirements(
    block: Any, prefix: str = ""
) -> list[tuple[str, Any]]:
    """Collect ``(dotted_path, const)`` pairs pinned by nested required+const.

    Walks the ``properties`` subobjects of a ``then``/``else`` block. When
    an object-level subschema lists a field in ``required`` and that
    field's subschema pins ``const``, the pair is a hard value
    requirement the agent must write. ``not`` subschemas are never
    descended (negation flips the semantics).
    """
    pairs: list[tuple[str, Any]] = []
    if not isinstance(block, dict):
        return pairs
    props = block.get("properties")
    if not isinstance(props, dict):
        return pairs
    required = block.get("required")
    required_set = set(required) if isinstance(required, list) else set()
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        path = f"{prefix}{name}"
        if name in required_set and "const" in sub:
            pairs.append((path, sub["const"]))
        pairs.extend(_extract_nested_const_requirements(sub, f"{path}."))
    return pairs
```

### Edit 4: `_extract_conditional_requirements` (:621-673) - surface nested
const-pinned requirements from then AND else

- Change the return annotation to `list[dict[str, Any]]` (const values can
  be non-strings) and update the docstring: each entry now also carries
  ``value`` (a const the field must equal, ``None`` when unconstrained).
- All three `entries.setdefault(...)` calls gain `"value": None` in the
  default dict.
- After the existing `then_required` loop and BEFORE the
  `prohibited - set(then_required)` loop, insert:

```python
        if isinstance(then_block, dict):
            for path, value in _extract_nested_const_requirements(then_block):
                entry = entries.setdefault(
                    path,
                    {"field": path, "condition": None, "prohibited_when": None, "value": None},
                )
                if entry["condition"]:
                    entry["condition"] = f"{entry['condition']}; OR {condition}"
                else:
                    entry["condition"] = condition
                if entry["value"] is None:
                    entry["value"] = value
        if else_condition:
            for path, value in _extract_nested_const_requirements(else_block):
                entry = entries.setdefault(
                    path,
                    {"field": path, "condition": None, "prohibited_when": None, "value": None},
                )
                if entry["condition"]:
                    entry["condition"] = f"{entry['condition']}; OR {else_condition}"
                else:
                    entry["condition"] = else_condition
                if entry["value"] is None:
                    entry["value"] = value
```

### Edit 5: `_render_schema_constraints` (:188-198) - render the value

Replace the `for entry in conditional:` loop body with:

```python
        for entry in conditional:
            field = entry["field"]
            if entry.get("value") is not None and entry["condition"]:
                line = (
                    f"- `{field}` \u2014 must be `{entry['value']}`"
                    f" when: {entry['condition']}"
                )
                if entry["prohibited_when"]:
                    line += f"; do NOT include when: {entry['prohibited_when']}"
                lines.append(line)
            elif entry["condition"] and entry["prohibited_when"]:
                lines.append(
                    f"- `{field}` \u2014 required only when: {entry['condition']}; "
                    f"do NOT include when: {entry['prohibited_when']}"
                )
            elif entry["condition"]:
                lines.append(f"- `{field}` \u2014 required only when: {entry['condition']}")
            else:
                lines.append(f"- `{field}` \u2014 do NOT include when: {entry['prohibited_when']}")
```

(Every `\u2014` above is the two-character escape backslash-u2014 in the REAL
edit: the existing renderer already emits U+2014 as brief text, and the
architecture validator forbids the literal character in docs, so the
pinned source must write the escape. The subagent must reproduce the
escape form exactly, matching the pre-existing renderer lines.)

## Deliberate scope limits (do NOT extend)

- Bare top-level `else.required` (role-invocation-closure `termination`)
  simply STOPS being listed as prohibited; no new requirement entry is
  synthesised for non-const fields. The brief loses a wrong instruction;
  adding the affirmative one is out of the pinned scope.
- Enum-pinned nested constraints (method.schema.json then-branch
  `lineage.change_source.kind` enum) stay unsurfaced: the plan pins
  const-pinned only.
- Nested `allOf` inside then/else (authority-event, publication-receipt)
  is not walked; the walker descends `properties` only.

## Regression tests (all in tests/test_harness_outputs.py; every one MUST
fail on the pre-fix code; names pinned)

1. `test_else_branch_bare_required_is_not_prohibited` - real schema:
   `package.schemas.get("role-invocation-closure.schema.json")`; assert
   `entries.get("termination")` is None or its `prohibited_when` is None.
   Pre-fix: `prohibited_when == "`terminal_status` is not `succeeded`"`.
2. `test_double_negation_required_is_not_prohibited` - synthetic:
   `_extract_prohibited_fields({"not": {"not": {"required": ["x"]}}})`
   returns empty; and the canonical shape
   `{"not": {"anyOf": [{"required": ["a"]}]}}` still returns `{"a"}`.
   Pre-fix: first assertion fails (returns `{"x"}`).
3. `test_nested_const_then_requirement_surfaced` - real
   `evidence.schema.json`: `entries["alignment_at_creation.state"]` has
   `condition == "`applicability_at_creation.method_match` is
   `older_method_version`"` and `value == "outdated"`; and
   `_render_schema_constraints("evidence.schema.json", package.schemas)`
   contains the line
   `- \`alignment_at_creation.state\` \u2014 must be \`outdated\` when:
   \`applicability_at_creation.method_match\` is \`older_method_version\``.
   Pre-fix: KeyError on the entries lookup.
4. `test_nested_const_else_requirement_surfaced` - real
   `method.schema.json`: `entries["lineage.change_source.kind"]` has
   `value == "research_run"` and
   `condition == "`lineage.change_class` is not `lifecycle`"`.
   Pre-fix: KeyError.

Use the existing `ARCHITECTURE` / `SpecificationPackage.load` pattern from
`test_conditional_fields_render_else_prohibitions` (tests/
test_harness_outputs.py:147-152) for catalog access. Tests 3 and 4 build
`entries = {entry["field"]: entry for entry in
_extract_conditional_requirements(schema)}`.

## Expected post-fix extractor output (coordinator-verified targets)

- evidence.schema.json adds exactly one entry:
  `alignment_at_creation.state` / condition as above / value `outdated`.
- method.schema.json adds exactly one entry:
  `lineage.change_source.kind` / value `research_run` / condition
  `` `lineage.change_class` is not `lifecycle` ``.
- role-invocation-closure.schema.json: `termination` entry disappears
  entirely (no entries remain from that schema's allOf[0]; allOf[1] and
  allOf[2] contribute nothing - verify and report if they do).
- attention-item.schema.json: unchanged (existing test green).

## Gates (both MUST exit 0 before commit)

- `.venv/bin/python -m pytest tests -q` (baseline 1369; expect 1373 = +4)
- `.venv/bin/python architecture/tools/validate_package.py`

## Boundaries

- Write ONLY inside /home/tez/product/model-forge; never create or edit
  files outside it - not skill files, notes, memory, or scratch outside
  /tmp.
- Touch ONLY `src/model_forge/harness/task_briefs.py` and
  `tests/test_harness_outputs.py`. No schema edits, no architecture/ doc
  edits, no other production files.
- One commit: `Audit-2026-08-31 Pkg H: not-depth prohibition tracking +
  nested const-pinned conditional extraction in task briefs (R16)`.
- Do not redesign; execute the pins verbatim. If a pin conflicts with the
  code, STOP and report the conflict with evidence.
