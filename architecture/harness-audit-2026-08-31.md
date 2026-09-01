# Harness Audit 2026-08-31: Post-Sweep Residual Findings

Status: findings only (no code changes, no new tests)
Author: coder profile (5 parallel audit lanes + independent verification)
Basis: tree at `2abf534`. Suite state at audit time: backend pytest exit 0.
Method: five delegated file-lane audits over all of `src/model_forge/harness/`
plus the driving boundary (`run_coordinator.py`, `correction_execution.py`,
`cancel_run`, `local_hermes` executor). Every P1/P2 finding below was
independently re-verified against the code by the author before inclusion;
lane claims that failed verification were dropped or re-graded.

Prior sweeps whose findings are NOT repeated here: 2026-08-16 (NA/K items),
2026-08-29 (`9260dde`, 21 findings). Still-open knowns: NA-2 (cancel
relabeling across restart; needs persisted cancel intent - design decision),
K-7 (reviewer-memory boundary; open by design).

## P1 - reachable, run- or integrity-impacting

### R1: A server restart with an in-flight role terminally FAILS the healthy run

Chain (every link verified):

1. `local_hermes.reconcile()` returns `None` while the process is alive and
   identity-matched (`executors/local_hermes.py:683`).
2. `role_execution.py:1528-1533` raises `RoleExecutionPending` on a
   non-terminal acknowledged execution and re-raises it untouched.
3. `stage_execution.py` does not catch it (serial path 121-124; parallel
   path re-raises `errors[0]` at 132-135).
4. `ContractSequentialOrchestrator` has no `RoleExecutionPending` handling
   (zero references in `orchestration/`).
5. `run_coordinator._execute` (300-336) never returns `True` - the
   `if pending: return` branch at `run_coordinator.py:135-136` is dead code.
6. `run()`'s generic `except Exception` (167-170) routes to `_handle_error`
   (1150-1179): status `running` is not terminal/cancellation/conflict, so
   the run is CASed to FAILED with `run.coordination_failed`.
7. `list_incomplete_runs` excludes terminal runs, so the run is never
   resumed. No test exercises restart-with-in-flight-role
   (`tests/test_run_coordinator_recovery.py` covers only pre-preparation
   cancellation and terminal-resume noop; `RoleExecutionPending` appears in
   no test).

Impact: the "recovery-safe coordinator" kills exactly the runs recovery
exists to save. Any restart (deploy, crash, gateway bounce) during a 30-75
min run destroys it.

Fix: catch `RoleExecutionPending` in `_execute` (return `True`, making the
pending branch live) or return a PENDING `StageOutcome` from
`execute_or_reconcile_stage`; the run then stays `running` and the next
`resume_incomplete`/notify pass reconciles. Regression test: acknowledged
execution + executor whose reconcile returns `None` → `resume_incomplete`
leaves the run `running`.

### R2: `content_sha256` is stale on every record that receives pointer or definition stamping

`_fix_self_referential_hashes` (`role_execution.py:866-959`) recomputes
`content_sha256` at step 1 (`:873-877`) and then mutates the document at
step 2 (`handoff_artifact.sha256`, `:879-888`), step 3
(`identity.definition_sha256`, `:897-905`), step 4 (E-2 `output://`
pointer stamping, `:913-934`) and step 5 (E-2e `input://` stamping,
`:945-957`). Single pass, no fixpoint, no recomputation afterward
(call site `:236`). The last population-layer recompute
(`envelope.py:443-444`) happens BEFORE this whole repair stage
(`role_execution.py:160` vs `:236`), so it cannot cover these mutations.

Per `architecture/contracts/digest-contracts.json` (e.g.
`method_record.content`), the payload is the complete document minus
`/content_sha256` - so the sealed value is the digest of bytes that never
existed on disk whenever steps 2-5 changed anything. Step 3 alone (method
records with `canonical_definition`) is the common case.

Latent today because nothing in the closure/submission path recomputes the
embedded `content_sha256` (`digests/registry.py:verify_all` has no harness
caller; submission validation re-checks artifact byte digests, not embedded
digests). It is still an integrity defect: the sealed record's self-digest
is wrong by the registry's own contract.

Fix: in `_fix_record`, stamp pointers and `handoff_artifact`/
`definition_sha256` FIRST and recompute `content_sha256` LAST (or iterate
to fixpoint); mirror the ordering in `apply_normalize_transformations`
(`:534-536`). Regression test: method record whose `definition_sha256` is
stamped must have `content_sha256` matching the sealed bytes per
`method_record.content`.

### R3: Partial-scope Lane B corrections of multi-output roles deterministically fail blast-radius

- `correction_execution.py:1172-1182` builds `source_output_bytes` from ALL
  sealed outputs of the source closure (unscoped).
- `role_execution.py:1916-1923` filters the repair plan to `output_scope`;
  `:1930-1939` snapshots `agent_raw_bytes` for in-scope specs only.
- `:2018-2025` therefore builds `source_documents` = all outputs,
  `corrected_documents` = in-scope only.
- `verify_correction_blast_radius` (`correction_execution.py:966-979`)
  iterates `set(source) | set(corrected)`; an out-of-scope output has
  `corrected=None` ≠ source → automatic `correction.blast_radius_violated`.

Scenario: role seals outputs A and B; correction authorized for `{A}`;
agent edits only A → close fails on B, attempt spent. Two attempts →
`correction_exhausted` on a run the agent corrected correctly. Suite never
sees it: correction fixtures seal a single output
(`tests/test_correction_command_path.py:225,323`). Production shape exists
today (P2 `lead_reconciliation` seals 3 outputs).

Corollary hole (worse): because out-of-scope outputs are absent from
`corrected_documents`, agent tampering with them is never compared. For a
K5-3 partial-seal source, wholesale creation of an out-of-scope output
passes blast-radius unexamined and is sealed into a SUCCEEDED correction
closure (`:1975-1978` seals all validated specs).

Fix: build `agent_raw_bytes` from ALL of the role's specs in the
correction plan (not `scoped_plan`); untouched out-of-scope files then
compare byte-equal and tampering is caught. Regression test: two-output
role, scope={A}, agent edits A only → correction SUCCEEDS; agent also
edits B → blast-radius violation.

### R4: Correction replay clobbers the agent's in-place edits, then records a silent no-op as success

`execute_correction` runs `_prepare_correction_invocation` unconditionally
BEFORE the acknowledgement check (`role_execution.py:1623` vs `:1645`).
Prepare materializes source bytes with plain `write_bytes` over the
correction output paths (`:1798-1805`), destroying any edits the agent
already made before a crash. On replay with the same correction identity
(idempotent command replay, `service.py:2543-2551`): acknowledge exists →
`reconcile` returns the terminal result → close validates the restored
SOURCE bytes (valid, since they were sealed valid) → blast radius compares
restored-source vs source → vacuously clean → SUCCEEDED correction closure
byte-identical to the pre-correction output, which `load_existing` then
prefers over the base. The correction is recorded as successful while
having done nothing.

Fix: when an acknowledgement exists, skip source-byte materialization
(the `_recovery_invocation` pattern at `:2260-2293`), or materialize only
into absent paths with a loud digest-mismatch failure. Regression test:
acknowledged correction, workspace edited, replay → agent bytes survive.

## P2 - real defects, narrower blast radius

### R5: `identity.version` bump crashes on agent-authored non-numeric version; the role can never close

`role_execution.py:196`: `identity.get("version", 1) < 1` raises TypeError
for `version: null` or `"0"`. The only try in the repair pass wraps file
read/parse (`:119-125`); `_validate_and_close` calls repair unguarded
(`:2668`); `execute_or_reconcile`'s try (`:1521-1541`) ends before the close
call (`:1551`). Agent writes `"identity": {"version": null}` → run FAILED
via `_handle_error`, no closure sealed; resume reconciles to the same
SUCCEEDED execution and crashes identically. Unrecoverable inside the run.

Fix: `v = identity.get("version"); if isinstance(v, bool) or not
isinstance(v, (int, float)) or v < 1: identity["version"] = 1`; or wrap
per-spec repair so repair crashes degrade to a FAILED closure.

### R6: Broad `except Exception` turns transient infrastructure errors into durable, unretryable FAILED closures

`role_execution.py:1534-1541` (mirrored at `:1659-1666` for corrections)
converts ANY exception from `executor.execute`/`reconcile` - including
observer/repository failures such as a DB error inside
`acknowledge_execution` - into a FAILED `RoleExecutionResult` that
`_validate_and_close` then seals immutably. `load_existing` returns the
base closure with no retry, so the role is permanently failed for the run
identity even if the agent never ran. (Adjacent to NA-2 but distinct:
transient-error durability, not cancel relabeling.)

Fix: narrow the catch to executor-domain failures, or make harness-side
exceptions non-sealing (retryable).

### R7: Correction closures never preserve raw output bytes (HV-1.1 asymmetry)

`role_execution.py:2110` hard-codes `"raw_output_sha256": None`; no
`preserve_raw_output` call in `_validate_and_close_correction`. The base
path treats raw preservation as mandatory and fail-closed
(`:2617-2646`: "without the raw snapshot the harness could not prove which
bytes the agent wrote"). A failed correction's agent bytes survive only in
the transient `agent_raw_bytes` dict; the repair pass already destroyed
them on disk.

Fix: preserve before repair, record the digest, mirror the base path.

### R8: Schema helpers hardcode `parents[3]/architecture/schemas` and swallow all failures silently

`role_execution.py:1000`, `:1023`, `:1208` resolve schemas from a fixed
relative path while validation's `SchemaCatalog` loads from the
configurable `architecture_root`. Broad swallows with no logging:
`:1005-1006` (record_type const → `""`), `:1051-1052` (`_empty_schema_info`
→ all repairs skipped), `:1296-1297` (heuristic fallback). Under an
alternate architecture root or installed-package layout, validation passes
against configured schemas while timestamp injection, record_type
derivation, and ID sanitization silently no-op or degrade to name
heuristics - repair coverage diverges from the validating schema with zero
signal.

Fix: thread the specification's schema directory into these helpers; log
at ERROR (or fail closed) when an existing schema file fails to parse.

### R9: `review_basis_generation_id` survives agent fabrication when the harness has no value

`envelope.py:420-421` overwrites only when the run fact is truthy, but the
field is harness-owned for review-finding, review-report, and review-issue
schemas, and `_sealed_run_facts` leaves it `""` whenever the recipe has no
P5 review-target input (`role_execution.py:2563-2572`). An agent can then
fabricate a `review_basis_generation_id` pointing at an arbitrary
generation; it survives population, passes schema validation, and flows
into formal state via the review-issue upsert binding. Contradicts the
docstring's always-overwrite policy (`envelope.py:311-315`) and the F-1
strip-when-empty rule applied to generation identity (`:373-382`).

Fix: pop provenance-class fields when the run fact is empty, mirroring
the generation-identity strip. Audit which other conditional-overwrite
fields (`record_type` :357, `sequence`/`to_role` :410-413, `lineage`
:438-439) need the same treatment.

### R10: ADR-015 reclassification misroutes agent-authored `identity`/`lineage` errors in catalog modes

`identity`/`lineage` are unconditionally harness-owned for
`method.schema.json` (`envelope.py:86-93`), so
`reclassify_harness_owned_finding` converts their findings to
OPERATIONAL_FAILURE with `correction_class="none"`. But
`populate_harness_fields` deliberately leaves `identity` agent-authored
when no method is selected (`:360-367`, "by design" for
`p2.full_catalog`/`researcher_proposal`). A catalog-mode agent error under
`identity.*` becomes an uncorrectable operational fault that kills the run
instead of entering a correction lane - the ADR-015 premise ("the harness
re-populates those fields at every close") is false in exactly these modes.

Fix: make reclassification mode-aware (exclude `identity`/`lineage` when
no method is selected).

### R11: Declared reducer input binding never enforced - a populated index can be silently replaced by a from-scratch one

`source_input_ids` is an allowed binding field (`publication.py:609`) read
nowhere in the file; `_validate_bindings` never checks it;
`_materialize_writes` verifies only `source_output_sha256`. If the recipe
lacks the declared frozen prior input, `prepare_index_transforms` reduces
with `prior=None` (`index_reducers.py:75-83`), discarding all prior index
entries; publish still succeeds (slot CAS compares generation IDs only).
Compounded by R12.

Fix: require `set(prepared.source_input_sha256) ==
set(binding.source_input_ids)` in `_materialize_writes`; fail when a
binding declares a source input and the slot has a prior generation but
the transform consumed none.

### R12: Index reducers silently treat a malformed pinned prior as empty

`_prior_items` (`index_reducers.py:215-218`) returns `[]` when the prior
document isn't a dict or its field isn't a list; no format/format_version
check. A digest-frozen but shape-wrong prior index silently rebuilds empty
and the truncated index is published as the new current record - silent
history loss, fail-open where the rest of the pipeline fails closed.

Fix: when `prior is not None` and shape/format mismatch, raise.

### R13: Scope wall - a SUCCEEDED closure with zero sealed outputs gets plan-declared correction scope

`service.py:2990`: `if declared and str(closure_payload.get("status")) !=
"failed": return declared`. For a non-failed closure with EMPTY sealed
outputs the guard is falsy, so control falls into the K5-3/C-2 union
branch and the gate returns the plan-declared scope - authorizing
wholesale creation of a never-sealed artifact. The C-2 plan
(`archive/c2-partial-seal-correction-scope-plan-2026-08-25.md:41-44,58`)
specifies "SUCCEEDED closures keep the sealed-only scope"; tests cover
only succeeded-with-nonempty (`test_correction_command_path.py:1093-1107`).

Fix: `if str(closure_payload.get("status")) != "failed": return declared`
 -  return the (possibly empty) sealed set for non-failed closures.

### R14: Cancellation never reaches the in-flight role

Design 02 §11.1 says the harness "asks active work to stop". The only
`executor.cancel` call is in `settle_cancellation`
(`role_execution.py:2235`), which runs inside `run()` - but the first
`run()` pass holds the per-run `asyncio.Lock` while awaiting
`executor.execute`, and the `local_hermes` execute loop
(`executors/local_hermes.py:420-489`) polls only process exit and the
deadline, never `cancellation_requested`. The notifier's second `run()`
pass blocks on the lock until the role exits naturally. Cancel during a
15-minute role = wait for natural exit. `executor.cancel`'s prompt-kill
path (with its PID-identity guards) is unreachable for the role that
matters.

Fix: have the execute loop (or observer heartbeat) poll
`repository.cancellation_requested` and call `cancel`, or document the
weaker semantics in 02-run-harness.md.

### R15: The invocation-fencing machinery is decorative

- `InvocationFencer.advance`/`check_fence`/`is_terminal` have zero
  production callers (only tests); the docstring invariant "a stale token
  cannot launch, heartbeat, cancel, or close" is enforced nowhere. No
  production code writes heartbeats either.
- The coordinator lease's holder is the deterministic string
  `f"coordinator:{run_id}"` (`run_coordinator.py:111`), identical in every
  process, and conflict requires DIFFERENT holders
  (`invocation_fencing.py:122`) - so the lease excludes no one,
  cross-process included. It also expires after 120 s with no renewal
  during multi-hour runs. The real protection is the per-process
  `asyncio.Lock` plus the DB compare-and-swap in
  `RunLifecycle._mutate` → `compare_and_swap_run` (verified sound).
- `_seed_from_heartbeats` (`invocation_fencing.py:175-188`) swallows all
  DB errors and fails OPEN to 0 - if the token path were ever wired, a
  transient read error would regress the counter below previously issued
  tokens.

Fix (matches Tez's retired-code preference): delete the dead token/lease
machinery and downgrade the docstring, or wire `check_fence` into the
executor lifecycle and make seeding fail closed. Do not leave the current
middle state - it reads as a safety control that does not control.

### R16: Task-brief conditional extraction misreads `else`-block `required` and misses nested then-constraints

- `_extract_prohibited_fields` (`task_briefs.py:242-244`) collects a bare
  `required: [...]` in an `else` block as PROHIBITED; JSON Schema semantics
  are the opposite (required when the condition fails). Latent: current
  schemas use only the `not: {anyOf: [{required: ...}]}` shape (verified
  across scientific-record/theory-record/review-issue/evidence).
- `_extract_conditional_requirements` (`task_briefs.py:634-673`) reads only
  top-level `then.required`; real counterexample:
  `evidence.schema.json` - `if method_match == "older_method_version"` then
  `alignment_at_creation.state` must be const `"outdated"` via NESTED
  properties/required; extraction yields NO brief entry, so the agent is
  never told a rule that validation then blocks on (burning a correction
  cycle).

Fix: track `not` depth for prohibitions; walk then/else recursively for
nested const-pinned requirements.

### R17: Mode/stage instruction layers and the P1 gap appendix are resolved LIVE at execution, not sealed in the manifest

`run_coordinator._execution_components` (`:534-582`) loads the CURRENT
project brief at execution time to render mode/stage instructions and the
LITERATURE_GAP appendix; the manifest seals role souls/skills
(`role_resources`) but not these instruction layers. A brief edit between
command acceptance and execution (or before a correction) changes what the
run executes without any stale-basis rejection. The phase instruction
itself IS frozen via `choice_values`; this is the derived layers only.
Possibly deliberate (corrections SHOULD see updated guidance) - flagged as
a decision item, not a defect.

## P3 - small, low-likelihood, or cosmetic-integrity

- **R18**: `outputs.py:177,198` - `resolve(strict=True)` fully resolves
  symlinks, so `resolved.is_symlink()` is always False; the
  `output.not_regular_file` guard never fires for symlinks. Check
  `path.is_symlink()` pre-resolve.
- **R19**: `_stamp_canonical_artifact` (`role_execution.py:802-805`)
  resolves `input://<name>` without a basename/containment check -
  `input://../../x` reads outside the sandboxed inputs dir and stamps its
  digest into a sealed record (content oracle).
- **R20**: corrupt sealed submission payload surfaces `json.*` finding
  codes classified as correctable/packaging (`submission_validation.py:66-71`),
  routing an unfixable harness-side corruption into the correction lane
  until exhaustion. Emit a dedicated operational code.
- **R21**: run-submission schema findings bypass the ADR-015 harness-owned
  reclassification (`submission_validation.py:93-96` passes no
  `schema_file`/`failing_property`); harness-assembled submission defects
  misroute as agent-correctable.
- **R22**: blast-radius-failed corrections record a PASSING validation
  attempt report (`role_execution.py:1981-2006` persists before the
  blast-radius check at `:2026-2036`); ledger consumers read a false pass.
- **R23**: `to_role` silently empty when the next stage is multi-role
  (`role_execution.py:2556-2562`); the envelope comment says "empty when
  terminal", which is wrong for this case.
- **R24**: compact-view fallback materializes the FULL raw artifact bytes
  as the "compact" markdown when the envelope lacks `summary_markdown`
  (`role_execution.py:2351-2359`), inflating briefs with raw JSON.
- **R25**: `_STABLEID_POSITIONS_CACHE` permanently caches transient-failure
  heuristic fallbacks (`role_execution.py:1296-1298`); cache successes only.
- **R26**: `_classify_transformations` has no population-aware codes; HV-4
  overwrites record as generic `value_rewrite` and deliberate
  generation-id strips as `additional_properties_strip`
  (`role_execution.py:321-326,381-386`) - audit-trail attribution wrong.
- **R27**: `_promote` re-validation failure raises a bare ValueError that
  `_handle_error` records as `run.coordination_failed` FAILED
  (`run_coordinator.py:399-401`) - misleading class for a deterministic
  re-check flip after an upgrade.
- **R28**: `_validate_phase_semantics` can AttributeError on a truthy
  non-object `identity` (`submission_validation.py:370,379-383`; latent -
  escapes the `(PublicationError, ValueError)` catch and stalls the run in
  `validating`).
- **R29**: `_has_cycle` recurses over agent-controlled dependency depth
  (`scientific_validators.py:1523-1539`; `statements` has no maxItems) -
  RecursionError instead of a finding at ~1000-deep chains.
- **R30**: `preserve_raw_output`'s AttributeError fallback
  (`output_adapters.py:143-152`) masks real bugs and writes outside the
  store via the private `artifacts._paths.root` - the returned digest then
  doesn't resolve through the store.
- **R31**: companion scan registers stale same-stem leftovers as linked
  artifacts (`output_adapters.py:91-110`); unguarded `relative_to`.
- **R32**: bundle generations carry component-1's artifact metadata as
  their own (`publication.py:1090-1093`) - resolving the generation's
  artifact yields bytes unrelated to the bundle.
- **R33**: `applicable_modes` accepted but never enforced
  (`publication.py:606`); `upsert_each` bypasses slot scope/resolver
  (`publication.py:942`) - both latent today.
- **R34**: `capture_publication_basis` reads head and slot inventory on two
  connections (`publication_basis.py:35-39`) - torn snapshot possible;
  fail-closed downstream, so retry-inducing only.
- **R35**: literature-index fold keys on the lexicographically smallest
  identifier only (`index_reducers.py:221-235`) - enriched identifiers or
  any content edit duplicate instead of update.
- **R36**: `run()`'s `raise` after `_handle_error` is dead code (the
  handler always returns True); `next(...)` over `.instructions` choices
  raises a messageless StopIteration if absent
  (`run_coordinator.py:170,520-524`).
- **R37 (possibly deliberate)**: P5 review-revision validators pass
  vacuously when NO review outputs exist - all four are `required: False`
  (`scientific_validators.py:1096-1196`). If "zero findings" should require
  at least one review artifact, the contract must say so.

## Verified sound (selection)

- ADR-019 seed channel: seeds targeting required inputs are rejected
  (`inputs.py:109-135`); supplementary slots never resolve from the store.
- Submission assembly: CAS-fenced, idempotent, correction-attempt ordinals
  crash-safe (`submissions.py`).
- Base closure path: raw preservation before repair, fail-closed;
  `_load_closure` verification chain complete.
- Publication atomicity: single `BEGIN IMMEDIATE`, commit-time CAS,
  idempotent retry fails loud.
- Frozen-contract backfill (`9260dde`): pin-matched, idempotent,
  conflict-safe.
- `compare_and_swap_run` under `RunLifecycle` provides the actual
  single-advancement guarantee (see R15).
- Lane-1 correction F-3 ordering: agent bytes snapshotted before harness
  repairs; blast radius judges agent bytes.
- All emitted finding codes checked against the policy registry; no
  typo-inert validators; mode/output literals match contracts.

## Decisions (Tez, 2026-08-31)

- R15 (fencing machinery): DELETE the dead token/lease path; keep the
  per-process asyncio lock and the DB compare-and-swap as the documented
  single-advancement mechanism; update 02-run-harness.md accordingly.
- R14 (cancellation): ENFORCE - wire cancellation polling into the
  execution path so `executor.cancel` reaches the in-flight role.
- R17 (instruction layers): KEEP LIVE resolution of mode/stage instruction
  layers and the P1 gap appendix at execution time; record as deliberate.
- R37 (vacuous review-revision pass): left as-is; flagged for a future
  contract decision (not part of this fix program).
