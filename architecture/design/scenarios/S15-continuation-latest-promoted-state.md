# S15: Continuation Sees Exactly the Latest Promoted State

`scenario_id: s15.continuation_latest_promoted_state`

## Purpose

Verify that a persistent rerun receives exactly the latest promoted memory
and safe session snapshot, byte-identical and with complete provenance.

## Contract under test

- ADR-012 items 5 and 6 (snapshot semantics; only allowed mutable state is
  promoted): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 3, fixed rule 3, and acceptance item 3 (a successful
  rerun sees exactly the latest promoted memory and safe session snapshot,
  with complete provenance):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-63
  (continuation state is exactly the latest promoted state), MF-03 (frozen
  basis) and MF-53 (exact snapshot semantics). Invariant INV-003.

## Setup

- At least one successful run for the role has been promoted, so current
  project-role memory and a current safe session snapshot exist with recorded
  digests.
- The current state has not been touched since promotion.

## Steps

1. The user starts a rerun of the same role.
2. The assembler selects the current project-role state as the declared
   state input and copies memory and the safe session snapshot into the run
   profile.
3. The manifest records the snapshot identity and digests.
4. The run executes, validates, and promotes.
5. The promotion receipt records the exact before and after digests.

## Expected evidence

- The before-state digest of the rerun equals the after-state digest of the
  immediately preceding promotion, byte for byte.
- The manifest names the exact snapshot identity with complete provenance;
  no older or partial state is mixed in.
- Pilot evidence: in the project-004-eld Phase 2 pilot, the second-stage
  theorist run opened with a `state.db` digest identical to the digest the
  first-stage theorist run promoted
  (`a324fc998f5e711dcf45f5e2b8fcb72dd1d58a8a3bb98870b8f1095430fce47d` in both
  `run_promotion_records.after_digest` and the following run's
  `before_digest`).

## Failure conditions

- The rerun receives an older, partial, or mixed state.
- The manifest cannot name the exact promoted snapshot it copied.
- State is copied from the run profile of a previous run instead of the
  promoted current state.
