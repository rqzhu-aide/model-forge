# HV-3: Lifecycle Separation and Diagnostics

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Make the user-facing state scientifically and operationally accurate. Separate
execution success from output conformance from publication from scientific
outcome.

## What the audit found

### Current model: single-axis state machine

The current model is a **single scalar `RunStatus`** on `RunRecord`
(`domain/runs.py:254`) with a strict CAS-enforced transition table
(`runs.py:46-84`). A run is exactly one of 13 states:

```
created → preparing → prepared → running → submitted → validating → promoting
                                                              ↓
                                                    published / failed / rejected
                                                    conflicted / cancelled
```

Publication is **fused** to conformance: a validated submission is always
promoted. There is no "conforms but not published" or "published despite
failure" state.

### The exact FAILED path

```
Hermes exit (role_execution.py:660)
  → executor exception → synthetic FAILED result (671-678)
  → on SUCCEEDED: _apply_disclosed_mechanical_repairs (976-982)
  → validate_role_outputs (983-989)
  → if not passed: status=FAILED, failure_code="output.structural_validation_failed" (991-993)
  → _validate_and_close seals closure (959-1098)
  → stage: any role FAILED → StageOutcome(FAILED) (stage_execution.py:164-175)
  → orchestrator: stage FAILED → OrchestrationResult(FAILED) (sequential.py:129-136)
  → coordinator: _fail(run_id, failure_code) (run_coordinator.py:292-302)
  → lifecycle.transition(FAILED) -- terminal, no outgoing edges (runs.py:81)
```

### The exact REJECTED path

```
coordinator._validate (run_coordinator.py:331-344)
  → validate_submission (submission_validation.py:35-200)
  → if not validation.passed: _reject(run_id, "submission.validation_failed") (337-344)
  → lifecycle.transition(REJECTED) -- terminal, no outgoing edges
```

### Key blocking constraints

1. **FAILED has no outgoing edges** (`runs.py:81`). Any correction loop needs a
   new non-terminal state.
2. **REJECTED is also terminal** -- submission-level failures have no correction
   path either. The plan must decide: does `needs_output_correction` cover both?
3. **The transition table is enforced by `require_transition` and DB CAS**
   (`runs.py:99`). New states need new transition edges.
4. **Role closure recovery is already idempotent** (`_load_closure`,
   `role_execution.py:1133-1188`), so a "re-run role N" loop is mechanically
   feasible.
5. **NO_SCIENTIFIC_ROLE_RETRY policy** is frozen in `OrchestrationBinding`
   (`protocol.py:24,136-140`). A correction loop would need to bypass or extend
   this.
6. **The submission gate is a single CAS**: `seal_submission` atomically
   transitions `running → submitted` and inserts the submission
   (`submissions.py:70-115`, `repository.py:559-619`).

### What the API and UI currently expose

- API: `RunLifecycleState` Literal of all 13 statuses (`api/models.py:19-33`)
- `RunSummary.state` (`models.py:385-389`)
- `RunDetail` adds `terminal_reason`, `validation_report`, `publication_receipt`,
  per-stage `status: StageState` (`models.py:467-478`)
- UI: `RunPage.tsx` branches on `run.state === "failed" | "rejected" |
  "conflicted"` (`RunPage.tsx:17-44, 146-156`)

## Design decision: projection vs. new states

### Option A: Add new terminal/non-terminal states (deep refactor)

Add `needs_output_correction` as a new `RunStatus` value with appropriate
transition edges. This is the parent plan's implied approach.

**Pros:** explicit in the state machine, queryable, clear semantics.
**Cons:** touches every consumer of `RunStatus` (domain, coordinator, API,
UI, tests). Large blast radius.

### Option B: Derive axes as projections over existing status (shallow)

Keep the existing 13-state `RunStatus` but add derived projection fields:

```python
@dataclass
class RunLifecycleProjection:
    execution_state: Literal["not_started", "running", "completed", "failed", "cancelled"]
    conformance_state: Literal["not_checked", "passed", "correction_required", "integrity_rejected"]
    publication_state: Literal["not_attempted", "published", "withheld", "conflicted"]
    scientific_outcome: str  # phase-specific
    recovery_summary: Literal["ok", "needs_output_correction", "failed", "rejected", "conflicted", "cancelled", "in_progress"]
```

The projection is computed from the run's status + closure findings +
validation report + publication state.

**Pros:** no state-machine changes, smaller blast radius, can be done
incrementally.
**Cons:** `needs_output_correction` is a derived label, not a real state. The
coordinator still hard-fails to FAILED; recovery requires the correction loop
from HV-5.

### Recommendation: Option B first, Option A deferred to HV-5

Start with projections (Option B) in HV-3 so the UI can immediately show
accurate status. Defer the real non-terminal state (Option A) to HV-5 when the
correction loop is implemented and we know exactly what transitions are needed.

This gets the UI fix (stop showing "Execution failed" for correctable issues)
without the deep domain refactor in the same package.

## Work items

### HV-3.1: Add lifecycle projection to run detail

**Target:** `src/model_forge/api/models.py`, `src/model_forge/application/run_views.py`

Add `RunLifecycleProjection` to `RunDetail` and `RunSummary`:

```python
class RunLifecycleProjection(BaseModel):
    execution_state: Literal["not_started", "running", "completed", "failed", "cancelled"]
    conformance_state: Literal["not_checked", "passed", "correction_required", "integrity_rejected"]
    publication_state: Literal["not_attempted", "published", "withheld", "conflicted"]
    recovery_summary: Literal[
        "ok", "needs_output_correction", "failed", "rejected",
        "conflicted", "cancelled", "in_progress",
    ]
    blocking_finding_count: int
    correctable_finding_count: int
    scientific_outcome: str | None  # phase-specific
```

`recovery_summary` must have a value for every one of the 13 `RunStatus`
states; the original draft's four-value Literal could not represent
`conflicted`, `cancelled`, or any in-progress state.

Compute the projection in `run_views.py` from:
- `status` (existing)
- closure findings (blocked vs correctable, from HV-2 policy)
- validation report (existing)
- publication receipt presence

### HV-3.2: Compute needs_output_correction

The `recovery_summary` projection:

| Condition | recovery_summary |
| --- | --- |
| status=published | `ok` |
| status=failed, failure_code=executor.* | `failed` |
| status=failed, failure_code=output.structural_validation_failed, findings all correctable | `needs_output_correction` |
| status=rejected, findings all correctable | `needs_output_correction` |
| status=rejected, any integrity blocker | `rejected` |
| status=conflicted | `conflicted` |
| status=cancelled | `cancelled` |
| any non-terminal status | `in_progress` |

This requires HV-2's `blocks_publication` and `correction_class` fields on
findings.

**Interim bridge, marked as such:** keying on the `failure_code` string
(`output.structural_validation_failed`) reintroduces inferring policy from
message text, the pattern the parent plan Section 5 bans. It is acceptable
only until closure findings carry HV-2 classes; the durable computation reads
finding classes and never the failure-code string. State this in the code
with a comment linking this plan.

### HV-3.3: Expose complete diagnostics through the run detail API

**Target:** `src/model_forge/api/models.py`, `src/model_forge/application/run_views.py`

Add to `RunDetail`:
- Complete validation attempts (from HV-0.6/parent plan §6.1)
- Role closures with bounded diagnostics
- Output inventories (raw + candidate)
- Available recovery controls (which actions are available for this run)

**Control gating (important):** HV-3 ships before HV-5. A run in
`needs_output_correction` is still terminally FAILED or REJECTED in the state
machine, so no correction action can work yet. The detail view must expose
`available_recovery_controls` as an empty list (or omit it) until HV-5 lands,
and the UI must not render dead buttons. The projection tells the truth about
state; it must not promise actions that do not exist.

Replace the current sparse `terminal_reason` with a structured finding view
grouped by class.

### HV-3.4: Update the UI

**Target:** `web/src/pages/RunPage.tsx`

Stop converting a successful Hermes exit into an "Execution failed" display when
validation fails. The run page should show:

> Hermes completed the assigned work. Formal publication was withheld because
> 3 output checks require correction. Your current project record was not
> changed.

When `recovery_summary == needs_output_correction`:
- Show blocking findings grouped by class
- Show preserved artifacts
- Show available recovery controls ONLY if HV-5 has landed; otherwise show a
  plain-language note that correction actions are not yet available
- Never show "Execution failed"

When `recovery_summary == failed`:
- Show executor/process failure details
- Show preserved partial work

When `recovery_summary == rejected`:
- Show integrity violation details
- Explain that this material cannot become formal state

### HV-3.5: Fix project overview counting

**Target:** `web/src/pages/OverviewPage.tsx` (or equivalent)

Project overview must not count validation rejection as executor failure.
Separate "execution failed" from "output correction required" in any status
summaries.

## Acceptance criteria

- [ ] A completed but nonconforming role never displays "Execution failed"
- [ ] The researcher can locate every blocking field and preserved artifact
- [ ] Project overview does not count validation rejection as executor failure
- [ ] The UI states whether formal project state changed
- [ ] The projection is computed purely from existing data -- no new states added
- [ ] All existing tests pass

## Files touched

| File | Change |
| --- | --- |
| `src/model_forge/api/models.py` | `RunLifecycleProjection`, extend `RunDetail`/`RunSummary` |
| `src/model_forge/application/run_views.py` | Compute projection, expose complete diagnostics |
| `web/src/pages/RunPage.tsx` | Accurate status wording, grouped findings, recovery controls |
| `web/src/pages/OverviewPage.tsx` | Separate failure types in counting |
| `web/src/utils/format.ts` | `isRunActive` may need to account for `needs_output_correction` |
| `tests/` | New tests for projection computation |

## Dependencies

- HV-2 (provides `blocks_publication` and `correction_class` on findings)
- HV-1 (provides raw artifact preservation for diagnostics)

## Risks

- **Projection accuracy depends on HV-2 classification**: if classification is
  wrong, the projection is wrong. Mitigate by running in shadow mode (HV-7).
- **UI wording review**: the user has strong preferences on progressive
  disclosure and not showing programmer-facing vocabulary. Review the finding
  view layout carefully.

## Revision 2 changelog (2026-08-12, coder review)

- A1 (HV-3.1): extended `recovery_summary` to cover all 13 run states; the
  original four-value Literal could not represent conflicted, cancelled, or
  in-progress runs.
- A2 (HV-3.2): completed the mapping table and flagged the `failure_code`
  string keying as an interim bridge, with the durable replacement named
  (finding classes from HV-2).
- A3 (HV-3.3/HV-3.4): added control gating. HV-3 ships before HV-5, so the
  run page must not render recovery controls whose backing machinery does not
  exist yet.
