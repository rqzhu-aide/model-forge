# Harness Mechanics Audit and Fix Log

Status: Active fix log, 2026-08-15
Author: coder profile
Scope: the formal-lane delivery path as implemented (`run_coordinator.py`,
`stage_execution.py`, `role_execution.py`, `outputs.py`, `task_briefs.py`,
`envelope.py`, `submission_validation.py`), audited against the phase
contracts and the real run history in `~/.method-hub/method-hub.sqlite3`.

Related: [harness-validation-index.md](harness-validation-index.md) (HV-0..HV-7,
implemented in `63dca62`). This audit covers what that program did not:
the wiring between the new policy/envelope machinery and the delivery path.

## Evidence base

Production run history (39 formal-lane runs): 11 published, 26 failed,
2 rejected. All 26 failures are `output.structural_validation_failed`; 177 of
204 role closures succeeded. Finding codes across failed closures:

```
 78  schema.required
 33  schema.minItems
 17  schema.additionalProperties
 12  schema.type
 10  schema.enum
  8  schema.pattern
  5  schema.const
  3  output.required_missing
  3  schema.maxLength
 ...
```

Live probe (2026-08-15, this audit): for every (stage, role) group in all 8
phase modes, synthesized schema-valid outputs, stripped the fields the task
brief declares harness-owned, and ran the REAL
`_apply_disclosed_mechanical_repairs` + `validate_role_outputs`. Result:
every group producing record-typed outputs (all lead stages, P3/P4 analyst
stages, P5 review stages) fails with blocking `schema.required` findings on
`content_sha256`, `authority_at_creation`, and (P4) `finalized_at` and
identity fields. Groups producing handoffs pass.

## ISS-1 (P0): the brief promises harness-populated fields; nothing populates them

- The brief tells agents: "Timestamps ... are stamped by the harness from
  sealed run facts - do not write them" (`task_briefs.py:711-712`) and, per
  output, "The harness will populate: ... do not attempt to write them"
  (`task_briefs.py:800-805`), using `envelope.harness_owned_fields`.
- `envelope.populate_harness_fields` / `prepare_candidate_output` exist but
  have ZERO callers outside `envelope.py` itself (verified by grep).
- The repair pass fills only: top-level `created_at`/`updated_at`
  (`role_execution.py:141-144`, `_TIMESTAMP_FIELDS` covers no other fields),
  `schema_version` (145-147), `content_sha256` only when the key already
  exists (549-553), parent-scoped nested timestamps.
- An agent that obeys the brief therefore fails validation on every schema
  that requires `content_sha256` (all record schemas), `authority_at_creation`
  (scientific-record, theory-record, manuscript-package, review-finding,
  review-report, decision-record), `finalized_at` (empirical-protocol), and
  run-identity fields (`source_run_id`, `phase`, `mode`, `record_id`,
  `generation_id`, ...) where the envelope registry declares them
  harness-owned.

This is the single largest deliverable defect: it converts obedient agent
behavior into run failures on the exact stages (lead synthesis, P3/P4 records,
P5 reviews) that carry the formal record.

## ISS-2 (P0, latent): envelope.py defects that block safe wiring

Found while evaluating ISS-1's fix:

- a. `envelope._compute_content_sha256` uses `json.dumps(sort_keys=True)`,
  not RFC 8785 (`digests.jcs.canonicalize`). `digest-contracts.json` declares
  `construction: rfc8785_sha256` for every embedded `content_sha256`.
  Default `json.dumps` inserts whitespace separators and serializes numbers
  differently than JCS, so the stamped hash is not the contract digest.
- b. `envelope._build_authority` returns a dict
  `{source_run_id, manifest_sha256, sealed_basis_digest}`, but
  `authority_at_creation` is `common-definitions#/$defs/creationAuthority`,
  a string enum (`run_local_candidate` | `formal_generation`). Wiring this in
  would produce schema-invalid documents.
- c. `created_at` handling contradicts its own comment: the comment says the
  harness overrides, the code preserves an agent-written value
  (`envelope.py:240-243`). Harness-owned fields must be overwritten; an
  agent-written run timestamp is exactly what the design forbids.
- d. `envelope._derive_record_id` returns `{prefix}.{run_short}` for every
  item: all items of one array output (for example `p2.method_changes`)
  would receive the SAME record id, producing duplicate stable identities.
- e. `prepare_candidate_output` rejects non-dict payloads
  (`envelope.py:429-442`), so every `each_item` (array) output is unusable
  through it.
- f. `populate_harness_fields` writes `method_identity`/`identity`/`lineage`
  unconditionally from run facts. In catalog modes (`p2.full_catalog`,
  `p2.researcher_proposal`) no method is selected (empty dict) and new
  methods NEED agent-authored identities; unconditional population is wrong
  there.

## ISS-3 (P1): repair hash stamping uses the wrong canonicalization

`role_execution.py:_compute_content_hash` (497-519) and the handoff and
`definition_sha256` stamping in `_fix_self_referential_hashes` (522-607) use
`json.dumps(sort_keys=True)` instead of RFC 8785. Additionally
`definition_sha256` is computed over the whole `mathematical_definition`
dict, while the domain model (01-research-domain-model §3.3) and digest
contract scope it to `canonical_definition` only. Nothing re-verifies these
embedded digests today (latent), but every stamped value disagrees with the
registered digest contract, so future verification (and any independent
writer) fails against current artifacts.

## ISS-4 (P1, latent): `_load_closure` cannot reload closures that omit optional outputs

`role_execution.py:1406-1409` requires a SUCCEEDED closure to bind EVERY
declared output (`actual_outputs != expected_outputs` raises). P5 declares 6
optional outputs (`p5.review_issues`, `p5.assembly_report`, `p5.theory_audit`,
`p5.empirical_audit`, `p5.outside_review`, `p5.revision_account`; verified in
`contracts/phases/P5.json`). The first successful P5 run that omits an
optional output produces a closure that raises `RoleLifecycleError` on every
reload, breaking restart reconciliation and downstream stage recovery.
P1-P4 declare no optional outputs, so this has not fired in production.

## ISS-5 (P1): raw-output preservation fails silently

`_validate_and_close` wraps `preserve_raw_output` in `except Exception` and
records `raw_seal_sha256 = None` (`role_execution.py:1159-1168` and
1208-1218). HV-1's acceptance requires the original digest to be recoverable
for every outcome; today a preservation failure is invisible. It should be
loud (a recorded finding on the closure and a log line at minimum), because
publication without preserved raw bytes loses the provenance evidence.

## ISS-6 (P2): dynamic schema.* findings are misclassified as integrity blockers

`domain/validation.py:_DEFAULT_POLICY` classes every unregistered code as
`INTEGRITY_BLOCKER`. The jsonschema-derived codes (`schema.required`,
`schema.minItems`, ...) are the dominant real-world findings (78+33+17+...
in production) and are structural, correctable contract errors, not integrity
violations. The classification feeds the lifecycle projection's
`needs_output_correction` vs `rejected` distinction (HV-3), so
misclassification misroutes recovery. They must still BLOCK publication until
corrected; only the class changes.

## ISS-7 (P2): ID sanitization coverage gaps can both miss and break references

`_deep_sanitize_ids` (`role_execution.py:163-197`) rewrites values under keys
ending `_id`/`_ids` (plus `stable_id`, `affected_record_ids`). Production
shows a pattern-valid failure surviving repair
(`evidence.kernel_overhead_quantified_50x_at_M_100` fails
`^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$`), so at least one ID-bearing field is
not covered. Conversely, rewriting an ID at its definition site without
rewriting same-valued references under non-matching key names creates
dangling cross-references. The safe policy is to sanitize exactly the fields
the schemas pattern-check, and to rewrite same-valued references document-wide.

## ISS-8 (P3): dead/confused code in `_fix_item`

`role_execution.py:124-140`: the `_ids`-array sanitization clause has an
operator-precedence-tangled condition and is subsumed by
`_deep_sanitize_ids`. Remove or simplify after ISS-7 lands.

## ISS-9 (P3): the 5 new phase schemas have no positive examples

`theory-record`, `empirical-protocol`, `manuscript-package`, `review-finding`,
and `review-report` have no `architecture/examples/*.example.json`. HV-6
acceptance requires a positive example per newly allowed structure; examples
also anchor the brief skeletons and validator tests.

## Fix order

ISS-3 -> ISS-2 -> ISS-1 -> ISS-4 -> ISS-5 -> ISS-6 -> ISS-7/8 -> ISS-9.
Each fix lands with tests and keeps the backend suite and the spec gate green.

Fix log entries are appended below as work completes.

## Fix log

### 2026-08-15/16: ISS-3, ISS-2, ISS-1, ISS-4, ISS-5, ISS-6 (one wiring changeset)

ISS-3 landed first as the shared canonicalization base, then ISS-2's six
envelope defects, then ISS-1 wiring on top; ISS-4/5/6 are independent and
landed in the same changeset. All changes uncommitted until suite + gate
verification on 2026-08-16.

- **ISS-3**: `_compute_content_hash` and `_fix_self_referential_hashes` now
  use `digests.jcs.canonicalize` (RFC 8785); `definition_sha256` is computed
  over `canonical_definition` only, matching 01-research-domain-model §3.3.
- **ISS-2**: (a) `_compute_content_sha256` uses JCS; (b)
  `authority_at_creation` is stamped as the `creationAuthority` enum string
  `run_local_candidate`; (c) harness-owned `created_at` is unconditionally
  overwritten from sealed run facts; (d) `_derive_record_id` takes
  `item_index` so `each_item` array outputs get unique identities
  (`{prefix}.{run_short}.{item_index}`); (e) `prepare_candidate_output`
  accepts list payloads for `each_item` outputs; (f)
  `method_identity`/`identity` are populated only when the run actually
  selected a method, so catalog modes keep agent-authored identities.
- **ISS-1**: `RoleLifecycleService._sealed_run_facts` builds run facts from
  the frozen plan/manifest/recipe (method identity from
  `*.selected_method` choices, `to_role` from the next single-role stage,
  `review_basis_generation_id` from the `p5.current_manuscript` frozen
  input); `_record_type_by_output` maps output IDs to publication-binding
  record types; `_apply_disclosed_mechanical_repairs` now takes
  `run_facts` + `record_type_by_output` and populates harness-owned envelope
  fields inside the repair pass, so the source digest stays the agent's raw
  bytes.
- **ISS-4**: `_load_closure` requires a SUCCEEDED closure to bind every
  REQUIRED output only; optional outputs (P5's six) may be absent. Closures
  that omit optional outputs now reload cleanly.
- **ISS-5**: raw-output preservation failure on the success path fails
  closed: the closure is FAILED with `output.raw_preservation_failed`, the
  candidate is not validated, and the exception is logged. The failure path
  (`executor.role_failed`) still preserves-best-effort and logs.
- **ISS-6**: `domain/validation.py` classifies the dynamic `schema.*` family
  as `CORRECTABLE_CONTRACT_ERROR` (still publication-blocking) via a bounded
  prefix rule in `get_policy`; all other unregistered codes remain
  fail-closed integrity blockers. `POLICY_VERSION` 1.5.0 -> 1.6.0.

Verification (2026-08-16): backend suite 1062 passed, 0 failed;
`architecture/tools/validate_package.py` exit 0. New tests:
`tests/test_role_closure_integrity.py` (ISS-4 reload of a
succeeded-without-optional-output closure incl. no-relaunch reconciliation;
ISS-5 fail-closed preservation via monkeypatched `preserve_raw_output`),
plus updated `tests/test_envelope_construction.py` and
`tests/test_harness_repairs.py`. Test-authoring note: `RoleInvocation` is a
frozen dataclass; executors that filter expected outputs must derive a copy
with `dataclasses.replace` (mutating in place raises FrozenInstanceError,
which the harness converts to `executor.role_failed`).

Remaining: ISS-7/ISS-8 (ID sanitization coverage + `_fix_item` cleanup),
ISS-9 (positive examples for the 5 new phase schemas).
