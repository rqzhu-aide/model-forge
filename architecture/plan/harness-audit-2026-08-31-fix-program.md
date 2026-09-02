# Fix Program: Harness Audit 2026-08-31

Status: COMPLETE 2026-09-02 (P-J closure commit 840925e; all packages
DONE). One package, one commit, in the order below.
Source of truth for findings: [../harness-audit-2026-08-31.md](../archive/completed/harness-audit-2026-08-31.md)
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

### P-B: Digest ordering (R2) -- DONE

DONE 2026-09-01: pins commit 11e017c, fix commit 8cd6fb2. Tests 1342 ->
1344 (+2: test_content_sha256_recomputed_after_definition_stamping,
test_content_sha256_recomputed_after_output_pointer_stamping; both
verified by the coordinator to fail on pre-fix code with the predicted
stale-digest assertion). Gates: pytest exit 0, validate_package.py exit
0. Implementation: the content_sha256 recompute block moved to the END
of `_fix_self_referential_hashes._fix_record` (after handoff,
definition_sha256, output:// and input:// pointer stamping), docstring
updated; both call sites (role lane monolith :243, normalize lane :542)
share the helper so no separate normalize-lane change was needed. Probe
fact recorded in the pins doc: no schema carries both content_sha256 and
handoff_artifact, so a single reorder is exact and no fixpoint iteration
was added.

- R2: `content_sha256` is stale on every record that receives pointer or
  definition stamping. Fixed per above; regression tests named above.

### P-C: Correction lane (R3, R4, R13, R7, R22) -- DONE

DONE 2026-09-01: pins commit a350be9, fix commit 977e82b. Tests 1344 ->
1351 (+7: test_partial_scope_correction_of_multi_output_role_passes,
test_out_of_scope_edit_of_multi_output_role_violates_blast_radius,
test_correction_replay_preserves_agent_edits,
test_correction_closure_preserves_raw_output,
test_correction_raw_preservation_failure_closes_failed,
test_blast_radius_violation_attempt_report_records_failure,
test_correction_scope_succeeded_empty_closure_refused; all seven
verified by the coordinator to fail on pre-fix code with the predicted
defects). Gates: pytest exit 0, validate_package.py exit 0 (re-run by
the coordinator after the commit). Probe facts recorded in the pins
doc: R3/R4/R13 recipes were reproduction-probed against pre-fix code
before dispatch (six out-of-scope violations on an agent-correct
partial-scope correction; replay sealed restored source bytes without
the agent marker; succeeded-empty closure command accepted). One
approved pin amendment during execution: the R3 violation test edits
decision.json (dict) instead of attention-items.json (JSON array,
which the dict-only editing factory cannot mutate). Implementation:
agent_raw_bytes snapshot iterates all of the role's specs via
output_plan.for_stage_role; execute_correction reads the
acknowledgement before prepare and passes materialize_source_bytes
(False on the reconcile path); _validate_and_close_correction preserves
raw bytes fail-closed (base-path parity, nested so a preservation
failure records no attempt row), records the validation attempt AFTER
blast-radius verification with violation findings in the persisted
report, and seals raw_output_sha256; _correction_scope_outputs returns
the (possibly empty) sealed set for every non-failed closure.

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

### P-D: Envelope and provenance (R9, R10, R26) -- DONE

DONE 2026-09-01: pins commit cfccf57, fix commit 67b58e6. Tests 1351 ->
1358 (+7: test_review_basis_generation_id_stripped_when_run_fact_empty,
test_to_role_stripped_when_terminal, test_record_type_stripped_when_unresolved,
test_catalog_mode_method_identity_finding_stays_correctable,
test_method_bound_method_identity_finding_stays_operational,
test_generation_identity_strip_code, test_harness_population_overwrite_code;
all seven verified by the coordinator to fail on pre-fix code with the
predicted defects: fabricated-value survival for the R9 trio, TypeError on
the new method_bound/harness_owned parameters for R10/R26). Gates: pytest
exit 0 (1358 passed, 0 failures), validate_package.py exit 0 (re-run by
the coordinator after the commit). Pre-dispatch reproduction probe
(/tmp/pd_probe.py) confirmed all three defects live; the same probe
post-fix confirms the flips. Probe decisions recorded in the pins doc:
sequence needs no strip (phase contracts 1-based), lineage gets no strip
(never populated by the harness, required by method.schema.json - residual
ADR-015-premise gap for method-bound lineage recorded in the pins doc, not
fixed here), record_type stripped when unresolved (scientific-record's
recordType is an enum, so in-enum fabrication would pass). No R26 rule-7
test migrations were needed (legacy _classify_transformations callers do
not pass harness_owned and no test pinned the old codes on harness-owned
fields).

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

### P-E: Publication and reducers (R11, R12, R32, R33, R34, R35) -- DONE

DONE 2026-09-01: pins commit d099e03, fix commit 3d1b539. Tests 1358 ->
1368 (+10: test_index_transform_missing_declared_prior_input_fails,
test_bundle_generation_registers_own_artifact,
test_keyed_binding_with_slot_scope_is_rejected,
test_plan_binding_outside_run_mode_is_rejected,
test_malformed_prior_index_non_object_raises,
test_malformed_prior_index_wrong_format_raises,
test_malformed_prior_index_missing_array_raises,
test_shared_smallest_identifier_does_not_merge,
test_recover_publication_head_requires_sealed_inventory,
test_capture_publication_basis_single_snapshot; the coordinator
independently re-verified the nine regression tests fail on pre-fix code
with the predicted defects - the tenth is a behavior-preservation smoke
for the single-transaction refactor). Gates: pytest exit 0 (1368
passed), validate_package.py exit 0 (re-run by the coordinator after the
commit). Probe facts recorded in the pins doc
(plan/harness-audit-2026-08-31-pe-pins.md): R11 conditioned on a prior
generation because an unconditional set-equality check would fail every
legitimate first-run index build (frozen_inputs holds only resolved
inputs); R33 applicable_modes enforced only when the binding source
carries a mode (all 22 real contract bindings declare it, so field
rejection would break all publication); R35 audit symptom correction
recorded in the audit doc's Coordinator notes - the pinned full-tuple
key fixes the silent-merge collision case, while the named enrichment
case ([isbn:Y] vs [doi:X, isbn:Y]) still yields two entries and needs an
identity-resolution design decision. Implementation: transform-input
consumption check in the deterministic_index replace branch; fail-closed
_prior_items with format/format_version checks; bundle payloads
registered as their own content-addressed artifacts (new artifacts
parameter on publish/validate_materialization, wired from the
coordinator); binding-mode applicability check in _extract_bindings;
keyed upsert_each + slot scope rejected fail-loud;
capture_head_and_current_slots reads head and inventory in one
immediate transaction; recover_publication_head requires the sealed
current_generations when the inventory flag is set.

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

### P-F: Fencing deletion (R15; decided: delete) -- DONE

DONE 2026-09-01: pins commit d3cf9c4, fix commit 6dc2ff7. Tests 1368 ->
1368 (delta 0: removed the 3 TestInvocationFencer tests, added 3 in
tests/test_run_advancement_guarantee.py; all three verified by the
coordinator to fail on pre-fix code with the predicted defects -
find_spec assertion, _fencer source assertion, AttributeError on the
lease call). Gates: pytest exit 0 (1368 passed), validate_package.py
exit 0 (re-run by the coordinator after the commit). Probe facts
recorded in the pins doc
(plan/harness-audit-2026-08-31-pf-pins.md): production usage was exactly
four lines in run_coordinator.py; the same-named fencing classes in
diagnostics/store.py and application/run_profile_assembler.py are
separate machinery and were left untouched. Implementation: module
deleted; coordinator import, construction, acquire/release, and the
lease-only try/finally removed (asyncio lock kept); unused imports and
stale docstrings cleaned in the two WP1/WP2 test files;
02-run-harness.md section 10 now documents the single-advancement
guarantee as per-run asyncio lock + compare_and_swap_run CAS +
closure-existence checks.

- R15: removed the unused token machinery (`advance`, `check_fence`,
  `current_token`, `_seed_from_heartbeats`, `is_terminal`) and the
  in-memory lease store from `harness/invocation_fencing.py`; remove
  `acquire_lease`/`release_lease` usage in `run_coordinator.py:112,172`
  (the per-run asyncio lock stays). Update `tests/test_wp1_wp2_modules.py`
  and any other references. Update `architecture/design/02-run-harness.md`
  so the single-advancement guarantee is documented as: per-process
  asyncio lock + `compare_and_swap_run` CAS + closure-existence checks.

### P-G: Cancellation enforcement (R14; decided: enforce) -- DONE

DONE 2026-09-01: pins commit 9868ba1, fix commit b72f939. Tests 1368 ->
1369 (+1: test_mid_flight_cancellation_terminates_role_and_closes_cancelled;
passes on the pre-package tree because the mechanism already shipped - see
below). Gates: pytest exit 0 (1369 passed), validate_package.py exit 0.
CONTRADICTION recorded in the audit doc's Coordinator notes: R14's premise
that settle_cancellation is the only executor.cancel call site and that
the prompt-kill path is unreachable was already false at audit time -
RepositoryExecutionObserver.heartbeat polls cancellation_requested on
every heartbeat and calls executor.cancel (execution_observer.py:96-114,
present in groundwork commit 429c198), the local_hermes poll loop
heartbeats once per poll interval with the same executor instance, and
both closure paths convert the killed role to CANCELLED. Live probe
(plan/harness-audit-2026-08-31-pg-pins.md, probe fact 4): a 30 s
in-flight role terminated 0.33 s after cancellation acceptance; both
parallel roles received executor.cancel; stage outcome CANCELLED; both
closures sealed "cancelled". Resolution per the program's contradiction
rule: no production change; the package ships the planned mid-flight
regression test (pinning the previously untested behavior) and the
02-run-harness.md 11.1 prompt-enforcement paragraph. Executed
planner-direct (test + two doc edits smaller than the brief; pins doc
records the rationale).

- R14: verified already implemented (observer-heartbeat cancellation
  polling -> executor.cancel -> PID-identity-guarded process-group kill ->
  CANCELLED closure). Regression test named above pins it.

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

### P-H: Brief extraction (R16) -- DONE

DONE 2026-09-01: pins commit f66e04d, fix commit bf8ea5f. Tests 1369 ->
1373 (+4: test_else_branch_bare_required_is_not_prohibited,
test_double_negation_required_is_not_prohibited,
test_nested_const_then_requirement_surfaced,
test_nested_const_else_requirement_surfaced; all four verified by the
coordinator to fail on pre-fix code with the predicted defects -
prohibition misread on role-invocation-closure termination, double
negation collected, KeyError on both nested const entries). Gates: pytest
exit 0 (1373 passed), validate_package.py exit 0 (re-run by the
coordinator after the commit). The dispatch died after writing code and
tests but before gates/commit; the coordinator audited the diff against
the pins (verbatim match), salvaged per the P1-variant pattern, and
applied one approved pin amendment (recorded in the pins doc): Edit 2's
_describe_condition/_describe_else_condition recursion rendered nested
conditions with leaf-only names while the pinned tests require dotted
paths - both functions gained a `_prefix` parameter threading the dotted
path. Implementation: _extract_prohibited_fields tracks not-depth (a
bare else.required affirms, not prohibits); _extract_conditional_requirements
surfaces nested const-pinned required constraints from then AND else via
_extract_nested_const_requirements; _render_schema_constraints renders
the pinned value. Verified extractor outcomes match the pins' expected
table (evidence.schema.json gains alignment_at_creation.state=outdated;
method.schema.json gains lineage.change_source.kind=research_run;
role-invocation-closure termination prohibition gone;
attention-item.schema.json rendering unchanged).

- R16: fixed per above; regression tests named above.

### P-I: P3 sweep (R18-R25, R27-R31, R36) -- DONE

DONE 2026-09-01: pins commit 9dc592b, fix commit ba713a4. Tests 1373 ->
1388 (+15, in two new files tests/test_p3_hardening_harness.py and
tests/test_p3_hardening_submission.py: test_symlinked_output_is_not_regular_file,
test_canonical_input_pointer_rejects_traversal,
test_compact_view_skips_summary_less_envelope,
test_stableid_positions_cache_stores_success_only,
test_has_cycle_deep_chain_iterative, test_has_cycle_deep_cycle_detected,
test_preserve_raw_output_propagates_put_bytes_failures,
test_preserve_raw_output_fallback_when_put_bytes_missing,
test_companion_scan_skips_outside_workspace,
test_companion_scan_skips_stale_leftovers,
test_unreadable_submission_payload_is_operational,
test_run_submission_schema_finding_reclassifies_harness_owned,
test_promote_revalidation_failure_is_classified,
test_phase_semantics_guards_non_object_identity,
test_execution_components_reports_missing_instructions; the coordinator
verified all fourteen defect-pinning tests fail on pre-fix code with the
predicted defects via per-file stash-revert probes - the fifteenth,
test_preserve_raw_output_fallback_when_put_bytes_missing, is a
behavior-preservation guard for the R30 fallback). Gates: pytest exit 0
(1388 passed), validate_package.py exit 0 (run after the commit tree was
final). Stray-write sweep clean. Executed as two parallel lanes against
the committed pins doc (plan/harness-audit-2026-08-31-pi-pins.md, which
records the re-probed live-tree locations - audit line numbers had
drifted - and one pinned interpretation: R31 "stale" means mtime strictly
older than the validated output, since the audit does not define it).
One documented pin deviation: the R24 test uses real sha256 digests
because the placeholder guard skips single-character digests before the
fallback path. R23 is comment-only per plan ("where cheap"). Also in
scope per run directive: the environmental TestHermesVersion flake fix,
a single-constant bump of the version-probe timeout
(local_hermes.py wait_for timeout 10 -> 30); no test depends on the
value.

- R18-R25, R27-R31, R36: fixed per the pins doc; regression tests named
  above.

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

### P-K: Schema helper root and failure signal (R8) -- DONE

DONE 2026-09-02: pins commit e58d363, fix commit cca96c2. Tests 1388 ->
1398 (+10, new file tests/test_schema_helper_root.py:
test_schema_record_type_const_honors_non_default_root,
test_schema_info_honors_non_default_root,
test_stableid_positions_honors_non_default_root,
test_stableid_positions_cache_isolated_by_schemas_dir,
test_malformed_existing_schema_logs_error_record_type,
test_malformed_existing_schema_logs_error_schema_info,
test_malformed_existing_schema_logs_error_stableid,
test_missing_schema_file_degrades_without_error_log,
test_repair_monolith_uses_threaded_schemas_dir,
test_normalize_transformations_threads_schemas_dir; the coordinator
independently verified via stash-revert that all ten fail on pre-fix
code with the predicted TypeError). Gates: pytest exit 0 (1398 passed),
validate_package.py exit 0 (run after the commit tree was final).
Stray-write sweep clean. The first dispatch stopped correctly on a pin
conflict: probe fact 5 assumed self.schemas is always a real
SchemaCatalog, but five test stand-ins (four _PermissiveSchemas, one
OutputPermissiveSchemas across five test files) lack .directory,
producing 36 identical AttributeError failures. Approved amendment
(recorded in the pins doc): the fakes gained a real directory pointing
at the repo schemas dir (production code stays strict/fail-loud; no
getattr fallback), applied planner-direct per the P1-variant rule.
Implementation: _default_schemas_dir helper; the three schema helpers
gain keyword-only schemas_dir (default preserves the prior parents[3]
resolution); existing-but-unparseable schema files now log ERROR via
the module logger before the unchanged degrade (missing file stays
silent); _STABLEID_POSITIONS_CACHE keyed by (str(directory),
schema_file), store still success-only; schemas_dir threaded through
_apply_disclosed_mechanical_repairs and apply_normalize_transformations
and wired from RoleLifecycleService (self.schemas.directory, both call
sites) and correction_execution.py (schemas.directory, both call
sites).

Added 2026-09-02 after P-J closure verification found R8 unassigned
(coverage gap recorded in the audit doc's Coordinator notes). Audit
line numbers have drifted; the live-tree locations below were verified
on the post-P-I tree.

- R8: thread the configured schema directory into
  `_schema_record_type_const`, `_schema_info`, and
  `_stableid_positions` (`role_execution.py:1055,1078,1263`) in place of
  the hardcoded `parents[3]/architecture/schemas`, so repair coverage
  cannot silently diverge from the schemas validation actually uses
  (SchemaCatalog honors the configured architecture_root). Log at ERROR
  (or fail closed) when an existing schema file fails to parse,
  replacing the silent `except Exception` swallows (`:1060-1061`,
  `:1106-1107`, and the `_stableid_positions` heuristic fallback).
  Regression tests: helpers honor a non-default architecture root; a
  malformed existing schema file surfaces an ERROR signal instead of
  silently degrading to empty schema info / name heuristics.

### P-J: Closure -- DONE

DONE 2026-09-02: closure commit 840925e. Tests 1398 -> 1398 (delta 0;
docs-only package, no test changes). Gates: pytest exit 0 (1398
passed), validate_package.py exit 0. Coverage re-verified
programmatically at closure: all 37 findings (P1/P2 headings R1-R17,
P3 bullets R18-R37) are present in the audit doc and assigned in this
program (P-A through P-K) or decided-no-change (R17, R37). The audit
doc moved to `architecture/archive/completed/` with a closure note
citing all package commits; the pins-doc and plan links were
retargeted; `architecture/archive/completed/README.md` gained a
program entry; `architecture/issues/README.md` does not reference this
audit (verified).

- Verify every R-number is either landed or explicitly recorded as
  decided-no-change (R17, R37). DONE 2026-09-02 (programmatic check):
  all findings accounted for once P-K was added; R8 was the sole gap.
  Re-verified at closure (commit 840925e).
- Move `architecture/harness-audit-2026-08-31.md` to
  `architecture/archive/completed/` with a closure note citing the package
  commits; update `architecture/issues/README.md` if it references this
  audit. DONE 2026-09-02 in commit 840925e. Verified 2026-09-02:
  issues/README.md does not reference this audit.
- Closure-time link maintenance (noted 2026-09-02): the pins docs under
  `architecture/plan/` reference `../harness-audit-2026-08-31.md`;
  retarget those links to `../archive/completed/harness-audit-2026-08-31.md`
  when the audit moves. DONE 2026-09-02 in commit 840925e (8 pins/plan
  link retargets plus 2 backtick path updates).
- UNBLOCKED 2026-09-02: P-K landed (fix cca96c2); closure may proceed.

## Progress log

- 2026-08-31: program created; groundwork commit carries the audit doc and
  this plan.
- 2026-09-02: P-J closure verification found R8 assigned to no package
  and not decided-no-change; the gap is recorded in the audit doc's
  Coordinator notes and the program is extended with P-K (R8). Program
  remains ACTIVE; P-J is blocked until P-K lands.
- 2026-09-02: P-K (R8) DONE - pins e58d363, fix cca96c2, tests 1388 ->
  1398. First dispatch stopped on a pin conflict (test-double catalogs
  lack .directory, 36 AttributeError failures); resolved by approved
  amendment giving the five fakes a real directory. P-J unblocked.
- 2026-09-02: P-J closure DONE (commit 840925e, tests 1398 -> 1398).
  Audit doc archived to `architecture/archive/completed/` with a
  closure note citing all package commits; links retargeted; archive
  README entry added. Program COMPLETE.
