# P-B Implementation Pins: Digest ordering (R2)

Source finding: `architecture/archive/completed/harness-audit-2026-08-31.md` R2.
Program entry: `architecture/plan/harness-audit-2026-08-31-fix-program.md` P-B.
Re-probed against the live tree 2026-08-31 (post P-A): finding stands.
`_fix_self_referential_hashes` now lives at `role_execution.py:835-980+`
(line numbers shifted by the P-A diff); `_fix_record` recomputes
`content_sha256` FIRST (step 1, `:879-884`) and then mutates the document
in steps 2-5 (`handoff_artifact.sha256`, `identity.definition_sha256`,
E-2 `output://` pointer stamping, E-2e `input://` pointer stamping).
No recomputation afterward. Call sites: `role_execution.py:243` (role lane
monolith) and `role_execution.py:542` (`apply_normalize_transformations`,
K-1b normalize lane, called without `pointer_context` so only steps 2-3
apply there).

## Defect

Per `architecture/contracts/digest-contracts.json`
(`method_record.content`, and the parallel `*.content` contracts), the
embedded `content_sha256` is `rfc8785_sha256` over the whole document
minus `/content_sha256`. Because steps 2-5 mutate the document AFTER the
step-1 recompute, the sealed embedded value is the digest of bytes that
never existed whenever any of steps 2-5 changed anything. Step 3 (method
records with `mathematical_definition.canonical_definition`, stamped at
`/identity/definition_sha256` per `method_record.definition`) is the
common case.

## Probe facts (verified 2026-08-31, pin these - do not re-derive)

- `_compute_content_hash(data, exclude_keys)` (`role_execution.py:648`)
  implements exactly the `*.content` contract: RFC 8785 canonicalize
  (`digests.jcs.canonicalize`) of the document with the excluded keys
  removed, sha256 hex.
- Step 2 (`handoff_artifact.sha256`) hashes a snapshot of the WHOLE
  record dict including the current `content_sha256` value, minus
  `handoff_artifact.sha256` itself. This is a potential mutual
  dependency with step 1, BUT `architecture/schemas/handoff.schema.json`
  is the only schema with `handoff_artifact` and it has NO
  `content_sha256` property (verified by scanning all
  `architecture/schemas/*.schema.json`). No schema has both fields, so a
  single reorder is exact; NO fixpoint iteration is needed or wanted (a
  mutual-hash fixpoint would be unreachable).
- Nested-record scan: among plausible agent-output schemas (method,
  evidence, scientific-record, decision-record, attention-item,
  review-*), none nests a `content_sha256` below its top-level
  properties. The three schemas that do (current-index,
  method-lifecycle-command, publication-receipt) are harness-generated,
  not role-lane agent outputs. The existing recursion into nested lists
  (`role_execution.py:968+`, covering evidence lists, attention-items,
  p2 method-changes) is unaffected by the reorder: nested records are
  processed by their own `_fix_record` call.
- `_stamp_output_pointer` (`:719-771`) and `_stamp_canonical_artifact`
  (`:774+`) mutate only the in-memory document (plus the E-2d
  `.as-authored` sidecar write, which is order-independent: file bytes
  on disk do not change during `_fix_self_referential_hashes`; the
  repaired-text write happens later at `:250-251`). Reordering steps
  within `_fix_record` cannot change which bytes get hashed into a
  pointer.

## The fix (exact)

In `src/model_forge/harness/role_execution.py`, inside
`_fix_self_referential_hashes._fix_record` ONLY:

1. Move the step-1 `content_sha256` block (current `:879-884`) to the
   END of `_fix_record`, after step 5. New order: handoff (step 2),
   definition_sha256 (step 3), output:// pointers (step 4), input://
   pointers (step 5), then content_sha256 recompute LAST.
2. Keep the `touched` bookkeeping semantics unchanged: the moved block
   still sets `touched = True` when it changes the value; the function
   still returns whether anything changed.
3. Update the step comments to reflect the new order, and update the
   `_fix_self_referential_hashes` docstring: state that
   `content_sha256` is recomputed LAST so the stamped value matches the
   sealed bytes per the `*.content` digest contracts
   (`architecture/contracts/digest-contracts.json`), because steps 2-5
   mutate the document the digest covers.
4. Do NOT add fixpoint iteration. Do NOT touch the recursion structure,
   `_stamp_output_pointer`, `_stamp_canonical_artifact`,
   `_compute_content_hash`, or either call site. The fix is internal to
   `_fix_record`; both call sites (`:243` monolith, `:542` normalize
   lane) inherit the corrected ordering because they share
   `_fix_self_referential_hashes`. This IS the "mirror in
   `apply_normalize_transformations`" requirement: the normalize lane
   calls the same helper at `:542`, so no separate change exists there.

Allowed files (exactly two):

- `src/model_forge/harness/role_execution.py`
- `tests/test_harness_repairs.py`

## Regression tests (add to tests/test_harness_repairs.py)

Follow the file's existing conventions (module-level functions,
`tmp_path` fixture named `tmp_output` where used, imports of
`_fix_self_referential_hashes` and `model_forge.digests.jcs.canonicalize`
inside the test body). Both tests MUST FAIL on the pre-fix code and PASS
after; that is the TDD gate.

Test 1 - `test_content_sha256_recomputed_after_definition_stamping`:
build a method-style record with a placeholder `content_sha256`, an
`identity` dict (with a WRONG placeholder `definition_sha256`), and a
`mathematical_definition.canonical_definition`. Run
`_fix_self_referential_hashes(record, tmp_output)`. Assert
`record["content_sha256"] == hashlib.sha256(canonicalize(snapshot)).hexdigest()`
where `snapshot = {k: v for k, v in record.items() if k != "content_sha256"}`
taken AFTER the repair (i.e. including the stamped
`identity.definition_sha256`). Pre-fix this fails because the embedded
value was computed before `definition_sha256` was stamped. (Mirror the
assertion style of `test_content_sha256_is_computed_from_record_content`
at `tests/test_harness_repairs.py:38-58`.)

Test 2 - `test_content_sha256_recomputed_after_output_pointer_stamping`:
mirror the fixture vocabulary of
`tests/test_information_layers.py:28-70`: build an
`_OutputPointerContext` via `SimpleNamespace` specs and a real sibling
file (e.g. `synthesis-compact.json` with text `{"title": "x"}`) under
`tmp_path`; record has `content_sha256` placeholder AND a
`representations[0].artifact` with `uri = "output://synthesis-compact.json"`.
Call `_fix_self_referential_hashes(record, tmp_path / "synthesis-candidate.json",
pointer_context=context)`. Assert the stamped pointer fields landed
(`artifact["sha256"]` is the sibling file's digest) AND
`record["content_sha256"]` equals the post-repair recomputation (same
snapshot recipe as Test 1, including the stamped artifact fields).
Pre-fix this fails: the embedded digest predates the pointer stamp.

## Boundaries

- Write ONLY inside /home/tez/product/model-forge; never create or edit
  files outside it - not skill files, notes, memory, or scratch outside
  /tmp.
- No architecture-decision changes, no schema changes, no new codes.
- No em/en dashes and no trailing whitespace anywhere (validator-enforced
  under `architecture/`; keep the same discipline in code).
- One commit.
