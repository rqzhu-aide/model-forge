# K-1 Remaining Implementation Plan + NA-2 (2026-08-17)

Status: In progress (updated 2026-08-18 audit). P1, P2, P3a, and P3b are
landed and verified: `ad3e2a6` (P1 foundation), `c1cf087` (P2 Lane A
re-entry + D4 fix), `b91fe9e` (P3a command path), `74b243f` (P3b router
endpoint). Suite 1122 green, vitest 120/120, validator exit 0 at `74b243f`.
Remaining: P4 (normalize + preview), P5 (Lane B), P6 (UI), P7 (NA-2), and
the deferred K-5 item below. K-2 and D5 were decided 2026-08-19 (Tez):
K-2 doc-only, D5 recover-not-rerun.
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
> discard valid role work for no accuracy gain. Implementation: extend the
> target-closure rule so that, when no failed closure exists (the
> REJECTED case), the service revalidates each succeeded closure in the
> permitted scope and targets the first whose outputs no longer conform
> under the current schema catalog and policy version. If every in-scope
> closure still conforms, refuse CORRECTION_NOT_APPLICABLE (the stale
> findings no longer reproduce; the user reruns validation through the
> normal lane). Lands together with P4. Original analysis kept below.

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
