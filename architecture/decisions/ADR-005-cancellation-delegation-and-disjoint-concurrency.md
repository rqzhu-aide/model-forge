# ADR-005: Cancellation, Delegation, and Disjoint Concurrency

## Status

Accepted

## Context

Researchers need to stop a run without changing formal scientific records, and
may authorize a remote operator to perform a narrowly defined action. At the
same time, independent method branches should not conflict merely because their
formal publications share one global event journal. These operations require
explicit authority and race semantics.

A bare `cancel_run(run_id, actor)` call cannot prove which run state the user saw,
prevent submission from winning concurrently, or provide idempotency. A generic
remote-agent permission cannot distinguish launching research from withdrawing
an exact formal generation. A strict global-head compare-and-swap for every
research publication would reject scientifically independent method updates.

## Invariants that must remain true

- Only an authenticated user or an operator under active user delegation may
  start, cancel, retire, reactivate, or withdraw.
- A role or agent recommendation is not user authority, especially for formal
  withdrawal.
- Cancellation never changes formal project state and is impossible after
  immutable submission.
- Cancellation and submission have one deterministic compare-and-swap winner.
- Scientific content is never silently rebased onto newer inputs.
- Same-target concurrent replacement fails closed.
- The authority-event journal remains contiguous, hash chained, and totally
  ordered even when publication targets are disjoint.

## Options considered

### Option A: Treat cancellation as a formal control command

This would mix run execution state with formal research authority and suggest
that cancellation should create authority events or publication receipts.

### Option B: Use a typed run cancellation command

Use an authenticated, idempotent `RunCancellationCommand` with an exact run-head
basis. Its accepted state closes submission immediately, then stops active work
cooperatively.

### Option C: Grant a remote operator broad project authority

This is simple to implement but cannot express action or target limits and makes
a compromised operator unnecessarily powerful.

### Option D: Use immutable scoped delegation

Bind one user, operator, project, validity interval, revocation handle, and
explicit action-specific target scopes. Check it at command acceptance and again
before commit.

### Option E: Conflict on every global journal-head advance

This preserves a simple global compare-and-swap, but rejects two runs whose
scientific targets and dependencies are independent.

### Option F: Serialize disjoint commits with exact read and write sets

Allow the later transaction to append after the actual current event root only
when the backend proves that intervening changes are disjoint from its target and
hard dependencies. Do not change the submission or frozen scientific basis.

## Decision

Select Options B, D, and F.

`RunCancellationCommand` remains outside the formal `ControlCommand` union. Its
legal source states are exactly `created`, `preparing`, `prepared`, and `running`.
Acceptance enters nonterminal `cancellation_requested`, closes submission and
new-role gates, and later enters `cancelled` after cooperative stopping. If
immutable submission commits first, cancellation fails. Cancellation is never
legal from `submitted` or later.

Delegation grants are immutable and action-specific. Remote cancellation,
retirement, reactivation, and withdrawal remain disabled without a valid grant
covering the exact project, action, and target. Expiry and append-only revocation
are checked again immediately before commit. Every command attempt and its
authorization decisions are recorded in an append-only operational audit log;
remote entries include the exact grant checks.
No grant permits direct formal writes or self-expansion. Agent recommendations
cannot authorize withdrawal.

Research publications retain exact target-generation and hard-dependency checks.
A global journal-head advance alone does not conflict the later run when an
intervening receipt proves disjoint read and write sets. The publisher serializes
commits, appends the later events to the actual preceding root, and rebuilds a
complete current index containing both updates. Same-target replacement remains
conflicted. Formal lifecycle and withdrawal commands continue to require their
exact global control head because they directly change user-authorized authority.

## Consequences

### Benefits

- A researcher can stop work safely without inventing a formal research event.
- Cancellation-submission races produce exactly one outcome.
- Remote operation has explicit least authority, expiry, and revocation.
- Withdrawal remains a deliberate user correction rather than an agent action.
- Independent method branches can publish concurrently without losing global
  audit order.
- Same-target work remains protected from last-writer-wins behavior.

### Costs and risks

- The run state machine adds `cancellation_requested` and cooperative stop
  boundaries.
- The authorization service needs signed grants and an append-only revocation
  registry.
- Every remote commit needs a second authorization check.
- The publisher must derive the later run's exact read set from its sealed
  manifest and its write set from sealed publication bindings, then compare both
  with the intervening receipt's exact changed targets.
- The publisher must distinguish safe transaction placement from prohibited
  scientific rebasing.

## Contract changes

- The run harness defines cancellation fencing and disjoint publication.
- The UI uses discriminated, actor-specific action descriptors.
- The control-command specification defines grant and revocation semantics while
  keeping cancellation outside formal control commands.

## Schema changes

- The common lifecycle includes `cancellation_requested`.
- Run-state transitions restrict entry to the four pre-submission states and exit
  to `cancelled`.
- New schemas define `RunCancellationCommand`, `DelegationGrant`,
  `DelegationRevocation`, and `ActionDescriptor`.

## Scenario changes

- S12 proves that two disjoint method targets both publish in one ordered journal
  and that a same-target replacement still conflicts.
- Cancellation fixtures cover exact run-head binding and the nonterminal request
  state.
