# Architecture Implementation Plans

These documents translate the accepted Method Hub architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Active plans

- [K-1 Remaining Implementation Plan + NA-2](k1-remaining-implementation-plan-2026-08-17.md) -
  the current controlling implementation sequence. P1 through P3b are landed
  (`ad3e2a6` through `74b243f`): correction error codes, attempt-aware
  submission read, Lane A submission re-entry, the
  `request_output_correction` service, and the corrections endpoint.
  Remaining: P4 (normalize + preview), P5 (Lane B role re-invocation),
  P6 (UI correction controls), P7 (NA-2 persisted cancel intent), plus the
  deferred K-2 decision and the K-5 production re-exercise.
- [K-1 Correction Command Path Design](k1-correction-command-path-design.md) -
  the design basis for the correction lane. D1-D4 are resolved; D5
  (revalidate unreachable for REJECTED runs) is open for the method owner.
- [Trusted Local Execution Program](trusted-local-execution-program.md) -
  the program-level plan for Version 1 execution work (WP-A through WP-I).
  WP-A through WP-H are complete (WP-G: `8edeeb1`; WP-H1: `f494aa0`; WP-H2:
  `b8f7b37` + `095b421`; WP-F: through `8efcd1c`). WP-I (phase adapters and
  five-phase pilot) remains.
- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)
  defines the block definitions the program dispatches; WP-I cites its
  acceptance evidence.
- [Harness Audit 2026-08-16](harness-audit-2026-08-16.md) - missing-component
  and misalignment findings with a fix log. NA-1, K-1 (through P3b), K-3,
  K-4, and K-6 are resolved; NA-2 (tracked as P7), K-2, K-5, and K-7 remain.

## Active issues

- [Context Selection UI Issues](context-selection-issues.md) - audit findings
  from the cross-phase context-card review (2026-08-07). P0-2 needs a
  contract-author decision (a schema change requires an ADR); P1-3 is a
  product decision for Tez; the remaining confirmed findings are unfixed.
- [Stage+Role Instruction Changes Review](stage-role-instructions-review.md) -
  review of the stage+role instruction plan and its implementation
  (2026-08-08, two audit rounds). P0-1, P0-2, P1-1, P1-2, P1-3, P2-2, P2-3,
  P3-1, and P3-2 are addressed. P0-3 and the remaining backend and frontend
  findings stay open.
- [Instruction, Output-Integrity, and UI Fix Plan](instruction-output-integrity-fix-plan.md) -
  work packages FP-1 through FP-8. FP-3 and FP-4 are complete; FP-1, FP-5,
  and FP-6 are partially complete; FP-2, FP-7, and FP-8 remain open. FP-2
  remains the publication-integrity gate for further real runs.

[ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md) defines the
boundary: Method Hub is a trusted, single-user local control plane.
[ADR-013](../decisions/ADR-013-layered-prompts-and-phase-specific-output-contracts.md)
defines layered prompt composition, phase-mode separation, and the dedicated
theory, protocol, manuscript, and review output contracts.
[ADR-014](../decisions/ADR-014-independent-lifecycle-axes-and-validation-policy.md)
defines the validation-policy axes and the correction lane now implemented by
the HV program and K-1.

## Completion order from the current checkpoint

1. P4-P7 of the K-1 plan (correction lane completion), then the K-5
   controlled production re-run as the evidence gate.
2. WP-I (WP2 adapters and five-phase pilot).
3. Resolve the context-selection issues above; P0-2 (contract presence model)
   gates any further P5 contract work and needs a contract-author decision.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Method Hub itself is production-ready.

Recently archived (2026-08-18 audit):

- Harness Validation and Output Recovery program: parent plan,
  implementation index, and HV-0 through HV-7 (delivered in `63dca62`;
  the production re-exercise remains open as K-5).
- Harness Validation coder review (applied as revision 2).
- Harness Mechanics Audit ISS-1 through ISS-9 (all landed and verified).
- Stage+Role Instruction Templates for P1, P3, P4, P5 (15 template files
  created; non-template findings remain in the active fix plan).
- Manual Sequential Orchestration baseline (development baseline
  implemented; superseded as a forward-looking plan by the Trusted Local
  Execution Program).

Older archived records:

- End-to-End OCI Diagnostic Closure (deferred optional hardening)
- Headless Hermes Runtime Closure (historical OCI failure cases)
- Hermes Diagnostic Lane Revision (historical safety baseline)
- Operational Completion Plan (superseded by the Trusted Local Execution Program)
- Phase 0: Safe Hermes Execution (controlling implementation package delivered)
- WP0: Reviewed-Basis Closure (implemented; remaining gaps tracked in WP-H)
- WP1 and WP2: Execution and Validation (WP1 done via trusted local; WP2 -> WP-I)
