# S21: Stale Locks Cannot Promote or Release Another Owner's Lock

`scenario_id: s21.stale_lock_ownership`

## Purpose

Verify that a stale owner cannot promote state or release another owner's
project-role lock, and that fencing tokens and leases protect ownership.

## Contract under test

- Closure plan fixed rule 8 (one writer owns role state; a stale owner
  cannot promote or release another owner's lock):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- ADR-012 item 6 (only a successful, valid run under the current ownership
  token may atomically replace the current project-role state):
  [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-69 (stale
  lock ownership) and MF-49 (idempotent compare-and-swap control).
  Invariant INV-007.

## Setup

- Owner A holds the project-role state lock with a fencing token and an
  active lease.
- Owner B holds a stale token from an expired lease, an aborted run, or a
  previous application generation.

## Steps

1. Owner B attempts to advance current state pointers (promotion) using its
   stale token.
2. Owner B attempts to release the lock, delete the lease, or overwrite the
   fencing token.
3. Owner A continues its preparation, execution, and promotion normally.

## Expected evidence

- Every stale-owner attempt is rejected with a stable error; no state
  pointer, lock row, lease, or fencing token changes.
- The rejection is recorded in the operational audit.
- Owner A's operations succeed under its own token and lease.
- A lock whose lease expired is reacquirable only through the normal
  acquisition path, never through a stale release.

## Failure conditions

- A stale token promotes memory, session, or formal state.
- A stale owner releases or overwrites another owner's lock, lease, or
  fencing token.
- Concurrent runs mutate the same project-role state.
- An expired lease is silently treated as still held.
