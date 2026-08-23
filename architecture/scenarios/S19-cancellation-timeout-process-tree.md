# S19: Cancellation and Timeout Terminate the Complete Process Tree

`scenario_id: s19.cancellation_timeout_process_tree`

## Purpose

Verify that cancellation and timeout terminate the complete Hermes process
tree, including descendants, and reach verified quiescence before closure.

## Contract under test

- ADR-012 invariant (cancellation and timeout cover the complete Hermes
  process tree and reach verified quiescence before closure):
  [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 4 and acceptance item 7 (cancellation, timeout, process
  crash, and application restart do not leave unaccounted descendants or
  launch replacements):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-67
  (complete process-tree termination with verified quiescence) and MF-52
  (authenticated idempotent cancellation). Invariants INV-001 and INV-017.

## Setup

- A run is sealed and launched; the Hermes process spawns a grandchild
  process that keeps running.
- Durable process identity (PID, start identity, executable, invocation
  marker) is recorded before launch.

## Steps

1. Cancellation trial: the user cancels the run. The supervisor sends a
   graceful termination signal, waits a fixed grace interval, then terminates
   the complete process tree, drains final output, and verifies quiescence
   before recording closure.
2. Timeout trial: a separate run is left running past its timeout. The same
   termination path fires without any user action.
3. After each closure, scan the process table for survivors and check the
   run lock and heartbeat state.

## Expected evidence

- No descendant process remains after closure: no live process, no zombie,
  and no process group member unaccounted for.
- The closure record carries the exact process identity, termination and
  cancellation evidence, and the quiescence verification result.
- The heartbeat stops, the state lock is released or fenced, and no current
  state changed.
- Repeating the cancellation command is idempotent.

## Failure conditions

- A grandchild process survives cancellation or timeout.
- Closure is recorded before writers are verified quiescent.
- Termination skips the grace interval or the complete tree.
- Cancellation or timeout promotes or partially promotes run state.
