# HV-1: Raw Preservation and Validation Unification

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Remove information loss and inconsistent validation decisions before adding
any recovery machinery. This is the first package that touches runtime code.

## What the audit found

### Problem 1: Repair rewrites output before sealing

`_apply_disclosed_mechanical_repairs` (`role_execution.py:51-275`) runs first
in `_validate_and_close` on SUCCEEDED (`role_execution.py:976-982`), rewriting
the workspace output in-place (`role_execution.py:239-242`). `_seal_output`
(`role_execution.py:994-997`, `outputs.py:276`) then seals the **post-repair**
bytes. `preserve_raw_output` (`output_adapters.py:122`) runs **only in the
FAILED branch** (`role_execution.py:1008-1015`).

**Consequence:** the sealed artifact and computed digest reflect repaired
content, not the agent's original output. If repair introduced an error, the
original bytes are lost.

### Problem 2: Timestamp injection walks the entire JSON tree

`_add_missing_timestamps` (`role_execution.py:245-275`) collects timestamp-like
field names from the schema via suffix scan (`_at`, `_timestamp`, `_time`,
excluding `searched_at`) in `_collect_nested_timestamps` (`role_execution.py:539-
561`). It then walks the **entire JSON tree** and inserts those fields into
**any dict lacking them** -- not just schema-declared locations.

**Example:** `assessed_at` declared only under `alignmentAssessment` gets
injected into every nested object (assumptions, statements, implications, etc.).

### Problem 3: Closed-schema unknown fields silently deleted, and more

For schemas with `additionalProperties: false` (`role_execution.py:97-98`),
`_fix_item` deletes any key not in `allowed_props` (`role_execution.py:149-154`).
Null values of optional fields are deleted (`role_execution.py:157-160`);
empty strings are deleted at any depth (`_strip_empty_strings`,
`role_execution.py:278-318`).

The same repair pass also performs content rewrites the original audit
understated (verified 2026-08-12): it sanitizes agent-authored identifier
fields in place (the `_ID_KEYS` list: `statement_id`, `assumption_id`,
`finding_id`, and 9 more, lowercased and character-normalized), rewrites ID
arrays (`*_ids`), injects `schema_version`, and bumps method identity
`version` to >= 1 (`role_execution.py:100-165`). Identifier rewriting is
arguably scientific-content mutation: it changes values the agent wrote and
that cross-references elsewhere in the document may depend on.

**Consequence:** useful content-bearing extra fields are silently lost, and
some agent-authored values are altered, all before the raw bytes are sealed.

### Problem 4: No transformation log

The "disclosed" in `_apply_disclosed_mechanical_repairs` is aspirational.
Closure findings come only from post-repair validation
(`role_execution.py:990`). No repair log or transformation report exists.

### Problem 5: Supervised adapter hardcodes empty mode

`_phase_plan_shim` (`output_validation.py:440-464`) hardcodes `mode_id=""`
(line 455), empty `choice_values`, no stages/contracts. Only `phase` is read
from the manifest (`output_validation.py:770-771`) even though the manifest
carries `mode` (`run-manifest.schema.json:18,63`).

The phase validators dispatch on `plan.mode_id`:
- P2 (`scientific_validators.py:151`) -- focused-method checks silently skipped
- P3 (`scientific_validators.py:351,486`) -- `development_mode_mismatch` fires
  on every real record; revision checks skipped
- P4 (`scientific_validators.py:583`) -- `protocol_mode_mismatch` fires spuriously
- P5 (`scientific_validators.py:885,999`) -- review-revision checks skipped;
  manuscript-kind check disabled

The shim's docstring claim that "every other field is unused by them"
(`output_validation.py:443-447`) is **false**.

### Problem 6: The digest is computed from post-repair content

`_fix_self_referential_hashes` (`role_execution.py:365-449`) runs after all
other repairs and recomputes/stamps hashes (`role_execution.py:237`). The
sealed digest thus reflects repaired+rehashed content.

## Work items

### HV-1.1: Seal raw output before repair

**Target:** `src/model_forge/harness/role_execution.py`

Change the ordering in `_validate_and_close` so that:
1. Read and seal the original workspace output bytes first (pre-repair).
2. Compute the raw output digest from the sealed raw bytes.
3. Apply repair to a **derived candidate** (copy, not in-place mutation).
4. Validate the candidate.
5. Seal the candidate (post-repair) as a separate artifact.

```
Current order:
  Hermes exit → repair (in-place) → validate → seal (post-repair) → close

New order:
  Hermes exit → seal raw → copy → repair (on copy) → validate → seal candidate → close
```

The raw snapshot must be preserved for **every** outcome (success, failure,
rejection), not just the FAILED branch.

**Digest binding rule:** publication binds the CANDIDATE. The sealed candidate
bytes are the artifact that submission digest checks (`submission.digest_*`)
and promotion verify. The raw digest is recorded on the role closure and in
the OutputTransformationRecord (HV-1.2) as evidence, but is not the published
artifact digest. State this explicitly in the closure schema so downstream
consumers never guess which of the two digests a receipt refers to.

**Acceptance:** the original output digest is recoverable for every executor
and validation outcome.

### HV-1.2: Record all mechanical transformations

**Target:** `src/model_forge/harness/role_execution.py`, new record type

Define an `OutputTransformationRecord` (parent plan §6.2) as an immutable
record for every mechanical transformation:

- source digest (pre-repair)
- result digest (post-repair)
- allowlisted transformation codes applied (e.g., `timestamp_injection`,
  `additional_properties_strip`, `id_sanitization`, `hash_recomputation`)
- affected JSON pointers
- before/after values when bounded and safe
- harness version
- confirmation that no primary scientific artifact changed

The repair function returns this record alongside the repaired data. The
record is stored in the role closure so the researcher can inspect exactly what
changed.

**Acceptance:** every repair is visible in a structured record.

### HV-1.3: Schema-path-aware timestamp injection

**Target:** `src/model_forge/harness/role_execution.py`, `_add_missing_timestamps`
(line 245) and `_collect_nested_timestamps` (line 539)

Replace the whole-tree walk with schema-path-aware traversal. Only inject
timestamps at schema-declared locations. Do not synthesize scientific
timestamps or provenance.

The current `_collect_nested_timestamps` collects field names by suffix and
then `_add_missing_timestamps` injects them anywhere a matching dict exists.
Instead, collect `(json_pointer, field_name)` pairs from the schema and inject
only at those paths.

**Acceptance:** repair cannot inject a field outside its schema path.

### HV-1.4: Stop silently deleting unknown fields

**Target:** `src/model_forge/harness/role_execution.py`, `_fix_item` (line 100)

Current behavior: for closed schemas, any key not in `allowed_props` is `del`-
eted silently (`role_execution.py:149-154`).

New behavior: preserve unknown fields in the raw snapshot. For the candidate,
either:
- Map them through an explicit extension mechanism, or
- Report a correctable contract finding (see HV-2) rather than silently
  deleting.

This is a behavior change that must be controlled to avoid breaking existing
passing runs. Introduce it with a feature flag or behind the repair-policy
decision from HV-0.

**Acceptance:** repair cannot lose useful content without a recorded finding.

### HV-1.5: Unify validation context

**Target:** `src/model_forge/application/output_validation.py`,
`_phase_plan_shim` (line 440)

Remove `_phase_plan_shim` entirely. Replace with a real `ValidationContext`
containing the exact contract, phase, mode, method, frozen basis, role, and
output bindings.

The manifest already carries `mode` (`run-manifest.schema.json:18,63`). Use it
instead of hardcoding `mode_id=""`.

**Feasibility (verified 2026-08-12):** the scientific and submission
validators read only three plan attributes: `plan.mode_id` (7 uses),
`plan.identity` (5 uses), and `plan.publication_bindings` (1 use). The run
manifest carries `mode`, `phase`, `phase_contract_version`,
`phase_contract_sha256`, and `publication_plan`. A real ValidationContext can
therefore be built from the sealed manifest without fabricating contract
choices; the shim docstring's claim that a full plan is unresolvable is stale.
The remaining work is confirming `publication_plan` in the manifest maps
cleanly onto `publication_bindings`, and extending the manifest schema (with
ADR note) if it does not.

Consolidate canonical and supervised validation around one
`ValidationContext`. The same bytes and context must receive the same decision
in both execution surfaces.

**Acceptance:** identical bytes and context receive the same decision in both
execution surfaces. The false-failure codes (`p3.development_mode_mismatch`,
`p4.protocol_mode_mismatch`) no longer fire on valid records.

### HV-1.6: Remove the empty-mode shim's spurious failures

This is a direct consequence of HV-1.5 but worth calling out explicitly. Once
the real mode is passed to validators:

- P2 focused-method identity checks run when `mode == p2.focused_method`
- P3 establishment vs revision checks dispatch correctly
- P4 preliminary vs comprehensive checks dispatch correctly
- P5 assembly vs review_revision checks dispatch correctly

**Acceptance:** no spurious mode-mismatch findings on valid records.

## Acceptance criteria

- [ ] The original output digest is recoverable for every executor and
      validation outcome (success, failure, rejection)
- [ ] Identical bytes and context receive the same decision in both canonical
      and supervised execution surfaces
- [ ] Repair cannot inject a field outside its schema path
- [ ] Every repair is visible in a structured `OutputTransformationRecord`
- [ ] No spurious mode-mismatch findings on valid records
- [ ] Unknown fields are not silently deleted without a recorded finding
- [ ] All existing tests pass (830 tests as of this audit)

## Files touched

| File | Change |
| --- | --- |
| `src/model_forge/harness/role_execution.py` | Reorder seal-before-repair, schema-path timestamps, stop silent deletion, transformation records |
| `src/model_forge/application/output_validation.py` | Remove `_phase_plan_shim`, pass real mode |
| `src/model_forge/domain/validation.py` | Add `OutputTransformationRecord` type (if not added in HV-0) |
| `tests/test_harness_repairs.py` | Update repair tests for new ordering |
| `tests/test_harness_outputs.py` | Add raw-preservation tests |
| `tests/test_scientific_validator_integrity.py` | Add mode-context consistency tests |

## Dependencies

- HV-0 should be completed first (provides the ADR and inventory that justify
  the repair-policy changes). However, HV-1.5 (fix the mode shim) is an
  independent correctness fix and can be done immediately if needed.
- HV-1.2's OutputTransformationRecord type comes from the HV-0.6 schema; the
  runtime dataclass mirrors it.

## Risks

- **Behavior change in repair**: stopping silent deletion of unknown fields
  may surface previously-hidden issues. Existing tests that assumed silent
  deletion will need updating. Mitigate with the feature flag and careful
  test review.
- **Digest stability**: sealing raw bytes before repair means the sealed
  artifact digest changes for every run. Historical records keep their
  existing digests (do not rewrite). New records get both raw and candidate
  digests.

## Revision 2 changelog (2026-08-12, coder review)

- A1 (Problem 3): broadened the repair-pass description. Beyond silent field
  deletion, the pass rewrites agent-authored identifiers, ID arrays,
  `schema_version`, and method identity versions in place
  (`role_execution.py:100-165`). This raises the stakes of HV-1.2's
  transformation record.
- A2 (HV-1.1): added the digest-binding rule. Publication binds the candidate
  digest; the raw digest is evidence on the closure. Previously unspecified,
  which would have left `submission.digest_*` checks ambiguous.
- A3 (HV-1.5): added verified feasibility evidence (validators read only
  `mode_id`/`identity`/`publication_bindings`; the manifest carries the
  needed fields) so the implementer knows a full contract resolution is not
  required.
