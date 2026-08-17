# K-1 Remaining Implementation Plan + NA-2 (2026-08-17)

Status: Approved for dispatch (Tez directive: audit carefully, fix all)
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

## Deferred (needs Tez, not code)

- **K-2** (two-lane output policy divergence): coder recommendation ,
  DOCUMENT the deliberate difference: the formal lane repairs with
  disclosure because it is the production path; the supervised WP-E1
  lane validates raw bytes because it is the trust-verification lane
  (repairing there would hide agent non-conformance from the verdict).
  Awaiting Tez sign-off; then a one-paragraph doc addition closes it.
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
