# Run Harness

## 1. Purpose

The run harness is the execution and publication boundary of the research system. It converts an explicit user command into an isolated, reproducible research operation and, when valid, into formal project records.

The harness is not an agent prompt and is not a generic workflow script. It is a state machine with permission boundaries, frozen inputs, validation, optimistic concurrency, atomic publication, and recovery behavior.

## 2. Run lifecycle

### 2.1 Primary states

```text
created
  -> preparing
  -> prepared
  -> running
  -> submitted
  -> validating
  -> promoting
  -> published
```

A cancellation request introduces a guarded cooperative path before immutable
submission:

```text
created, preparing, prepared, or running
  -> cancellation_requested
  -> cancelled
```

`cancellation_requested` is a durable execution-control state. It closes the
submission gate immediately, but allows an active tool call or role step to stop
at its next safe boundary. It is not a formal publication state.

### 2.2 Non-published terminal states

```text
cancellation_requested -> cancelled
preparing, prepared, or running -> failed
validating -> rejected
validating or promoting -> conflicted
validating or promoting -> failed after unrecoverable operational failure
```

An interrupted `validating` or `promoting` run is not immediately terminal. Recovery examines durable checkpoints and either resumes idempotently or resolves the run to `failed`, `rejected`, `conflicted`, or `published` without changing scientific content.

### 2.3 State meanings

| State | Meaning | Formal records changed? |
|---|---|---|
| `created` | Run ID and command have been accepted | No |
| `preparing` | Inputs, role plan, permissions, and expected publication targets are being resolved | No |
| `prepared` | Manifest is frozen and workspace is ready | No |
| `running` | Roles are executing within the run workspace | No |
| `cancellation_requested` | An authenticated cancellation command closed submission and new-work gates; active work is stopping cooperatively | No |
| `submitted` | Lead submission is immutable and ready for validation | No |
| `validating` | Validators are checking the submitted package and current publication basis | No |
| `promoting` | A durable, atomic publication transaction is in progress | Not visible until commit |
| `published` | Formal generations, authority events, derived record state, and the current index were committed with a receipt | Yes |
| `cancelled` | User cancelled before immutable submission | No |
| `failed` | An unrecoverable execution, validation, or promotion error ended the operation without a formal commit | No |
| `rejected` | Submission did not satisfy publication requirements | No |
| `conflicted` | Submission is valid but its publication assumptions no longer match current state | No |

Scientific outcomes such as contradicted or inconclusive are not run failures.

## 3. Transition contract

| Transition | Trigger | Required checks | Durable result |
|---|---|---|---|
| Command -> `created` | User or delegated operator | Authentication, authorization, idempotency | Run command and run ID |
| `created` -> `preparing` | Harness | Valid phase and command shape | Preparation journal entry |
| `preparing` -> `prepared` | Harness | Inputs resolvable, scope resolved, target generation known, workspace permissions applied | Immutable manifest and input inventory |
| `prepared` -> `running` | Harness under the original launch command | Manifest digest verified, role environment available | Start event |
| `running` -> `submitted` | Harness after lead closure | Every selected role-plan step has one successful validated closure, all required outputs resolve to accepted artifacts, and the lead closure is final | Immutable `RunSubmission` and submission-bound state event |
| `submitted` -> `validating` | Harness | Submission digest verified | Validation start event |
| `validating` -> `promoting` | Validator suite | All required validation passes and publication preconditions hold | Signed validation report and transaction plan |
| `promoting` -> `published` | Harness | Atomic commit succeeds | New generations, authority events, derived projections, current index, and publication receipt |
| Eligible pre-submission state -> `cancellation_requested` | User or delegated operator | Authenticated command, active delegation when remote, idempotency, exact run-head compare-and-swap | Durable cancellation fence and request event |
| `cancellation_requested` -> `cancelled` | Harness | No role step or tool process remains active; no immutable submission exists | Terminal cancellation event; diagnostics preserved |
| Phase-defined failure, rejection, or conflict source -> corresponding terminal state | Executor, validator, or concurrency check | Legal source state, reason code, and evidence | Terminal event; current records unchanged |

Only the harness changes run state. Actors request transitions by emitting commands or submissions.

## 4. User command and preparation

### 4.1 User control

The user selects every run and rerun. The command must state:

- Phase.
- Exact phase-contract version and digest, selected mode, and contract-defined `choice_values`.
- Method, instructions, search scope, and selected history through their exact phase-specific choice IDs.
- Global context policy, including whether selected history is enabled.
- Optional resource constraints.

UI defaults are conveniences. The backend receives the resolved values, not an instruction to infer them later.

An authorized remote operator may issue the same command on the user's behalf. The command records both the user authority and operating identity.

Remote operation requires an active `DelegationGrant` whose project, action, and
target scopes cover the exact command. The command service checks the grant at
acceptance and again immediately before committing a run creation, cancellation
fence, or formal control transaction. Expired or revoked grants fail closed.

### 4.2 Input resolution

During `preparing`, the harness:

1. Resolves the phase contract named by the command and verifies its exact version and digest before interpreting any choice.
2. Resolves required current formal records.
3. Resolves the selected method to an exact method identity.
4. Resolves optional user-selected context.
5. Constructs each mode-scoped prepared context only from its declared formal inputs and user choices, then freezes its artifact digest.
6. Binds every contract-selected formal input and prepared context to its exact executable-contract ID, including the source input and user-choice IDs for each prepared context.
7. Classifies each input as a hard or contextual dependency.
8. Records immutable generation IDs and digests.
9. Resolves every mode-scoped publication binding from contract output IDs to an append or current-slot operation, target record type and logical slot, named bundle components, and expected prior generation.
10. Records expected current generation IDs for every publication target.
11. Builds the exact stage plan, including stage IDs, execution groups, serial or parallel behavior, and role-specific profile assignments.
12. Binds every expected artifact to one exact run-local output obligation in the executable contract.
13. Freezes each role's read allowlist and role-specific write root, including profile, skill, tool, knowledge-resource, and output-contract digests.
14. Writes and seals the run manifest.

Preparation fails if a required current record is absent, incompatible, withdrawn, or not eligible under the phase contract. The error response must identify the missing scientific prerequisite and the user actions that could resolve it.

### 4.3 Input materialization

The run manifest is the authoritative run recipe. Its `role_plan` seals stage order, assignments, declared input and output IDs, profiles, and write roots before execution. It does not claim future prepared-context, handoff, produced-artifact, access-ledger, start-time, or closure digests.

Inputs may be materialized as read-only copies, content-addressed mounts, or verified references. In every case:

- The role sees the exact formal inputs and harness-prepared contexts named in the manifest.
- The role can resolve only the inputs on its frozen read allowlist.
- The resolver verifies each digest before use.
- Every contract-selected input carries `contract_binding_id`, every expected output carries `contract_output_id`, and every prepared context records its exact source inputs and user choices.
- A later change to `current` cannot alter the run.
- Materialization details do not change scientific identity.

## 5. Recommended run workspace

```text
runs/{phase_id}/{run_id}/
  command.json
  manifest.json
  inputs/
    inventory.json
    materialized/
  roles/
    {sequence}-{role_id}/
      prepared-context.json
      invocation-start.json
      invocation-closure.json
  handoffs/
    {sequence}-{producer}-to-{consumer}.json
  artifacts/
    primary/
    structured/
    compact/
  submission/
    submission.json
  validation/
    report.json
  publication/
    plan.json
    receipt.json
  events.jsonl
```

This is a logical layout. A backend may store it differently if the same identities, permissions, and atomicity are preserved.

### 5.1 Read and write permissions

- Each role may read only the actual inputs and accepted upstream artifacts bound by its validated `RoleInvocationStart`.
- Each role may write every artifact, including its handoff and proposed publication components, only to its assigned role-specific workspace while active.
- A completed role workspace becomes read-only before its handoff is accepted.
- After step closure, the harness verifies the declared schemas, identities, digests, and output-contract bindings. It then copies or content-addresses accepted artifacts into harness-owned `handoffs/`, `artifacts/`, or `submission/` locations.
- Later roles receive explicit read access to the accepted harness-owned references named in their allowlists.
- The lead prepares proposed submission components under its own role root. The harness assembles the immutable submission and does not permit the lead to rewrite primary artifacts produced by other roles.
- Validators write only under `validation/`.
- The publisher writes only the transaction plan, receipt, and formal storage targets.

Permission discipline runs through the capability broker defined in the role-context contract. A role process receives no project-store or formal-store credentials. Because Hermes inherits the researcher's host permissions, Method Hub supplies only declared inputs and paths; it does not deny path, link, subprocess, network, secret, or direct-storage access at the operating-system level. OS-level denial is deferred optional hardening (ADR-012), and prompt wording alone is not an access boundary.

## 6. Role execution and communication

The phase contract defines stage order, execution groups, and visibility. The sealed run manifest resolves that contract into a frozen recipe. Immediately before one role starts, the harness creates an immutable `PreparedRoleContext` and `RoleInvocationStart`. The start copies and hashes the exact manifest role-plan entry and binds the resolved profile, actual input artifacts, expected output contracts and paths, capability grants, the pinned trusted-local executor binding (executor profile, Hermes executable identity, working roots, process-control policy), write root, and start time. It contains no future output or terminal-status claim.

At termination, the harness creates an immutable `RoleInvocationClosure` that binds the start digest, terminal status, final `RoleContextSnapshot`, access-ledger head, verified outputs, accepted handoffs, and any failure or cancellation information. Roles in one parallel execution group receive the same frozen group-start basis and cannot read one another's in-group outputs. A later stage may start only after every required upstream closure is successful and each consumed artifact exactly matches the accepted output named by that closure.

At the end of a role step, the role submits:

- Produced artifacts and digests.
- Structured handoff.
- Scientific statements addressed.
- Changes from the incoming current record.
- Assumptions and limitations.
- Open issues and their severity.
- Questions for the next role.

The harness validates the handoff structure and digest under the producer's closed role root, then materializes or references the accepted handoff under harness-owned `handoffs/` before starting the next role. It does not validate that the scientific conclusion is true.

Conversational transcripts may be retained as diagnostic run artifacts, but later roles and future runs must not depend on unindexed transcript content. Scientifically material information belongs in the handoff or structured record.

## 7. Submission

The lead submission closes the research operation for validation. It contains:

- Proposed formal records.
- Required primary artifacts.
- Structured scientific statements and evidence links.
- Alignment, attention, and outcome assessments made on the frozen run basis.
- Material disagreements and issue dispositions.
- Compact user decision brief.
- Change summary relative to the prior current record.
- Proposed downstream impact and authority-event declarations.

All proposed components originate under declared role roots. The harness dereferences every start and closure, verifies that the ordered successful closure chain exactly covers the selected manifest role plan, verifies every required accepted output, and requires the final research-lead closure. It then assembles the immutable `RunSubmission`, which binds the manifest, complete closure chain, lead closure, and submitted artifacts under harness-owned `submission/`. The `running` to `submitted` event cites this exact submission artifact and digest. Submission makes that package immutable. A rejected submission is corrected through a new run or an explicitly defined resubmission operation that creates a new submission generation. Validators never edit scientific content in place.

## 8. Validation pipeline

Validation is ordered from least expensive to most contextual.

### 8.1 Structural validation

Checks:

- Required files and objects exist.
- Schemas and enumerations are valid.
- IDs are well formed and unique in scope.
- Digests, media types, and sizes match.
- No path escapes the run namespace.

### 8.2 Identity and provenance validation

Checks:

- Every frozen input resolves to the recorded generation and digest.
- Method-bound outputs contain the exact selected method identity.
- Evidence references resolve to immutable artifacts.
- Producing actor and source run are recorded.
- Review material uses the declared frozen snapshot.

### 8.3 Phase-semantic validation

Checks obligations defined in `phases/`, including:

- Required role order and handoffs.
- Required complete or cumulative output form.
- Required statement, evidence, uncertainty, and decision fields.
- Allowed publication targets for the selected mode.
- Complete, unambiguous publication bindings from required contract outputs to their append or current-slot operations.
- Phase-specific dependency and downstream impact rules.

This validation checks that the scientific judgment is explicitly represented. It does not replace that judgment.

### 8.4 Cross-record consistency validation

Checks:

- Cited statement and evidence IDs exist.
- Declared alignments agree with recorded hard-dependency digests.
- Compact views do not reverse or omit material qualifications from structured records.
- The lead records a disposition for every blocking role issue.
- The proposed change summary agrees with the prior and proposed generations.

### 8.5 Publication-safety validation

Checks:

- Expected current target generations still match.
- Required hard dependencies remain current or satisfy phase-defined compatibility policy.
- The publication plan has no partial or conflicting target writes.
- The publisher has exclusive transaction authority.

Failure in the first four groups produces `rejected`. A stale publication basis produces `conflicted`, because the submitted work may remain scientifically meaningful.

## 9. Atomic publication

### 9.1 Publication algorithm

The publisher must perform the following logical transaction:

1. Acquire a project publication lock or equivalent serializable transaction.
2. Re-read current target generations and hard-dependency state.
3. Compare them with the submission's expected generations.
4. If they differ outside an explicitly allowed merge policy, record `conflicted` and stop.
5. Resolve the sealed publication bindings and reject any missing, ambiguous, or undeclared source-to-target operation.
6. Construct every new immutable formal content generation in a private staging namespace from only the outputs and bundle components named by those bindings. Each generation records frozen `authority_at_creation` and never stores mutable current position or eligibility.
7. Verify staged object digests and references.
8. Construct append-only authority events for publication, supersession, dependency impact, alignment, attention, and evidence-eligibility changes. A research-run promotion must not construct withdrawal events; only a validated `FormalGenerationWithdrawalCommand` transaction may do so.
9. Replay the proposed events over the prior committed state to prepare complete derived record-state projections and one new current index.
10. Commit the staged generations, authority events, derived projections, current index, and publication receipt as one atomic operation.
11. Mark the run `published` only after the committed state can be read and verified.

The source run artifacts remain unchanged. A formal generation may contain verified copies, content-addressed references, or a package of selected run outputs. Later authority or dependency changes append events and rebuild projections; they never rewrite a committed content generation or change its digest.

The publication receipt names the committed event sequence range and event-root digest, categorizes each event exactly once as a record, cumulative-object, or derived-state-only change, and records every derived projection digest plus the new current-index generation and digest. Recovery verifies this set before another publication begins.

### 9.2 Phase-specific publication policies

The common transaction calls a phase policy:

- P1 merges unique literature entries and replaces the current synthesis.
- P2 updates the catalog and selected method lineages according to full or focused scope.
- P3 installs a complete new current theory generation for one method.
- P4 appends new immutable evidence and atomically replaces the current evidence index, empirical synthesis, implementation record, and phase decision for the selected method.
- P5 installs a complete new manuscript generation tied to exact upstream inputs.

The policy must be deterministic for a fixed prior state and validated submission.

### 9.3 No additional approval state

When the user started the run and the submitted result passes validation without conflict, the harness publishes it. The system does not insert a separate generic approval action. The resulting decision brief informs the user's next research decision.

## 10. Concurrency and conflicts

Two runs may execute concurrently when their phase contracts allow it. Publication uses optimistic concurrency:

- Each run records expected target generations during preparation.
- A publisher compares those expectations immediately before commit.
- Disjoint targets may publish independently.
- Concurrent cumulative updates may use only a phase-defined deterministic merge policy.
- Replacement records for the same logical target cannot use last-writer-wins.

Version 1 does not merge concurrent publications to the same formal target. If a target's expected generation changed, the later publication becomes `conflicted`. Runs affecting disjoint method targets may publish independently. A deterministic same-target merge policy requires a later architecture decision and phase-specific tests.

The global authority journal still has one total order. When two validated
research runs have disjoint publication targets and unchanged hard dependencies,
the publisher serializes their commits. The second transaction may append to the
new global event head and rebuild the current index over the first transaction's
unrelated update. This is transaction placement, not a rebase of scientific
content. The second transaction must retain its frozen inputs, revalidate every
target and hard dependency, and record the actual immediately preceding event
root in its receipt. A global event-head advance alone does not conflict a
research run when the intervening receipt proves that all changed targets are
disjoint from its read and write sets.

Validation seals the authority-event intents and exact affected subjects. The
publisher assigns final global sequence numbers, prior-root bindings, and event
digests under the publication lock. This changes only the authority envelope,
not the submitted scientific content or its frozen basis.

Formal control commands remain stricter. Their explicit control-head basis must
match at commit because the user authorized a direct change to formal authority.

A conflicted run remains immutable and inspectable. The user can launch a new run using the latest basis. The system may offer to copy the prior instructions and selected context, but it must not silently rebase scientific output.

## 11. Cancellation, failure, and recovery

### 11.1 Cancellation

The user may cancel only from `created`, `preparing`, `prepared`, or `running`
through an authenticated, idempotent `RunCancellationCommand`. The command binds
the exact run state and journal head observed by the user. It is separate from
the formal `ControlCommand` union because cancellation changes execution only.

Acceptance uses one compare-and-swap with submission. If cancellation wins, the
harness durably enters `cancellation_requested`, closes the submission and
new-role gates, asks active work to stop, and later enters `cancelled`. If lead
submission wins first, the command fails with `RUN_ALREADY_SUBMITTED` and cannot
alter `submitted`, `validating`, `promoting`, `published`, or any terminal run.
Neither side may infer priority from client timestamps. Repeating the same
idempotency key and digest returns the original result; reusing the key with
different content is rejected.

The command service writes a CommandAttemptAuditEvent at acceptance and again
immediately before a durable effect when that boundary is reached. A pre-commit
acceptance identifies the created run, cancellation-fence event, or formal
transaction. A rejection embeds the complete stable CommandError. The
cancellation-requested run event independently binds the exact cancellation
command, complete requesting identities, and accepted pre-commit audit event and root.
These operational links do not enter the scientific authority journal.

Cancellation is cooperative for active tools, but the submission fence is
immediate. Late role output remains diagnostic run-local material and cannot be
accepted into a submission. Cancellation preserves available diagnostics and
never changes formal records.

### 11.2 Execution failure

Tool errors, inaccessible inputs, permission violations, and missing required role submissions produce `failed`. A scientific conclusion that the proposed method fails is not an execution failure when documented in a valid submission.

### 11.3 Validation rejection

The validation report must provide:

- Stable error codes.
- Object and field location.
- Violated invariant or phase rule.
- Whether the problem is structural, provenance-related, or scientific-communication related.
- Smallest correction needed.

### 11.4 Crash recovery

All state transitions are journaled durably. On restart:

- A run before `submitted` may resume only if the manifest and workspaces still verify.
- A `cancellation_requested` run restores its submission fence and completes
  cooperative stopping; it never resumes role work or accepts a submission.
- A `submitted` or `validating` run may restart validation idempotently.
- A promoting run must inspect the transaction journal and current index. It either completes the same prepared transaction or confirms rollback before any new promotion begins.
- Recovery verifies the append-only authority-event sequence and replays it to reconstruct derived record state and the current index. Replayed projections must match the last committed publication receipt before new work is published.
- Recovery separately verifies every retained raw command-request artifact, the contiguous operational-audit sequence, each RFC 8785 content digest, and the binary prior-root chain. It blocks new commands on a gap or mismatch without treating the audit journal as scientific state.
- Duplicate commands with the same idempotency key return the original run rather than creating another.

## 12. Harness interfaces

The UI, command-line tools, and authorized remote agents should use the same command service:

- `create_run(command)`
- `get_run(run_id)`
- `cancel_run(command)`
- `list_eligible_actions(project_id, method_id?)`
- `resolve_context_options(project_id, phase_id, method_id?)`
- `get_validation_report(run_id)`
- `get_publication_receipt(run_id)`
- `change_method_lifecycle(command)`
- `withdraw_formal_generation(command)`

These two typed control commands use the same authority transaction service but
do not create a research run, run workspace, or role execution. Method lifecycle
changes atomically replace the method and catalog generations while preserving
mathematical identity. Withdrawal changes the authority of one exact generation
without creating a replacement or restoring history as current. Both commands
freeze the control head, target state, actor, reason, and command digest. See
[Control commands](09-control-commands.md).

No client receives a direct formal-record write interface. A role recommendation
alone cannot authorize either control command.

`cancel_run` accepts a `RunCancellationCommand`; it does not accept a bare run ID
and actor. Remote destructive actions, including cancellation, retirement,
reactivation, and withdrawal, are disabled unless an active delegation covers
the exact project, action, and target.

## 13. Required harness tests

At minimum, implementation must prove:

1. A user command freezes exact inputs.
2. An agent cannot write outside its unique role root, and only the harness can materialize accepted output under `handoffs/`, `artifacts/`, or `submission/`.
3. A failed or rejected run leaves current records unchanged.
4. A scientifically negative but complete result can publish.
5. A method identity mismatch is rejected.
6. A changed publication target produces a conflict rather than overwrite.
7. An interruption at every publication checkpoint recovers atomically.
8. Repeating an idempotent command or promotion does not duplicate records.
9. Historical context is absent unless required or selected.
10. Every published current generation resolves to one receipt and either one source run or one typed control command.
11. The sealed manifest fixes exact stage IDs, execution groups, role profiles, read allowlists, and per-role write roots.
12. Supersession, method changes, and evidence reclassification do not change any committed generation digest.
13. Replaying committed authority events reconstructs the same record-state projections and current index.
14. Every publication receipt identifies the exact committed event range, event root, projection digests, and current-index generation.
15. Every formal append, create, or replacement operation resolves to one sealed publication binding and no publisher infers a target from a filename.
16. Independent event writers compute identical content digests and journal roots from the same canonical payload and prior root.
17. A method lifecycle command atomically replaces only the method and catalog generations while preserving exact mathematical identity and creating no run.
18. A formal-generation withdrawal creates no replacement generation, never restores history as current, and records dependent impacts.
19. A stale control head, target generation, or state digest yields a conflict with no generation, event, receipt, or index change.
20. The Web UI and authorized remote client submit the same typed control commands and receive the same idempotency and conflict behavior.
21. Cancellation is accepted only from `created`, `preparing`, `prepared`, or
    `running`; it closes submission before active work stops.
22. A cancellation-submission race produces exactly one compare-and-swap winner.
23. An expired, revoked, wrong-project, wrong-action, or wrong-target delegation
    fails both at acceptance and at the pre-commit recheck.
24. Two disjoint method targets both publish in one ordered event journal, while
    a same-target replacement conflicts without last-writer-wins.
25. Accepted, rejected, malformed, and unauthenticated command attempts replay to one identical operational audit root; an accepted cancellation audit resolves to its exact command and digest-bound RunState effect.
26. A manifest contains no unknown future role artifact, context-snapshot, access-ledger, start-time, or closure digest.
27. A later role cannot start from a failed, cancelled, missing, or digest-mismatched upstream closure or accepted artifact.
28. `RunSubmission` is rejected unless successful closures cover the complete selected role plan in order, the lead closure is final, and every required output is present.

End-to-end forms of these tests belong in `scenarios/`.
