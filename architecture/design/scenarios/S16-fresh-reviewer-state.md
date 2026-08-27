# S16: Fresh Reviewer State Is Always Ephemeral

`scenario_id: s16.fresh_reviewer_state`

## Purpose

Verify that the outside reviewer always starts from a fresh, ephemeral
runtime state with no prior project-role memory or session, regardless of how
much state other roles have accumulated.

## Contract under test

- ADR-012 invariant (the outside reviewer starts from a fresh runtime state
  unless a later user decision and architecture change explicitly allow
  otherwise): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 3, fixed rule 3, and acceptance item 4 (a reviewer run
  receives no prior project-role memory or sessions):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-64 (fresh
  reviewer state) and MF-29 (the outside reviewer receives only the
  harness-prepared review packet). Invariant INV-004.

## Setup

- The research lead, theorist, and data analyst roles have accumulated
  promoted memory and session state.
- The outside reviewer role is configured.
- A Phase 5 review-revision run is eligible.

## Steps

1. The user starts a Phase 5 review run that includes the outside reviewer.
2. The assembler applies the reviewer's fresh/ephemeral state policy and
   copies no project-role memory and no session snapshot into the reviewer
   run profile.
3. The reviewer run profile is prepared with only the harness-prepared
   `p5.review_packet` and its metadata allowlist as scientific context.
4. The run executes and its closure is recorded.
5. Verify the reviewer run profile is discarded and nothing reviewer-specific
   was promoted back to any project-role state.

## Expected evidence

- The reviewer manifest records an empty memory input and an empty session
  snapshot.
- No project record, attention item, selected history, project memory, or
  project-specific knowledge appears in the reviewer run profile outside the
  review packet.
- The reviewer promotion policy (empty allowlist) prevents any reviewer
  state from becoming current.
- A second reviewer run also starts from the same empty baseline; reviewer
  state never accumulates.

## Failure conditions

- The reviewer inherits memory or session state from any project role.
- Project records or knowledge outside the review packet reach the reviewer.
- A reviewer run promotes state into a persistent project-role.
