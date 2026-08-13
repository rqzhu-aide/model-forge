# HV-5: Bounded, User-Controlled Recovery

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Correct the smallest affected output without repeating completed scientific
work. Three distinct recovery actions, each with clear authority boundaries.

## What the audit found

### Both FAILED and REJECTED are terminal -- no correction path

The audit confirmed that both terminal states have no outgoing edges in the
transition table (`domain/runs.py:46-84`):

- **FAILED** (`runs.py:81`): reachable when role validation fails
  (`failure_code = "output.structural_validation_failed"`). The coordinator
  hard-stops: "A declared role group failed. No scientific role was retried."
  (`run_coordinator.py:292-302`).

- **REJECTED** (`runs.py:83`): reachable when submission validation fails
  (`failure_code = "submission.validation_failed"`). The smallest correction
  is currently "launch a new run" (`run_coordinator.py:864`).

Both are enforced by `require_transition` (`runs.py:99`) and DB CAS.

### Role closure recovery is already idempotent

`_load_closure` (`role_execution.py:1133-1188`) is idempotent -- re-running a
role is mechanically feasible. The blocker is the
`NO_SCIENTIFIC_ROLE_RETRY` policy frozen in `OrchestrationBinding`
(`protocol.py:24,136-140`).

### The submission gate is a single CAS

`seal_submission` (`submissions.py:70-115`) atomically transitions
`running → submitted` and inserts the submission in one transaction
(`repository.py:559-619`). The status pair is hardcoded in
`execution_context.py:56-57`.

### Correction must cover both FAILED and REJECTED

The parent plan focuses on FAILED → `needs_output_correction`, but REJECTED
faces the same recovery cost. A run rejected for
`submission.required_output_missing` (a correctable contract error per HV-2)
should not require a full rerun.

## Design: three recovery actions

### Action 1: Revalidate unchanged output

**When:** validator code, schema policy, or transient dependency changed.
No model call. Records a new `ValidationAttempt` against unchanged bytes.

**Authority:** explicit user click. No new scientific authority needed.

**Mechanism:** re-run validation against the sealed raw (or last candidate)
output with the current policy version. Produce a new `ValidationAttempt`
linked to the prior attempt.

### Action 2: Apply deterministic normalization

**When:** allowlisted representation changes only. Show the exact diff.

**Authority:** covered by the original launch authority (mechanical, not
scientific). Must be fully disclosed and cannot alter scientific meaning.

**Allowlisted transformations:**
- Timestamp injection (schema-path-aware, from HV-1)
- ID sanitization
- Hash recomputation
- Additional-properties stripping (with recorded finding)

**Mechanism:** apply the allowlisted transformation codes to the raw output,
produce a new candidate, validate, record an `OutputTransformationRecord`.

### Action 3: Request targeted correction

**When:** the user explicitly authorizes the affected role to correct specified
output.

**Authority:** explicit user click + optional instruction. The correction
attempt receives:
- The same frozen inputs and method identity
- The previous raw and candidate outputs
- The complete structured validation report
- A scope limited to the named outputs
- An instruction distinguishing packaging correction from scientific correction

**Mechanism:** a new role invocation that corrects the specified output. The
attempt records which previous output it is correcting.

**Basis pinning (decided, Revision 2):** the correction seals against the
ORIGINAL run's frozen basis content (input generations and digests, method
identity, role profile versions). The reviewed-basis drift check compares that
pinned content, not the current authority head, so a correction is not
rejected merely because unrelated work published in between. If the pinned
inputs themselves have drifted (a referenced input generation was superseded),
the correction is refused and the researcher chooses a rerun instead.
Publication of the corrected output goes through the existing atomic head
check and may yield `conflicted`, exactly as an ordinary run. This keeps WP0
sealing intact: no drift check is bypassed; the correction simply reuses an
older, still-identified basis.

## Work items

### HV-5.1: Add non-terminal correction states

**Target:** `src/method_hub/domain/runs.py`

Add new states to the transition table:

```
failed → correction_authorized → correcting → (submitted | correction_exhausted)
rejected → correction_authorized → correcting → (submitted | correction_exhausted)
```

`correction_authorized`: user has authorized a correction; the system is about
to execute it.

`correcting`: the correction role is running.

`correction_exhausted`: correction attempts exhausted without conformance.
Terminal. Displays as "completed, correction still required."

**Important:** FAILED and REJECTED closures are not mutated. The correction
creates a new attempt record linked to the original closure (parent plan §4:
"Do not rewrite old immutable closures").

### Submission re-entry mechanics (the hard part, specified)

The `correcting -> submitted` edge crosses the submission gate, whose current
mechanics constrain the design in three verified ways:

1. `run_submissions.run_id` is UNIQUE and the table has immutable triggers
   (`storage/migrations.py:219-233`): one submission row per run, never
   updated or deleted. A REJECTED run already holds its row, so a correction
   CANNOT insert a second row into `run_submissions`.
2. The gate's status pair is a configurable execution-context field
   (`execution_context.py:56-57`, `submission_from_status` /
   `submission_to_status`, default `running -> submitted`), and
   `seal_submission` refuses entry from any other status
   (`harness/submissions.py:70-79`), with an idempotent prior-outcome path
   that returns the OLD submission if one exists.
3. Validation and promotion read the run's single submission
   (`repository.py:584`).

Design:

- New migration: `run_submission_attempts` (attempt_id PK, run_id FK,
  submission_id, attempt_ordinal, payload_json, submission_sha256,
  submitted_at, link to the OutputCorrectionCommand; immutable triggers like
  the base table). The base `run_submissions` row is never touched.
- The correction execution context sets `submission_from_status="correcting"`,
  so the CAS edge is `correcting -> submitted` and the existing idempotency
  semantics are preserved for the correction path.
- "The run's active submission" becomes: the newest row of
  `run_submission_attempts` if any exist, else the base row. Validation and
  promotion read the active submission; receipts name both the base
  submission and the attempt ordinal.
- Publication still goes through the existing atomic head check; a concurrent
  publication since the original run yields `conflicted` as today.

This is the only new write path HV-5 needs in the storage layer. If the
implementer finds a simpler mechanism that preserves immutability and the CAS
semantics, bring it back for review before building it.

### HV-5.2: OutputCorrectionCommand

**Target:** `src/method_hub/domain/`, `src/method_hub/application/run_coordinator.py`

Define the command (parent plan §6.4):

```python
@dataclass(frozen=True)
class OutputCorrectionCommand:
    run_id: str
    role_closure_id: str
    validation_attempt_id: str
    expected_lifecycle_head: str  # for optimistic concurrency
    correction_type: Literal["revalidate", "normalize", "packaging", "scientific"]
    permitted_output_scope: tuple[str, ...]  # output IDs
    user_instruction: str | None  # only for scientific correction
```

The command must not authorize a different method, phase scope, or context
basis. A change to those items remains a new phase run or rerun.

### HV-5.3: Implement revalidation

**Target:** `src/method_hub/application/run_coordinator.py`

The simplest recovery action. Re-run validation against the sealed output with
the current policy version.

```
revalidate(run_id, role_closure_id, expected_head) → ValidationAttempt
```

No model call. No transformation. Just re-checks bytes with new policy.

### HV-5.4: Implement deterministic normalization

**Target:** `src/method_hub/application/run_coordinator.py`,
`src/method_hub/harness/role_execution.py`

Apply allowlisted transformation codes to the raw output:

```
normalize(run_id, role_closure_id, transformation_codes, expected_head)
  → (CandidateOutput, OutputTransformationRecord)
```

The normalization runs as part of the original launch authority. It must never
alter a primary research artifact or semantic claim.

### HV-5.5: Implement targeted correction

**Target:** `src/method_hub/application/run_coordinator.py`,
`src/method_hub/harness/role_execution.py`

The most complex action. The correction attempt:

1. Receives the same frozen inputs and method identity.
2. Receives the previous raw and candidate outputs.
3. Receives the complete structured validation report (all findings).
4. Has scope limited to the named outputs.
5. Runs a new Hermes invocation with a correction-specific instruction.

The instruction distinguishes:
- **Packaging correction:** fix envelope structure, missing fields, format
  issues. No intended scientific change. Default to at most 1 attempt.
- **Scientific correction:** fix a scientific claim, add missing evidence,
  downgrade an unsupported claim. Within frozen scope. Default to at most 1
  attempt.

**Never repeat completed upstream roles automatically.** For a parallel role
group, preserve the common frozen basis and rerun only the nonconforming role
after user authorization. Start the downstream lead stage only after every
required parallel closure conforms.

### HV-5.6: Correction attempt bounds

Default bounds:
- At most 1 packaging correction attempt
- At most 1 user-authorized scientific correction attempt

Exhaustion results in `correction_exhausted`, which displays as "completed,
correction still required" -- not a false execution failure.

Bounds are configurable later only with a separate decision (not in Version 1).

### HV-5.7: Expose correction actions in the API and UI

**Target:** `src/method_hub/api/models.py`,
`src/method_hub/application/run_views.py`,
`web/src/pages/RunPage.tsx`

Add correction controls to the run detail view when applicable:

| Condition | Available actions |
| --- | --- |
| `needs_output_correction` + correctable findings | Revalidate, Normalize (if allowlisted), Request correction |
| `correction_authorized` / `correcting` | No new actions (wait for completion) |
| `correction_exhausted` | Start full phase rerun |

### HV-5.8: Restart reconciliation

**Target:** `src/method_hub/application/run_coordinator.py`

If the server restarts during a correction, the correction state must be
reconciled:

- `correction_authorized`: the correction was authorized but not started.
  Offer to start it or cancel.
- `correcting`: the correction was in progress. Do not automatically relaunch.
  Offer to retry or cancel.

**Restart never relaunches a correction automatically.**

## Acceptance criteria

- [ ] Every correction attempt has a unique immutable identity
- [ ] Restart reconciliation never relaunches a correction automatically
- [ ] Packaging correction cannot change primary scientific artifact digests
- [ ] Scientific correction cannot expand phase scope or change the selected
      method
- [ ] Exhaustion results in `completed, correction still required`, not a
      false execution failure
- [ ] Both FAILED and REJECTED runs with correctable findings can enter the
      correction flow
- [ ] All existing tests pass

## Acceptance matrix (from parent plan §9)

End-to-end tests must cover at minimum:

1. Revalidation after a validator-policy change, with unchanged output digest.
2. User-authorized targeted correction, with all attempts retained.
3. Restart during correction, with no automatic relaunch.
4. Packaging correction that fixes an envelope issue without scientific change.
5. Scientific correction that downgrades an unsupported claim.
6. Correction exhaustion → "completed, correction still required".
7. Correction for a REJECTED run (not just FAILED).

## Files touched

| File | Change |
| --- | --- |
| `src/method_hub/domain/runs.py` | New states, new transition edges |
| `src/method_hub/domain/validation.py` | `OutputCorrectionCommand`, `ValidationAttempt` |
| `src/method_hub/application/run_coordinator.py` | Correction loop, revalidation, normalization |
| `src/method_hub/harness/role_execution.py` | Correction role invocation |
| `src/method_hub/storage/migrations.py` | New migration: `run_submission_attempts` (+ the two hard-coded `initialize() == N` test bumps this always triggers) |
| `src/method_hub/storage/repository.py` | Active-submission reads (attempt-aware) |
| `src/method_hub/harness/submissions.py` | Correction-context submission entry |
| `src/method_hub/api/models.py` | Correction action descriptors |
| `src/method_hub/application/run_views.py` | Expose correction controls |
| `web/src/pages/RunPage.tsx` | Correction UI |
| `tests/` | E2E correction tests |

## Dependencies

- HV-0 (ADR for correction authority)
- HV-1 (raw preservation -- correction needs the raw output)
- HV-2 (finding classification -- correction needs to know which findings are
  correctable)
- HV-3 (lifecycle projection -- UI needs to show `needs_output_correction`)
- HV-4 (envelope construction -- packaging correction uses the envelope builder)

This is the most complex package. It depends on all prior packages.

## Risks

- **Domain model complexity**: new states increase the state machine's surface
  area. Mitigate by keeping Version 1 bounds tight (1 packaging + 1 scientific).
- **Parallel role groups**: restarting a single nonconforming role in a parallel
  group requires careful basis preservation. Test thoroughly.
- **Hermes re-invocation cost**: scientific correction is a model call. Bound
  attempts strictly.

## Revision 2 changelog (2026-08-12, coder review)

- A1 (HV-5.1): added the submission re-entry mechanics subsection. The original
  transition sketch (`correcting -> submitted`) ignored three verified
  constraints: `run_submissions.run_id` is UNIQUE with immutable triggers, the
  gate's status pair is context-configured, and the idempotent prior-outcome
  path returns the OLD submission. The new design adds
  `run_submission_attempts`, a `correcting -> submitted` CAS pair, and
  attempt-aware active-submission reads.
- A2 (Action 3 mechanism): resolved the basis-inheritance conflict with
  reviewed-basis sealing. The correction pins the original run's basis
  content; drift checks compare content, not the authority head; publication
  conflicts surface through the existing atomic check. Previously the plan
  said "inherits the exact frozen run basis" with no reconciliation, which
  would have made corrections impossible after any concurrent publication.
- A3: files-touched updated for the migration and storage/repository changes,
  including the standing note that every new migration requires bumping two
  hard-coded `initialize() == N` test assertions.
