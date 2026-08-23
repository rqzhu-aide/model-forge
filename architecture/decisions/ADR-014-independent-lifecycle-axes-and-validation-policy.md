# ADR-014: Independent Lifecycle Axes and Validation Policy

## Status

Proposed

## Context

Model Forge conflates operational execution success with output conformance.
A successful Hermes exit followed by any schema finding becomes role FAILED
(`role_execution.py:991-993`), stage FAILED, run FAILED, and the UI reports
"Execution failed". This happens even when the scientific work is complete and
the only problem is a missing envelope field, a wrong output shape, or another
correctable contract issue.

Three root causes produce this behavior:

1. The `ValidationReport.passed` property reads
   `not any(severity == ERROR)` (`validation.py:52-53`). Every one of the
   approximately 75 finding codes is `ValidationSeverity.ERROR`; the
   `WARNING` and `INFORMATION` enum values have zero uses repo-wide. There is
   no per-code policy, so a sparse metadata field and a digest mismatch have
   identical operational consequence.

2. The run lifecycle is a single scalar `RunStatus` with 13 values. FAILED and
   REJECTED are terminal with no outgoing edges (`runs.py:81,83`). Publication
   is fused to conformance: a validated submission is always promoted. There is
   no "conforms but withheld" or "completed but needs correction" state.

3. The researcher has no bounded recovery action between "do nothing" and
   "launch a full phase rerun". A run rejected for a missing output file costs
   the same recovery effort as a run that crashed during role execution.

ADR-013 established that structural and semantic validation establish
conformance, never scientific truth, and that honest negative, contradictory,
or incomplete outputs remain valid when represented honestly. This decision
defines the lifecycle and policy machinery to make that principle operational.

## Invariants that must remain true

- Formal project state changes only after all blocking checks pass.
- Invalid or ambiguous material must not become a formal current record.
- Exact project, run, phase, method, producer, frozen basis, artifact, and
  digest bindings remain required for publication.
- No failed or incomplete phase launches another scientific invocation by
  itself.
- A deterministic format normalization may be part of the already authorized
  run if it is fully disclosed and cannot alter scientific meaning.
- Any model-based or scientifically substantive correction requires an explicit
  user action.
- The original workspace and output bytes are sealed before repair,
  normalization, or adaptation.
- The harness owns harness facts: run identity, role identity, method identity,
  frozen-basis identity, timestamps, generation identifiers, artifact
  locations, and digests.
- An honestly labeled null result, failed proof attempt, counterexample,
  inapplicable diagnostic, or unresolved question may be scientifically useful.
  Validation prevents unsupported positive claims, not artificial positive
  content.
- Do not rewrite old immutable closures. A correction creates a new attempt
  record linked to the original closure.

## Options considered

### Option A: Add a recoverable run status and per-code severity tiers

Introduce `needs_output_correction` as a new `RunStatus` value with new
transition edges from FAILED and REJECTED. Replace the all-ERROR severity model
with an explicit per-code policy registry where each finding code declares
whether it blocks publication and what correction class it belongs to.

**Benefits:** Explicit in the state machine; queryable; clear semantics.

**Costs:** New non-terminal states touch every consumer of `RunStatus`
(domain, coordinator, API, UI, tests). The submission gate mechanics require a
new `run_submission_attempts` table because `run_submissions.run_id` is UNIQUE
with immutable triggers and a REJECTED run already holds its row.

### Option B: Derive lifecycle projections from existing status

Keep the existing 13-state `RunStatus` and compute a derived projection
(execution state, conformance state, publication state, recovery summary) for
display. Add the policy registry for per-code blocking decisions. Defer the
non-terminal correction state to a later package.

**Benefits:** Smaller blast radius; UI fix ships immediately; the projection
layer can later be backed by real states.

**Costs:** `needs_output_correction` is a derived label, not a real state. The
coordinator still transitions to terminal FAILED; the correction loop needs
separate implementation.

### Option C: Do not separate the axes; relax validators instead

Reclassify findings from ERROR to WARNING to let more outputs pass. Keep the
single-axis lifecycle.

**Benefits:** Smallest implementation.

**Costs:** Does not solve the lifecycle conflation. A corrected run still shows
"Execution failed" if any finding remains. Weakens the publication boundary
without giving the researcher recovery control. Rejected by ADR-013's
validation-boundary principle.

## Decision

### 1. Four independent lifecycle axes

Represent each run using four independent axes. A user-facing summary is
derived from them, but the underlying facts remain separate.

| Axis | Values | Meaning |
| --- | --- | --- |
| Agent execution | `not_started`, `running`, `completed`, `failed`, `cancelled` | Whether Hermes and its tools completed operationally |
| Output conformance | `not_checked`, `passed`, `correction_required`, `integrity_rejected` | Whether the produced packet can enter formal validation and publication |
| Publication | `not_attempted`, `published`, `withheld`, `conflicted` | Whether canonical project state changed |
| Scientific outcome | phase-specific controlled values | Supported, negative, inconclusive, contradictory, open, or not applicable |

Version 1 implements these as a derived projection over the existing
`RunStatus` (Option B first). The non-terminal correction states and the
submission-attempt table are added when the correction loop is built (HV-5).
The projection layer is designed so it can later be backed by real domain
states without breaking consumers.

### 2. needs_output_correction condition

A run is in `needs_output_correction` when:

- the assigned Hermes process completed;
- produced work has been preserved;
- formal publication did not occur;
- one or more blocking findings are correctable without changing run
  authority;
- the next action remains under researcher control.

Reserve `failed` for executor, tool, timeout, process-control, or
infrastructure failure. Reserve `rejected` for material that cannot be trusted
under the sealed authority, identity, provenance, or integrity rules. Preserve
`conflicted` for an atomic-publication head conflict.

### 3. Validation policy registry

Create an explicit registry for every validation finding code. Each registry
entry declares: stable code, finding class, default severity, whether it blocks
publication, applicable phases and modes, correction class, responsible
component, whether deterministic repair is allowed, whether a model call is
required, whether researcher override is allowed, rationale, and user-facing
guidance.

The overall pass/fail decision is computed from explicit `blocks_publication`
policy, not from severity level.

The registry uses a fail-closed default: unregistered codes (including
dynamically composed codes from jsonschema paths) block publication. Finding
factories validate the emitted code against the registry at construction time
so a typo or an unregistered code cannot silently change acceptance behavior.

Publication policy keys on harness-owned finding codes only. Agent-authored
severity fields (for example review-finding `severity=minor`) inform triage
display but never set `blocks_publication`. This prevents a model from
downgrading its own findings.

### 4. Finding classes

| Class | Severity | Blocks? | Effect |
| --- | --- | --- | --- |
| Operational failure | ERROR | Yes | Execution fails. Preserve work. Do not publish. |
| Integrity blocker | ERROR | Yes | Publication rejected or conflicted. Never silently repaired. Cannot be overridden in Version 1. |
| Correctable contract error | ERROR | Yes (correctable) | Publication withheld, run enters `needs_output_correction`. Not called an execution failure. |
| Scientific claim blocker | ERROR | Yes | Publication withheld. User may request targeted correction or claim downgrade. Harness must not decide. |
| Scientific attention | WARNING | No | Visible warning retained. Publish under original launch authority when no blocking finding remains. |
| Information | INFORMATION | No | Recorded and displayed without blocking. |

### 5. Correction authority

Which actions require new user authority:

| Action | Model call | Changes scientific content | Authority |
| --- | --- | --- | --- |
| Revalidate unchanged output | No | No | Explicit click. No new scientific authority. |
| Apply deterministic normalization | No | No | Covered by launch authority. Visible record. |
| Request packaging correction | Yes | No intended scientific change | Explicit click. |
| Request scientific correction | Yes | Yes, within frozen scope | Explicit click + optional instruction. |
| Start full phase rerun | Yes | Yes | Existing run/rerun control. |

Do not introduce a generic post-run Approve button. If the user launched the
run and all blocking checks pass, publication proceeds under that launch
authority.

### 6. Correction basis pinning

A correction attempt seals against the original run's frozen basis content
(input generations and digests, method identity, role profile versions), not
the current authority head. The reviewed-basis drift check compares that pinned
content, not the current authority head, so a correction is not rejected merely
because unrelated work published in between. If the pinned inputs themselves
have drifted (a referenced input generation was superseded), the correction is
refused and the researcher chooses a rerun instead.

Publication of the corrected output goes through the existing atomic head check
and may yield `conflicted`, exactly as an ordinary run. This keeps WP0 sealing
intact: no drift check is bypassed; the correction reuses an older, still
identified basis.

### 7. Submission re-entry

The base submission record is immutable and unique per run
(`storage/migrations.py:219-233`, `run_submissions.run_id` UNIQUE with
immutable triggers). A correction that passes validation creates a new
submission attempt record in a new `run_submission_attempts` table. Publication
binds the latest passing attempt. The original submission is never rewritten.

The correction execution context sets `submission_from_status="correcting"`,
so the CAS edge is `correcting -> submitted` and the existing idempotency
semantics are preserved for the correction path.

### 8. Do not rewrite immutable closures

FAILED and REJECTED closures are not mutated. A role correction creates a new
attempt record linked to the original closure.

## Consequences

### Benefits

- A completed but nonconforming role never displays "Execution failed".
- Correctable output problems preserve completed work and offer the smallest
  user-controlled recovery action.
- The researcher can inspect every relevant output, validation finding, and
  mechanical transformation before deciding what to run next.
- Negative, inconclusive, contradictory, or open research results remain valid
  outcomes when represented honestly.
- Changing message wording cannot change acceptance behavior.

### Costs and risks

- The policy registry requires per-code review of approximately 75 finding
  codes. Mitigate by delegating per-phase review and running in shadow mode
  (HV-7) before changing publication behavior.
- The submission-attempt table is a new storage migration with immutability
  triggers. The standing test pattern requires bumping two hard-coded
  `initialize() == N` assertions.
- The lifecycle projection is an interim representation; the durable model uses
  finding classes from HV-2, not the `failure_code` string. The projection must
  not promise recovery controls before the correction machinery exists (HV-5).

## Contract changes

- New record types: `ValidationAttempt`, `OutputTransformationRecord`,
  `RoleAttempt` identity extension, `OutputCorrectionCommand`. Authored as
  architecture schemas before runtime code depends on them (HV-0.6).
- Revised S05 scenario: distinguishes executor failure from completed work
  requiring output correction.
- New scenarios S25-S29: deterministic normalization, output correction,
  revalidation, integrity rejection, warning-only publication.
- `contracts/traceability.json`: register the five new scenarios and their
  invariant back-links; extend the validator's scenario ID range from S01-S24
  to S01-S29.

## Schema changes

- `architecture/schemas/validation-attempt.schema.json` (new): immutable
  validation attempt record.
- `architecture/schemas/output-transformation-record.schema.json` (new):
  immutable mechanical transformation record.
- `architecture/schemas/output-correction-command.schema.json` (new): user
  correction command shape.
- `architecture/schemas/run-submission-attempt.schema.json` (new):
  submission-attempt record for correction re-entry.
- RoleAttempt identity extension: attempt ordinal/ID and prior-closure link,
  added to the role-invocation-closure schema or a dedicated schema.
- Runtime dataclasses mirror these schemas; they do not redefine them.
- `RunLifecycleProjection`: derived projection added to API models (not a
  persisted schema).

## Scenario changes

- S05 revised to distinguish executor failure from completed work requiring
  output correction.
- S25: deterministic normalization applied and disclosed.
- S26: user-requested output correction, attempt retained, scope bounded.
- S27: revalidation after policy change, unchanged output digest.
- S28: integrity rejection (wrong identity/basis/digest), hard rejection.
- S29: warning-only publication (honest negative/inconclusive result).
