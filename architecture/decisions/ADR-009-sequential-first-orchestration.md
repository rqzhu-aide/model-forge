# ADR-009: Sequential-First Orchestration with a Replaceable Adapter Boundary

## Status

Accepted

## Context

The executable phase contracts already define each stage, role assignment,
execution group, input visibility, required output, and publication binding.
Phase 4 currently has a fixed data analyst, theorist, and research lead order.
The other phases also have bounded plans, with some contract-declared parallel
groups.

LangGraph can help a later workflow that needs durable branching, revision
loops, conditional routing, or mid-run user interruption. It does not provide
scientific judgment, output validation, method identity, role isolation, or
publication authority. Introducing it before those needs exist would add a
second recovery model and checkpoint store before the generic harness is
complete.

At the same time, directly embedding stage order in phase-specific scripts
would make a later orchestration change affect the harness, phase adapters, and
possibly the Web UI. The initial implementation therefore needs a small stable
boundary without requiring a workflow framework.

## Invariants that must remain true

- Every run and rerun begins with one authenticated user command or an exact
  active delegation acting for that user.
- Completion, failure, validation, or publication never launches another run.
- The sealed phase contract and run manifest determine the complete stage plan.
- Contract-declared parallel roles receive the same frozen group-start basis
  and cannot inspect one another's in-group outputs.
- A downstream stage consumes only successful immutable upstream closures and
  their accepted artifact digests.
- A failed scientific role execution is not retried automatically. Another
  scientific attempt requires a new user-started run.
- The harness, not the orchestrator, owns cancellation fences, role isolation,
  validation, submission, publication, authority, and recovery records.
- An orchestration engine cannot invent a stage, change scope, choose a method,
  select history, judge a scientific result, or write formal records.
- An active run never changes orchestration adapter or workflow definition.

## Options considered

### Option A: Phase-specific procedural scripts

Each phase directly invokes its roles in local code. This is initially small,
but it duplicates lifecycle and recovery behavior and creates no stable future
adapter boundary.

### Option B: LangGraph in the first implementation

LangGraph coordinates every Phase 4 run from the outset. This provides graph
checkpoints and routing abstractions, but the current workflow has no dynamic
branching or scientific repair loop. The harness would still need its own
authoritative invocation, cancellation, validation, and publication records.

### Option C: Engine-neutral port with a sequential first adapter

Define one narrow `PhaseOrchestrator` port and implement a
`ContractSequentialOrchestrator` that advances the sealed execution groups.
Keep LangGraph as a possible later adapter when workflow complexity justifies
it.

## Decision

Select Option C.

Version 1 uses `ContractSequentialOrchestrator` for every phase. It reads the
sealed role plan through narrow harness services, advances execution groups in
contract order, checks the durable cancellation and submission gates, executes
or reconciles each declared role invocation, and asks the harness to assemble
the immutable submission after the complete closure chain succeeds.

The sequential adapter preserves contract-declared parallel semantics. Roles in
one parallel execution group use one frozen group-start basis, run without
mutual visibility, and all close successfully before the next group becomes
eligible. Sequential describes ordered advancement between execution groups;
it does not convert a declared parallel research design into a conversational
sequence.

The port exposes execution, recovery, and best-effort cancellation notification.
Cancellation authority remains the durable harness fence. The services exposed
to an orchestrator are limited to manifest verification, gate inspection,
idempotent role execution or reconciliation, closure lookup, progress append,
and submission assembly. They expose no formal-storage writer, authority
journal, current-index writer, validator mutation interface, or publisher.

Each manifest freezes an engine-neutral orchestration binding containing the
protocol version, adapter identity and version, workflow identity and digest,
supported phase-contract digest, and `no_scientific_role_retry` policy. A later
adapter applies only to newly prepared runs. Recovery uses the adapter and
workflow version frozen by the unfinished run.

LangGraph is not a version 1 runtime dependency. A future
`LangGraphPhaseOrchestrator` may implement the same port after branching,
revision loops, dynamic parallel work, or mid-run user interaction become
accepted contract requirements. Its checkpoints remain operational aids and
cannot replace harness-owned invocation, closure, submission, or authority
records.

## Consequences

### Benefits

- The initial runtime matches the current bounded scientific workflows.
- Execution and recovery remain easy to inspect and test.
- Phase contracts remain independent of orchestration frameworks.
- LangGraph or another engine can be added without changing commands, storage,
  publication, or researcher-facing views.
- The same adapter handles fixed serial stages and contract-declared parallel
  groups.

### Costs and risks

- The harness must implement durable stage reconciliation and progress records
  itself.
- A later graph adapter requires compatibility tests against the same port and
  frozen workflow binding.
- Workflow branching cannot be introduced by configuration alone. It requires
  an accepted contract and scenario change.

## Contract and schema changes required before runtime implementation

- Define the engine-neutral `PhaseOrchestrator` and `OrchestrationServices`
  contracts.
- Add an orchestration-binding schema and freeze it in `RunManifest`.
- Add a `RoleExecutionRecord` so process launch and recovery cannot duplicate a
  scientific invocation.
- Add a `RunProgressEvent` for monotone researcher-facing execution progress.
- Register deterministic digest contracts for these persisted objects.
- Add conformance tests proving that the sequential adapter derives execution
  only from the sealed phase plan.

## Validation changes

- Reject a missing, unsupported, or digest-mismatched orchestration binding.
- Reject any adapter that adds, removes, reorders, or reassigns a contract stage.
- Reject downstream execution from a failed, cancelled, missing, or
  digest-mismatched upstream closure.
- Reconcile an existing invocation instead of launching it again after a crash.
- Verify that a role failure ends the run without an automatic scientific retry.
- Verify that changing the adapter registry affects only newly prepared runs.
