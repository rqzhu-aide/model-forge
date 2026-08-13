# Method Hub Architecture Specification

## Purpose

This directory is the normative architecture for the Method Hub implementation
in this repository. It is greenfield relative to the legacy
[Research Hub](https://github.com/rqzhu-aide/research-hub), which uses a different
storage and authority model.

Version 1 does not define legacy-project import, dual writing, or cutover from
Research Hub. Programmers must not create two sources of formal truth by
partially connecting the applications. Any later adoption path for existing
projects requires a separate accepted decision record, a one-way audited
importer, reconciliation tests, and a rollback boundary.

This boundary is recorded in
[ADR-006: Greenfield Boundary and Future Existing-Project Adoption](decisions/ADR-006-greenfield-boundary.md).
The one-time product and protocol identity change is recorded in
[ADR-010: Method Hub Product and Protocol Namespace](decisions/ADR-010-method-hub-namespace.md).

The specification is written for three audiences:

- Researchers, who need to understand what the system records and what decisions remain theirs.
- Developers, who need precise objects, states, transitions, and failure behavior.
- Test authors, who need observable acceptance criteria rather than implied workflow conventions.

For a concise, cross-checked view of file and record types, phase-specific reads and writes, and each role's responsibilities, see [Roles and Files](../role%20and%20files/README.md).

The system is intended to support iterative statistical, machine learning, mathematical, computational, and biological research. Its central task is not merely to store agent output. It must preserve the scientific basis of each result, coordinate role-specific reasoning, and show the researcher which conclusions are current, which evidence supports them, and which questions remain unresolved.

## The five architectural concerns

The design keeps five concerns separate.

| Concern | Question answered | Canonical mechanism |
|---|---|---|
| Information layer | How much detail does this file contain? | Primary artifact, structured scientific record, or compact decision view |
| Formal authority | Has the system validated and published this record? | Immutable generations, authority events, derived state, and publication receipts |
| Scientific identity | Which exact method or research object does this result concern? | Stable identifiers, versions, and content digests |
| Scientific assessment | What does the work establish, and with what uncertainty? | Statements, evidence, alignment, attention, and outcome records |
| User control | What may happen next? | Typed actions, explicit commands, cancellation, and bounded delegation |

Information layers describe file format and retrieval depth only. A compact decision view can report a current conclusion, while a detailed artifact can be obsolete or invalid. No code may infer authority from file depth, location, filename, or apparent completeness.

## Core operating model

Every research run is a controlled operation:

1. The user selects the phase, scope, method when applicable, instructions, and optional context, either directly or through a valid bounded delegation.
2. The harness freezes the exact command and a manifest containing the contract, input basis, role recipe, resource limits, and publication plan. The manifest does not claim later context materialization, role output, or completion.
3. Before each role begins, the harness seals a `PreparedRoleContext` and `RoleInvocationStart`, then launches the bound trusted local executor. The role can write only within its run-local role root and can read only through its declared capability broker.
4. When a role ends, the harness seals a `RoleInvocationClosure`. A downstream role may consume only successful upstream closures and their exact accepted outputs.
5. After the selected role plan has one complete ordered successful closure chain, including the final lead closure, the harness seals one immutable `RunSubmission`. Submission closes the cancellation gate and binds every candidate artifact sent to validation.
6. Validators check structure, identity, provenance, phase obligations, scientific-basis completeness, and publication safety.
7. The harness atomically commits formal generations, authority events, derived state, the current index, and a self-digested publication receipt bound to the exact submission.
8. The Web UI projects the resulting records and offers typed possible actions. An action descriptor is not authorization, and the interface does not select or launch the next phase.

Publication means that the result is the formal record of what the run concluded. It does not mean that the result is favorable or mathematically proven by the software. A valid result may conclude that a claim is contradicted, a proof is incomplete, or an experiment is inconclusive.

Every attempt to start or cancel a run, retire or reactivate a method, or withdraw a formal generation enters a separate tamper-evident operational audit. That audit explains command handling but never changes scientific authority.

## Specification map

Read the files in this order:

1. [System principles](00-system-principles.md) defines non-negotiable invariants and actor boundaries.
2. [Research domain model](01-research-domain-model.md) defines the scientific objects and their relations.
3. [Run harness](02-run-harness.md) defines controlled execution, validation, promotion, concurrency, and recovery.
4. [Storage and authority](03-storage-and-authority.md) defines immutable generations, append-only authority events, rebuildable current state, logical paths, and phase-specific storage semantics.
5. [UI contract](04-ui-contract.md) defines how formal records and user commands are projected into the Web interface.
6. `phases/` defines the scientific and operational contract for Phases 1 through 5.
7. `contracts/` contains the executable phase registry, deterministic digest registry, and invariant-to-test traceability registry used by adapters and validators.
8. `schemas/` contains 46 machine-validatable schemas, while `examples/` contains 58 valid examples and 16 focused invalid fixtures.
9. `scenarios/` defines 12 end-to-end acceptance cases, including failures, method changes, control commands, and [S12 disjoint concurrent publication](scenarios/S12-disjoint-concurrent-publication.md).
10. [Validation strategy](05-validation-strategy.md) defines how conformance is proved without treating software checks as scientific judgment.
11. [Implementation roadmap](06-implementation-roadmap.md) gives the required build order and definition of done.
12. [Contract traceability](07-contract-traceability.md) defines research-workflow rules and their machine-readable links to invariants, tests, scenarios, phase contracts, and milestones.
13. [Role and context contract](08-role-context-and-communication.md) defines reproducible profiles, prepared contexts, invocation starts and closures, downstream closure gates, immutable submission, capability-broker isolation, handoffs, and reviewer isolation.
14. [Control commands](09-control-commands.md) defines cancellation, method lifecycle changes, formal-generation withdrawal, remote delegation, and shared command failures.
15. [Open implementation gaps](10-open-implementation-gaps.md) records unresolved structural integrity requirements that must close before the harness is complete.
16. [Operational completion plan](plans/completed/operational-completion-plan.md) orders the remaining work from reviewed-basis sealing through supported release.
17. `tools/` contains the restricted RFC 8785 reference and one-command package conformance validator.
18. `decisions/` records accepted changes to invariants, schemas, and phase behavior.

If prose, an executable contract, and a schema disagree, implementation must stop until the inconsistency is resolved. None is silently treated as more authoritative. Schemas constrain representation, executable contracts drive deterministic behavior, and prose defines scientific meaning.

## Programmer starting point

The development baseline already implements the domain kernel, local storage,
sequential harness, all five schema-example phase paths, API, and Web interface.

1. Run `python architecture/tools/validate_package.py`, `python -m pytest`, and
   the frontend tests before changing a contract boundary.
2. Start every behavior change from its invariant, executable phase contract,
   schema, and scenario. Do not infer authority or phase behavior from UI code.
3. Follow the
   [Operational Completion Plan](plans/completed/operational-completion-plan.md) for the
   remaining production sequence. The reviewed-basis seal precedes real Hermes
   execution, and real execution precedes remote operation.
4. Keep production role execution disabled until the plan's isolation,
   authentication, recovery, and deployment gates pass.

When a phase contract changes, edit its file under `contracts/phases/`, run
`python architecture/tools/build_contract_registry.py`, update the corresponding
prose and scenarios, and rerun package validation.

## Recommended logical project layout

The specification uses logical paths so that storage can later be implemented on a local filesystem, object store, or database without changing the domain model.

```text
project/
  project.json
  records/
    literature/current/
    method-catalog/current/
    methods/{method_id}/
      definition/current/
      theory/current/
      empirical/current/
      manuscript/current/
  generations/
    {record_type}/{record_id}/{generation_id}/
  runs/
    {phase_id}/{run_id}/
  control/
    current-index/
      current.json
      generations/{index_generation_id}.json
    record-state/{subject_kind}/{subject_id}.json
    authority-events/{sequence}-{event_id}.json
    publication-journal/{publication_id}.json
    command-request-artifacts/{request_sha256}.bin
    command-attempt-audit/{sequence}-{audit_event_id}.json
    replay-checkpoints/{checkpoint_id}.json
```

These paths express responsibilities, not permission by convention. The run harness is the only component allowed to create formal generations, append authority events, or update derived projections under `records/`, `generations/`, or `control/`. Agents receive write access only to their allocated role roots under `runs/`.

Formal objects should refer to one another with stable logical references rather than operating-system paths. Examples include:

```text
record://literature/current
record://method/{method_id}/definition/current
record://method/{method_id}/theory/current
generation://{record_type}/{record_id}/{generation_id}
run://{run_id}/artifact/{artifact_id}
```

The resolver maps each reference to its physical representation and verifies its digest. See [Storage and authority](03-storage-and-authority.md).

## Phase semantics at a glance

The five phases do not share one generic replacement rule.

| Phase | Formal object maintained | Update semantics |
|---|---|---|
| Phase 1 | Literature corpus and synthesis | Cumulative, deduplicated expansion with explicit corrections and withdrawals |
| Phase 2 | Method catalog and method definitions | Full-catalog or focused-method publication with method lineage |
| Phase 3 | Current theory record for one method | Complete replacement by a new validated generation |
| Phase 4 | Empirical evidence registry plus current evidence index, synthesis, and implementation record for one method | Immutable evidence accumulation plus four atomically replaced current slots, including the phase decision |
| Phase 5 | Current manuscript for one method | Complete replacement tied to exact upstream generations |

The detailed input, role, validation, promotion, and user-decision rules belong in the phase specifications.

## How developers should use this package

For each feature, developers should proceed in this order:

1. Identify the applicable invariant and phase contract.
2. Implement or update the persisted schema.
3. Implement a typed domain representation.
4. Implement validation without adding scientific meaning not present in the contract.
5. Implement state transitions through the run harness.
6. Add positive, negative, conflict, and recovery tests.
7. Add the UI projection only after the backend record is authoritative.

A feature is not complete when a page renders or a file is written. It is complete when its state transitions, invalid inputs, interrupted publication, scientific uncertainty, and user-visible consequences have all been tested.

## Normative language

The words **must**, **must not**, **should**, and **may** are normative:

- **Must** and **must not** define required behavior.
- **Should** defines the preferred behavior; deviations require a documented reason.
- **May** defines optional behavior that must not change the meaning of required behavior.

Invariant identifiers, object names, and state names are stable interfaces. Renaming them requires a specification change and migration plan.
