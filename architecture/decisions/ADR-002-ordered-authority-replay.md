# ADR-002: Ordered Authority Replay

## Status

Accepted

## Context

Derived record state changes after publication without rewriting scientific
content. A projection validator that compares the final state with every event
independently cannot represent legitimate histories such as publication followed
by a later alignment assessment. Receipts also need to account for authority
events that change state without creating or replacing scientific content.

## Invariants that must remain true

- Formal scientific generations are immutable.
- Authority events are append-only, ordered, and hash chained.
- Current state and the current index are reproducible from the event journal.
- Every committed event appears exactly once in its transaction receipt.
- Replay changes authority state only and does not make scientific judgments.

## Options considered

### Option A: Compare every event with final state

Require the final projection to equal each event field. This works only when a
subject has one event and rejects legitimate later changes.

### Option B: Ordered whole-field fold

Process events by sequence. A later event replaces each complete top-level state
dimension it names, while unnamed dimensions carry forward. Track the complete
ordered event history for each subject.

## Decision

Select Option B. Alignment, research attention, and evidence eligibility are
replaced as complete objects, not deep-merged. Record generations start with
evidence eligibility not_applicable, and evidence items start with record
position none. A projection uses the global checkpoint sequence, root, and head
time. Events that depend on prior subject state bind its canonical digest.

Receipts separate record changes, cumulative-object changes, and
derived-state-only changes. The three categories must account for every
committed event exactly once.

## Consequences

### Benefits

- Publication followed by supersession, realignment, or attention change replays
  correctly.
- Complete ordered provenance is visible in each projection and current-index
  slot.
- Intermediate-state digests make later state transitions reproducible.
- Receipt recovery can detect omitted, duplicated, or misclassified events.

### Costs and risks

- Projectors must maintain deterministic defaults and whole-field replacement
  semantics.
- Receipt writers must distinguish content changes from state-only changes.
- A change to replay defaults or merge semantics requires a new architecture
  decision and migration plan.

## Contract changes

- Storage and authority defines exact fold semantics.
- Run harness receipts categorize every event once.
- Validation strategy requires multi-event and intermediate-state tests.

## Schema changes

- PublicationReceipt requires typed state_changes.
- AuthorityEvent rejects fields outside its event family.
- Record-state and current-index provenance is complete and sequence ordered.

## Scenario changes

- S09 recovery checks use ordered replay and exact receipt categories.
- The independent two-event replay fixture proves carry-forward and later-field
  replacement without changing the six-event Phase 4 transaction.
