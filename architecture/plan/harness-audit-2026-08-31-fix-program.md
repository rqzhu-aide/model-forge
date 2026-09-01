# Fix Program: Harness Audit 2026-08-31

Status: ACTIVE. One package, one commit, in the order below.
Source of truth for findings: [../harness-audit-2026-08-31.md](../harness-audit-2026-08-31.md)
(R1-R37 with file:line evidence). Decisions recorded in that document:
R15 delete, R14 enforce, R17 keep live (no code), R37 deferred.

## Execution rules

- Work on the tree at ~/product/model-forge, venv `.venv`.
- Implement via delegate_task subagents with self-contained briefs (see the
  model-forge skill's subagent-dispatch-playbook); the coordinator validates
  every claimed fix against the code before committing. Stray-write sweep
  after every subagent package.
- Gates before EVERY commit: `.venv/bin/python -m pytest tests -q` exit 0
  and `.venv/bin/python architecture/tools/validate_package.py` exit 0.
  No em/en dashes and no trailing whitespace in any file under
  `architecture/` (validator-enforced). UI packages additionally: vitest,
  `tsc --noEmit`, rebuilt dist.
- Every fix ships with a regression test that fails on the pre-fix code.
- Commit message convention: `Audit-2026-08-31 Pkg <letter>: <summary>`
  listing the R-numbers fixed.
- After each commit, mark the package DONE here with the commit SHA and
  the test count delta.
- If a package uncovers a contradiction with the audit's analysis, stop
  and record it in the audit doc instead of improvising.

## Packages

### P-A: Recovery core (R1, R5, R6) -- DONE

DONE 2026-08-31: pins commit 223edfa, fix commit ac8586e. Tests 1340 ->
1342 (+2: test_restart_with_in_flight_role_recovers,
test_null_identity_version_is_coerced_during_repair; both verified to fail
on pre-fix code). Gates: pytest exit 0, validate_package.py exit 0.
Implementation: `_execute` catches RoleExecutionPending and the new
RoleExecutionInfrastructureError (return True, run stays running);
observer repository calls wrap failures as RoleExecutionInfrastructureError
and both role_execution try blocks re-raise it unsealed;
identity.version coerced per pin.

- R1: `RoleExecutionPending` must not terminally fail the run. Catch it in
  `run_coordinator._execute` (return True, making the pending branch at
  `run_coordinator.py:135-136` live) or return a PENDING stage outcome;
  the run stays `running` and a later pass reconciles. Regression test:
  acknowledged execution + executor reconcile returns None through
  `resume_incomplete`; assert the run remains `running`.
- R5: `role_execution.py:196` version bump must coerce instead of raise:
  `v = identity.get("version"); if isinstance(v, bool) or not
  isinstance(v, (int, float)) or v < 1: identity["version"] = 1`.
  Regression test: agent output with `"identity": {"version": null}`
  closes as a normal validated closure, not a crashed run.
- R6: narrow the broad `except Exception` at `role_execution.py:1534-1541`
  and `:1659-1666` so harness-side/observer failures do NOT seal a durable
  FAILED closure (re-raise or mark retryable); executor-domain failures
  still seal FAILED. Regression test: observer raising a simulated DB
  error leaves the execution retryable, not sealed-failed.

### P-B: Digest ordering (R2)

- In `_fix_self_referential_hashes` (`role_execution.py:866-959`): stamp
  `handoff_artifact.sha256`, `identity.definition_sha256`, E-2 output://
  pointers, and E-2e input:// pointers FIRST; recompute `content_sha256`
  LAST (or iterate to a fixpoint). Mirror the ordering in
  `apply_normalize_transformations` (`:534-536`). Regression test: a method
  record requiring `definition_sha256` stamping must seal with
  `content_sha256` matching the sealed bytes per the
  `method_record.content` digest contract; same for a record with an
  E-2 `output://` representation pointer.

### P-C: Correction lane (R3, R4, R13, R7, R22)

- R3: build `agent_raw_bytes` from ALL of the role's specs in the
  correction plan, not `scoped_plan` (`role_execution.py:1916-1939`), so
  out-of-scope untouched outputs compare byte-equal and tampering is
  caught. Regression tests: two-output role, scope={A}, agent edits A
  only -> correction SUCCEEDS; agent also edits B -> blast-radius
  violation.
- R4: on the reconcile path (acknowledgement exists), skip source-byte
  materialization in `_prepare_correction_invocation`
  (`role_execution.py:1623` vs `:1645`, writes at `:1798-1805`), following
  the `_recovery_invocation` pattern. Regression test: acknowledged
  correction, workspace edited, replay -> agent bytes survive and the
  closure reflects the agent's edits.
- R13: `service.py:2990` - return the (possibly empty) sealed set for
  every non-failed closure; reserve the plan-declared union for
  `status == "failed"` only, per the C-2 plan. Regression test: SUCCEEDED
  closure with zero outputs + correction request -> refused as out of
  scope, not authorized.
- R7: preserve raw bytes in `_validate_and_close_correction` before the
  repair pass and record `raw_output_sha256` (`role_execution.py:2110`),
  mirroring the base path's fail-closed behavior (`:2617-2646`).
- R22: record the validation attempt AFTER blast-radius verification, or
  merge violation findings into the persisted report
  (`role_execution.py:1981-2006` vs `:2026-2036`).

### P-D: Envelope and provenance (R9, R10, R26)

- R9: pop provenance-class harness-owned fields when the sealed run fact
  is empty, mirroring the generation-identity strip
  (`envelope.py:373-382`); minimum: `review_basis_generation_id`
  (`:420-421`). Audit the other conditional overwrites (`record_type`,
  `sequence`, `to_role`, `lineage`) and apply the strip rule where an
  agent-fabricated value could pass schema validation. Regression test:
  review-finding output with agent-authored `review_basis_generation_id`
  on a run with no review-target input -> field absent at seal.
- R10: make `reclassify_harness_owned_finding` mode-aware: exclude
  `identity`/`lineage` for `method.schema.json` when the run is not
  method-bound (`envelope.py:86-93,243-258` vs `:360-367`). Regression
  test: catalog-mode method record with a bad `identity.version` routes to
  a correctable finding class, not OPERATIONAL_FAILURE.
- R26: pass the harness-owned field set into `_classify_transformations`
  and emit dedicated population codes for HV-4 overwrites and deliberate
  generation-identity strips (`role_execution.py:321-326,381-386`).

### P-E: Publication and reducers (R11, R12, R32, R33, R34, R35)

- R11: in `_materialize_writes`, require
  `set(prepared.source_input_sha256) == set(binding.source_input_ids)` and
  fail (`publication.transform_input_missing`) when a binding declares a
  source input, the slot has a prior generation, and the transform
  consumed none.
- R12: `_prior_items` (`index_reducers.py:215-218`) raises when
  `prior is not None` but the shape/format does not match.
- R32: register a real artifact for the canonical bundle payload (as
  `prepare_index_transforms` does, `index_reducers.py:86-95`) instead of
  attributing component-1's artifact (`publication.py:1090-1093`).
- R33: reject `applicable_modes` at the publication layer if unenforceable
  there, and route keyed `upsert_each` slots through scope/resolution or
  reject scope parameters when keyed bindings are present
  (`publication.py:606,942`). Both latent; the goal is fail-loud, not new
  behavior.
- R34: read the project head and slot inventory in ONE transaction in
  `capture_publication_basis` (`publication_basis.py:35-39`); make
  `recover_publication_head`'s missing `current_generations` a hard error
  when `complete_current_slot_inventory` is true.
- R35: literature-index fold keys (`index_reducers.py:221-235`): key on
  the full sorted identifier tuple (and a stable fallback) so enrichment
  updates instead of duplicates. Deterministic fold change; regression
  test with `[isbn:Y]` prior vs `[doi:X, isbn:Y]` change.

### P-F: Fencing deletion (R15; decided: delete)

- Remove the unused token machinery (`advance`, `check_fence`,
  `current_token`, `_seed_from_heartbeats`, `is_terminal`) and the
  in-memory lease store from `harness/invocation_fencing.py`; remove
  `acquire_lease`/`release_lease` usage in `run_coordinator.py:112,172`
  (the per-run asyncio lock stays). Update `tests/test_wp1_wp2_modules.py`
  and any other references. Update `architecture/design/02-run-harness.md`
  so the single-advancement guarantee is documented as: per-process
  asyncio lock + `compare_and_swap_run` CAS + closure-existence checks.

### P-G: Cancellation enforcement (R14; decided: enforce)

- Wire `cancellation_requested` polling into the local_hermes execute
  loop (alongside the heartbeat cadence, `executors/local_hermes.py:465-470`):
  when the repository flags cancellation for the run, call
  `executor.cancel` semantics on the in-flight process (terminate the
  process tree with the existing PID-identity guards) and return a
  CANCELLED `RoleExecutionResult`. Keep the cooperative close path in
  `_validate_and_close` (`role_execution.py:2614`) unchanged. Regression
  test: start a long fake execution, request cancellation mid-flight,
  assert prompt termination and a CANCELLED closure. Update
  `02-run-harness.md` section 11.1 to state prompt enforcement.

### P-H: Brief extraction (R16)

- `_extract_prohibited_fields` (`task_briefs.py:242-251`): track `not`
  depth; collect `required` as prohibition only under negation.
- `_extract_conditional_requirements` (`task_briefs.py:634-673`): walk
  then/else recursively and surface nested const-pinned required
  constraints. Regression test from the real counterexample:
  `evidence.schema.json` `method_match == "older_method_version"` must
  produce a brief entry requiring `alignment_at_creation.state` =
  `"outdated"`.

### P-I: P3 sweep (R18-R25, R27-R31, R36)

Small, independent hardening fixes; one commit, one regression test each
where cheap:

- R18: pre-resolve symlink check in `outputs.py:173-198`.
- R19: basename/containment check for `input://` names in
  `_stamp_canonical_artifact` (`role_execution.py:802-805`).
- R20: dedicated operational finding code for unreadable sealed submission
  payloads (`submission_validation.py:66-71`); register in the policy
  registry.
- R21: pass `schema_file`/`failing_property` for run-submission schema
  findings (`submission_validation.py:93-96`) so ADR-015 reclassification
  applies.
- R23: correct the `to_role` "empty when terminal" comment and document
  the multi-role-successor case (`envelope.py:63`,
  `role_execution.py:2556-2562`).
- R24: compact-view fallback skips summary-less JSON envelopes instead of
  dumping raw bytes (`role_execution.py:2351-2359`).
- R25: cache only successful parses in `_STABLEID_POSITIONS_CACHE`
  (`role_execution.py:1296-1298`).
- R27: classify promote-time re-validation failure honestly (not
  `run.coordination_failed`) (`run_coordinator.py:399-401`).
- R28: isinstance-guard `declared` in `_validate_phase_semantics`
  (`submission_validation.py:370,379-383`).
- R29: iterative DFS in `_has_cycle` (`scientific_validators.py:1523-1539`).
- R30: feature-check `put_bytes` with hasattr; propagate genuine failures
  (`output_adapters.py:143-152`).
- R31: guard the companion-scan `relative_to` and skip stale same-stem
  leftovers (`output_adapters.py:91-110`).
- R36: remove the dead `raise` after `_handle_error` and give the
  `.instructions` lookup a real error message
  (`run_coordinator.py:170,520-524`).

### P-J: Closure

- Verify every R-number is either landed or explicitly recorded as
  decided-no-change (R17, R37).
- Move `architecture/harness-audit-2026-08-31.md` to
  `architecture/archive/completed/` with a closure note citing the package
  commits; update `architecture/issues/README.md` if it references this
  audit.

## Progress log

- 2026-08-31: program created; groundwork commit carries the audit doc and
  this plan.
