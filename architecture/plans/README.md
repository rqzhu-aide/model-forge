# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Recommended next block

- [Headless Hermes Runtime Closure](next-block-headless-hermes-runtime-closure.md)
  is the controlling next implementation package. It turns the new profile,
  one-shot, diagnostic-store, and fencing scaffolds into one real Linux
  diagnostic invocation that is isolated, bounded, cancellable,
  restart-reconcilable, and unable to enter scientific state.

## Active plans and design records

- [Revised Diagnostic Lane Plan](revised-diagnostic-lane-plan.md) is the
  Hermes-specific design adaptation and implementation checkpoint. It defines
  exact profile isolation, mounted task briefs, and one-shot execution, and
  proposes a role-specific memory policy that still requires an architecture
  decision. Its exit gate remains open.
- [Original Diagnostic Closure Plan](next-block-hermes-diagnostic-closure.md)
  remains the strict safety and evidence baseline. Its earlier disposable
  profile details are superseded by the Hermes-specific design record and the
  controlling next block.
- [Operational Completion Plan](operational-completion-plan.md) remains the
  production-readiness program.
- [Manual Method Hub with Sequential-First Orchestration](manual-sequential-orchestration-implementation-plan.md)
  records the implemented development baseline and the remaining production
  boundary.
- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md) remains
  open. Transport and one-shot reconnaissance plus useful filesystem,
  database, and unit-test scaffolds are complete. Real containment, bounded
  supervision, durable control, memory-policy enforcement, and evidence have
  not passed their exit gates.
- [WP0: Reviewed-Basis Closure](wp0-reviewed-basis-closure.md) is partially
  implemented. The command-sealing scaffold exists, but the complete role and
  scientific basis is not yet sealed and verified fail closed.
- [WP1 and WP2: Execution and Validation](wp1-wp2-execution-and-validation.md)
  contains useful executor, capability, profile, diagnostic persistence,
  fencing, adapter, and validator scaffolds. Neither work package has passed
  its exit gate.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Method Hub itself is production-ready.
