# S09: Interrupted publication recovery

## Purpose

Verify that an interrupted controlled operation cannot leave ambiguous formal or
derived state.

## Initial state

- A valid current P2 catalog and current-index generation exist.
- The ordered authority-event journal has a verified event-root digest.
- A new P2 run has passed validation and has a sealed publication plan.
- The harness has recorded the logical location, byte length, and digest of every
  submitted run artifact before publication starts.

## Injected failures

Terminate the process separately at each publication checkpoint:

1. after new formal generations are staged;
2. after authority events are prepared;
3. after derived record-state projections are prepared;
4. after the replacement current index is prepared;
5. while the atomic commit marker and publication receipt are written;
6. after commit but before the run state becomes `published`.

## Expected recovery

- Restart detects the incomplete publication transaction.
- If no atomic commit completed, the earlier event root, projections, and current
  index remain authoritative and staged objects remain noncurrent.
- If commit completed, recovery verifies the receipt's contiguous event range,
  prior and new event roots, projection digests, and current-index generation.
- Recovery replays authority events from an empty state and from the latest
  verified checkpoint. Both replays produce the receipt's projection and index
  digests.
- Replay processes each subject's events in sequence, carries unnamed state
  dimensions forward, replaces named dimensions as complete objects, and
  reproduces the complete ordered source-event list.
- The receipt categorizes every committed event exactly once as a record,
  cumulative-object, or derived-state-only change.
- Recovery either completes the exact validated transaction or confirms the
  unchanged prior state. It never synthesizes a third state from partial files.
- Repeating recovery is idempotent.
- The run and recovery action remain in the audit log.
- Before and after every recovery path, each submitted run artifact remains at
  the same run-local logical location with the same byte length and digest. Formal
  generations are verified copies or references, not moved run artifacts.

## Prohibited behavior

- Old and new catalogs cannot simultaneously occupy the same current-index slot.
- A generation, event, projection, index, or receipt with a digest or sequence
  mismatch cannot become authoritative.
- Recovery cannot rewrite scientific content or silently create a new run.
- Publication and recovery cannot delete, move, normalize, or otherwise rewrite a
  submitted run artifact.
- The user is not asked to edit control files manually.
