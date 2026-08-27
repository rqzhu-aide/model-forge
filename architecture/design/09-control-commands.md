# Control Commands

## 1. Purpose

Control commands change formal project state without performing scientific work.
They are distinct from a `RunCommand` and must never create a research run, a run
workspace, or role execution.

Version 1 defines two commands:

1. `MethodLifecycleCommand` retires or reactivates one method through an atomic
   Phase 2 catalog transaction.
2. `FormalGenerationWithdrawalCommand` withdraws one exact formal generation
   through an atomic authority transaction.

These commands use separate schemas because they have different scientific
meanings. Method retirement is a reversible portfolio decision about whether a
method is available for ordinary work. Generation withdrawal is an irreversible
correction to the authority of exact published content. A common API may accept a
discriminated union of the two command types, but it must not replace them with a
generic target-state command.

`RunCancellationCommand` is not a third formal control command. It changes one
run's execution state before immutable submission and never enters the formal
authority journal. It has its own schema, idempotency record, and run-journal
compare-and-swap basis. See Section 7.

`OutputCorrectionCommand` is likewise an execution-lane command: it authorizes
bounded correction of a failed or rejected run and appends operational
records, but it never enters the formal authority journal by itself. See
Section 8.

## 2. Shared command requirements

Both commands contain:

| Field | Type | Requirement |
|---|---|---|
| `schema_version` | schema version | Required |
| `command_type` | discriminator | Required and fixed by command schema |
| `command_id` | stable ID | Required and globally unique within the project |
| `idempotency_key` | string | Required and unique for one intended user action |
| `project_id` | stable ID | Required |
| `expected_control_head` | object | Required optimistic-concurrency basis |
| `reason` | object | Required structured reason and explanation |
| `requested_by` | actor object | Required authenticated user authority and optional delegated operator |
| `content_sha256` | SHA-256 | Required digest of RFC 8785 canonical command JSON with this field omitted |
| `requested_at` | date-time | Required |

`requested_by` has the same semantics as `RunCommand.requested_by`. A delegated
operator records both the user authority and the operator identity. The service
must reject any command outside the delegation.

No role, profile, or agent recommendation authorizes a control command. This is
especially strict for withdrawal: an agent may identify a possible correction
and explain its evidence, but only an authenticated user or an operator acting
under a currently valid user grant may submit the command.

`reason` contains:

```json
{
  "code": "user_portfolio_decision",
  "explanation": "This method is no longer part of the active research portfolio."
}
```

Both fields are nonempty. A client-generated label is not sufficient as the
formal explanation.

`expected_control_head` contains:

```json
{
  "current_index_generation_id": "generation.current_index.040",
  "current_index_sha256": "...",
  "last_event_sequence": 40,
  "event_root_sha256": "..."
}
```

The service compares all four values before preparing the transaction and again
at commit.

## 3. MethodLifecycleCommand

### 3.1 Purpose and fields

`MethodLifecycleCommand` changes whether one stable method is active in the
research portfolio. Its `command_type` is `method_lifecycle_change`.

In addition to the shared fields, it requires:

| Field | Type | Meaning |
|---|---|---|
| `method_id` | stable ID | Permanent method ID |
| `expected_method` | object | Exact current method-record generation shown to the user |
| `expected_catalog` | object | Exact current method-catalog generation shown to the user |
| `target_lifecycle_state` | enum | `retired` or `active` |

`expected_method` contains:

```json
{
  "record_id": "record.method.example",
  "generation_id": "generation.method.example.004",
  "content_sha256": "...",
  "method_identity": {
    "stable_id": "method.example",
    "version": 2,
    "definition_sha256": "..."
  },
  "lifecycle_state": "active"
}
```

`expected_catalog` contains `record_id`, `generation_id`, and `content_sha256`.

### 3.2 Legal transitions

Only these transitions are legal:

| Expected state | Target state | Operation |
|---|---|---|
| `active` | `retired` | Retire method |
| `retired` | `active` | Reactivate method |

`proposed` activation remains a Phase 2 research publication. A withdrawn formal
generation cannot be reactivated. A new command requesting the state already in
force fails with `NO_STATE_CHANGE`. Repeating a previously committed command with
the same idempotency key returns its original receipt.

### 3.3 Validation and transaction effects

The service must verify that:

1. The expected method generation is the current formal `method_record` for
   `method_id`.
2. The expected catalog is the current formal `method_catalog`.
3. The catalog points to the expected method generation and lifecycle state.
4. The method identity, mathematical definition, version, definition digest,
   scientific content, provenance, assumptions, and limitations will remain
   unchanged.
5. The requested transition is legal and authorized.

The atomic transaction creates:

1. A replacement `method_record` generation with the new lifecycle state, the
   same exact method identity, and lifecycle lineage to the prior generation.
2. A replacement `method_catalog` generation that selects the new method-record
   generation and updates the active or retired portfolio view.
3. `published` authority events for the two new generations.
4. `superseded` authority events for the two prior generations.
5. Rebuilt `DerivedRecordState` projections and a complete replacement
   `FormalCurrentRecordIndex`.
6. One atomic receipt.

No Phase 2 role recommendation can authorize this transaction. Retirement and
reactivation do not change the method version or definition digest. They do not
change the publication, position, alignment, attention, or scientific outcome of
existing Phase 3, Phase 4, or Phase 5 records.

Retirement removes the method from ordinary Phase 3 and Phase 4 launch
eligibility. Reactivation restores eligibility only when all other phase
prerequisites are satisfied.

## 4. FormalGenerationWithdrawalCommand

### 4.1 Purpose and fields

`FormalGenerationWithdrawalCommand` withdraws one exact formal generation after
an authenticated scientific-correction or administrative decision. Its
`command_type` is `formal_generation_withdrawal`.

In addition to the shared fields, it requires:

| Field | Type | Meaning |
|---|---|---|
| `target` | object | Exact immutable formal generation to withdraw |
| `expected_target_state` | object | Exact derived state shown to the user |

`target` contains:

```json
{
  "record_id": "record.theory.example",
  "record_type": "theory_record",
  "generation_id": "generation.theory.example.003",
  "content_sha256": "..."
}
```

`expected_target_state` contains:

```json
{
  "publication_state": "formal",
  "record_position": "current",
  "record_state_sha256": "..."
}
```

The target may be current or historical, but its derived publication state must
be `formal` when the command commits.

### 4.2 Withdrawal rules

Withdrawal is not deletion. The immutable generation and its provenance remain
stored and addressable for audit, but the resolver must reject it as an eligible
ordinary downstream input.

A withdrawn generation cannot be reactivated. Corrected scientific content must
be published as a new generation through the applicable user-started research
run. The service must not automatically restore an older historical generation
to current position.

### 4.3 Validation and transaction effects

The service must verify that:

1. The target identity and digest resolve to one immutable generation in the
   project.
2. Its current `DerivedRecordState` matches `expected_target_state`.
3. Its publication state is `formal`.
4. The actor is authorized to perform formal correction or withdrawal.
5. Every current record with a hard or contextual dependency on the target has
   been identified before commit.

The atomic transaction:

1. Appends one `withdrawn` `AuthorityEvent` for the exact target generation.
2. Sets derived `publication_state` to `withdrawn`.
3. Sets derived `record_position` to `none` when the target was current, or
   preserves `historical` position when it was already historical.
4. Removes a withdrawn current generation from its current-index slot and does
   not fill that slot from history.
5. Appends typed alignment and attention events for affected current dependents.
6. Rebuilds affected `DerivedRecordState` projections and a complete replacement
   `FormalCurrentRecordIndex`.
7. Commits one atomic receipt.

A current hard dependent of the withdrawn generation becomes noneligible for
exact-current use. Its alignment changes to `unassessed` with cause
`withdrawn_dependency`, and its research attention becomes `blocking` until an
eligible replacement basis and an applicable user-started rerun resolve the
dependency. A contextual dependency creates explicit attention but does not by
itself erase the dependent record's scientific outcome.

The transaction creates no replacement scientific generation.

## 5. Receipt source semantics

The receipt schema represents both research-run publication and control
transactions. Its source is a discriminated union:

```json
{
  "source": {
    "kind": "research_run",
    "command_id": "...",
    "run_id": "...",
    "phase": "P4",
    "manifest_sha256": "..."
  }
}
```

```json
{
  "source": {
    "kind": "method_lifecycle_command",
    "command_id": "...",
    "command_sha256": "..."
  }
}
```

```json
{
  "source": {
    "kind": "generation_withdrawal_command",
    "command_id": "...",
    "command_sha256": "..."
  }
}
```

Only `research_run` may carry `run_id`, `phase`, or `manifest_sha256`. A control
receipt still records validation reports, prior and new current-index identities
and digests, the contiguous authority-event range and roots, derived projection
digests, exact record changes, impacts, actor command, transaction ID, and commit
time.

A method-lifecycle receipt records `replace` changes for `method_record` and
`method_catalog`. A withdrawal receipt records a `withdraw` change with
`subject_generation_id`, no `new_generation_id`, and every supporting
`authority_event_id`.

## 6. Optimistic concurrency and idempotency

Control transactions use compare-and-swap. The service first compares the
command's expected control head, exact target generations, content digests, and
derived state digests with current backend state. Immediately before commit, it
repeats the control-head comparison.

Any mismatch returns `409 CONFLICT`, appends no authority event, creates no
generation, and leaves the current index unchanged. The response identifies the
stale object and instructs the client to refresh. The service must not silently
rebase a user decision onto newer scientific state.

The idempotency key is bound to the canonical command digest. Repeating the same
key and digest returns the original outcome. Reusing the key with different
content is rejected. A transport retry resubmits the same serialized command;
it must not regenerate `command_id`, `requested_at`, or any other digested field.

### 6.1 Stable command errors

Every rejected run, cancellation, lifecycle, or withdrawal command returns a `CommandError`. Web and remote clients receive the same code, rule ID, affected object references, retryability, direct researcher message, and smallest corrective action. Free-form exception text is diagnostic only and cannot drive client behavior.

| Code | Category | HTTP | Retryable | Governing rule |
|---|---|---:|---|---|
| `AUTHENTICATION_REQUIRED` | `authentication` | 401 | yes | `MF-59` |
| `DELEGATION_NOT_ACTIVE` | `authorization` | 403 | yes | `MF-55` |
| `COMMAND_SCHEMA_INVALID` | `schema` | 422 | yes | `MF-59` |
| `COMMAND_DIGEST_MISMATCH` | `digest` | 422 | yes | `MF-57` |
| `IDEMPOTENCY_KEY_REUSED` | `idempotency` | 409 | yes | `MF-49` |
| `INVALID_TRANSITION` | `transition` | 409 | no | `MF-59` |
| `RUN_ALREADY_SUBMITTED` | `transition` | 409 | no | `MF-59` |
| `CANCELLATION_REQUESTED` | `concurrency` | 409 | no | `MF-59` |
| `CONTROL_HEAD_STALE` | `concurrency` | 409 | yes | `MF-49` |
| `TARGET_STATE_MISMATCH` | `concurrency` | 409 | yes | `MF-49` |
| `TARGET_NOT_FOUND` | `dependency` | 404 | no | `MF-59` |
| `DEPENDENCY_CLOSURE_INCOMPLETE` | `dependency` | 422 | yes | `MF-59` |
| `NO_STATE_CHANGE` | `transition` | 409 | no | `MF-47` |
| `PUBLICATION_CONFLICT` | `concurrency` | 409 | yes | `MF-56` |
| `CORRECTION_NOT_APPLICABLE` | `transition` | 409 | no | `MF-73` |
| `CORRECTION_SCOPE_INVALID` | `schema` | 400 | yes | `MF-74` |
| `CORRECTION_EXHAUSTED` | `transition` | 409 | no | `MF-75` |

The `CommandError` schema enforces this mapping. A code cannot be paired with a different category, HTTP status, retryability value, or rule.

HTTP status is transport metadata. The stable code and `MH` rule identify the architecture failure. `retryable: true` means that a new command may be prepared after the stated correction; it never authorizes automatic retry.

## 7. RunCancellationCommand

`RunCancellationCommand` is an authenticated, idempotent execution command. It
requires an exact `run_id`, expected pre-submission lifecycle state, last
run-journal sequence and root digest, structured reason, requesting identities,
command digest, and request time.

> **Supervised-lane cancel.** The supervised lane (ADR-012, see
> [02a](02a-supervised-run-walkthrough.md)) has its own explicit cancel
> command (`POST /projects/{id}/supervised-runs/{invocation_id}/cancel`).
> It consults the recorded durable process identity, terminates the process
> tree with a SIGTERM grace period, and closes the launch record as
> `cancelled` rather than `failed` when the cancel flag explains the signal
> death. It follows the same rule as below: no formal state changes.

Legal source states are exactly `created`, `preparing`, `prepared`, and `running`.
Acceptance atomically changes the run to `cancellation_requested` and closes its
submission and new-role gates. Active work stops at safe tool and role
boundaries, after which the harness enters `cancelled`. Late output is diagnostic
only. The command creates no formal generation, authority event, current-index
change, or publication receipt.

Cancellation and submission use one serialized compare-and-swap. If the
cancellation fence commits first, lead submission is rejected with
`CANCELLATION_REQUESTED`. If immutable submission commits first, cancellation is
rejected with `RUN_ALREADY_SUBMITTED`. Cancellation is never legal from
`submitted`, `validating`, `promoting`, `published`, or any terminal state.
Client timestamps do not determine the winner.

The command is separate from `ControlCommand`. Repeating its idempotency key and
digest returns the original cancellation result; changing content under the same
key is rejected.

The cancellation-requested RunState event contains a typed `command_source` that
binds the RunCancellationCommand ID and digest and the user and optional
operator and delegation. The accepted pre-commit audit event independently binds
that RunState event by its exact ID and event digest. This one-way link avoids a
digest cycle and does not place cancellation in the scientific authority journal.

## 8. OutputCorrectionCommand

`OutputCorrectionCommand` is an authenticated, idempotent control command that
authorizes bounded correction of a run whose outputs failed validation with at
least one correctable contract error (ADR-014). Its schema is
[output-correction-command.schema.json](../schemas/output-correction-command.schema.json).
The command binds the exact run, the target role closure, the validation
attempt being answered, the expected lifecycle head, the correction type
(`revalidate`, `normalize`, `packaging`, or `scientific`), and the permitted
output scope. It carries no authority to edit sealed records.

Legal source states are exactly `failed`, `rejected`, and
`correction_authorized`. Acceptance seals the command and moves the run to
`correction_authorized`. Every other state, a run without a correctable
finding, or a correction type the build does not offer is rejected with
`CORRECTION_NOT_APPLICABLE` (`MF-73`). A permitted scope naming outputs the
target closure did not declare is rejected with `CORRECTION_SCOPE_INVALID`
(`MF-74`). Correction attempts are bounded per run; when the bounds are spent
the command is rejected with `CORRECTION_EXHAUSTED` (`MF-75`) and the run
resolves to `correction_exhausted`.

A `revalidate` correction re-checks the already sealed output bytes against
the current schemas and records a new validation attempt; on pass the run
re-enters the normal `submitted -> validating -> promoting` pipeline through a
submission-attempt record that never rewrites the base submission. A
`normalize` correction applies only disclosed deterministic transformations
that were previewed to the researcher before authorization. `packaging` and
`scientific` corrections re-invoke the owning role under a correction identity
with a pinned basis and a derived pointer list; changed outputs seal as a new
correction closure in the closure family, never as an edit to the original
closure. Every correction appends new records: validation attempts, correction
closures, submission attempts, and transformation records.

## 9. Delegated authorization

A `DelegationGrant` is immutable user-issued authority for one operator. It binds
an exact project, a list of action-specific target scopes, issue and expiry times,
and a revocation handle. Permissions are action-specific:

- `start_run` names allowed phases and optional method targets. A method-bound
  command is covered only when its exact method ID is listed; omitting
  `method_ids` covers only non-method-bound modes in the named phases.
- `cancel_run` names exact runs or all runs in the project.
- `retire_method` and `reactivate_method` name exact method IDs.
- `withdraw_formal_generation` names exact generation IDs.

Delegation never includes direct formal-record writes, generic target-state
changes, or authority to enlarge its own scope. A grant is active only when its
signature and issuer remain valid, the current time is within its interval, and
no append-only `DelegationRevocation` for its grant and revocation handle exists.
Revocation is effective at its committed service sequence, regardless of client
caching. The authorization service verifies that `issued_at <= not_before <
expires_at`, checks the user signature over the immutable grant digest, and uses
one trusted service clock for validity decisions.

Every request first becomes an immutable raw-request artifact containing the
exact bytes received before parsing, their byte length, media type, and SHA-256.
A CommandAttemptAuditEvent then records the project, action family, check stage,
request artifact, requester status, authorization checks, result, service time,
and tamper-evident audit roots.

When command validation succeeds, the event binds the command ID and canonical
digest. An accepted or pre-commit event also requires the exact action-specific
target. A malformed or unauthenticated acceptance-stage rejection instead uses
an explicitly unresolved target and an unauthenticated requester form; it must
not invent a trusted command ID, user ID, or resolved target.

The service records acceptance and pre-commit checks as separate events when
both boundaries are reached. An accepted pre-commit event binds the exact created
or cancellation RunState event, or the committed publication receipt, by stable ID
and digest. A rejected event
embeds the complete schema-valid CommandError, including its stable code, rule,
affected objects, researcher message, and smallest correction. Remote events
also record the grant identity and digest and the individual project, action,
target, time-window, and revocation results.

The content digest covers RFC 8785 canonical event JSON with only
content_sha256 and audit_root_sha256 omitted. The new audit root is SHA-256 of
the decoded 32-byte prior audit root followed by the decoded 32-byte content
digest. These events are not formal authority events and cannot change
scientific state.

The service resolves and records the grant at command acceptance, then rechecks
project, action, exact target, expiry, and revocation immediately before the
operation commits. A run creation, cancellation fence, or formal transaction
fails with `DELEGATION_NOT_ACTIVE` if the second check fails. Remote cancellation,
retirement, reactivation, and withdrawal descriptors are disabled until a
covering active grant is resolved.

## 10. UI and remote-operation behavior

For formal control commands, the backend exposes typed action descriptors for:

- `retire_method`
- `reactivate_method`
- `withdraw_formal_generation`

Each descriptor contains the exact target identity and digest, current state,
allowed transition, expected control head, reason requirements, enabled state,
reason code when disabled, consequence summary, and affected-dependent preview.

The Phase 2 method table presents retire or reactivate according to the current
lifecycle state. Withdrawal appears in the selected formal record's correction
controls, not in the ordinary phase-run panel. The confirmation view states that:

- No research run or role execution will occur.
- Retirement preserves existing scientific records and history.
- Withdrawal removes exact content from eligible current use and may block
  dependent work.
- No formal control action launches a later phase.

The Web UI and authorized remote operator use the same command service and
receive the same eligibility and conflict responses. A confirmation interaction
is not a separate approval state.

The common `ActionDescriptor` schema has five discriminated branches:
`start_run`, `cancel_run`, `retire_method`, `reactivate_method`, and
`withdraw_formal_generation`. Run-launch fields, cancellation run-head fields,
method lifecycle fields, and withdrawal generation-state fields are disjoint.
The descriptor communicates eligibility and command construction; it is never
itself authorization.

## 11. Failure behavior

Authentication, authorization, schema, transition, digest, dependency-closure,
or concurrency failure occurs before commit and changes no formal state.

If interruption occurs during commit, recovery inspects the transaction journal.
It must either complete the same prepared transaction or confirm rollback before
accepting another authority transaction. Partial generations, partial events, or
a mixed current index must never become visible.

Deterministic control validation reports are retained with a successful receipt.
Rejected commands retain the required operational command-attempt audit entry,
but they do not receive a formal publication receipt and do not enter the
authority-event journal.

Recovery verifies the exact raw request artifacts, contiguous audit sequence,
registered content digests, and binary root chain before accepting another
command. A gap or mismatch fails closed and does not alter the last valid
scientific authority state.

## 12. Acceptance criteria

Implementation must prove:

1. An active method can be retired only from the exact method, catalog, and
   control-head state authorized by the user.
2. Retirement publishes lifecycle-only replacement method and catalog
   generations while preserving method identity, version, definition digest,
   scientific content, and downstream scientific records.
3. A retired method cannot be launched in ordinary Phase 3 or Phase 4 work.
4. A retired method can be reactivated by a new exact command when other
   prerequisites remain valid.
5. A recommendation from any role cannot retire or reactivate a method.
6. A formal generation can be withdrawn only by exact generation identity,
   content digest, derived-state digest, and control head.
7. Withdrawal leaves immutable bytes and provenance unchanged, removes current
   eligibility, records dependent impacts, and never restores history as current.
8. A withdrawn generation cannot be reactivated; correction requires a new
   generation from the applicable user-started research run.
9. Neither command creates a run ID, run workspace, manifest, role profile,
   handoff, or role execution.
10. A stale command returns `409 CONFLICT` and produces no generation, event, or
    index change.
11. Repeating an identical committed command returns the same receipt without
    duplicating generations or events.
12. Failure or interruption cannot expose a partial lifecycle or withdrawal
    transaction.
13. A role or agent recommendation cannot authorize withdrawal or any other
    formal control command.
14. Cancellation is accepted only from the four legal pre-submission states and
    closes the submission gate before cooperative stopping begins.
15. A cancellation-submission race has one compare-and-swap winner and never
    modifies formal project state.
16. Every remote operation is checked against an active grant at acceptance and
    immediately before commit.
17. Expired, revoked, wrong-project, wrong-action, or wrong-target delegation
    fails closed.
18. Each typed action descriptor rejects fields belonging to another action
    branch.
19. Every rejected command produces a schema-valid stable error and operational audit entry, with identical results through Web and remote clients.
20. Schema-invalid and unauthenticated requests remain traceable to their exact raw bytes without a fabricated command, target, or user identity.
21. Replaying accepted and rejected audit events reproduces the same chain root, and every accepted pre-commit event resolves to its exact durable effect.
22. A correction command is accepted only from `failed`, `rejected`, or
    `correction_authorized` with at least one correctable finding, and its
    permitted scope never exceeds the target closure's declared outputs.
23. A correction appends new validation-attempt, correction-closure, and
    submission-attempt records; no sealed output, closure, or base submission
    is rewritten.
24. When the correction bounds are spent, further correction commands are
    rejected and the run resolves to `correction_exhausted` with the findings
    preserved.
