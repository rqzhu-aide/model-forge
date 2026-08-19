# Manual Method Hub with Sequential-First Orchestration

Status: Development baseline implemented; production completion is tracked in [the operational plan](operational-completion-plan.md)

Prepared: 2026-08-02

Decision basis: [ADR-009](../../decisions/ADR-009-sequential-first-orchestration.md)

## 1. Decision in one sentence

Method Hub version 1 remains manually directed and uses a small,
contract-driven sequential orchestrator, while a stable engine-neutral boundary
keeps LangGraph or another workflow engine available as a future adapter.

The user's `RunCommand` is the go-ahead for one run. There is no second generic
approval, automatic phase progression, hidden repair loop, or automatic retry
of scientific role work.

## 2. Why this is the appropriate first implementation

The current executable phase contracts already define bounded research
procedures. Phase 4 is the clearest example:

```text
data analyst -> theorist -> research lead
```

LangGraph would not supply the scientific judgment, output validation, exact
method identity, isolation, or publication transaction that this procedure
requires. Those responsibilities belong to Method Hub and must be implemented
regardless of the orchestration library.

A direct phase-specific script would be smaller initially, but it would mix
stage advancement with invocation, recovery, validation, and publication. The
sequential-first design instead introduces one narrow orchestration interface
and one simple adapter. This is enough for the present workflows and preserves a
clean later upgrade path.

## 3. Current implementation checkpoint

As of 2026-08-03, the development baseline provides:

- durable run-local and formal storage, authority heads, and atomic publication;
- typed commands, exact input selection, run lifecycle events, and cancellation;
- contract-derived preparation, sequential group advancement, role execution
  records, closures, immutable submission, and restart recovery;
- structural, identity, provenance, phase, and publication validation;
- deterministic Phase 1, Phase 2, and Phase 5 cumulative reducers;
- FastAPI projections and a React interface for explicit user-controlled runs;
- schema-example end-to-end execution for all declared phase workflows.

The schema-example executor establishes harness conformance only. It does not
perform research. Direct Hermes Kanban execution also remains development-only.
Production execution is disabled until the reviewed-basis boundary, rootless
OCI isolation, capability broker, authentication, failure injection, and
supported deployment procedures are complete. Method retirement and
reactivation are implemented as no-run control transactions. Formal-generation
withdrawal remains specification-only and must either be completed or explicitly
deferred before version 1.

## 4. Researcher-visible operation

Every run follows one visible and bounded operation:

```text
User chooses phase, mode, method when applicable, instructions, and context
  -> backend resolves eligibility and shows the exact consequence
  -> user submits one RunCommand
  -> harness freezes inputs, role plan, resources, and publication bindings
  -> sequential orchestrator advances the declared execution groups
  -> harness assembles one immutable RunSubmission
  -> validators check structure, identity, provenance, and phase obligations
  -> publisher commits the complete phase transaction or commits nothing
  -> UI displays the formal result and waits for another user command
```

The launch command authorizes validation and publication of that one run when
the submission is valid and unconflicted. It does not authorize another run,
another phase, a method lifecycle change, or a formal withdrawal.

Before launch, the researcher sees:

- the exact phase contract and mode;
- selected method identity when applicable;
- current formal inputs and optional selected history;
- role sequence and contract-declared parallel groups;
- resource and access policies;
- records that success may append, create, or replace;
- consequences of success, failure, cancellation, rejection, or conflict.

After launch, the user may cancel only before immutable submission through the
typed cancellation command.

## 5. Version 1 scope

### 5.1 Included

- Authenticated, idempotent, user-started runs and reruns.
- Exact phase-contract and choice binding.
- Frozen current inputs and opt-in historical context.
- Versioned profiles, souls, skills, tools, knowledge resources, and memory
  policies.
- Role-local writes and capability-based reads.
- Contract-declared serial and parallel execution groups.
- Immutable prepared contexts, invocation starts, execution records, closures,
  handoffs, and submissions.
- Cooperative cancellation before submission.
- Structural, identity, provenance, phase, and publication-safety validation.
- Phase-specific atomic publication and recovery.
- Typed backend projections and user-controlled Web UI actions.
- The five existing phase workflows.

### 5.2 Excluded

- LangGraph or LangChain as a version 1 runtime dependency.
- An autonomous research director or scheduler.
- Model-selected phase progression, method selection, scope, history, or reruns.
- Hidden critique or repair rounds.
- Automatic retry of a failed scientific role or tool call.
- Graph time travel, checkpoint editing, or workflow forking as a product
  feature.
- Switching orchestration adapters inside an active run.
- A legacy-project importer or dual writing with Research Hub.

## 6. Authority boundaries

| Component | Owns | Must not do |
|---|---|---|
| Command service | Authentication, authorization, choice validation, idempotency, and run creation | Infer missing scientific choices or launch another phase |
| Generic harness | Preparation, lifecycle, role isolation, closure gates, submission, validation, publication, and recovery | Invent scientific content or change user scope |
| Sequential orchestrator | Advance the sealed execution groups and report operational progress | Add stages, choose research direction, validate scientific truth, or publish |
| Stage execution service | Create or reconcile one declared role invocation and seal its closure | Start an undeclared role or broaden its context |
| Hermes executor | Perform role work within the frozen capability boundary | Read formal storage or write outside the role root |
| Validator | Check machine-verifiable obligations | Treat an unfavorable conclusion as an operational failure |
| Publisher | Commit sealed publication bindings atomically | Infer targets from filenames or orchestrator state |
| UI | Display authoritative views and submit typed commands | Reimplement eligibility or start work automatically |

## 7. Replaceable orchestration port

Define the port before adding any workflow framework:

```python
class PhaseOrchestrator(Protocol):
    def supports(self, manifest: RunManifest) -> bool: ...

    async def execute(
        self,
        run_id: RunId,
        manifest_sha256: Sha256Digest,
        services: OrchestrationServices,
    ) -> OrchestrationResult: ...

    async def recover(
        self,
        run_id: RunId,
        manifest_sha256: Sha256Digest,
        services: OrchestrationServices,
    ) -> OrchestrationResult: ...

    async def notify_cancellation(self, run_id: RunId) -> None: ...
```

`notify_cancellation` is only a wake-up signal. The durable harness fence is
authoritative if the signal is delayed or lost.

`OrchestrationServices` exposes only:

- load and verify the sealed manifest;
- inspect cancellation, new-role, and submission gates;
- execute or reconcile one declared role step;
- read verified invocation closures and accepted outputs;
- append monotone operational progress;
- request immutable submission assembly after the complete plan.

It exposes no formal-storage writer, authority journal, projection writer,
current-index writer, validation mutation interface, publisher, role credential,
or capability-broker secret.

An `OrchestratorRegistry` resolves the exact adapter from the frozen
orchestration binding. Version 1 registers only
`ContractSequentialOrchestrator`.

## 8. Frozen orchestration binding

Add one immutable engine-neutral binding to `RunManifest`:

- orchestration protocol version;
- adapter ID and adapter version;
- workflow ID and workflow version;
- immutable workflow-definition artifact and digest;
- exact supported phase-contract digest;
- retry policy, fixed to `no_scientific_role_retry` in version 1.

The workflow definition references phase-contract stage IDs. It does not copy
prompts, scientific instructions, or publication rules.

An unfinished run recovers with its frozen adapter and workflow version. A
registry or package upgrade affects only newly prepared runs. Resolution fails
closed when the adapter, workflow digest, or supported phase-contract digest is
unavailable.

No orchestration-framework field belongs in the scientific phase contract.

## 9. Sequential execution algorithm

The adapter advances execution groups rather than hard-coding role names:

```text
verify manifest and orchestration binding
for each execution group in sealed contract order:
    check durable cancellation and new-role gates
    verify all required upstream closures and accepted artifacts
    freeze one group-start basis
    execute or reconcile every declared role in the group
    require one successful immutable closure per role
check cancellation and submission gates
request immutable submission assembly
return orchestration-complete
```

For a serial group, the group contains one role step. For a parallel group, all
roles receive the same frozen group-start basis and no role can read another
role's in-group output. Every role in the group must close before the next group
becomes eligible.

Physical concurrency is an executor concern. If a development executor runs a
parallel group one process at a time, it must still freeze the common basis and
withhold in-group outputs. Production should execute the group concurrently
when resources permit.

The adapter cannot add, omit, reorder, or reassign a stage. A scientific repair
round requires a changed executable phase contract and acceptance scenario.

## 10. Exact phase plans

| Phase and mode | Ordered execution groups |
|---|---|
| P1 literature update | Independent lead, theorist, and analyst discovery in one parallel group; lead synthesis |
| P2 full or focused | Independent lead, theorist, and analyst proposals in one parallel group; theorist and analyst cross-review in one parallel group; lead reconciliation |
| P3 theory update | Theorist; analyst; lead |
| P4 preliminary or comprehensive | Analyst; theorist; lead |
| P5 assembly | Lead assembly |
| P5 review revision | Theorist, analyst, and outside reviewer in one isolated parallel group; lead revision |

These plans are derived from the exact selected phase contract. This table is a
researcher-readable summary, not a second executable source.

## 11. Crash-safe role execution

The harness needs a `RoleExecutionRecord` bound to one exact
`RoleInvocationStart`. It records:

- deterministic execution ID and invocation-start digest;
- executor, Hermes job, container, and runtime identities;
- durable launch intent and launch acknowledgement;
- worker lease, fencing epoch, and heartbeat;
- execution events, exit state, and diagnostic references;
- cancellation request and termination result.

Dispatch is idempotent by invocation-start ID. Repeated dispatch reattaches to
or returns the existing execution. It never starts a second scientific attempt
under the same invocation.

On recovery, the harness:

1. verifies the manifest, run journal, execution record, and gates;
2. reattaches when the exact job remains active;
3. seals a closure from recorded results when execution completed and outputs
   still verify;
4. fails closed when execution identity cannot be established;
5. never launches replacement scientific work under the same invocation.

Infrastructure reads and compare-and-swap operations may be retried
idempotently. Hermes work and scientific tool calls are not retried
automatically. A new attempt requires another user command.

## 12. Cancellation and failure

Cancellation remains a typed harness command:

1. The command service commits `cancellation_requested`.
2. Submission and new-role gates close immediately.
3. The orchestrator receives a best-effort notification.
4. Stage entry and group transitions check the durable fence.
5. Active execution stops cooperatively, followed by bounded termination when
   required.
6. The harness seals cancellation diagnostics and enters `cancelled` only after
   no role process remains active.

Submission and cancellation use one compare-and-swap boundary. If immutable
submission wins, cancellation is rejected and validation continues.

| Situation | Result |
|---|---|
| Preparation cannot freeze exact inputs | `failed`; no role starts |
| Hermes or a scientific tool fails | Failed closure and run `failed` |
| Required role output is absent or invalid | Failed closure and run `failed` |
| Scientific result is negative or inconclusive | Successful closure; continue |
| Submission fails validation | `rejected`; current formal state unchanged |
| Publication basis changed | `conflicted`; submission preserved |
| Worker crashes | Reconcile the same execution records |
| Execution identity is uncertain | Fail closed; do not invoke again |
| Publisher crashes | Recover the generic atomic transaction |

## 13. Validation and publication boundary

After the orchestrator requests submission assembly, it has no further role.
The generic harness performs:

```text
submitted -> validating -> promoting -> published
```

Submission requires the complete selected role plan, exactly one successful
closure per role step, the final lead closure, and every required accepted
output.

Validation checks schemas, digests, identities, provenance, phase obligations,
cross-record consistency, and publication safety. It does not decide whether a
proof is correct or a conclusion is scientifically persuasive.

Publication uses the phase-specific policy:

- P1 appends unique literature and replaces current synthesis records.
- P2 applies the authorized catalog or focused method update.
- P3 replaces the complete current theory record.
- P4 appends evidence and attention and replaces the evidence index, empirical
  synthesis, implementation record, and phase decision atomically.
- P5 replaces the complete current manuscript package.

Failed, cancelled, rejected, conflicted, or interrupted work never replaces the
last valid current record.

## 14. Required specification repairs before live execution

Complete these representation gaps before binding live Hermes roles:

1. Add the orchestration binding, role execution record, and run progress event
   schemas, digest contracts, examples, and typed models.
2. Allow `RunState` to represent `created` and `preparing` before a manifest
   digest exists, while requiring the digest from `prepared` onward.
3. Extend `ResolvedPhasePlan` to expose prerequisites, required inputs,
   downstream effects, and UI projection data needed by preparation and views.
4. Add dedicated Phase 4 schemas for the protocol, analyst synthesis,
   mathematical-fidelity audit, evidence index, empirical synthesis, and
   implementation record.
5. Add compact P4 evidence-lineage context, explicit preliminary and
   comprehensive obligation dispositions, and typed data, code, simulation, or
   benchmark bindings.
6. Require the prior P4 evidence index, empirical synthesis, and implementation
   record to be jointly present or absent and to share one exact method identity
   and atomic publication receipt.
7. Keep unresolved evidence applicability separate from an inconclusive but
   eligible scientific outcome.

Changes to producer obligations require a new Phase 4 contract version. Engine
identity remains outside that scientific contract.

## 15. Recommended package boundaries

```text
src/method_hub/
  application/
    run_commands.py
    run_queries.py
    orchestration_registry.py
  domain/
    commands.py
    runs.py
    roles.py
    scientific.py
    authority.py
    orchestration.py
  storage/
    paths.py
    artifacts.py
    run_store.py
    authority_store.py
    journals.py
    transactions.py
  harness/
    lifecycle.py
    preparation.py
    role_invocation.py
    role_execution.py
    submission.py
    validation.py
    publication.py
    recovery.py
    supervisor.py
  orchestration/
    protocol.py
    contract_sequential.py
    registry.py
  executors/
    protocol.py
    fake.py
    hermes.py
    oci.py
  phases/
    p1/
    p2/
    p3/
    p4/
    p5/
  projections/
  api/
```

The contract kernel remains importable without any workflow framework. Do not
add the broad `langchain` package or a placeholder LangGraph dependency.

## 16. Implementation sequence and gates

Development checkpoint on 2026-08-02:

| Step | Status |
|---|---|
| 0. Sequential orchestration specification | Complete and validated |
| 1. Typed domain models | Complete for the development slice |
| 2. Storage and authority | Complete for local runs; backup and restore hardening remains |
| 3. Generic harness and sequential adapter | Complete with recovery and schema-example execution |
| 4. Production role executor | Not complete; direct Hermes remains development-only |
| 5. Phase 1 vertical slice | Complete with explicit launch, publication, cancellation, and rerun mechanics |
| 6. Phase 2 | Run, publication, retirement, and reactivation mechanics complete |
| 7. Phases 3 and 4 | Complete in the schema-example pipeline, including either-phase-first order |
| 8. Phase 5 | Assembly mechanics and upstream readiness gate complete in the schema-example pipeline |
| 9. Projections, API, and UI | Complete for local development use |
| 10. Operational hardening | Pending |

### Step 0: Complete the sequential orchestration specification

Deliver the representation repairs in Section 14, update traceability, and keep
the architecture validator passing.

Gate: two implementations derive the same execution groups, role visibility,
retry behavior, and submission boundary.

### Step 1: Complete typed domain models

Implement schema-backed models for commands, manifests, run state, profiles,
contexts, invocations, execution, closures, submissions, progress, scientific
records, authority events, projections, indexes, and receipts.

Gate: every positive example round-trips, every negative fixture fails with a
stable diagnostic, and every registered digest reproduces.

### Step 2: Implement storage and authority

Implement safe paths, immutable artifacts, run journals, formal generations,
ordered authority events, deterministic replay, current indexes, atomic
publication, compare-and-swap, and recovery.

Gate: failure injection produces either one complete commit or no commit, and
replay reproduces the same current-state digest.

### Step 3: Build the generic harness and sequential adapter

Use a deterministic one-stage dummy contract and fake executor. Implement
command intake, preparation, role boundaries, execution reconciliation,
closure, submission, validation, cancellation, conflict handling, publication,
and restart recovery through the sequential adapter.

Gate: successful, failed, cancelled, duplicate, interrupted, and conflicted
dummy runs preserve every lifecycle and authority invariant.

### Step 4: Implement the production role executor

Implement deterministic context packing, capability broker, rootless OCI Linux
executor, Hermes adapter, leases, heartbeats, output limits, cancellation, and
execution reconciliation.

Gate: isolation tests pass and a crash at every launch boundary cannot create
two accepted executions for one invocation start.

### Step 5: Deliver the first researcher-usable vertical slice

Implement a real Phase 1 run and rerun from project setup through the Web UI,
including cumulative literature publication and current synthesis views. Other
phases may be visible but remain disabled through typed backend eligibility.

Gate: a researcher can launch, monitor, cancel, inspect, and rerun Phase 1, and
the system never infers completion or starts Phase 2.

### Step 6: Implement Phase 2

Implement full-catalog and focused-method modes, exact method identity,
lineage, and no-run retirement and reactivation commands.

Gate: a fresh project can create real Phase 4 prerequisites without hidden
fixture seeding.

### Step 7: Implement Phases 3 and 4 together

Implement P3 complete theory replacement and P4 cumulative evidence with the
complete atomic current package. Both use the sequential adapter.

Gate: either phase can run first after P2, each uses available current sibling
context, and neither launches the other.

### Step 8: Implement Phase 5

Implement assembly and review-revision modes with the existing reviewer
isolation contract and exact upstream readiness gate.

Gate: the outside reviewer receives only the frozen review packet, and Phase 5
cannot combine method lineages or mismatched versions.

### Step 9: Complete projections, FastAPI, and the React UI

Complete typed phase views, action descriptors, command endpoints, SSE progress,
current and history panels, and accessible light and dark themes.

Gate: no component invents eligibility, parses prose for status, or launches a
run because another run completed.

### Step 10: Operational hardening

Add backup and restore, journal audits, concurrent-worker fencing, bounded logs,
large-evidence benchmarks, and supported Linux installation tests.

Gate: restore reproduces identical formal generations, journal roots, current
views, and receipts.

## 17. Required test matrix

### Manual authority

- No orchestrator starts without an accepted `RunCommand`.
- Duplicate command keys return the original run.
- Completing, failing, cancelling, rejecting, conflicting, or publishing a run
  creates no new run.
- An agent recommendation cannot authorize another action.

### Contract execution

- Every mode derives its exact stages and roles from the selected contract.
- P3 runs theorist, analyst, and lead in order.
- P4 runs analyst, theorist, and lead in order.
- P1, P2, and P5 parallel groups receive one frozen common basis and no mutual
  in-group visibility.
- An added, omitted, reordered, or reassigned stage fails closed.
- No adapter contains an undeclared repair edge or scientific retry.

### Recovery and idempotency

- Crash before and after prepared-context creation.
- Crash before and after invocation-start persistence.
- Crash after process launch but before launch acknowledgement.
- Crash after process completion but before closure.
- Crash after closure but before the next execution group.
- Two workers attempting to own one run.
- Completed closure reuse without another Hermes invocation.

### Cancellation and publication

- Cancellation at every pre-submission stage closes later-role and submission
  gates.
- Cancellation and submission have exactly one winner.
- Every non-published terminal state preserves prior formal records.
- Each phase commits its complete declared publication effects or none.
- A publication conflict never triggers an orchestrator retry or silent rebase.

### Research communication

- Material assumptions, limitations, disagreements, and unresolved issues reach
  lead synthesis.
- Negative and inconclusive outcomes can publish when structurally complete.
- Exact method mismatches block method-bound output.
- Historical context is absent unless explicitly selected.
- Compact views cite their structured statements and primary artifacts.

### UI and API

- Web and delegated clients submit the same command shapes.
- Launch review shows exact inputs, choices, stages, and publication
  consequences.
- Progress events are monotone and stale activity is explicit.
- Operational failure and unfavorable scientific outcome remain distinct.
- The orchestration adapter appears only as technical provenance.

## 18. Future LangGraph adapter

Consider LangGraph only after an accepted workflow requires one or more of:

- conditional scientific routing;
- explicit analyst and theorist revision loops;
- dynamic parallel simulation or analysis tasks;
- a durable mid-run user pause and continuation;
- workflow paths that cannot be represented as bounded contract execution
  groups.

Before activation, a future adapter must:

1. implement the same `PhaseOrchestrator` port;
2. call the same narrow harness services;
3. freeze its adapter and workflow identity only for new runs;
4. treat checkpoints as operational caches rather than authority;
5. recover completed stages from harness closures and execution records;
6. pass the complete authority, isolation, cancellation, recovery, and
   publication test suite;
7. introduce no model-directed scope choice or scientific retry unless a later
   accepted contract explicitly defines it.

The UI, command models, formal storage, phase publication policies, and Hermes
profiles must not change merely because the adapter changes.

## 19. Definition of done

The sequential-first version is complete when:

1. Every phase and rerun remains manually launched.
2. Every execution group is derived from the exact frozen phase contract.
3. Contract-declared parallel isolation is preserved.
4. Hermes execution is isolated, recoverable, and protected from duplicate
   accepted invocation.
5. A role failure causes no automatic scientific retry.
6. Validation and publication remain outside the orchestrator.
7. Every phase publication is atomic, traceable, and recoverable.
8. Failure, cancellation, rejection, conflict, and crash preserve prior formal
   state.
9. The UI clearly explains current evidence, uncertainty, change, and available
   user decisions.
10. A future adapter can replace the sequential adapter for new runs without
    changing commands, scientific records, authority, publication, or views.

## 20. Next implementation action

Keep production role execution disabled. Follow the
[Operational Completion Plan](operational-completion-plan.md): first seal the
exact researcher-reviewed basis and complete the missing runtime
representations, then replace the development execution boundary with the
rootless OCI executor, capability broker, durable external-job reconciliation,
and isolation tests. Validate every phase against actual Hermes outputs before
enabling remote operation. Do not add LangGraph until an accepted workflow
requires branching, revision loops, or a durable mid-run user pause.
