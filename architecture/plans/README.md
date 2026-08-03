# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Recommended next block

- [Complete the Non-Publishing Hermes Diagnostic Lane](next-block-hermes-diagnostic-closure.md)
  is the next bounded implementation package. It closes cancellation,
  reconciliation, containment, bounded logs, and diagnostic inspection around
  one real synthetic Hermes invocation. It does not authorize scientific
  publication.
- [Revised Diagnostic Lane Plan](revised-diagnostic-lane-plan.md) adapts the
  next block to verified host Hermes behavior: per-project persistent
  profiles with per-role memory policy, baked SOUL.md, mounted task briefs,
  and one-shot container execution (Revision 1, corrections C1–C10).

## Active plans

- [Operational Completion Plan](operational-completion-plan.md) remains the
  production-readiness program.
- [Manual Method Hub with Sequential-First Orchestration](manual-sequential-orchestration-implementation-plan.md)
  records the implemented development baseline and the remaining production
  boundary.
- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md) remains
  open. Transport reconnaissance and one host-based connectivity test are
  complete, but isolation, durable termination, recovery, quotas, and the
  diagnostic interface have not passed their exit gates.
- [WP0: Reviewed-Basis Closure](wp0-reviewed-basis-closure.md) is partially
  implemented. The command-sealing scaffold exists, but the complete role and
  scientific basis is not yet sealed and verified fail closed.
- [WP1 and WP2: Execution and Validation](wp1-wp2-execution-and-validation.md)
  contains useful executor, capability, fencing, adapter, and validator
  scaffolds. Neither work package has passed its exit gate.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Method Hub itself is production-ready.
