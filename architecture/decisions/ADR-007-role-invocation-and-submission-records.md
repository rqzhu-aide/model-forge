# ADR-007: Role Invocation and Submission Records

## Status

Accepted

## Context

The run manifest is sealed before research execution. It can fix the phase
recipe, but later role contexts, accepted handoffs, produced artifacts, access
events, and terminal outcomes do not yet exist. Treating all of these as if
they were frozen in the manifest either requires invented future digests or
allows the implementation to reconstruct execution history after the fact.

Submission also needs a durable boundary. A lifecycle state alone cannot prove
that every selected role completed successfully or that the submitted artifacts
are the exact outputs accepted from those roles.

## Invariants that must remain true

- The sealed manifest remains immutable and contains only the run recipe.
- Every role starts from one exact prepared context and resolved execution basis.
- A role start never claims a future output, access event, or terminal status.
- A downstream role consumes only accepted artifacts from successful upstream
  closures.
- A role start and closure are immutable records joined by exact digests.
- Submission requires the complete selected role plan, one successful closure
  per step, the final research-lead closure, and every required accepted output.
- Failed or cancelled pre-submission work cannot create a submission binding.

## Options considered

### Option A: Put all role state in the run manifest

This keeps one file, but future artifacts and context reads are unknown when the
manifest is sealed. Later mutation would destroy the manifest's meaning.

### Option B: Keep only mutable lifecycle state

This avoids future values in the manifest, but a mutable projection cannot prove
the exact context, handoffs, outputs, or successful closure chain used at
submission.

### Option C: Recipe, invocation, closure, and submission records

Keep the manifest as the sealed recipe. Persist a prepared-context record and
role-start record immediately before execution, a terminal closure afterward,
and a run submission only after the complete closure chain validates.

## Decision

Select Option C.

`PreparedRoleContext` is an immutable, schema-defined pre-execution object. It
binds project and run identity, stage and role identity, phase contract, role
profile, model capacity, packing policy, preference memory, exact context items,
rendered context, on-demand capabilities, a six-field projection digest, and a
whole-record digest.

`RoleInvocationStart` copies the complete matching manifest `role_plan` entry
and records its digest. It separately binds the resolved profile artifact,
actual input artifacts, expected output contracts and paths, capability set,
write root, prepared-context record, and start time. The role process may begin
only after this record validates.

`RoleInvocationClosure` binds the exact start digest and records terminal status,
the final `RoleContextSnapshot`, access-ledger head, verified produced outputs,
accepted harness-owned artifacts and handoffs, and failure or cancellation
information. It never modifies the start. A later stage begins only after every
required upstream closure is successful and every consumed artifact matches the
accepted artifact in that closure.

`RunSubmission` binds the run manifest, ordered successful closure chain, final
lead closure, and every required submitted artifact. The `running` to
`submitted` event cites its artifact and digest. RunState retains the submission
identity from submission onward, including later rejection, conflict, or
post-submission failure.

## Consequences

### Benefits

- The manifest remains truthful before execution.
- Actual context and handoff use cannot be invented retrospectively.
- Downstream role inputs have a direct verified source.
- Submission completeness and provenance are mechanically testable.
- Failure and cancellation remain inspectable without producing formal work.

### Costs and risks

- Each role execution creates three additional immutable records.
- The harness must resolve and validate cross-record digests before stage start
  and submission.
- Recovery must preserve the stage gate and submission boundary idempotently.

## Contract changes

- The run harness defines the manifest recipe, invocation gate, closure gate,
  and immutable submission boundary.
- The role-context contract defines exact prepared-context continuity through
  final snapshot closure.
- RunState binds `submission_id` and `submission_sha256` whenever its journal
  contains a submitted transition.

## Schema changes

- Add `prepared-role-context.schema.json`.
- Add `role-invocation-start.schema.json`.
- Add `role-invocation-closure.schema.json`.
- Add `run-submission.schema.json`.
- Extend RunState with submission identity and a submission evidence artifact.

## Validation changes

- Reject a start that differs from the copied manifest role-plan entry.
- Reject a downstream start with a missing, unsuccessful, or digest-mismatched
  upstream closure or accepted artifact.
- Reject submission with a missing, duplicated, unsuccessful, or reordered
  closure, a non-final lead closure, or any missing required output.
- Verify all new RFC 8785 digest contracts and RunState submission continuity.
