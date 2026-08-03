# S05: Failed or Cancelled Run Preserves Current State

## Purpose

Verify that failed, cancelled, incomplete, or invalid work cannot displace a valid current record, and that cancellation cannot race past immutable submission.

## Initial state

- A valid current P3 record exists for a method.

## User action

The user launches a P3 rerun. A tool failure stops execution before the data
analyst and research lead can complete their required work, so no valid lead
submission exists.

## Cancellation action

In a separate trial, the researcher submits an authenticated `RunCancellationCommand` while the rerun is in `created`, `preparing`, `prepared`, or `running`. The command names the exact run and expected lifecycle head. The harness accepts at most one of cancellation and immutable submission through the same compare-and-swap boundary.

## Delegated cancellation branch

In a remote-control trial, the operator submits the same typed cancellation
under a researcher grant covering the exact project, cancel_run action, and run
ID. The service records separate acceptance and pre-commit audit events. Both
checks must pass for the cancellation fence to commit.

A grant naming another run fails with DELEGATION_NOT_ACTIVE. A grant that
expires or is revoked after acceptance but before the fence also fails with
DELEGATION_NOT_ACTIVE. Each rejection embeds the complete stable CommandError in
its audit event and changes no run or scientific state.

## Expected behavior

- The run folder preserves the completed role artifacts, event record, and
  operational failure reason.
- The run enters `failed` without entering validation or promotion.
- The previous P3 current record remains unchanged.
- An accepted cancellation moves through `cancellation_requested` to `cancelled`, preserves completed run-local work, and launches no replacement work.
- Its cancellation-requested event binds the exact cancellation command, user, operator, delegation, and accepted pre-commit audit event and root.
- If immutable submission wins the race, cancellation is rejected with no state change and the submitted run continues through validation. Repeating either command is idempotent.
- The failed attempt is visible in run history but is not a default scientific
  input.
- The UI reports what failed, what run-local work remains available, and the
  smallest user-controlled rerun action.

## Prohibited behavior

- An incomplete role sequence cannot become current.
- The system cannot hide or delete the failed attempt.
- Failure or cancellation cannot launch a repair run automatically.
- An unauthenticated, stale, expired-delegation, or post-submission cancellation cannot change run state.
- A complete negative or inconclusive scientific result cannot be mislabeled as
  an execution failure.
