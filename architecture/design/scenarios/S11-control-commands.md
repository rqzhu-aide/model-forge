# S11: User-Controlled Lifecycle

## Purpose

Verify that method activation, retirement, and reactivation are explicit
user-authorized control transactions rather than research runs.

## Initial state

- Method `method.overlap_stabilized_score` is active at one exact current
  `method_record` generation.
- The current `method_catalog` identifies that generation as active.
- Current Phase 3 and Phase 4 records exist for the method.
- The UI has resolved current-index generation `generation.current_index.040`,
  event sequence 40, and the corresponding index and event-root digests.

## Retirement and reactivation

The user submits a `MethodLifecycleCommand` that names the exact method-record and
catalog generations, the exact control head, expected state `active`, target state
`retired`, and a reason.

The service validates the command and atomically publishes lifecycle-only
replacement generations for the method record and catalog. Their `published` and
`superseded` authority events, rebuilt projections, current index, and receipt
commit together. The method identity, version, definition digest, and scientific
content do not change. Existing Phase 3 and Phase 4 records remain formal and
unchanged, but ordinary launches for the retired method become ineligible.

Repeating the same idempotency key and command digest returns the same receipt.
A reactivation command based on the earlier control head returns `409 CONFLICT`
and changes nothing. After refresh, a new exact command may change `retired` to
`active` and restore ordinary launch eligibility when all other prerequisites are
satisfied. Activation from `proposed` uses the same sealed transaction (D-3).

## Delegated remote control

The researcher issues an immutable delegation that covers this project and the
`retire_method` action for `method.overlap_stabilized_score`. The remote operator
submits the same typed lifecycle command used by the Web UI. The service records
an acceptance check, rechecks the exact project, action, method target, time
window, and revocation state immediately before commit, and then commits the
retirement transaction. The pre-commit audit event binds the resulting
publication receipt ID and self-digest.

A command for a different method is denied with `DELEGATION_NOT_ACTIVE`. It
returns the same `CommandError` through Web and remote clients, appends a rejected
command-attempt audit event, and changes no method, catalog, authority event, or
current index.

If the researcher revokes the grant before the pre-commit check, the second check
fails closed with `DELEGATION_NOT_ACTIVE`. The rejection records the exact grant
and failed revocation check, and no formal change occurs. A role recommendation
cannot substitute for either the user command or the active delegation.

## Acceptance checks

- The command validates only against its schema and the `ControlCommand` union.
- The lifecycle command permits only `active` to `retired`, `retired` to
  `active`, and `proposed` to `active`.
- A no-op lifecycle command is rejected before any formal change.
- Every transaction compares the exact current-index generation and digest,
  event sequence and root, target generations, and target state before commit.
- Any stale basis returns `409 CONFLICT` without a generation, event, receipt, or
  index change.
- Retirement preserves downstream scientific records but disables ordinary
  Phase 3 and Phase 4 launches for that method.
- The command creates no run ID, run workspace, run manifest, handoff, role
  profile, or role execution.
- The command launches no later phase.
- A delegated lifecycle command commits only when the exact grant remains active
  for the project, action, and method at both acceptance and pre-commit.
- A wrong-target remote command and a grant revoked between the two checks both
  return `DELEGATION_NOT_ACTIVE`, create a tamper-evident rejection record, and
  change no formal state.
- Each accepted pre-commit audit event binds the exact durable RunState event or
  publication receipt by identity and digest.
- Web and remote clients receive the same stable error and smallest correction.
- No role output or recommendation authorizes a lifecycle command.
