# P-D Implementation Pins: Envelope and provenance (R9, R10, R26)

Status: PINNED 2026-09-01 (coordinator). Subagent executes; it does not
design. Every probe fact below was re-verified against the live tree at
commit 23d54e7 (post P-C), including a throwaway reproduction script run
with the repo venv (`/tmp/pd_probe.py`).

Source findings: [../harness-audit-2026-08-31.md](../archive/completed/harness-audit-2026-08-31.md).
Program entry: P-D in
[harness-audit-2026-08-31-fix-program.md](harness-audit-2026-08-31-fix-program.md).

## Reproduction probe results (pre-fix, all confirmed live)

- `populate_harness_fields({"review_basis_generation_id": "generation.fabricated.001"}, facts, "review-finding.schema.json")`
  with `review_basis_generation_id=""` in facts -> the fabricated value
  SURVIVES (R9).
- Same for `to_role="theorist"` on handoff.schema.json with `to_role=""`
  (terminal stage) -> survives (R9 audit-extension case).
- Same for `record_type="manuscript"` on scientific-record.schema.json with
  `record_type=""` -> survives (R9 audit-extension case).
- `reclassify_harness_owned_finding(finding, schema_file="method.schema.json",
  failing_property="identity")` -> finding_class=operational_failure,
  correction_class="none", even when the run has no selected method (R10).
- `_classify_transformations({"generation_id": "generation.fake.001",
  "source_run_id": "agent-value", "title": "a"}, {"source_run_id": "r",
  "title": "a"})` -> `additional_properties_strip /generation_id` and
  `value_rewrite /source_run_id` (R26: both mislabeled).

## Probe facts (live-tree verified)

- `envelope.py:420-421` overwrites `review_basis_generation_id` only when
  the run fact is truthy. The field is harness-owned for
  review-finding.schema.json (:144), review-report.schema.json (:152),
  review-issue.schema.json (:204).
- All three review schemas REQUIRE `review_basis_generation_id` (stableId
  $ref: pattern + minLength 2). Popping a fabricated value therefore turns
  a silent fabrication into a loud required-finding on a harness-owned
  field (OPERATIONAL_FAILURE). Fail-loud is the intent.
- `_sealed_run_facts` (role_execution.py:2638-2647) leaves
  `review_basis_generation_id=""` unless a frozen recipe input carries
  contract_input_id `p5.review_target_manuscript` or
  `p5.current_manuscript`.
- `handoff.schema.json`: `to_role` is NOT required; it is a roleId $ref,
  and common-definitions roleId is an ENUM
  ["user","system","research_lead","theorist","data_analyst",
  "outside_reviewer"]. An empty string would FAIL validation, so the empty
  case must POP, not write "". A fabricated valid role on a terminal stage
  passes validation today.
- `sequence` needs NO strip: phase contracts are 1-based
  (phase-contract.schema.json sequence minimum 1; P2.json/P5.json stages
  start at 1), so `run_facts.sequence` is always truthy and the overwrite
  at envelope.py:410-411 always fires.
- `record_type` DOES need the strip for scientific-record.schema.json:
  its record_type is a recordType $ref (14-value enum), not a const, so a
  fabricated in-enum value passes validation. theory-record has
  `const: theory_record` (fabrication cannot pass unless correct).
  manuscript-package has NO record_type property (pop is a no-op).
  record_type is REQUIRED by scientific-record, so a pop when the harness
  cannot resolve a value fails loud. Resolution at
  role_execution.py:143-157 has three fallbacks (binding map ->
  spec.record_type -> schema const), so empty is rare in practice.
- `lineage` gets NO strip: probe fact - `SealedRunFacts.method_lineage` is
  NEVER populated (the only constructor, role_execution.py:2648-2659,
  omits it; default None), and method.schema.json REQUIRES lineage, so
  agent-authored lineage is de facto load-bearing in every mode today.
  Stripping would fail every method-producing run. R10's mode-aware
  reclassification is the remedy for catalog modes. Residual observation
  (recorded, not fixed here): the ADR-015 premise is also false for
  `lineage` in method-bound runs because the harness never populates it.
- `reclassify_harness_owned_finding` (envelope.py:229-258) has exactly two
  production callers: outputs.py:139 (module `_finding`, always passes
  `spec.schema_file`) and submission_validation.py:425 (module `_finding`,
  guarded by `schema_file is not None`).
- `validate_role_outputs` (outputs.py:146) has exactly six production call
  sites: role_execution.py:2041, role_execution.py:2754,
  correction_execution.py:254, :572, :890, :897.
- role_execution.py:2034 and :2750 already compute
  `self._sealed_run_facts(stage, role)` inline just before the
  validate_role_outputs calls; `method_identity` on the result is the
  method-bound signal ({} when not method-bound, per _sealed_run_facts
  :2627-2630).
- correction_execution.py call sites all have `plan` in scope (from
  `_plan_from_recipe`), with `plan.choice_values` available.
- `validate_submission` (submission_validation.py:36-46) already receives
  `selected_method: MethodIdentity | None`; only ONE internal `_finding`
  call passes schema_file (:306).
- `_classify_transformations` (role_execution.py:268) is called only at
  role_execution.py:247 with `renames=id_renames`; `spec.schema_file` is
  in scope there. role_execution.py:41 currently imports
  `from .envelope import SealedRunFacts, populate_harness_fields`.
- Transformation codes are NOT enumerated by any schema (checked
  role-invocation-closure.schema.json: no code enum), so adding codes is
  safe. The normalize allowlist (ALLOWED_NORMALIZE_CODES =
  timestamp_injection, id_sanitization, schema_version_injection,
  null_strip, empty_string_strip) simply will not include the new codes,
  which is correct: harness-owned fields are not agent-correctable.
- Test vocabulary: tests/test_envelope_construction.py has `_facts(**overrides)`
  (:39-60) building SealedRunFacts, imports make_finding/FindingClass and
  all envelope helpers. tests/test_harness_repairs.py imports
  `_classify_transformations` locally inside each test (:548, :560, :572).

## R9 pin: strip-when-empty for provenance-class harness-owned fields

In `envelope.py:populate_harness_fields`, replace three conditional
overwrites with mirror-image strip blocks (exactly the generation-identity
pattern at :373-382):

1. record_type (:357-358) becomes:
```python
    if "record_type" in owned:
        if run_facts.record_type:
            result["record_type"] = run_facts.record_type
        else:
            result.pop("record_type", None)
```
2. to_role (:412-413) becomes:
```python
    if "to_role" in owned:
        if run_facts.to_role:
            result["to_role"] = run_facts.to_role
        else:
            result.pop("to_role", None)
```
   (sequence at :410-411 stays as-is; see probe facts.)
3. review_basis_generation_id (:420-421) becomes:
```python
    if "review_basis_generation_id" in owned:
        if run_facts.review_basis_generation_id:
            result["review_basis_generation_id"] = run_facts.review_basis_generation_id
        else:
            result.pop("review_basis_generation_id", None)
```
4. lineage (:438-439) stays as-is (see probe facts).
5. Update the docstring "Overwrite policy" section (:311-325): add a
   bullet stating that provenance-class harness-owned fields
   (`record_type`, `to_role`, `review_basis_generation_id`) follow the
   generation-identity strip rule: when the sealed run fact is empty, any
   agent-supplied value is DELETED (fail-loud via the schema's required
   rule where applicable), because a fabricated value could otherwise pass
   validation.

## R10 pin: mode-aware ADR-015 reclassification

1. `envelope.py:reclassify_harness_owned_finding` gains a keyword-only
   parameter `method_bound: bool = True`. Effective owned set:
```python
    owned = harness_owned_fields(schema_file)
    if schema_file == "method.schema.json" and not method_bound:
        owned = owned - {"identity", "lineage"}
```
   then use `owned` in the existing membership check (:246). Extend the
   docstring: the ADR-015 premise (the harness re-populates those fields
   at every close) holds for `identity`/`lineage` only when the run is
   method-bound; catalog modes (p2.full_catalog, p2.researcher_proposal)
   leave them agent-authored by design (populate_harness_fields :360-367).
2. `outputs.py`: `validate_role_outputs` gains keyword-only
   `method_bound: bool = True`; module `_finding` gains keyword-only
   `method_bound: bool = True` forwarded to reclassify; every `_finding`
   call inside validate_role_outputs passes `method_bound=method_bound`.
3. `role_execution.py`: at BOTH call sites (:2041 correction close, :2754
   base close) hoist the inline `self._sealed_run_facts(stage, role)` into
   a local `run_facts` before the `_apply_disclosed_mechanical_repairs`
   call, pass `run_facts=run_facts` there, and add
   `method_bound=bool(run_facts.method_identity)` to the
   validate_role_outputs call.
4. `correction_execution.py`: add a module-level helper
```python
def _plan_method_bound(plan: ResolvedPhasePlan) -> bool:
    """True when the frozen plan selected a method (any
    ``*.selected_method`` choice carrying a Mapping value)."""
    return any(
        str(key).endswith(".selected_method") and isinstance(value, Mapping)
        for key, value in plan.choice_values.items()
    )
```
   (Mapping from collections.abc; adjust imports.) Pass
   `method_bound=_plan_method_bound(plan)` at :254, :572, :890, :897.
5. `submission_validation.py`: `_finding` gains keyword-only
   `method_bound: bool = True` forwarded to reclassify; the single
   schema_file-carrying call site (:306, inside validate_submission)
   passes `method_bound=selected_method is not None`.

## R26 pin: population-aware transformation codes

1. `role_execution.py`: module-level constant near _classify_transformations:
```python
_GENERATION_IDENTITY_FIELDS = frozenset(
    {"generation_id", "generation_number", "review_basis_generation_id"}
)
```
2. `_classify_transformations` gains keyword-only parameter
   `harness_owned: frozenset[str] = frozenset()` (default keeps existing
   callers/tests unchanged).
3. In the keys-removed branch (:300-333), insert as the FIRST condition
   (before the `_at`-suffix check):
```python
                if not ptr and key in _GENERATION_IDENTITY_FIELDS and key in harness_owned:
                    entries.append(TransformationEntry(
                        code="generation_identity_strip",
                        json_pointer=child_ptr,
                        detail=f"stripped agent-fabricated generation identity '{key}'",
                    ))
                elif ...
```
4. In the keys-in-both value-differs branch, insert AFTER the
   `identity_version_bump` elif (:382-387) and BEFORE the final
   `value_rewrite` else:
```python
                elif not ptr and key in harness_owned:
                    entries.append(TransformationEntry(
                        code="harness_population_overwrite",
                        json_pointer=child_ptr,
                        detail=f"harness-populated field '{key}': {rv!r} -> {pv!r}",
                    ))
```
   (Use the same arrow style as the neighboring details.)
5. Update the call at :247:
   `entries = _classify_transformations(raw_snapshot, data, renames=id_renames, harness_owned=harness_owned_fields(spec.schema_file))`
   and extend the import at :41 to include `harness_owned_fields`.
6. Update the `_classify_transformations` docstring (:283 area) to name
   the two new codes.
7. Known semantic change: top-level harness-owned overwrites that were
   recorded as `value_rewrite` (e.g. created_at, source_run_id,
   record_type) now record as `harness_population_overwrite`, and
   generation-id pops recorded as `additional_properties_strip` /
   `null_strip` / `empty_string_strip` now record as
   `generation_identity_strip`. If a pre-existing test pinned the OLD code
   for a harness-owned top-level field, update that expectation to the new
   code and list EVERY such migration in the report-back (this is the
   intended attribution fix, not masking). Nested fields (ptr != "") are
   NEVER reclassified by this change.

## Regression tests (each must FAIL on pre-fix code)

Add to tests/test_envelope_construction.py:

1. `test_review_basis_generation_id_stripped_when_run_fact_empty`:
   populate `{"review_basis_generation_id": "generation.fabricated.001"}`
   with `_facts(review_basis_generation_id="")` on
   review-finding.schema.json; assert the field is ABSENT. Pre-fix:
   survives -> FAIL.
2. `test_to_role_stripped_when_terminal`: populate `{"to_role": "theorist"}`
   with `_facts()` (to_role defaults to "") on handoff.schema.json; assert
   ABSENT. Pre-fix: survives -> FAIL.
3. `test_record_type_stripped_when_unresolved`: populate
   `{"record_type": "manuscript"}` with `_facts(record_type="")` on
   scientific-record.schema.json; assert ABSENT. Pre-fix: survives -> FAIL.
4. `test_catalog_mode_method_identity_finding_stays_correctable`:
   make_finding on pointer /identity/version, reclassify with
   schema_file="method.schema.json", failing_property="identity",
   method_bound=False; assert the SAME finding object is returned
   (unchanged, still CORRECTABLE_CONTRACT_ERROR). Pre-fix: TypeError
   (unexpected keyword) -> FAIL.
5. `test_method_bound_method_identity_finding_stays_operational`: same
   finding, method_bound=True; assert OPERATIONAL_FAILURE and
   correction_class "none". Pre-fix: TypeError -> FAIL.

Add to tests/test_harness_repairs.py:

6. `test_generation_identity_strip_code`:
   `_classify_transformations({"generation_id": "generation.fake.001",
   "title": "a"}, {"title": "a"}, harness_owned=harness_owned_fields(
   "decision-record.schema.json"))`; assert exactly one entry with code
   "generation_identity_strip" and json_pointer "/generation_id".
   Pre-fix: TypeError -> FAIL.
7. `test_harness_population_overwrite_code`:
   `_classify_transformations({"source_run_id": "agent", "title": "a"},
   {"source_run_id": "run-x", "title": "b"}, harness_owned=
   harness_owned_fields("scientific-record.schema.json"))`; assert
   "/source_run_id" entry has code "harness_population_overwrite" and
   "/title" entry has code "value_rewrite". Pre-fix: TypeError -> FAIL.

## Boundaries

- Allowed files: src/model_forge/harness/envelope.py,
  src/model_forge/harness/outputs.py,
  src/model_forge/harness/role_execution.py,
  src/model_forge/harness/submission_validation.py,
  src/model_forge/application/correction_execution.py,
  tests/test_envelope_construction.py, tests/test_harness_repairs.py,
  plus any pre-existing test file whose expectation migrates under R26
  rule 7 (list each in the report).
- No edits under architecture/. No new error codes. No schema changes.
- Suite: `.venv/bin/python -m pytest tests -q` (baseline 1351 passed).
  Validator: `.venv/bin/python architecture/tools/validate_package.py`.
- Write ONLY inside /home/tez/product/model-forge; never create or edit
  files outside it - not skill files, notes, memory, or scratch outside
  /tmp.
- One commit, message: `Audit-2026-08-31 Pkg D: envelope provenance strips
  and mode-aware reclassification (R9, R10, R26)`.

## Report-back fields

Files changed; per-R-number summary; test-count delta and names of new
tests; any pre-existing test expectations migrated under R26 rule 7 (with
file:line); suite and validator exit codes; any deviation from these pins
with evidence.
