# K-1 Design: Correction Command Path

Status: Draft for review (2026-08-16)
Author: coder profile
Basis: harness audit 2026-08-16 finding K-1; HV-5 plan
([HV-5-bounded-user-controlled-recovery.md](HV-5-bounded-user-controlled-recovery.md))
acceptance criteria; current tree at `0cdbee4`.

## Problem

HV-5 shipped the correction machinery but not the command path. Verified
present: domain states + transitions (domain/runs.py:34-37, 84-92), the
correction module (application/correction.py, pure functions),
`run_submission_attempts` storage (migrations.py:601-617, repository.py
632-712), restart reconciliation honoring correction states
(run_coordinator.py:142-143), lifecycle projection and UI messaging
(run_views.py:216/304/360, RunPage.tsx:194-215), API action type
declarations (api/models.py:40-52), and the command contract
(schemas/output-correction-command.schema.json).

Verified missing: no API endpoint accepts a correction command; no service
method invokes `correction.py` (zero imports of the module outside itself);
no `validation_attempts` persistence in the formal lane; no UI control
triggers an action. A run in `needs_output_correction` is a dead end for
the user.

## Scope decision (Version 1)

Implement all three recovery actions from HV-5, in two lanes of increasing
risk:

- **Lane A (no model call): revalidate + normalize.** Fully deterministic,
  bounded by construction, testable end-to-end without Hermes.
- **Lane B (model call): packaging + scientific targeted correction.**
  Re-invokes one role with a correction instruction on the pinned basis.

Both lanes share the same command acceptance path (Lane A is the smaller
package and de-risks the command plumbing before any model call exists).

## Design

### 1. Command acceptance (shared)

New endpoint:

```
POST /projects/{project_id}/runs/{run_id}/corrections
body: CorrectionRequest (StrictModel):
  correction_type: "revalidate" | "normalize" | "packaging" | "scientific"
  permitted_output_scope: list[str] (minItems 1)
  action_descriptor_id: str        # displayed-action binding, cancel-run pattern
  user_instruction: str | null     # scientific only
  transformation_codes: list[str]  # normalize only, allowlisted
```

Service method `request_output_correction(project_id, run_id, command,
raw_request)` mirroring `cancel_run` (service.py:1818):

1. Action-descriptor head check (displayed action must be current), same as
   cancel_run's CONTROL_HEAD_STALE guard.
2. Run status must be FAILED or REJECTED with at least one finding whose
   policy class is CORRECTABLE_CONTRACT_ERROR (domain/validation.py
   `get_policy`; ISS-6 routes the dominant `schema.*` family there). Runs
   whose findings are all INTEGRITY_BLOCKER are refused with a new error
   code (see errors section).
3. Validate the command document against
   `output-correction-command.schema.json` via the repo SchemaCatalog.
4. Seal the command (`repository.seal_command`, cancel-run pattern) and
   transition FAILED/REJECTED -> CORRECTION_AUTHORIZED through the
   repository's head-checked update, recording a `run.correction_authorized`
   event.

Idempotent replay: `correction_command_id` is deterministic
(correction.py:146-151); replay returns the original sealed command, never
a second attempt (matches the run-command convention).

### 2. ValidationAttempt persistence (new migration)

New table `run_validation_attempts` (immutable triggers, the
run_submission_attempts pattern): attempt_id PK, run_id FK, ordinal,
policy_version, report_json, source_sha256, correction_type (NULL for the
initial validation), prior_attempt_id, correction_command_id,
attempted_at, index on (run_id, ordinal).

The closure's original validation is attempt ordinal 0 (recorded lazily on
first correction entry from the closure payload; no backfill migration of
existing closures - attempt 0 is synthesized from the closure at read
time). This keeps the migration additive and the two `initialize() == N`
test bumps apply (WP-E0..F1c precedent: every new migration breaks exactly
those two assertions).

### 2a. Correction closure identity (verified constraint, added 2026-08-16)

Role identities are deterministic: `execution_records.role_identity`
(execution_records.py:94-108) derives (invocation_id, execution_id,
closure_id) from exactly (run_id, manifest_sha256, stage.sequence,
stage_id, role), and `_load_closure` looks up closures BY that
execution_id (role_execution.py:1639-1654). A correction re-invocation
under the same run would collide with the existing failed closure row -
and closures are immutable.

Design:

- `RunExecutionContext` gains `identity_suffix: str = ""` (additive,
  defaulted - the same pattern as the existing `submission_from_status`
  field, execution_context.py:52-53). `role_identity` appends the suffix
  to the basis when non-empty, so correction attempt N derives a distinct
  deterministic identity family: base + `("correction", correction_command_id)`.
- `RoleLifecycleService.load_existing` becomes family-aware: fetch the base
  identity's closure; if absent or not succeeded, walk the run's correction
  commands (newest first, from `run_validation_attempts` joined to the
  sealed commands whose `role_closure_id` names the base closure), derive
  each correction execution_id, and return the first succeeded closure.
  The submission chain loader (submissions.py:150-157) then works
  unchanged.
- Any SUCCESSFUL correction action (including revalidate with unchanged
  bytes) writes a NEW closure for the stage/role under the correction
  identity, carrying the conforming output digests and status succeeded.
  The failed closure is never mutated (HV-5.1); history shows both. The
  closure DOCUMENT keeps the exact existing schema shape (no new fields);
  the correction linkage lives in `run_validation_attempts` (the
  correction_command_id column), the identity derivation (the command id
  is embedded in the closure identity), and the intent row payload. The
  closure's `invocation_sha256` carries the sealed correction command's
  digest, binding the closure to its authorizing command.
- The correction execution context also sets `submission_from_status =
  "correcting"` so `seal_submission`'s CAS accepts the
  correcting -> submitted edge (submissions.py:70-79).

### 3. Lane A execution (synchronous, in the service call)

- **Revalidate**: load the sealed candidate bytes for the in-scope outputs
  (artifact store, digest-checked against the closure's sealed digests),
  re-run `validate_role_outputs`-equivalent checks against the CURRENT
  schema catalog and policy version. Record the attempt. If the report
  passes: transition CORRECTION_AUTHORIZED -> CORRECTING -> SUBMITTED and
  insert the `run_submission_attempts` row (attempt-aware active
  submission, HV-5 revision A1), letting the normal validation/promotion/
  publication pipeline proceed. If it fails: transition back to
  CORRECTION_AUTHORIZED stays illegal by the state table, so a failed
  revalidate records the attempt and leaves the run FAILED/REJECTED-side
  via `correction_exhausted` ONLY when bounds are exhausted; otherwise the
  run remains in CORRECTION_AUTHORIZED awaiting another action. DECISION
  POINT D1: the state table has no correction_authorized -> failed edge;
  simplest legal flow is to remain in correction_authorized (re-entry from
  there to correcting is legal). Confirm with Tez.
- **Normalize**: same, but first apply the allowlisted transformations
  (reuse the role_execution repair primitives: timestamp injection, id
  sanitization, hash recomputation, additional-properties strip,
  schema_version injection, null/empty-string strip - exactly
  ALLOWED_NORMALIZE_CODES, correction.py:206-214) to a COPY of the raw
  bytes, record the OutputTransformationRecord on the attempt, then
  validate the result.
- **Normalize preview (dry run, read-only)**: a separate endpoint
  `POST /projects/{id}/runs/{run_id}/corrections/preview` that runs the
  same allowlisted transformations on a TEMP COPY of the raw bytes and
  re-validates, WITHOUT writing anything: no events, no attempts, no
  state transitions. The response lists, per finding, whether it would be
  mechanically fixed (code + json_pointer), the transformation diff summary
  (from the OutputTransformationRecord entries), and which findings remain
  - so the user chooses the cheapest sufficient action with the outcome
  known in advance. This directly answers D3: normalize never needs to be
  attempted blind, so refusing non-coverable normalize requests at command
  time is friendly (the user already saw the preview).

### 4. Lane B execution (background, mirrors launch)

- Bounds check first (`check_correction_bounds`): 1 packaging + 1
  scientific attempt, counted from prior attempts (HV-5.6).
- Transition CORRECTION_AUTHORIZED -> CORRECTING, then re-invoke ONLY the
  nonconforming role through the normal RoleLifecycleService with:
  the same frozen inputs and method identity (basis content pinned,
  HV-5 revision A2), the previous raw + candidate outputs, the full
  structured findings, and `build_correction_instruction` text
  (packaging vs scientific wording, correction.py:282-324).
- The new closure is a NEW immutable record linked via
  correction_command_id; the FAILED/REJECTED closure is never mutated
  (HV-5.1 rule).
- On closure success: CORRECTING -> SUBMITTED with a
  `run_submission_attempts` row; the execution context for the correction
  uses `submission_from_status="correcting"` (execution_context.py:56-57)
  so `seal_submission`'s CAS accepts the edge. On failure: CORRECTING ->
  CORRECTION_EXHAUSTED when bounds are spent, else back is illegal - the
  run stays CORRECTING-side per D1's resolution.
- Restart: run_coordinator.py:142-143 already never auto-advances
  correction states; the run detail must surface "authorized but not
  started" / "in progress at restart" with a retry action (HV-5.8). No
  automatic relaunch.

### 4a. Correction as a verifiable patch (pointer-scoped blast radius)

Every validation finding already carries a `json_pointer`
(schema.required at `/statements/3/...`, etc.). Lane B uses them to turn a
correction from a full-document rewrite into a PATCH with a verified blast
radius - this is what keeps a large record easy to fix instead of a huge
messy output.

- **Contract-untouched scoping**: `output-correction-command.schema.json`
  has `additionalProperties: false`, and contract changes require an ADR
  before code (project rule). So the command is NOT extended; the permitted
  pointer set is DERIVED harness-side from the findings being corrected
  (finding json_pointers + harness-owned envelope fields, which the agent
  never writes post-ISS-1). No ADR needed for Version 1; a user-visible
  pointer-override field can be proposed later via the ADR path if wanted.
- **Instruction**: for packaging corrections, `build_correction_instruction`
  gains the pointer list - "change ONLY these locations; every other byte
  of the document must remain identical". Scientific corrections keep
  output-level scope (downgrading a claim may legitimately touch the
  summary, statement, and evidence references together).
- **Post-correction verification (the QC property)**: when the correction
  closure lands, the harness diffs old candidate vs new candidate per
  in-scope output. PACKAGING: any change outside the permitted pointer set
  rejects the correction attempt (recorded as a finding; the attempt is
  spent, matching the bounds rule). SCIENTIFIC: any change to an
  OUT-OF-SCOPE output rejects the attempt. The verification report is
  recorded on the validation attempt, so the published basis shows exactly
  what the correction was allowed to touch and what it actually touched.

### 5. UI (RunPage)

When `recovery == "needs_output_correction"`, render action descriptors
returned by the run detail: Preview fixes (always available; opens the
dry-run result panel with per-finding fixability and the transformation
diff), Revalidate, Normalize (enabled when the preview shows all failing
findings are coverable by allowlisted codes; the descriptor carries the
proposed transformation_codes), Request packaging correction, Request
scientific correction (with the user_instruction text field).
`correction_authorized`/`correcting`: progress display, no new actions.
`correction_exhausted`: the existing "completed, correction still
required" display plus a link to start a full phase rerun.

### Error codes

New codes follow the MH-registry rule (extend validator ranges +
07-contract-traceability.md): CORRECTION_NOT_APPLICABLE (409: not
FAILED/REJECTED, or no correctable findings), CORRECTION_SCOPE_INVALID
(400: outputs outside the run's declared outputs), CORRECTION_EXHAUSTED
(409: bounds spent), CONTROL_HEAD_STALE reused for the descriptor check.

## Package split (dispatch order, single writer)

1. **K-1a**: migration + `run_validation_attempts` store methods + command
   acceptance endpoint/service for Lane A (revalidate only) + the read-only
   preview endpoint, with attempt recording and the legal state flow.
   Tests: command schema validation, head-stale rejection, revalidate-pass
   path reaching SUBMITTED via submission attempt, preview returns
   per-finding fixability with zero state writes, idempotent replay, the
   two `initialize() == N` bumps.
2. **K-1b**: normalize action (allowlist enforcement, transformation
   record on the attempt; preview already proves the outcome).
3. **K-1c**: Lane B targeted correction (bounds, role re-invocation,
   correction instruction with the derived pointer list, post-correction
   blast-radius verification per section 4a, submission re-entry, restart
   non-relaunch surfacing).
4. **K-1d**: RunPage correction controls (preview panel, action
   descriptors, scientific instruction field, correction-state displays).

## Decision points (RESOLVED 2026-08-16, Tez delegated to coder)

- D1: RESOLVED - when a correction attempt fails but bounds remain, the run
  STAYS in `correction_authorized`; no new state-machine edge. The user
  reviews the new findings and chooses the next action or gives up.
- D2: RESOLVED - revalidation re-checks the sealed output bytes with the
  role-output validator against the CURRENT schema catalog and policy
  version ("would this output pass today?"), not the submission-shape
  machinery (a failed run has no submission to re-check).
- D3: RESOLVED BY DESIGN (Tez sign-off): the preview endpoint means
  normalize is never attempted blind, so non-coverable normalize requests
  are refused at command time with the preview as the explanation.

## Acceptance (from HV-5, unchanged)

Every attempt uniquely and immutably identified; restart never relaunches;
packaging cannot change primary artifact digests; scientific cannot expand
scope or change the method; exhaustion displays as "completed, correction
still required"; both FAILED and REJECTED runs can enter; all existing
tests pass; plus the HV-5 acceptance matrix items 1-7 as end-to-end tests
across K-1a..K-1c. New for the 1+2 additions: the preview writes no state;
a packaging correction that touches bytes outside the permitted pointer set
is rejected and the attempt spent.
