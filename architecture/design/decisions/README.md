# Architecture Decisions

Use architecture decision records for changes that alter a system invariant,
persisted schema, phase contract, promotion rule, user decision, or scientific
status meaning.

Small wording corrections do not require a decision record. A change requires
one when two reasonable implementations would produce different formal records,
run behavior, or researcher decisions.

## Process

1. Copy `ADR-000-template.md` and assign the next number.
2. State the research and engineering problem without assuming a solution.
3. List the alternatives and their consequences.
4. Record the decision, affected contracts, schema changes, and scenario changes.
5. Mark the record Accepted before implementation begins.
6. Never rewrite an accepted decision to hide a later change. Supersede it with
   a new decision record.

## Required decision topics

Create a decision record for at least:

- adding or changing an authority state;
- changing which scientific outcomes may become current;
- changing a phase role order or run mode;
- changing method-version semantics;
- changing cumulative versus replacement storage behavior;
- changing default context or history policy;
- changing Phase 5 readiness;
- adding automated invalidation or promotion behavior;
- changing a researcher-visible status meaning;
- changing a control-command transition or concurrency basis;
- changing canonicalization, digest payload, or method-identity construction;
- changing the role-isolation boundary, context packing policy, or context
  overflow behavior;
- changing cancellation, remote delegation, or typed action semantics;
- changing the greenfield boundary, legacy-project adoption policy, or cutover
  behavior.
- changing the role invocation, role closure, or immutable submission boundary;
- changing the operational command-audit payload, authorization checks, effect
  binding, or audit-root construction.
- changing the orchestration adapter boundary, stage advancement semantics, or
  scientific retry policy.
- changing the product, package, schema, environment, or protocol namespace.

## Accepted decisions

- [ADR-001: Contract-Bound Run Choices](ADR-001-contract-bound-run-choices.md)
- [ADR-002: Ordered Authority Replay](ADR-002-ordered-authority-replay.md)
- [ADR-003: Deterministic Digest Contracts](ADR-003-deterministic-digest-contracts.md)
- [ADR-004: Role Isolation and Context Snapshots](ADR-004-role-isolation-and-context-snapshots.md)
- [ADR-005: Cancellation, Delegation, and Disjoint Concurrency](ADR-005-cancellation-delegation-and-disjoint-concurrency.md)
- [ADR-006: Greenfield Boundary and Future Existing-Project Adoption](ADR-006-greenfield-boundary.md)
- [ADR-007: Role Invocation and Submission Records](ADR-007-role-invocation-and-submission-records.md)
- [ADR-008: Tamper-Evident Operational Command Audit](ADR-008-tamper-evident-operational-audit.md)
- [ADR-009: Sequential-First Orchestration with a Replaceable Adapter Boundary](ADR-009-sequential-first-orchestration.md)
- [ADR-010: Model Forge Product and Protocol Namespace](ADR-010-model-forge-namespace.md)
- [ADR-011: Per-project Hermes Profile Memory and Session Model](ADR-011-per-project-memory-model.md)
- [ADR-012: Trusted Local Hermes Execution for Version 1](ADR-012-trusted-local-hermes-execution.md)
- [ADR-013: Layered Prompts and Phase-Specific Output Contracts](ADR-013-layered-prompts-and-phase-specific-output-contracts.md)
- [ADR-014: Independent Lifecycle Axes and Validation Policy](ADR-014-independent-lifecycle-axes-and-validation-policy.md)
- [ADR-015: Broadcast Handoff Addressing and Harness-Owned-Field Finding Routing](ADR-015-broadcast-handoff-and-harness-owned-findings.md)
- [ADR-016: Correction Resume-Execution Edge for Mid-Pipeline Failures](ADR-016-correction-resume-execution-edge.md)
- [ADR-017: P2 Structured Lead Evaluation - Three-Axis Method Scores](ADR-017-p2-structured-lead-evaluation.md)
- [ADR-018: Researcher Seed Channel for Run Inputs - superseded by ADR-019](ADR-018-researcher-seed-channel.md)
- [ADR-019: Seeds Are Additive Supplementary Material, Never Replacements](ADR-019-additive-supplementary-seeds.md)
