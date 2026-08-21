# S26: User-Requested Output Correction

## Purpose

Verify that the researcher can authorize a targeted correction of specified
output without repeating completed scientific work, that every correction
attempt has a unique immutable identity, and that the correction cannot expand
phase scope or change the selected method.

## Initial state

- A completed role output has a blocking finding that requires correction:
  either a packaging defect (missing field, wrong envelope shape) or a
  scientific claim issue (unsupported theorem, missing evidence).
- The run's formal publication was withheld. The previous project record is
  unchanged.

## User action

The researcher submits an authenticated `OutputCorrectionCommand` naming the
exact run, role closure, validation attempt, expected lifecycle head,
correction type (packaging or scientific), permitted output scope, and an
optional instruction for scientific correction.

## Expected behavior

- The correction attempt seals against the original run's frozen basis content,
  not the current authority head. If a referenced input generation was
  superseded, the correction is refused and the researcher chooses a rerun.
- The correction creates a new submission attempt record linked to the original
  submission. The original submission row is never rewritten.
- The correction attempt receives the previous raw and candidate outputs, the
  complete structured validation report, and a scope limited to the named
  outputs.
- Packaging correction makes no intended scientific change. Scientific
  correction stays within the frozen scope and method identity.
- The correction attempt has a unique immutable identity linked to the prior
  closure. It does not mutate or replace the prior closure.
- Default bounds: at most one packaging correction attempt and one
  user-authorized scientific correction attempt.
- For a parallel role group, the harness preserves the common frozen basis and
  reruns only the nonconforming role after user authorization.
- Start the downstream lead stage only after every required parallel closure
  conforms.
- When the corrected failure interrupted the pipeline before every stage
  closed (a mid-pipeline failure), a passed correction resumes execution
  (`correcting -> running`, ADR-016) instead of sealing a submission:
  completed and corrected stage roles reconcile through the family-aware
  closure read without re-invocation, the remaining stages execute, and the
  submission seal follows once every stage role holds a succeeded closure.
- Publication of the corrected output goes through the existing atomic head
  check and may yield `conflicted`.

## Prohibited behavior

- The correction cannot authorize a different method, phase scope, or context
  basis.
- The correction cannot mutate or replace a prior immutable closure.
- The harness cannot relaunch a correction automatically after a restart.
- The harness cannot relaunch completed upstream roles.
- A resumed run cannot re-invoke a role that already holds a succeeded base
  or correction closure.
- Packaging correction cannot change primary scientific artifact digests.
- Exhaustion cannot be displayed as a false execution failure. It displays as
  "completed, correction still required".
