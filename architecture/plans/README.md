# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation programs. A plan is not itself a phase contract or an accepted
architecture decision. If a plan changes an invariant, schema, phase contract,
or acceptance scenario, the corresponding specification and decision record
must be updated before code relies on the change.

Current plans:

- [Operational Completion Plan](operational-completion-plan.md) is the active
  production-readiness program.
- [Manual Method Hub with Sequential-First Orchestration](manual-sequential-orchestration-implementation-plan.md)
  records the implemented development baseline and replaceable orchestration
  boundary.
- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md) is the
  non-publishing diagnostic program that proves the bounded, isolated,
  recoverable Hermes execution boundary (Revision 1, with grounded-review
  amendments A1–A8).
- [WP0: Reviewed-Basis Closure](wp0-reviewed-basis-closure.md) scopes the
  compare-and-seal implementation that binds the researcher-reviewed basis
  into the accepted run command (Revision 1, corrections C1–C6).
- [WP1+WP2: Execution and Validation](wp1-wp2-execution-and-validation.md)
  scopes the rootless OCI production executor, capability broker, invocation
  fencing, and phase-specific output adapters and validators (Revision 1,
  corrections C1–C7).
- [Phase 0 Spike Findings](phase-0-spike-findings.md) records the Checkpoint
  0-pre transport reconnaissance results and the 0G real connectivity test.
