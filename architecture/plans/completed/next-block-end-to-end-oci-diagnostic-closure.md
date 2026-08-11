# Next Work Block: End-to-End OCI Diagnostic Closure

Status: Deferred optional hardening plan. Not a Version 1 prerequisite.

Version 1 replacement:

- [Trusted Local Hermes Execution Closure](../next-block-local-hermes-execution-closure.md)

Retain this file as a future isolation reference. Do not implement it as the
current work order.

Baseline: commit `009a50a`, audited 2026-08-04.

Parent gate:

- [Headless Hermes Runtime Closure](next-block-headless-hermes-runtime-closure.md)

Related records:

- [Hermes diagnostic design](revised-diagnostic-lane-plan.md)
- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md)
- [Operational Completion Plan](operational-completion-plan.md)
- [ADR-004: Role Isolation and Context Snapshots](../../decisions/ADR-004-role-isolation-and-context-snapshots.md)
- [Per-project Hermes memory decision](../../decisions/ADR-011-per-project-memory-model.md)

## 1. Target outcome

Deliver one real Linux path with this exact control flow:

```text
method-hub diag start
  -> diagnostic composition root
  -> DiagnosticService
  -> OciExecutor
  -> one rootless OCI container
  -> one Hermes one-shot invocation
  -> fixed diagnostic output validation
  -> durable terminal record
```

The invocation uses one exact project-role profile, one sealed synthetic task,
and one diagnostic workspace. A rejected request launches no container. An
accepted idempotency key launches at most one container. Cancellation, timeout,
lease loss, and restart recovery control that same container and never create a
replacement.

This is still a non-publishing diagnostic. It must not start a scientific run,
write formal research storage, advance a phase, or make a scientific result
current.

The block is complete only when the integrated public path passes the full
Linux evidence matrix without skips. Unit tests and hand-built Podman commands
do not close the gate.

## 2. Why this is the next block

Commit `009a50a` adds useful foundations:

- Hermes can execute inside rootless Podman on the tested Linux host;
- the image can use a read-only root with dropped capabilities;
- the OCI executor emits CPU, memory, and process-limit options, but
  exhaustion enforcement has not been verified;
- diagnostic state, profile locks, fencing tokens, runtime snapshots, output
  contracts, and an OCI executor now exist; and
- output can be checked independently of the Hermes process exit code.

The H0-B completion claim is not accepted because the demonstrated pieces are
not yet one safe operational path:

- the diagnostic CLI still constructs the Bubblewrap one-shot executor;
- the scientific `oci` setting constructs Bubblewrap inside the scientific
  coordinator, while the OCI executor is not composed into diagnostics;
- the service enters `running` before executor callbacks begin, producing an
  invalid lifecycle transition on a real invocation;
- the OCI path mounts the complete host Hermes home read-write instead of one
  isolated runtime profile;
- successful read-only and ephemeral profiles can be promoted;
- the persisted identity is a placeholder or launcher PID rather than the
  exact container identity;
- cancellation, reconciliation, lease renewal, and promotion are not one
  fenced control protocol;
- provider allowlist mode currently means unrestricted host networking;
- output and retained-state bounds are incomplete; and
- the committed evidence primarily tests hand-built commands or components,
  not `CLI -> service -> OCI executor -> Hermes`.

These gaps can cause incorrect execution, cross-profile writes, stale-owner
promotion, unverifiable cancellation, or a misleading success report. Closing
them is more urgent than adding UI features or enabling scientific roles.

## 3. Fixed boundaries

The programmer may change internal classes and module boundaries, but the
following rules are fixed.

### 3.1 Separate authority

- Diagnostic execution has no publication, promotion, phase-transition,
  method-lifecycle, or role-chaining authority.
- The scientific `RunCoordinator` cannot select the diagnostic OCI executor.
- The diagnostic feature flag blocks new starts when disabled. Read-only
  inspection, cancellation, reconciliation, and ownership-checked cleanup
  remain available for existing invocations.
- No scientific executor is enabled merely because the diagnostic gate passes.

### 3.2 Exact request basis

The accepted request resolves to one immutable diagnostic manifest containing:

- project identifier and role;
- selected profile identity and revision;
- memory policy and policy version;
- exact SOUL, configuration, and declared skill digests;
- task-brief path and digest;
- diagnostic workspace root;
- model and provider selection;
- network policy;
- runtime image reference and digest;
- resource limits; and
- idempotency key.

User-controlled workspace, task, output, and evidence paths are not trusted
merely because they exist. Each must resolve inside its declared diagnostic
root, and a formal project-storage path cannot be a writable workspace.
Registered images, profiles, and runtime resources resolve separately through
contained trusted roots recorded in the manifest.

### 3.3 Controlled OCI operation

Use a create, acknowledge, then start handshake:

1. validate the request and acquire current ownership;
2. create the container without starting Hermes;
3. inspect and persist the exact container ID, immutable image identity, and
   invocation marker;
4. verify the persisted record still owns the current lease and token; and
5. start that container exactly once.

Do not acknowledge a placeholder. Do not use a Podman client PID as the
durable execution identity.

### 3.4 Formal records remain unchanged

Before and after every real evidence scenario, construct a canonical logical
inventory of authority roots, current indexes, formal generations, scientific
artifacts, submissions, receipts, and their content digests. Those scientific
inventories must be identical. Exclude diagnostic-only tables and physical
SQLite details such as page order and WAL state. Diagnostic logs, profiles,
snapshots, and evidence live in a separate bounded namespace.

## 4. Implementation sequence

Complete these slices in order. Later implementation may be explored early,
but no later exit can be accepted before its dependencies pass.

### Slice 1: composition and fail-closed entry points

Goal: make the real public diagnostic path unambiguous.

Required work:

- Add one diagnostic composition root that constructs `DiagnosticStore`, the
  project and runtime profile managers, `DiagnosticService`, and `OciExecutor`.
- Make `diag start`, `cancel`, and `reconcile` use that same composition.
- Enforce `diagnostic_enabled` before any new start or configuration change.
  Do not block status, logs, cancellation, reconciliation, or safe cleanup for
  an invocation that already exists.
- Remove or reject the unsafe scientific `executor_kind="oci"` mapping until
  WP1 explicitly integrates a production scientific executor.
- Make unsupported or missing runtime configuration fail before container
  creation.
- Add one integration test proving the call chain reaches a real observer and
  does not enter scientific orchestration.

Acceptance:

- a disabled, malformed, or blocked request creates zero containers;
- a valid request reaches `DiagnosticService -> OciExecutor`; and
- no scientific command can reach this executor.

### Slice 2: manifest-bound preflight and exact profile construction

Goal: bind execution to the exact project-role resources the user selected.

Required work:

- Validate the profile manifest before acquiring launch authority.
- Provision a new canonical project-role profile atomically with rollback.
  It must not inherit base-profile memories, sessions, state databases, or
  runtime caches. Install exactly the manifest-declared skills and derive the
  default memory policy from the role, including an ephemeral outside reviewer.
- Resolve ownership, maintenance, and retirement from the profile manifest,
  never a filename prefix. Record SHA-256 evidence and apply symlink-aware path
  containment to every copied or mounted resource.
- Derive the profile and workspace from registered project configuration rather
  than accepting unrelated arbitrary paths.
- Fail closed on missing or mismatched profile, role, SOUL, configuration,
  skill, brief, provider, image, or policy digest.
- Build an invocation-specific synthetic Hermes home containing only the exact
  selected runtime profile and the minimum global files Hermes requires.
- Put the Hermes executable and dependencies in the pinned runtime image. Do
  not mount the host installation tree or complete host Hermes home.
- Fail closed when the configured image digest is empty, unavailable, or does
  not match. A local image ID is acceptable only when that exact immutable ID
  is sealed in the manifest.
- Mount identity, configuration, declared skills, and the task brief read-only.
  Mount only the diagnostic workspace and policy-allowed runtime state
  read-write.
- Make sibling profiles, undeclared skills, host-local files, and formal Method
  Hub storage absent from the container.

Acceptance:

- the selected role sees exactly its declared resources;
- write attempts outside the two declared writable roots fail; and
- cross-profile and formal-storage canaries cannot be read or modified.

### Slice 3: one lifecycle owner and durable container identity

Goal: make every state transition describe the real external execution.

Required work:

- Assign lifecycle transitions to one owner. The service must not pre-mark
  states that the executor observer will later repeat.
- Persist launch intent before `podman create` and persist the inspected
  container identity before `podman start`.
- Store container ID, stable name, image digest, invocation labels, creation
  time, and runtime identity fields needed to reject identity reuse.
- Disable automatic removal. Retain an exited container until its logs and
  post-exit state are inspected, durable closure is recorded, and the current
  owner performs idempotent cleanup.
- Make idempotent retries return or adopt the same invocation. They must not
  create another container.
- Make restart reconciliation inspect the stored container identity and
  invocation marker, never PID presence alone.
- Make every state mutation atomically require the current fencing token and an
  unexpired lease.
- Every path that can write a profile, including diagnostics, development
  Kanban, memory commands, maintenance, and future scientific execution, must
  use the same durable profile mutex or a physically disjoint profile.
- Renew the lease from durable heartbeats. On lease loss, the stale worker must
  stop promotion and all durable mutations. A recovery owner may terminate or
  close the exact verified container only after obtaining a new fencing token.
  Ownership cannot transfer while the prior runtime may still write.

Acceptance:

- two coordinators still create at most one container;
- stale tokens cannot update state or release a lock; and
- restart recovery never relaunches work.

### Slice 4: memory-policy enforcement and safe promotion

Goal: make runtime memory behavior match the accepted policy.

Required work:

- `persistent`: clone the canonical snapshot, run in the clone, and promote
  only the allowed mutable profile state after validated success, verified
  quiescence, and a final current token and lease check.
- `read_only`: expose the selected memory snapshot without permitting a
  canonical change. Discard all runtime mutations.
- `ephemeral`: begin without prior memories, sessions, or state and discard the
  complete runtime profile after closure.
- Never promote failed, cancelled, timed-out, lease-lost, conflicted, or
  unresolved work.
- Capture memory-before from the immutable input snapshot. Whenever a launched
  invocation reaches a readable closure, seal a runtime-after snapshot,
  accessible-file inventory, and digests, including failed, cancelled,
  timed-out, lease-lost, and unresolved outcomes. Use runtime-after state for
  promotion only after validated persistent success.
- Make profile replacement atomic and crash-reconcilable. A stale owner cannot
  promote, prune, quarantine, or clean up another invocation.
- Keep active and unresolved snapshots until ownership is resolved. Apply
  retention only to safely closed records.
- Make inspect, export, clear, and policy changes explicit audited commands,
  not side effects of a run.

Acceptance:

- two persistent runs demonstrate intended continuity;
- read-only and ephemeral runs leave canonical state unchanged; and
- failure, cancellation, timeout, and lease loss never promote state.

### Slice 5: bounded supervision, cancellation, and reconciliation

Goal: ensure the process tree and all observable output reach a verified end.

Required work:

- Drain stdout and stderr continuously into bounded ring buffers. Bounds must
  apply across the whole invocation, including newline-free floods.
- Enforce CPU, memory, process, open-file, file-size, file-count, workspace,
  log, snapshot, and aggregate retained-evidence limits.
- Record `cancellation_requested`, await graceful stop, escalate to forced
  termination when needed, reap and remove the container, drain final output,
  and verify write quiescence before recording `cancelled`.
- Apply the same verified termination protocol to timeout and lease loss.
- Reconcile every launch boundary: before create, after create before durable
  acknowledgement, after acknowledgement before start, while running, during
  termination, and after exit before closure.
- Never mark a terminal state merely because a cancellation task was queued.

Acceptance:

- child and grandchild writers stop before terminal closure;
- repeated cancel and reconcile operations are idempotent; and
- no scenario leaves an unowned live container or blocked output pipe.

### Slice 6: provider-only network and secret-safe delivery

Goal: allow the selected model provider without granting ambient network or
credential access.

Required work:

- Replace host networking with an enforceable provider-only egress boundary,
  such as a dedicated proxy or equivalent rootless network control.
- Deny arbitrary Internet, host-loopback, LAN, metadata-service, and undeclared
  provider endpoints.
- Deliver the minimum credential through an ephemeral secret mechanism. The
  value must not appear in command arguments, OCI inspection, environment
  dumps, logs, crash diagnostics, database records, snapshots, or evidence.
- Redaction is defense in depth. It does not substitute for secret-safe
  delivery.
- Bind provider identity and network policy to the diagnostic manifest.

Acceptance:

- the configured provider call succeeds;
- arbitrary Internet and host-local calls fail; and
- a canary credential scan is clean across every required surface.

### Slice 7: outcome validation and evidence package

Goal: make a terminal result scientifically and operationally interpretable.

Required work:

- Validate the fixed diagnostic result, brief digest, profile identity, file
  inventory, and usage report independently of process exit code.
- Treat exit-zero internal failure, missing output, malformed output, wrong
  basis, inconsistent usage, or undeclared files as failure.
- Preserve bounded raw diagnostics for failed and unresolved invocations.
- Produce a machine-readable evidence manifest tied to the exact source commit,
  runtime image digest, Hermes version, Podman version, host facts, test case,
  invocation ID, and artifact digests.
- Retain the commands and logs needed to reproduce each result, with secrets
  excluded.
- Reclassify partial host observations separately from integrated gate evidence.

Acceptance:

- every gate claim points to retained evidence from the public path; and
- no passing test accepts either success or failure as equivalent outcomes.

## 5. Required real Linux evidence

Run these cases through the public headless path and the production OCI
executor. A skipped case leaves the gate open.

1. preflight rejection, feature-disabled rejection, and malformed manifest,
   each with zero containers created;
2. one accepted request, repeated idempotent submission, and two-coordinator
   race, with exactly one container;
3. exact profile, exact skills, read-only identity, declared writable roots,
   cross-profile denial, and formal-storage denial;
4. persistent continuity, read-only discard, fresh reviewer state, failed-run
   quarantine, and lease-lost non-promotion;
5. cancellation and timeout at every launch boundary, including descendant
   writers and forced termination;
6. restart, stale-token, expired-lease, identity-mismatch, and host-reboot
   simulations with no relaunch;
7. stdout, stderr, newline-free output, CPU, memory, process, open-file,
   file-size, file-count, workspace, and retained-evidence exhaustion;
8. permitted provider call plus denied arbitrary Internet, host-local, LAN, and
   metadata-service calls;
9. canary-secret scan of command line, environment, OCI inspection, logs,
   files, database, crash output, snapshots, and evidence;
10. exit-zero internal failure, missing or malformed fixed output, wrong brief
    or profile identity, inconsistent usage, and undeclared output;
11. active, unresolved, and closed retention and cleanup behavior; and
12. identical canonical logical inventories of authority roots, current
    indexes, formal generations, scientific artifacts, submissions, receipts,
    and content digests before and after every scenario, excluding diagnostic
    tables and physical SQLite representation.

The parent plan's complete 27-case matrix remains authoritative. This grouped
list is an implementation work order, not a reduced evidence standard.

## 6. Deliverables

- one separately gated OCI diagnostic composition root;
- one manifest-bound preflight and exact synthetic profile builder;
- one pinned runtime image that contains Hermes without mounting the host
  Hermes installation;
- one durable create, acknowledge, then start protocol using container identity;
- one token- and lease-guarded lifecycle and promotion protocol;
- enforced persistent, read-only, and ephemeral memory behavior;
- bounded supervision, awaited cancellation, and restart reconciliation;
- provider-only network control and secret-safe credential delivery;
- fixed-output and usage validation;
- a portable unit and component suite;
- a complete real Linux integration suite and machine-readable evidence bundle;
  and
- concise operator notes for preflight, start, status, logs, cancel, reconcile,
  memory operations, and evidence inspection.

Likely touch points include application settings and bootstrap, diagnostic CLI,
service, store and runtime-profile management, the OCI executor and image,
diagnostic contracts and schemas, migrations, integration tests, and evidence
indexing. The programmer may reorganize these internals if the fixed boundaries
and public behavior remain unchanged.

## 7. Exit gate

This corrective block closes only when all statements are true:

- [ ] the public diagnostic path uses `DiagnosticService -> OciExecutor`;
- [ ] scientific execution cannot select or reach the diagnostic executor;
- [ ] rejected requests create zero containers and accepted idempotency keys
      create at most one;
- [ ] one exact synthetic profile and only declared resources are visible;
- [ ] canonical profiles and formal scientific storage are never directly
      writable by Hermes;
- [ ] real container and image identity are persisted before Hermes starts;
- [ ] lifecycle, lock, promotion, cleanup, and reconciliation operations are
      atomically fenced by a current token and lease;
- [ ] persistent, read-only, and ephemeral memory policies behave as declared;
- [ ] cancellation, timeout, and lease loss are awaited, escalated, reaped,
      and verified quiescent;
- [ ] output, resources, workspace, profile state, logs, and evidence are
      bounded;
- [ ] only the configured provider is reachable and secrets are absent from
      all inspected surfaces;
- [ ] outcome and usage are validated independently of process exit code;
- [ ] formal scientific state is unchanged;
- [ ] the portable suite passes; and
- [ ] every required real Linux case passes without skips through the public
      path, with retained evidence tied to exact source and image digests.

Partial results remain open. Record the unmet criterion and retain the useful
observation without relabeling it as H0-B completion.

## 8. Deferred work and the next accepted step

This block does not add:

- the user-facing diagnostic Web interface;
- scientific Phase 1 through Phase 5 execution;
- reviewed-basis closure;
- phase-specific scientific adapters or pilots;
- remote operation;
- backup and restore packaging; or
- Windows execution support.

After this exit gate passes, the next bounded block is the local diagnostic
status, logs, cancellation, profile-memory, and evidence interface. That UI
work completes the remaining Phase 0 usability evidence. WP0 reviewed-basis
closure follows before any real scientific pilot.
