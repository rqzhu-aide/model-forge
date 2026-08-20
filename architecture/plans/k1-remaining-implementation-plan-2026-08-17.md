# K-1 Remaining Implementation Plan + NA-2 (2026-08-17)

Status: COMPLETE (updated 2026-08-20). All packages landed and verified:
`ad3e2a6` (P1 foundation), `c1cf087` (P2 Lane A re-entry + D4 fix),
`b91fe9e` (P3a command path), `74b243f` (P3b router endpoint),
`a5a666d`/`a7532d0`/`e9f4c7e` (P4a/b/c normalize + preview),
`894203a` (P7 NA-2 persisted cancel intent),
`d1f3777`/`7a99f1e`/`8447cb6` (P5a/P5b Lane B), `d0b2ca2` (D5
recover-not-rerun), `bbd4274` (P6 prep: preview output_scope),
`18c5e8e` (P6 design pins), `b8abe8b` (P6 K-1d correction controls UI,
coder-built per Tez directive). Suite 1248 green, vitest 130/130,
validator exit 0 at `b8abe8b`. Remaining: the deferred K-5 production
re-exercise below (now unblocked: P1-P6 have all landed). K-7 stays
open by design. K-2 and D5 were decided 2026-08-19 (Tez): K-2
doc-only, D5 recover-not-rerun.
Author: coder profile
Basis: K-1 design (k1-correction-command-path-design.md), harness audit
2026-08-16, full re-audit of the current tree at `57529d4`.

## Audit verification results

Every claimed gap was re-verified against the code:

| Item | Verified state |
|---|---|
| Correction endpoint | ABSENT: `api/router.py` has 8 POST routes, none for corrections |
| Service entrypoint | ABSENT: zero references to `correction` in `service.py` |
| Preview endpoint | ABSENT |
| `CorrectionRequest` model | ABSENT from `api/models.py` (action type literals exist at :49-51) |
| Error codes | ABSENT from `CommandErrorCode`/`ERROR_RULES` (`api/errors.py`) |
| Run-view correction descriptors | ABSENT: `run_views.py` builds only `cancel_run`; `available_recovery_controls` hardcoded `[]` (:374) |
| Lane A execution core | PRESENT: `correction_execution.py` (K-1a3/a4); its docstring defers transitions/submission to "K-1a5" |
| Storage | PRESENT: `run_validation_attempts` (migration 12), repository methods :719-837 |
| Identity family | PRESENT: `correction_role_identity` (execution_records.py:135), family-aware `load_existing` (role_execution.py:1104-1144) |
| UI | RunPage shows "in-place correction controls are not yet available" (:240) |
| NA-2 | CONFIRMED: `_cancel_requests` in-memory only (service.py:239, 1655); `_watch_reconciled_run` maps all non-succeeded to `failed` (service.py:432-436); `reconcile` never returns CANCELLED (local_hermes.py:635+) |

### NEW finding (not in the audit): the attempt-aware submission read does not exist

`validate_submission` (submission_validation.py:49) reads ONLY the base
`run_submissions` row via `repository.get_submission`. The design's
re-entry ("insert the `run_submission_attempts` row, letting the normal
pipeline proceed") cannot work for REJECTED runs (which already have a
base submission): the pipeline would re-validate the OLD bytes.
`get_latest_submission_attempt`/`insert_submission_attempt` have zero
callers outside the repository. `SubmissionAssembler.submit_or_reconcile`
also short-circuits on any base submission (submissions.py:54-56).

Resolution (pins D-follow-up, consistent with HV-5 revision A1):
1. `validate_submission` becomes attempt-aware: prefer the latest
   `run_submission_attempts` row (same `payload_json`/`submission_sha256`
   columns), fall back to the base submission.
2. `SubmissionAssembler` gains a correction branch: when
   `context.submission_from_status == "correcting"` and a base submission
   exists, assemble the corrected document from the (family-aware)
   closure chain, insert it as a submission attempt (ordinal =
   count+1), and CAS the run `correcting -> submitted` with a
   `run_submitted` event naming the attempt. When no base submission
   exists (pre-submission FAILED runs), the normal seal path already
   works via `seal_submission(from_status="correcting")`.

## Error code registry pins (verified free)

- CORRECTION_NOT_APPLICABLE: transition, 409, retryable no, MH-73
- CORRECTION_SCOPE_INVALID: schema, 400, retryable yes, MH-74
- CORRECTION_EXHAUSTED: transition, 409, retryable no, MH-75

Each new code requires edits in exactly five places:
`api/errors.py` (Literal + ERROR_RULES),
`architecture/schemas/command-error.schema.json` (code enum + oneOf
policy entry), `architecture/09-control-commands.md` (catalog row),
`architecture/tools/validate_package.py` (`error_policies` table ~:1338),
`architecture/07-contract-traceability.md` (MH-73/74/75 rows).

## Package split (dispatch order, sequential, single writer)

- **P1 (K-1a5 foundation)**: error codes (5 places above), API models
  (`CorrectionRequest`, `CorrectionPreviewRequest`), repository helper
  `list_role_closures_for_run(run_id)` (join
  `role_execution_intents`↔`role_execution_closures`), attempt-aware
  `validate_submission`. Tests for each.
- **P2 (K-1a5 Lane A execution)**: `seal_correction_submission` in
  `correction_execution.py` (stage outcomes from family-aware
  `load_existing`; SubmissionAssembler path), the assembler correction
  branch. Tests: FAILED-run re-entry seals base submission;
  REJECTED-run re-entry inserts attempt and CASes to submitted.
- **P3 (K-1a5 command path)**: `service.request_output_correction`
  (idempotent replay; descriptor head check; FAILED/REJECTED +
  correctable-findings gate; closure lookup; scope gate; schema
  validation; seal command; CAS to CORRECTION_AUTHORIZED; synchronous
  Lane A: CORRECTING transition -> revalidate -> on PASS closure +
  submission + handoff via `run_launcher(run_id)` task; on FAIL stay
  CORRECTION_AUTHORIZED per D1); run-detail correction action
  descriptors in `run_views.py`; router endpoint
  `POST /projects/{project_id}/runs/{run_id}/corrections`.
  Tests: acceptance gates, replay, head-stale, E2E revalidate-pass to
  SUBMITTED, fail-stays-authorized.
- **P4 (K-1b normalize + preview)**: shared transformation application
  (reuse role_execution repair primitives; NO behavior change to the
  role lane), normalize execution writing transformed copies to the
  artifact store + OutputTransformationRecord on the attempt, and the
  read-only preview endpoint
  `POST /projects/{id}/runs/{run_id}/corrections/preview` (zero state
  writes; per-finding fixability + transformation diff + remaining
  findings). Non-coverable normalize refused at command time (D3).
- **P5 (K-1c Lane B)**: packaging/scientific targeted correction:
  bounds via `check_correction_bounds` (counts from
  `run_validation_attempts`), CORRECTION_EXHAUSTED when spent, role
  re-invocation through `RoleLifecycleService` with
  `identity_suffix=f"correction.{command_id}"`, pinned basis, the
  correction instruction (packaging gains the derived pointer list per
  design 4a), post-correction blast-radius verification (packaging:
  changes only at permitted pointers; scientific: no out-of-scope
  output changes; violation = spent attempt recorded as finding),
  submission re-entry, restart non-relaunch surfacing.
- **P6 (K-1d UI)**: RunPage correction controls driven by the run
  detail's action descriptors (preview panel, revalidate, normalize
  enabled when preview covers all findings, packaging/scientific
  request with instruction field), correction-state displays; web
  types; vitest.
- **P7 (NA-2)**: persisted cancel intent. Migration 13:
  `ALTER TABLE run_launch_records ADD COLUMN cancel_requested_at TEXT`.
  `RunSealStore.mark_launch_cancel_requested(launch_id, at)`;
  `cancel_supervised_run` writes it BEFORE signalling (clear-on-failure
  = delete not possible on immutable-ish record; instead the column is
  only consulted at close time when the outcome was a signal death ,
  see below); `_watch_reconciled_run` closes as `cancelled` when the
  launch record carries `cancel_requested_at` and reconcile reports the
  process gone; the launcher's in-memory `cancel_requested` path stays
  as the same-session fast path. Regression test: cancel event
  persisted, restart simulated (no in-memory event), watcher closes
  `cancelled`, not `failed`.
- **K-4: CLOSED as already-fixed (live probe 2026-08-17).** With
  `executor_kind="disabled"`, the phase view emits the
  `executor.unavailable` eligibility finding, `build_phase_configuration`
  disables the start_run action (`enabled = not findings`), and the
  service's `action.enabled` gate rejects the command with a clear
  researcher message. Verified by live probe: `start_run` raises
  CommandRejected ("No role executor is configured for this server...")
  and no run row is created. The audit's zombie-run claim was stale.
  Note: tests that simulate pre-launch crashes set
  `service.run_launcher = None` AFTER construction; that hook bypasses
  the command path and stays valid for recovery testing.

## Deferred
- **K-2: CLOSED 2026-08-19 (Tez sign-off, doc-only).** The two-lane output
  policy divergence is deliberate and now documented in
  `architecture/05-validation-strategy.md`: the formal lane repairs with
  disclosure (production path); the supervised WP-E1 lane validates raw
  bytes (trust-verification lane - repairing there would hide agent
  non-conformance from the verdict). No code change, no rerun.
- **K-5** (production re-exercise): run a controlled P2 full-catalog
  run after P1-P6 land, exercising the correction lane end to end.
- **K-7**: open by design (reviewer-memory boundary).

## Already fixed this round (coder-direct, 2026-08-17)

- **K-3** (`c79b02d`): kanban executor `sk-` redaction regex aligned
  with local_hermes (`[a-zA-Z0-9_-]`); regression test added.
- **K-6** (`57529d4`): `_classify_transformations` now takes the exact
  rename map from `_deep_sanitize_ids`; schema-derived sanitizations
  and reference rewrites label as `id_sanitization` (no case
  heuristic); regression tests added.

## P3 design pins (added 2026-08-17, verified against code)

Service-side facts (all probed in the tree):
- `MethodHubService` gains an additive kwarg `run_coordinator` (wired in
  bootstrap.py:104-117). When None (executor disabled), correction
  commands refuse with CORRECTION_NOT_APPLICABLE (Lane A needs the
  coordinator's harness construction; Lane B needs its executor).
- `RunCoordinator` gains a public method
  `correction_services(run_id, *, correction_command_id, correction_type)`
  that reuses `_execution_components` and returns a new
  `HarnessExecutionServices` built on
  `dataclasses.replace(context, submission_from_status="correcting",
  correction_command_id=..., correction_type=...)`.
- Command family: add `"request_output_correction"` to the CommandFamily
  Literal (api/ports.py:40).
- Router: `POST /projects/{project_id}/runs/{run_id}/corrections`,
  response_model=RunDetail, `_capture_and_parse(..., CorrectionRequest,
  command_family="request_output_correction", project_id=...)`,
  openapi_extra `_body_contract(CorrectionRequest)` (cancel_run pattern).
- run_views: emit a `revalidate_run` ActionDescriptor when
  (state in failed/rejected AND projection.recovery_summary ==
  "needs_output_correction") OR state == "correction_authorized";
  descriptor_id = `_action_id(run_id, "correction:revalidate",
  str(head_sequence))`; also populate `available_recovery_controls`
  with ["revalidate"] in that case (currently hardcoded []).
  normalize/packaging/scientific descriptors land with P4/P5.

`request_output_correction` flow (P3 implements revalidate only;
other types refuse CORRECTION_NOT_APPLICABLE "not yet available"):
1. get_run detail; attach raw request; idempotent replay via
   get_command_by_idempotency (payload run_id mismatch ->
   IDEMPOTENCY_KEY_REUSED; replay returns the current detail).
2. Descriptor head check against detail.actions (CONTROL_HEAD_STALE).
3. State gate: status in failed/rejected/correction_authorized, else
   CORRECTION_NOT_APPLICABLE. Correctable gate: the run payload's
   closure_findings must include at least one correctable finding,
   else CORRECTION_NOT_APPLICABLE.
4. Failed closure: latest row from `list_role_closures_for_run` whose
   payload status is "failed"; none -> CORRECTION_NOT_APPLICABLE.
5. Scope gate: command.permitted_output_scope must be a subset of the
   closure's declared output ids, else CORRECTION_SCOPE_INVALID.
6. Build the command document per output-correction-command.schema.json
   (command_id = correction._derive_command_id(run_id, type,
   str(head_sequence)); validation_attempt_id = latest attempt id or
   f"attempt.{run_id}.0"; expected_lifecycle_head = str(head_sequence));
   validate via specification.schemas.require_valid; seal via
   repository.seal_command (cancel-run pattern).
7. If status is failed/rejected: CAS to correction_authorized with a
   run.correction_authorized event. (Already-authorized runs skip this.)
8. Lane A (synchronous): `revalidate_closure_outputs(...)`.
   - PASS: `record_revalidation_closure(..., invocation_sha256=<sealed
     command digest>)`; CAS correction_authorized -> correcting with a
     run.correcting event; `seal_correction_submission(services=
     coordinator.correction_services(...), ...)`; hand off with
     `asyncio.create_task(self.run_launcher(run_id))` (the coordinator
     loop picks up submitted -> validating -> promoting -> published).
   - FAIL: stay in correction_authorized (D1; the state table has no
     correcting -> authorized edge, so the transition to correcting
     happens only after a known pass). The recorded attempt row is the
     failure evidence.
9. Return the updated RunDetail.

Test pin: a revalidate-PASS fixture is a FAILED run whose sealed output
bytes actually CONFORM (stale/transient failure); revalidate re-runs
validation on the sealed bytes ("would this output pass today", D2) and
passes regardless of the old closure status. See
tests/test_correction_execution.py:263 for the passing-revalidate
pattern.

## P5 design pins (added 2026-08-19, verified against code)

Package split: P5a = Lane B execution core; P5b = service command path
(bounds, packaging/scientific branches, exhaustion, descriptors).

Verified constraints that shape the pins:
- State table (domain/runs.py:84-96): CORRECTION_AUTHORIZED ->
  {CORRECTING, CORRECTION_EXHAUSTED}; CORRECTING -> {SUBMITTED,
  CORRECTION_EXHAUSTED}. There is NO correcting -> correction_authorized
  edge, so a failed Lane B attempt with bounds remaining CANNOT return
  to authorized. D6 (coder interpretation, flag for Tez): the run STAYS
  in correcting; the retry path is a new correction command ACCEPTED
  from the correcting state (all four types), whose pass CASes
  correcting -> submitted (legal) and whose fail needs no transition.
  This also covers the HV-5.8 restart case (a run left in correcting by
  a crash mid-correction gets a retry action, never an auto-relaunch;
  run_coordinator.py:142-143 already never auto-advances correction
  states).
- Lane B runs SYNCHRONOUSLY in the service call, deviating from the
  design doc's "background, mirrors launch": Lane A set the synchronous
  precedent (P3 pins), the DeterministicFakeExecutor keeps tests
  deterministic, and the async handoff after submission already goes
  through run_launcher. A production model call blocks the HTTP request
  for its duration; accepted for Version 1, flagged here.
- Workspace collision: a correction re-invocation through the base
  execution path would _immutable_write over the base run's task.md /
  role dirs. execute_correction therefore uses correction-suffixed
  workspace dirs: roles/{seq}-{role}.correction.{command_id}/ and
  tasks/{seq}-{role}.correction.{command_id}/task.md. Base workspace is
  never touched.
- Identity: replace(context, identity_suffix=f"correction.{command_id}")
  at derivation time (load_existing pattern, role_execution.py:1243).
- Brief: render_task_brief with researcher_instruction REPLACED by the
  correction instruction (phase/mode/stage-role layers unchanged).
- Previous outputs: the source closure's sealed candidate bytes are
  materialized digest-verified INTO the correction run root's output
  paths before invocation, so the agent edits in place.
- Blast-radius verification runs BETWEEN output validation and closure
  sealing (NOT after): a violation seals the correction closure as
  FAILED with the violation finding (the attempt is spent), so a
  violated correction NEVER enters the family-aware load_existing walk
  (which only returns SUCCEEDED correction closures). Verification
  rules (design 4a): PACKAGING - recursive JSON diff of source vs new
  candidate per in-scope output; any changed path not at or under a
  permitted pointer is a violation; permitted pointers = the finding
  json_pointers from the failed validation attempt's report.
  SCIENTIFIC - any change to an OUT-OF-SCOPE output is a violation;
  in-scope outputs may change freely. The verification report rides on
  the validation attempt row.
- Instruction: build_correction_instruction gains an optional
  permitted_pointers parameter; for packaging the instruction appends
  "change ONLY these locations; every other byte of the document must
  remain identical" with the derived pointer list. Scientific keeps
  output-level scope.
- Bounds (P5b): prior packaging/scientific attempts counted from
  run_validation_attempts.correction_type; over bound ->
  CORRECTION_EXHAUSTED before sealing the command. On a FAILED Lane B
  attempt: if is_correction_exhausted (both spent) CAS correcting ->
  correction_exhausted with an event; else stay correcting (D6).
- Acceptance flow: failed/rejected -> correction_authorized (as today)
  -> correcting BEFORE the invocation; already-correcting retries skip
  both CASes.

## D4 (resolved 2026-08-17, coder): correction family supersedes a SUCCEEDED base closure

Found by the P2 scenario-B test: K-1a2's `load_existing` was base-first
("walk the correction family only when the base is missing or failed").
For REJECTED runs every base closure succeeded, so a Lane B correction
closure would never enter the re-assembled submission; the correction
would validate the pre-correction bytes and silently do nothing.
Resolution: `load_existing` now walks the correction family FIRST
(newest command first; first succeeded correction closure wins) and
falls back to the base closure. The failed-base case (K-1a2's design
target) is subsumed. Rationale: a succeeded correction closure is the
latest user-authorized output for the role; older/base output is
superseded by definition. All K-1a2/K-1a4 identity tests stay green.

## D5 (RESOLVED 2026-08-19, Tez: recover, not rerun): revalidate for REJECTED runs

> Decision (Tez sign-off 2026-08-19): add the rejected-run branch. A
> REJECTED run's sealed outputs are intact - the failure was at submission
> validation - so recovery is cheap and faithful, and a rerun would
> discard valid role work for no accuracy gain. Lands together with P4.
> Original analysis kept below.
>
> IMPLEMENTED 2026-08-19 (mechanism amended from the first sketch): the
> service now targets the newest SUCCEEDED closure when no failed closure
> exists, preferring one whose declared outputs cover the requested scope;
> the normal Lane A flow then revalidates that closure (expected pass for
> a stale-schema rejection), writes the correction-family closure, and
> re-enters submission, where the attempt-aware `validate_submission`
> re-checks the assembled document against the CURRENT catalog. The first
> sketch ("probe every succeeded closure, target the first nonconforming,
> refuse when all conform") was dropped for two reasons: probing via
> `revalidate_closure_outputs` records one attempt row PER PROBE before
> the command is even sealed (side-effectful search), and the
> refuse-when-all-conform branch is exactly the common REJECTED case -
> it would have made revalidate useless precisely where recovery is
> cheapest. If the submission still violates the current schema it is
> rejected again with the attempt row as evidence, and normalize (P4) or
> Lane B (P5) is the next recovery step. Tests:
> `test_rejected_run_revalidate_recovers_to_submission`,
> `test_rejected_run_without_closures_is_not_applicable`.

The P3 pins' step 5 targets "the newest FAILED role closure".  On a
REJECTED run every base closure SUCCEEDED (the rejection happened at
submission validation, not role validation), so the failed-closure gate
finds nothing and the service answers CORRECTION_NOT_APPLICABLE --
revalidate corrections are only reachable for FAILED runs whose role
closure failed after sealing outputs.  The Lane A machinery itself
supports revalidating a SUCCEEDED closure (P2 scenario B does exactly
that, targeting a succeeded base closure).  If corrections for rejected
runs are intended, the target-closure rule needs a rejected-run branch:
e.g. revalidate every succeeded closure in scope and target the first
whose outputs no longer conform, or take the target closure id
explicitly in the command.  P3a implements the pins as written; flagged
for the method owner to decide.


## P6 design pins (added 2026-08-20, coder; Tez directed coder-built, no subagent)

Backend facts probed in the tree at bbd4274:

- The descriptor block (run_views.py run_summary_view) emits ALL FOUR
  correction descriptors together (revalidate_run, normalize_run_outputs,
  package_run_outputs, revise_scientific_content) whenever the surface
  condition holds: (failed/rejected AND recovery_summary ==
  needs_output_correction) OR state in (correction_authorized,
  correcting). All four are enabled=True; applicability is enforced at
  command time (bounds, D3 coverability, scope).
- CorrectionRequest requires permitted_output_scope min 1;
  user_instruction is scientific-only; transformation_codes
  normalize-only (model_validator). The normalize command rejects EMPTY
  codes with CORRECTION_SCOPE_INVALID; the PREVIEW accepts empty codes
  (= full ALLOWED_NORMALIZE_CODES).
- ALLOWED_NORMALIZE_CODES = timestamp_injection, id_sanitization,
  hash_recomputation, additional_properties_strip,
  schema_version_injection, null_strip, empty_string_strip.
- Preview response (bbd4274): current_findings / remaining_findings /
  fixed_findings (ValidationFinding dicts: code, message, severity,
  object_id, json_pointer, finding_class, blocks_publication,
  correction_class), transformations (OutputTransformationRecord dicts:
  contract_output_id, source_sha256, result_sha256, entries[]
  {code, json_pointer, detail}, primary_artifact_unchanged), passing,
  output_scope (the target closure's declared contract_output_ids).
  response_model_exclude_none=True, so object_id may be absent.
- Preview transport: _capture_and_parse tolerates a missing
  Idempotency-Key (request.headers.get). Preview is read-only; the
  client uses a plain POST, not commandRequest.
- The normalize APPLY codes are derived from the preview itself: the
  distinct entry codes across preview.transformations[].entries. This
  is exactly the set that acted in the dry run, it is non-empty
  whenever passing (passing requires the blocking findings fixed, which
  requires transformations), and it is allowlist-safe by construction.
- Status.tsx already labels/tones correction_authorized, correcting,
  correction_exhausted; isRunActive polls through
  correction_authorized/correcting.

Web implementation pins:

- types.ts: ActionType gains "package_run_outputs" and
  "revise_scientific_content" (backend P5b added them; the web literal
  is behind). New exports: CorrectionType, CorrectionFinding,
  CorrectionTransformationEntry, OutputTransformationRecordView,
  CorrectionPreview.
- client.ts: previewRunCorrection(projectId, runId, codes) as a plain
  POST (read-only, no Idempotency-Key); requestRunCorrection(projectId,
  runId, action, input) via commandRequest<RunDetail> mirroring
  cancelRun.
- RunPage: a "Correct outputs" Panel renders when ANY correction
  descriptor is present (same surface condition as the backend). One
  preview query (plain useQuery, key ["correction-preview", projectId,
  runId]) fetches previewRunCorrection with EMPTY codes on panel mount;
  its output_scope scopes ALL four command buttons. Command buttons
  stay disabled until the preview resolves (scope source) and show the
  preview error on failure.
- Each correction command reuses ConfirmActionDialog (descriptors do
  not set requires_reason, so no reason field). Scientific adds a
  required instruction textarea inside the dialog (user_instruction).
  Mutation onSuccess mirrors cancel: setQueryData(["run", ...]) +
  invalidateCancellationRequestDependents (rename-neutral alias kept
  for the existing test).
- Normalize apply is enabled IFF preview.passing (D3 coverability is
  also the server gate; CORRECTION_NOT_APPLICABLE otherwise).
- Guidance text update: recoveryGuidance for needs_output_correction
  now points at the on-page correction controls instead of "return to
  the phase". The stale placeholder at RunPage "in-place correction
  controls are not yet available" is removed.
- Correction-state messages: correction_authorized -> neutral status
  message naming the authorized correction; correcting -> neutral
  status (an attempt is in flight or a bounded attempt failed; the
  descriptors remain for retry per D6); correction_exhausted ->
  warning message: both bounded attempts spent, start a full phase
  rerun (links to the phase configure anchor like the existing
  guidance panel).
- Tests: new RunPage.correction.test.tsx (jsdom + RTL, the
  provision-test pattern: vi.mock the api seam, QueryClient retry
  false, MemoryRouter). Cases: panel renders from descriptors; revalidate
  posts the exact payload; scientific requires the instruction;
  normalize apply disabled until passing preview and sends the derived
  codes; correction_exhausted message renders; preview error disables
  the commands. Pure helpers (codes derivation, state presentation)
  extend RunPage.test.ts.
