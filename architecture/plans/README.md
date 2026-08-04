# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Recommended next block

- [Trusted Local Execution Program](trusted-local-execution-program.md) is
  the program-level plan: it restructures all remaining Version 1 execution
  work into dispatchable packages WP-A through WP-I with dependencies,
  sizes, and acceptance checks. Follow it first.
- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)
  defines the six blocks the program dispatches and the acceptance evidence
  that closes them.

[ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md) defines the
boundary: Method Hub is a trusted, single-user local control plane. It provides
workflow and state integrity, not operating-system isolation from Hermes.

## Active plans

- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md) remains
  open under its Revision 3 trusted-local topology. The local closure plan is
  its controlling implementation package.
- [Operational Completion Plan](operational-completion-plan.md) is historical
  program context; its WP0-WP9 execution framing is superseded by the
  Trusted Local Execution Program.
- [Manual Method Hub with Sequential-First Orchestration](manual-sequential-orchestration-implementation-plan.md)
  records the development baseline and research workflow that must be retained.
  Its OCI-specific implementation guidance is superseded for Version 1.
- [WP0: Reviewed-Basis Closure](wp0-reviewed-basis-closure.md) remains partially
  implemented and follows the local execution closure.
- [WP1 and WP2: Execution and Validation](wp1-wp2-execution-and-validation.md)
  remain open. WP1 now targets trusted local execution; WP2 validation work
  remains required.

## Historical and deferred records

OCI source and tests were removed from the working tree on 2026-08-04 (ADR-012
Amendment 1); git history preserves them. The documents below remain as
historical design records and optional future hardening references only - no
Version 1 work depends on them.

- [End-to-End OCI Diagnostic Closure](next-block-end-to-end-oci-diagnostic-closure.md)
  is deferred optional hardening for multi-user, remote, unattended, or
  untrusted-tool operation.
- [Headless Hermes Runtime Closure](next-block-headless-hermes-runtime-closure.md)
  retains detailed OCI failure cases and evidence requirements but is not a
  Version 1 gate.
- [Hermes Diagnostic Lane Revision](revised-diagnostic-lane-plan.md) retains
  useful profile, memory, lifecycle, and validation observations. Its OCI
  topology is historical.
- [Original Diagnostic Closure Plan](next-block-hermes-diagnostic-closure.md)
  is a historical safety baseline.
- [H0-B OCI evidence](../evidence/h0b-oci-evidence-index.md) remains historical
  feasibility evidence, not a completion gate.
- The dated roadmap under `.hermes/plans/` is historical gap analysis.

## Completion order from the current checkpoint

1. Complete trusted local Hermes execution, including configuration, run
   profiles, supervision, validation, state promotion, and Web controls.
2. Complete WP0 reviewed-basis integrity.
3. Finish the remaining phase-specific WP2 adapters and validation using real
   Hermes fixtures.
4. Run controlled real five-phase pilots through the same local path.
5. Complete reconciliation, backup and restore, packaging, and release evidence.

OCI may be reconsidered later if the operating model changes. It must not delay
this local Version 1 path.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Method Hub itself is production-ready.
