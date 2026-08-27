# S28: Integrity Rejection

## Purpose

Verify that material with wrong identity, wrong frozen basis, false provenance,
artifact-byte or digest mismatch, or unsafe paths is strictly rejected and
cannot become formal project state, even when the scientific content appears
complete.

## Initial state

- A completed role output or submission carries an integrity violation: wrong
  project, run, phase, producer, or selected method identity; frozen-basis or
  authority mismatch; false or contradictory provenance; artifact-byte or
  digest mismatch; unresolved identity collision; unauthorized method or
  lifecycle mutation; stale atomic-publication head; unsafe paths or symlinks.

## User action

The harness detects the integrity violation during validation or promotion.

## Expected behavior

- Publication is rejected or conflicted. These checks are never silently
  repaired and cannot be overridden in Version 1.
- The run enters `rejected` (or `conflicted` for an atomic-publication head
  conflict). The terminal state is recorded with the exact integrity finding
  code and evidence.
- The completed work is preserved for inspection but cannot become formal
  current state.
- The previous project record remains unchanged.
- The UI displays the integrity violation details and explains that this
  material cannot become formal state.

## Prohibited behavior

- The harness cannot silently repair an integrity violation.
- The harness cannot override an integrity rejection in Version 1.
- A rejected run cannot enter the correction flow for the integrity-violating
  output. Only correctable contract errors and scientific claim issues are
  eligible for correction.
- The harness cannot relaunch the run automatically.
