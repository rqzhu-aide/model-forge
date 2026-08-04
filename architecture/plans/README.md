# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Recommended next block

- [End-to-End OCI Diagnostic Closure](next-block-end-to-end-oci-diagnostic-closure.md)
  is the controlling next implementation package. It connects the public
  diagnostic command to the OCI executor, isolates one exact runtime profile,
  makes identity and cancellation durable, enforces memory and network policy,
  and repeats the complete Linux evidence matrix through the real path.

This corrective block is required because commit `009a50a` proves useful
rootless Podman and Hermes feasibility, but it does not satisfy the H0-B exit
gate. The local diagnostic UI, WP0 reviewed-basis closure, and scientific
Hermes execution remain later work.

## Active plans and design records

- [Headless Hermes Runtime Closure](next-block-headless-hermes-runtime-closure.md)
  remains the parent Phase 0 backend gate. Its detailed invariants and 27-case
  evidence matrix remain controlling. The end-to-end OCI block above is the
  bounded corrective package needed to finish it.
- [Revised Diagnostic Lane Plan](revised-diagnostic-lane-plan.md) records the
  Hermes-specific profile, memory, and one-shot design. Its exit gate remains
  open.
- [Original Diagnostic Closure Plan](next-block-hermes-diagnostic-closure.md)
  remains the strict safety and evidence baseline. Its earlier disposable
  profile details are superseded by the Hermes-specific design.
- [Operational Completion Plan](operational-completion-plan.md) remains the
  production-readiness program.
- [Manual Method Hub with Sequential-First Orchestration](manual-sequential-orchestration-implementation-plan.md)
  records the implemented development baseline and remaining production
  boundary.
- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md) remains
  open. Runtime scaffolding and partial Linux feasibility evidence exist, but
  the integrated OCI diagnostic and the local diagnostic interface have not
  passed their gates.
- [WP0: Reviewed-Basis Closure](wp0-reviewed-basis-closure.md) is partially
  implemented. It must not become the active block until the diagnostic
  execution boundary is trustworthy.
- [WP1 and WP2: Execution and Validation](wp1-wp2-execution-and-validation.md)
  contain useful scaffolding. Neither work package has passed its exit gate,
  and the diagnostic executor must remain unreachable from scientific runs.

The dated roadmap under `.hermes/plans/` is retained as a historical gap
analysis. Its older baseline, sequencing, and OCI deferral are not controlling.

## Completion order from the current checkpoint

1. Complete the end-to-end OCI diagnostic closure and accept H0-B evidence.
2. Add the local diagnostic status, log, cancellation, and memory interface to
   finish the remaining Phase 0 usability gate.
3. Complete WP0 reviewed-basis integrity.
4. Continue with production scientific execution and output validation under
   WP1 and WP2.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Method Hub itself is production-ready.
