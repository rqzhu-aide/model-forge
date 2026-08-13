# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Active issues

- [Context Selection UI Issues](context-selection-issues.md) - audit findings
  from the cross-phase context-card review (2026-08-07). Four critical issues,
  three moderate, three minor.
- [Stage+Role Instruction Changes Review](stage-role-instructions-review.md) -
  review of the stage+role instruction plan and its uncommitted implementation
  (2026-08-08, two audit rounds). P0-1 and P0-2 are resolved. The related
  P1-1, P1-2, P1-3, P2-2, P2-3, P3-1, and P3-2 findings are also addressed.
  P0-3 and the remaining backend and frontend findings stay open.
- [Instruction, Output-Integrity, and UI Fix Plan](instruction-output-integrity-fix-plan.md) -
  active work packages FP-1 through FP-8. FP-3 is complete; FP-1, FP-4,
  FP-5, and FP-6 are partially complete; FP-2, FP-7, and FP-8 remain open.
  FP-2 remains the publication-integrity gate for further real runs.

## Active plans

- [Harness Validation and Output Recovery](harness-validation-and-output-recovery-plan.md)
  separates execution failure from output conformance and adds bounded,
  user-controlled recovery. Implementation is indexed in
  [harness-validation-index.md](harness-validation-index.md) (packages HV-0
  through HV-7). Revision 2 (2026-08-12) applied the corrections from the
  [coder review](harness-validation-review-2026-08-12.md): verified code
  counts, registry totality, correction basis pinning, submission re-entry
  mechanics, HV-4 rescope, and the traceability procedure for new scenarios.
- [Trusted Local Execution Program](trusted-local-execution-program.md) is
  the program-level plan for Version 1 execution work (WP-A through WP-I).
  WP-A through WP-H are complete (WP-G: `8edeeb1`; WP-H1: `f494aa0`; WP-H2:
  `b8f7b37` + `095b421`; WP-F: through `8efcd1c`). WP-I (phase adapters and
  five-phase pilot) remains.
- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)
  defines the block definitions the program dispatches.
- [Manual Sequential Orchestration](manual-sequential-orchestration-implementation-plan.md)
  records the development baseline and research workflow that must be retained.
- [Stage+Role Instruction Templates for P1, P3, P4, P5](stage-role-instructions-all-phases.md)
  adds stage+role-specific instruction templates matching the P2 pattern. The
  15 template files are created. Layered composition and mode-specific P2
  directives resolve the related routing issues; remaining non-template
  findings stay in the active fix plan.

[ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md) defines the
boundary: Method Hub is a trusted, single-user local control plane.
[ADR-013](../decisions/ADR-013-layered-prompts-and-phase-specific-output-contracts.md)
defines layered prompt composition, phase-mode separation, and the dedicated
theory, protocol, manuscript, and review output contracts.

## Completion order from the current checkpoint

1. Complete WP-I (WP2 adapters and five-phase pilot).
2. Resolve the context-selection issues above; P0-2 (contract presence model)
   gates any further P5 contract work and needs a contract-author decision.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Method Hub itself is production-ready.

The following historical plans have been moved to `completed/` because their
stated scope is finished or they have been superseded:

- End-to-End OCI Diagnostic Closure (deferred optional hardening)
- Headless Hermes Runtime Closure (historical OCI failure cases)
- Hermes Diagnostic Lane Revision (historical safety baseline)
- Operational Completion Plan (superseded by the Trusted Local Execution Program)
- Phase 0: Safe Hermes Execution (controlling implementation package delivered)
- WP0: Reviewed-Basis Closure (implemented; remaining gaps tracked in WP-H)
- WP1 and WP2: Execution and Validation (WP1 done via trusted local; WP2 → WP-I)
