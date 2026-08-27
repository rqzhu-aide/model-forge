# Completed Planning Records

This folder contains bounded work whose stated scope has been completed and
verified. It is an evidence archive, not a declaration that the surrounding
phase or production system is complete.

## Completed work

### K-1 remaining implementation plan + NA-2 (correction lane)

Completed 2026-08-20; archived 2026-08-23. All packages landed and
verified (P1 through P7 plus D4/D5): the output-correction command path
(preview, revalidate, normalize, packaging, scientific), Lane A/Lane B
execution, correction UI controls, and the K5-1..K5-4 production fixes
(ADR-015 broadcast handoffs, findings propagation, plan-declared scope,
ADR-016 resume edge). The K-5 production re-exercise closed 2026-08-21
(controlled re-run published, zero findings) and the evidence gate over
the E-1/E-2 build was satisfied 2026-08-23. D5 (revalidate unreachable
for REJECTED runs) stays open for the method owner in the K-1 design
record; K-7 stays open by design in the harness audit.

Evidence: [K-1 remaining implementation plan](k1-remaining-implementation-plan-2026-08-17.md),
`../../evidence/k5-production-re-exercise-2026-08-20.md`,
`../../evidence/k5-production-re-run-2026-08-21.md`, and
`../../evidence/k5-production-re-run-2026-08-23.md`.

### Harness validation and output recovery program (HV-0 through HV-7)

Completed 2026-08-15 (commit `63dca62`): raw output preservation, the
validation policy registry, lifecycle separation with correction states,
harness envelope construction, bounded user-controlled recovery machinery,
phase schema calibration, and the pilot measurement harness. The
production re-exercise closed as K-5 (2026-08-21; evidence gate re-run
satisfied 2026-08-23).

Evidence: [parent plan](harness-validation-and-output-recovery-plan.md),
[implementation index](harness-validation-index.md),
[HV-0](HV-0-architecture-and-failure-baseline.md) through
[HV-7](HV-7-pilot-measure-harden.md), and the
[calibration corpus](evidence/hv7-calibration-corpus/).

### Harness validation plan coder review

Applied 2026-08-12 as revision 2 of the parent plan: verified code counts,
registry totality, correction basis pinning, submission re-entry mechanics,
the HV-4 rescope, and the traceability procedure for new scenarios.

Evidence: [review findings](harness-validation-review-2026-08-12.md).

### Harness mechanics audit (ISS-1 through ISS-9)

Closed 2026-08-16: all nine delivery-path findings landed and were verified,
including schema-exact ID sanitization and positive examples for the phase
record schemas.

Evidence: [audit and fix log](harness-mechanics-audit-2026-08-15.md).

### Stage+role instruction templates for P1, P3, P4, P5

Completed 2026-08-08: the 15 stage+role template files exist under
`resources/instructions/`, with layered composition and mode-specific P2
directives. Non-template findings from the review remain in the active fix
plan.

Evidence: [template plan](stage-role-instructions-all-phases.md).

### Manual sequential orchestration baseline

Development baseline implemented. Superseded as a forward-looking plan by the
Trusted Local Execution Program; retained as the record of the manual,
contract-driven sequential harness baseline that must be preserved.

Evidence: [baseline plan](manual-sequential-orchestration-implementation-plan.md).

### Hermes transport reconnaissance and first connectivity subtest

Completed on 2026-08-03 against Hermes v0.19.0.

The work established the real Kanban status vocabulary, retry behavior,
idempotent-create behavior, archived-task hole, worker topology, event sources,
and cancellation limitation. The development adapter was corrected to use the
real statuses, one-attempt behavior, a restricted environment, profile
preflight, and an initial capped control-command capture foundation. One
synthetic theorist task completed successfully and changed no formal
scientific state.

Evidence: [Phase 0 Spike Findings](phase-0-spike-findings.md).

This proves development connectivity only. It does not prove rootless
isolation, provider-only networking, durable worker termination, restart-safe
reconciliation, a fully bounded cross-platform supervisor, workspace quotas,
or publishable scientific execution.

### Initial Hermes one-shot and profile-state reconnaissance

Completed on 2026-08-03 against Hermes v0.19.0 on Linux.

The host observations established one-shot exit and stream behavior, the usage
record fields, signal response, the writable profile footprint, persistent
memory behavior, the role of `state.db` in session storage, task-brief file
delivery, profile-clone credential behavior, and model/provider overrides.

Evidence: [One-Shot Behavior Findings](spike-report-s5.0.md).

This is a completed observation record, not a completed runtime spike or
diagnostic lane. It does not prove exact profile selection inside the sandbox,
declared-skill isolation, read-only identity execution, output quiescence,
ephemeral reviewer state, provider-only egress, bounded output, durable
cancellation, or restart reconciliation. The committed diagnostic script still
exercises the development Kanban path rather than this one-shot path.

## Implemented foundations that remain under active plans

The following foundations exist but are not archived as completed work
packages:

- the manual, contract-driven sequential development harness and schema-example
  execution for all declared phase workflows;
- initial command `sealed_basis` wiring and stale-authority detection;
- initial Bubblewrap, capability-broker, in-memory fencing, output-adapter, and
  scientific-validator modules;
- initial project-profile, memory metadata, diagnostic-table, one-shot command,
  durable-token, and profile-lock scaffolds, covered by unit tests but not by a
  real isolated execution test.

Their active plans remain outside this folder because their production or
scientific-integrity exit gates are still open.
