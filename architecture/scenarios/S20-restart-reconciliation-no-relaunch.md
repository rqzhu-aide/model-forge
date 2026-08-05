# S20: Restart Reconciliation Inspects Durable Identity, Never Relaunches

`scenario_id: s20.restart_reconciliation_no_relaunch`

## Purpose

Verify that after an application restart, reconciliation inspects the
recorded durable process identity and never launches a replacement
invocation automatically.

## Contract under test

- ADR-012 invariant (application restart never launches a replacement
  invocation automatically) and item 7 (durable supervision):
  [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 4 and acceptance item 7 (application restart does not
  leave unaccounted descendants or launch replacements):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MH-68
  (restart reconciliation never relaunches), MH-01 (only the user starts or
  reruns) and MH-08 (no completion or status change starts another run).
  Invariant INV-001.

## Setup

- A run is launched and its durable identity is recorded: PID, process start
  identity, executable, invocation marker, and host boot or session identity.
- The application is killed mid-run and restarted.

## Steps

1. On startup, the application scans active invocation records and compares
   each recorded identity with the live process table.
2. If the process still exists with matching identity, supervision resumes.
3. If the process is gone, the invocation is reconciled as failed or
   unresolved with bounded diagnostic evidence.
4. Verify no second launch record exists for the same idempotency key.
5. The user is offered a new run explicitly; nothing starts automatically.

## Expected evidence

- Exactly one launch record per idempotency key; no duplicate process is
  ever created.
- PID reuse is not mistaken for the original process: start identity,
  executable, invocation marker, and boot or session identity are compared.
- An unresolved invocation is surfaced to the user with the smallest safe
  next action.
- Pilot evidence: in the project-004-eld pilot, the preflight-refused launch
  of `p2s1-theorist-002` recorded no external execution identity, and the
  relaunch of the same seal created exactly one new launch record; no
  replacement process was spawned automatically.

## Failure conditions

- A replacement invocation starts without a user action.
- PID reuse is accepted as the original process.
- Reconciliation marks a live process failed or a dead process running.
- Duplicate work is executed under one idempotency key.
