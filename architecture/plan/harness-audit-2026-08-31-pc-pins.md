# P-C Implementation Pins: Correction lane (R3, R4, R13, R7, R22)

Status: PINNED 2026-09-01 (coordinator). Subagent executes; it does not
design. Every probe fact below was re-verified against the live tree at
commit 19e508a (post P-B).

Source findings: [../harness-audit-2026-08-31.md](../harness-audit-2026-08-31.md).
Program entry: P-C in
[harness-audit-2026-08-31-fix-program.md](harness-audit-2026-08-31-fix-program.md).

## Probe facts (live-tree verified)

- `role_execution.py:_validate_and_close_correction` (:1909-2160): the
  snapshot loop at :1960-1969 iterates `scoped_plan.specs` (in-scope
  only). `source_documents` (:2048-2051) covers ALL sealed source
  outputs; `corrected_documents` (:2052-2055) covers in-scope only, so
  every untouched out-of-scope output compares `corrected=None` vs
  source and trips `correction.blast_radius_violated` (R3).
- End-to-end R3 reproduction (throwaway probe, scientific correction on
  the 7-output role `p1.lead_synthesis`/`research_lead`, scope =
  `{p1.synthesis_candidate}`, agent mutating ONLY the in-scope output):
  `passed == False` with SIX `correction.blast_radius_violated`
  findings, one per out-of-scope output. Post-fix prediction for the
  same recipe: `passed == True`, zero findings.
- `execute_correction` (:1600-1717): `_load_closure` short-circuit at
  :1623, cancellation check at :1632, `_prepare_correction_invocation`
  at :1651, acknowledgement read at :1673. Prepare materializes source
  bytes with plain `write_bytes` at :1831-1835. So on the reconcile
  path prepare runs BEFORE the acknowledgement check and clobbers the
  agent's in-place edits (R4).
- Closure document at :2140 hard-codes `"raw_output_sha256": None`;
  `_validate_and_close_correction` never calls `preserve_raw_output`.
  The base close path preserves at :2653-2661 with fail-closed handling
  at :2662-2676 and records the digest at :2783 (R7).
- `record_validation_attempt` at :2026-2036 persists the attempt row
  (report built from `validation.findings` at :2011-2016) BEFORE the
  blast-radius check at :2056-2066, so a blast-radius-failed correction
  persists a PASSING report (R22).
- `service.py:_correction_scope_outputs` :2990:
  `if declared and str(closure_payload.get("status")) != "failed":
  return declared`. For a non-failed closure with EMPTY `declared` the
  guard is falsy and control falls into the plan-declared union branch
  at :3010-3013 (R13). The docstring at :2982-2983 already specifies
  the fixed behavior ("SUCCEEDED closures keep the sealed-only scope").
- `preserve_raw_output` (`output_adapters.py:122-127`) signature:
  `(workspace: Path, run_id: str, role: str, artifacts) -> str`;
  returns the artifact SHA-256 of a tar.gz of the role workspace.
- `get_or_create_execution` (`repository.py:908-917`) raises
  `RepositoryConflictError` when an existing intent row's
  invocation_sha256/payload differ. CONSEQUENCE: regression tests must
  NOT hand-pre-create the correction execution row; drive the real
  acknowledge-then-crash path instead (see R4 test pin).
- `verify_correction_blast_radius` (`correction_execution.py:956-1006`)
  already implements the exact semantics the R3 fix relies on:
  `source == corrected` skips; out-of-scope difference violates;
  in-scope scientific changes are free; in-scope source-absent
  creation (K5-3) is allowed. No change to this function.
- Multi-output role for tests: `p1.lead_synthesis`/`research_lead`
  (stage index 1) seals 7 outputs: p1.source_changes
  (source-changes.json), p1.synthesis_compact (synthesis-compact.json),
  p1.synthesis_candidate (synthesis-candidate.json),
  p1.coverage_candidate (coverage-candidate.json), p1.phase2_handoff
  (phase2-handoff.json), p1.attention_items (attention-items.json),
  p1.decision (decision.json). `_golden_output`
  (test_correction_submission.py:52) produces a conforming document for
  every one of these file names. `_basis_before(lead_synthesis)`
  (`stage_execution.py:223`) resolves once stage-0 discovery closures
  are sealed SUCCEEDED: the 4 frozen recipe inputs (shared with
  discovery) plus the 3 discovery output closures equal exactly the
  role's 7 input ids.
- `_PermissiveSchemas` (test_correction_execution.py:55-60) validates
  nothing; the blast-radius comparison parses documents with
  `json.loads`, so parsed-document equality (not byte equality) is what
  keeps untouched out-of-scope outputs clean.
- `TargetedCorrectionOutcome` (correction_execution.py:1089-1094):
  fields `closure_id: str`, `passed: bool`,
  `findings: tuple[ValidationFinding, ...]` (findings are OBJECTS with
  `.code` / `.object_id` / `.message`, not dicts).
- `RoleExecutionPending` lives in
  `model_forge.harness.execution_records` (:23).

## Fix 1 (R3): snapshot ALL of the role's specs, not the scoped plan

File: `src/model_forge/harness/role_execution.py`,
`_validate_and_close_correction`.

In the SUCCEEDED branch, change ONLY the snapshot loop spec set. The
loop currently reads `for scoped_spec in scoped_plan.specs:`. Replace
with an iteration over `output_plan.for_stage_role(stage.stage_id,
role)` (the correction output plan already rewires every one of this
role's specs into the correction workspace, so the snapshot paths are
correct for in-scope AND out-of-scope outputs). Keep `scoped_plan`
exactly as-is for the `_apply_disclosed_mechanical_repairs` call (the
F-3 repair scope restriction is unchanged). Replace the loop-variable
name `scoped_spec` with `role_spec` in the loop body, and replace the
snapshot comment block with:

```
            # Snapshot the agent's raw bytes for ALL of the role's specs
            # (not only the in-scope repair plan) BEFORE the repair pass:
            # blast-radius verification below judges the agent's own edits.
            # Untouched out-of-scope outputs then compare equal to their
            # materialized source bytes, and agent tampering with an
            # out-of-scope output is caught instead of comparing against
            # an absent corrected document (R3).
```

Nothing else changes in this function for R3: `corrected_documents`
(:2052-2055) automatically covers every role spec present on disk, and
`verify_correction_blast_radius` handles equality, scope, and the K5-3
source-absent branch. Note: `json.loads` on out-of-scope bytes is safe
because the blast-radius block only runs when `validation.passed`,
which already requires every output to parse.

## Fix 2 (R4): skip source-byte materialization on the reconcile path

File: `src/model_forge/harness/role_execution.py`.

1. In `execute_correction`, move the line
   `acknowledgement = self._acknowledgement(execution_id)` from its
   current position after `observer.launch_intent` to immediately
   BEFORE `output_plan = self._correction_output_plan(stage, role,
   command_id)`. Pass a new keyword to the prepare call:
   `materialize_source_bytes=acknowledgement is None`. Delete the old
   assignment (the try block keeps using the same local). Add one
   docstring sentence: on the reconcile path (a durable acknowledgement
   exists) source-byte materialization is skipped so the agent's
   in-place edits survive an idempotent replay (R4).
2. In `_prepare_correction_invocation`, add a keyword-only parameter
   `materialize_source_bytes: bool` (no default; the single call site
   passes it explicitly). Guard the write loop:

```
        for spec, output_path in zip(specs, output_paths):
            source = source_output_bytes.get(spec.contract_output_id)
            if source is None or not materialize_source_bytes:
                continue
            output_path.write_bytes(source)
```

   Extend the loop's comment block with: when a durable acknowledgement
   exists the correction workspace may hold the agent's in-place edits
   from before a crash; re-materializing source bytes would clobber
   them and record a silent no-op as success (R4), so the caller skips
   materialization on the reconcile path (the `_recovery_invocation`
   pattern).

## Fix 3 (R7): preserve raw bytes in the correction close path

File: `src/model_forge/harness/role_execution.py`,
`_validate_and_close_correction`. Mirror the base close path
(:2646-2677) EXACTLY, including its nesting structure:

1. Declare `raw_seal_sha256: str | None = None` with the other
   initializers near :1935.
2. At the TOP of the `elif status is RoleExecutionStatus.SUCCEEDED:`
   branch, insert the preservation block, mirroring :2653-2676 verbatim
   (lazy `from .output_adapters import preserve_raw_output`; call with
   `workspace=invocation.workspace, run_id=invocation.run_id, role=role,
   artifacts=self.artifacts`; on exception: `logger.exception` with the
   same message, `status = RoleExecutionStatus.FAILED`,
   `failure_code = "output.raw_preservation_failed"`, and replace
   `result` with the same FAILED RoleExecutionResult summary text the
   base path uses).
3. Nest the ENTIRE remaining body of the branch (the scoped_plan /
   snapshot / repair / validation / blast-radius / attempt-recording
   code, with the R3 and R22 edits applied) one level deeper under
   `if status is RoleExecutionStatus.SUCCEEDED:`, exactly as the base
   path nests at :2677. This matters: a preservation failure must NOT
   record an HV-5.6 executor-failed attempt row (base-path parity).
4. In the closure document, replace `"raw_output_sha256": None`
   (:2140) with `"raw_output_sha256": raw_seal_sha256`.

## Fix 4 (R22): record the attempt AFTER blast-radius verification

File: `src/model_forge/harness/role_execution.py`, same branch.

Reorder so the persisted attempt report reflects the final outcome:

1. Immediately after `sealed_outputs = tuple(...)`, declare
   `violations: tuple[ValidationFinding, ...] = ()`.
2. `if not validation.passed:` sets FAILED +
   `output.structural_validation_failed` (unchanged). The `else:` blast
   block is unchanged except it assigns the module-level `violations`
   variable instead of a block-local one.
3. MOVE the whole ordinal / attempt_id / report / digest_input /
   source_sha256 / prior / `record_validation_attempt` block to AFTER
   the if/else, and build the report from the final findings:
   `list(violations) if violations else validation.findings` as the
   findings argument. Everything else in the moved block (chaining via
   `get_latest_validation_attempt`, correction_type and command id
   columns, digest input over `validation.outputs`) is byte-identical.
4. The closure-doc `findings` variable keeps its current behavior:
   validation finding dicts, replaced by violation dicts when the blast
   radius fails.

Exactly one attempt row is still recorded per correction re-invocation;
only its content changes (failing report + violation findings on
blast-radius failure).

## Fix 5 (R13): non-failed closures keep the (possibly empty) sealed set

File: `src/model_forge/application/service.py`,
`_correction_scope_outputs` :2990. Replace

```
        if declared and str(closure_payload.get("status")) != "failed":
```

with

```
        if str(closure_payload.get("status")) != "failed":
```

One-line change; the docstring already specifies this behavior. Effect:
a SUCCEEDED closure with zero sealed outputs returns the empty set, the
scope gate at :2399 rejects with CORRECTION_SCOPE_INVALID, and only
`status == "failed"` closures reach the K5-3/C-2 plan-declared union.

## Regression tests (all must FAIL on the pre-fix code)

Suite baseline: 1344 passed at commit 19e508a. Expected after: 1351
(+7). Test files: `tests/test_correction_lane_b.py` (+6),
`tests/test_correction_command_path.py` (+1).

### tests/test_correction_lane_b.py additions

New imports to add: `document_sha256`, `closure_artifact_id`,
`output_artifact_id`, `role_identity` from
`model_forge.harness.execution_records` (alongside the existing
`correction_role_identity` import); `canonicalize` from
`model_forge.digests.jcs`; `RoleExecutionResult`,
`RoleExecutionStatus` from `model_forge.executors.protocol`;
`RoleExecutionPending` from `model_forge.harness.execution_records`;
`_digest` from `test_correction_execution` (extend the existing
import); `hashlib`, `dataclasses` as needed (check what is already
imported).

Helpers (add once, module level):

- `_seal_multi_output_failed_closure(fixture, role)`: generalize
  `_seal_failed_closure_bytes` (test_correction_command_path.py:221) to
  seal EVERY spec of
  `fixture.output_plan.for_stage_role(fixture.plan.stages[1].stage_id,
  role)`; per-spec payload bytes are
  `(json.dumps(_golden_output_by_name(name), indent=2) + "\n").encode()`
  where the document comes from `_golden_output` invoked with a stub
  whose `expected_output_paths[offset - 1]` ends in the spec's file
  name (mirror the probe pattern: a tiny class with an
  `expected_output_paths` list). Stage is `fixture.plan.stages[1]`;
  the closure document is the same shape as
  `_seal_failed_closure_bytes` (status "failed", failure_code
  "output.structural_validation_failed", empty findings) with the full
  outputs list. Return the closure_id.
- `_golden_editing(edit_names)`: factory wrapping `_golden_output`;
  when the output file name (from
  `invocation.expected_output_paths[offset - 1]`) is in `edit_names`
  and the document is a dict, return a copy with
  `doc["agent_correction_edit"] = True`.
- `_CrashAfterAckExecutor(DeterministicFakeExecutor)`: `execute` awaits
  `super().execute(invocation, observer)` and then raises
  `RoleExecutionPending("Simulated post-acknowledgement crash.")`.
  (DeterministicFakeExecutor.execute writes the factory outputs,
  acknowledges via the observer, and stores the SUCCEEDED result in
  `self.results`, so `reconcile` on the replay returns it.)

Tests:

1. `test_partial_scope_correction_of_multi_output_role_passes` (R3):
   fixture with
   `DeterministicFakeExecutor(_golden_editing(frozenset({"synthesis-candidate.json"})))`;
   `fixture.execute()` to seal stage-0 discovery closures; seal the
   7-output failed base closure; drive `_drive(fixture,
   _lane_b_services(fixture, "cmd_r3", "scientific"), base_closure_id,
   "cmd_r3", "scientific", ("p1.synthesis_candidate",))`. Assert
   `outcome.passed is True` and `outcome.findings == ()`. PRE-FIX:
   fails with `passed == False` and six blast-radius findings (probe
   verified).
2. `test_out_of_scope_edit_of_multi_output_role_violates_blast_radius`
   (R3): same recipe with edit set
   `{"synthesis-candidate.json", "attention-items.json"}` and command
   id "cmd_r3b". Assert `outcome.passed is False` and the violation
   findings contain EXACTLY ONE finding with
   `code == "correction.blast_radius_violated"` and
   `object_id == "p1.attention_items"` (the in-scope scientific edit is
   free). PRE-FIX: six out-of-scope findings fire, so the exactly-one
   assertion fails.
3. `test_correction_replay_preserves_agent_edits` (R4): fixture with
   `_CrashAfterAckExecutor(_golden_editing(frozenset({"theory-discovery.json"})))`.
   Wait: the theorist output file name is theory-discovery.json;
   confirm with
   `Path(fixture.output_plan.for_stage_role(fixture.stage.stage_id,
   "theorist")[0].relative_path).name` in the test and build the edit
   set from that name. Seal the base closure with
   `_seal_failed_closure_bytes(fixture, "theorist",
   _fixable_defect_bytes())`. First `_drive` (command id "cmd_r4",
   scientific, scope `(_scope(fixture),)`): assert it raises
   RoleExecutionPending (wrap in pytest.raises). Second `_drive` with
   the same command id: returns normally. Assert (a)
   `len(fixture.executor.invocations) == 1` (the replay reconciled, no
   fresh execute); (b) the correction closure payload (closure id =
   `correction_role_identity(RUN, fixture.recipe.sha256, fixture.stage,
   "theorist", "cmd_r4")[2]`, payload via
   `json.loads(fixture.repository.get_role_closure(closure_id)["payload_json"])`)
   has `status == "succeeded"`; (c) the sealed output bytes
   `fixture.artifacts.read_bytes(payload["outputs"][0]["sha256"])`
   contain `b"agent_correction_edit"` (the agent's edit survived into
   the sealed closure). PRE-FIX: the replay's prepare re-materializes
   the source bytes over the agent's edit, the sealed bytes lack the
   marker, assertion (c) fails.
4. `test_correction_closure_preserves_raw_output` (R7): mirror
   `test_packaging_correction_passes` (command id "cmd_r7"); after the
   successful drive, load the correction closure payload and assert
   `payload["raw_output_sha256"]` is a 64-char hex string and
   `fixture.artifacts.verify(payload["raw_output_sha256"])` returns
   without raising. PRE-FIX: the value is None.
5. `test_correction_raw_preservation_failure_closes_failed` (R7):
   `monkeypatch.setattr("model_forge.harness.output_adapters.preserve_raw_output",
   _raising)` where `_raising(**kwargs)` raises
   `RuntimeError("simulated store failure")` (the call site imports
   lazily inside the function, so the patched attribute is picked up);
   drive a normal packaging correction ("cmd_r7b"); assert
   `outcome.passed is False` and the closure payload has
   `status == "failed"` and
   `failure_code == "output.raw_preservation_failed"`. PRE-FIX: the
   correction close never calls preserve_raw_output, so it succeeds.
6. `test_blast_radius_violation_attempt_report_records_failure` (R22):
   mirror `test_packaging_correction_blast_violation_fails` (command id
   "cmd_r22"); after the failed drive, read
   `fixture.repository.list_validation_attempts(RUN)`, assert exactly
   one row, and `report = json.loads(attempts[0]["report_json"])` has
   `report["passed"] is False` and at least one finding with
   `code == "correction.blast_radius_violated"`. PRE-FIX: the persisted
   report passed (validation findings only), so both assertions fail.

### tests/test_correction_command_path.py additions (R13)

Helper `_seal_empty_outputs_succeeded_closure(fixture, role)`: mirror
`_seal_empty_outputs_failed_closure` (:778) with `"status":
"succeeded"`, `"failure_code": None`, and empty findings.

Test `test_correction_scope_succeeded_empty_closure_refused`: mirror
the setup of
`test_correction_scope_uses_plan_declared_outputs_when_nothing_sealed`
(:938) using the new helper: fixture + `_ServiceStack`, seal the
succeeded empty closure, `_set_run(fixture, "failed",
_run_payload(fixture, CORRECTABLE))`, get the "package_run_outputs"
action, build the CorrectionRequest with scope `[_scope(fixture)]`,
preserve the raw request, then assert
`pytest.raises(CommandRejected)` with
`caught.value.error.code == "CORRECTION_SCOPE_INVALID"`. PRE-FIX: the
gate returns the plan-declared union, the command is accepted, and no
exception is raised.

## Boundaries

- Production edits: ONLY `src/model_forge/harness/role_execution.py`
  and `src/model_forge/application/service.py`.
- Test edits: ONLY `tests/test_correction_lane_b.py` and
  `tests/test_correction_command_path.py`.
- Do NOT change `verify_correction_blast_radius`,
  `_correction_output_plan`, the base close path, or any architecture
  document.
- No new error codes (`output.raw_preservation_failed` and
  `correction.blast_radius_violated` already exist), so the error-code
  registry is untouched.
