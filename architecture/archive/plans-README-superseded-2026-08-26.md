# Architecture Implementation Plans

These documents translate the accepted Model Forge architecture into bounded
implementation work. A plan does not change an invariant, schema, phase
contract, or acceptance scenario by itself. Update the corresponding
specification or decision record before code relies on such a change.

## Active plans

- [K-1 Correction Command Path Design](k1-correction-command-path-design.md) -
  the design basis for the correction lane; implementation COMPLETE
  (2026-08-20). D1-D4 are resolved; D5 (revalidate unreachable for
  REJECTED runs) stays open for the method owner.
- [E-1: P2 Structured Lead Evaluation](e1-p2-structured-evaluation-plan-2026-08-21.md) -
  E-1a through E-1d plus E-1c/E-1f UI and contract polish landed
  (2026-08-21); the E-1d production exercise published clean. E-1e LANDED
  2026-08-25 (`43433cb`): handoff schema carries optional
  method_evaluations, the blocking p2.review_evaluations_missing rule gives
  the axis check teeth, and both stage-2 instruction templates require the
  field.
- [E-2: Information Layers Made Real](e2-information-layers-plan-2026-08-22.md) -
  E-2a through E-2d landed (pointer stamping, compact views, layer-aware
  materialization, primary-pointer sidecars; policy 1.11.0).
- [E-2e: P2 canonical_artifact Pointers](e2e-p2-canonical-artifact-plan-2026-08-23.md) -
  LANDED 2026-08-23 (`896615a`); E-2f hardening 2026-08-24 (`c6970c6`).
  Production probe SATISFIED 2026-08-24 (fresh-cycle P2 `8fd97448`):
  canonical_artifact pointers stamped and lookup-bound to hash-verified
  stage-1 proposal bytes.
- [F-1: Candidates Carry No Generation Identity](f1-candidate-generation-identity-plan-2026-08-23.md) -
  LANDED 2026-08-23. Production proof SATISFIED 2026-08-24 (fresh-cycle
  P1 `7e0c9a54` published; strip verified on 73 source records; E-2d
  pointer probe passed). Follow-ups landed: F-1b (`9ef9e7a`, schema-const
  record_type fallback), F-1c (`b960790`, contract-declared record_type),
  F-2 (`eacf55c`, decision-record generation identity).
- [C-2: Partial-Seal Correction Scope](c2-partial-seal-correction-scope-plan-2026-08-25.md) -
  LANDED 2026-08-25 (`255fd47`). Failed closures now admit sealed UNION
  plan-declared outputs, closing the dominant recovery gap (two production
  hits).
- [Trusted Local Execution Program](trusted-local-execution-program.md) -
  the program-level plan for Version 1 execution work (WP-A through WP-I).
  WP-A through WP-H are complete (WP-G: `8edeeb1`; WP-H1: `f494aa0`; WP-H2:
  `b8f7b37` + `095b421`; WP-F: through `8efcd1c`). WP-I is CLOSED
  (2026-08-26, section 7 of the program doc): the single default output
  adapter carried every phase of the fresh five-phase pilot
  (P1-P5 published on the entangled-Langevin project, authority
  revisions 1..7); no phase-specific adapter proved necessary.
- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)
  defines the block definitions the program dispatches; WP-I cites its
  acceptance evidence.
- [Harness Audit 2026-08-16](harness-audit-2026-08-16.md) - missing-component
  and misalignment findings with a fix log. NA-1, K-1 (through P3b), K-3,
  K-4, K-5, and K-6 are resolved; NA-2/P7 is RESOLVED (`894203a`, persisted
  cancel intent + 4 tests); K-2 is RESOLVED (2026-08-19, two-lane divergence
  deliberate, Tez sign-off). K-7 (reviewer-memory boundary) stays open by
  design.

## Active issues

- [Context Selection UI Issues](../issues/context-selection-issues.md) - audit findings
  from the cross-phase context-card review (2026-08-07). P0-2 needs a
  contract-author decision (a schema change requires an ADR); P1-3 is a
  product decision for Tez; the remaining confirmed findings are unfixed.
- [Stage+Role Instruction Changes Review](stage-role-instructions-review.md) -
  review of the stage+role instruction plan and its implementation
  (2026-08-08, two audit rounds). P0-1, P0-2, P1-1, P1-2, P1-3, P2-2, P2-3,
  P3-1, and P3-2 are addressed. P0-3 (silent output rewriting) is covered
  by the FP-2 satisfaction note above (2026-08-25); the remaining small
  backend and frontend findings track with FP-6/FP-7.
- [Instruction, Output-Integrity, and UI Fix Plan](instruction-output-integrity-fix-plan.md) -
  work packages FP-1 through FP-8. FP-2 is SATISFIED (2026-08-25 review):
  the HV program rebuilt the repair lane as disclosed mechanical repairs
  with transformation records (no content fabrication remains; verified in
  `harness/role_execution.py`), and K-2 signed off the two-lane divergence
  as deliberate. FP-3 and FP-4 are complete; FP-1, FP-5, and FP-6 are
  partially complete; FP-7 (small frontend repairs) and FP-8 (design
  decisions) remain open.

[ADR-012](../design/decisions/ADR-012-trusted-local-hermes-execution.md) defines the
boundary: Model Forge is a trusted, single-user local control plane.
[ADR-013](../design/decisions/ADR-013-layered-prompts-and-phase-specific-output-contracts.md)
defines layered prompt composition, phase-mode separation, and the dedicated
theory, protocol, manuscript, and review output contracts.
[ADR-014](../design/decisions/ADR-014-independent-lifecycle-axes-and-validation-policy.md)
defines the validation-policy axes and the correction lane now implemented by
the HV program and K-1.

## Completion order from the current checkpoint

1. ~~K-5 controlled production re-run~~ - SATISFIED 2026-08-23: the
   controlled P2 full-catalog run on the E-1/E-2 build (`1f0b240`)
   published with zero findings on all five closures; E-1 evaluations,
   E-2b compact materialization, and artifact integrity verified live.
   Evidence: `../evidence/k5-production-re-run-2026-08-23.md`.
2. ~~E-2e production probe~~ - SATISFIED 2026-08-24 (fresh-cycle P2
   `8fd97448`): canonical_artifact pointers stamped, lookup-bound to real
   artifact registry rows, digests re-hash to the sealed stage-1 proposal
   bytes. The E-2 arc (E-2a..E-2f) is fully production-verified.
3. ~~E-1e reviewer structured evaluations~~ - LANDED 2026-08-25
   (`43433cb`).
4. ~~C-2 partial-seal correction scope~~ - LANDED 2026-08-25 (`255fd47`).
5. WP-I (WP2 adapters and five-phase pilot) - the fresh entangled-Langevin
   cycle (P1-P3 published 2026-08-24/25, P4 in flight) is the five-phase
   pilot evidence; closure note follows P5.
6. Resolve the context-selection issues above; P0-2 (contract presence model)
   gates any further P5 contract work and needs a contract-author decision.

## Completed records

Completed and narrowly scoped records are indexed in
[completed/README.md](completed/README.md). Moving a record there means only
that its stated scope is complete. It does not imply that Phase 0, a work
package, or Model Forge itself is production-ready.

Recently archived:

- K-1 Remaining Implementation Plan + NA-2 (2026-08-23): all packages
  landed and verified (P1 through P7 plus D4/D5); the K-5 production
  evidence gate over the E-1/E-2 build is satisfied. K-7 stays open by
  design (tracked in the harness audit).
- Harness Validation and Output Recovery program: parent plan,
  implementation index, and HV-0 through HV-7 (delivered in `63dca62`;
  the production re-exercise closed as K-5 on 2026-08-21, gate re-run
  satisfied 2026-08-23).
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
