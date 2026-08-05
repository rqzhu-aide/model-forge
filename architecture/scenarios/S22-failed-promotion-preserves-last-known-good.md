# S22: Failed Promotion Preserves Last Known Good State Byte-Identically

`scenario_id: s22.failed_promotion_preserves_last_known_good`

## Purpose

Verify that a failure at any promotion step preserves the last known good
formal and project-role state byte-identically, and that current pointers
advance only after the complete promotion succeeds.

## Contract under test

- ADR-012 invariant (failed, cancelled, timed-out, invalid, or unresolved
  work cannot become current and cannot replace current memory or session
  state): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 5, fixed rule 7, and acceptance items 9 and 10 (failed,
  invalid, stale, cancelled, timed-out, and unresolved runs cannot promote;
  injected promotion failure preserves the last known good state):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MH-70
  (failed promotion preserves last known good state), MH-05 (commit the
  complete validated change or nothing) and MH-12 (invalid work cannot
  replace current state). Invariants INV-006 and INV-007.

## Setup

- A valid current state exists: formal records with digests, plus current
  project-role memory and session snapshot with recorded digests.
- A validated run is staged for promotion with staged memories and a staged
  session snapshot.

## Steps

Inject a failure separately at each promotion step:

1. staging of allowlisted memory and session files;
2. verification of the current lock and command heads;
3. atomic advance of the current pointers;
4. writing the promotion record.

After each injection, verify the current state and then restore and repeat.

## Expected evidence

- After every injected failure, current formal records and current
  project-role memory and session digests are unchanged, byte for byte.
- The last known good state remains usable: the previous pointers, backups,
  and receipts are intact and a subsequent successful run can proceed.
- No staged file becomes current; promotion receipts record the previous
  current state.
- Failed, invalid, stale, cancelled, timed-out, and unresolved runs change no
  current pointers.

## Failure conditions

- A partial promotion advances some pointers and not others.
- The last known good state is overwritten or corrupted.
- A promotion failure rolls back into a state that cannot run.
- Scientific outputs or role state are promoted without a complete success.
