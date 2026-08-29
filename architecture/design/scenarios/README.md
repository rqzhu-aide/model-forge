# Acceptance Scenarios

These files describe normative researcher workflows. They are not illustrative
stories. Each scenario must become an automated end-to-end test.

## Scenario format

Every scenario defines:

1. purpose;
2. initial formal state;
3. user action;
4. frozen run basis;
5. expected role execution;
6. expected run-local outputs;
7. validation and promotion result;
8. expected formal state;
9. expected UI communication;
10. prohibited behavior.

## Scenario index

The exact identifiers, invariant links, test groups, phase suites, and milestones are machine-checked in [`contracts/traceability.json`](../../contracts/traceability.json). S11 intentionally belongs to the control-command suite rather than a phase contract, and S13-S24 belong to the trusted-local execution suite (ADR-012) with no phase contract.

| ID | Executable ID | Scenario | Phase contracts | Milestones |
|---|---|---|---|---|
| S01 | `s01.first_project` | First project through P1 and P2 | P1, P2 | M4, M5 |
| S02 | `s02.phase2_scopes` | Full-catalog and focused P2 reruns | P2 | M5 |
| S03 | `s03.phase4_before_phase3` | P4 runs before P3 | P3, P4 | M6 |
| S04 | `s04.method_definition_change` | Calculation-defining method change | P2, P3, P4 | M5, M6 |
| S05 | `s05.failed_run` | Failed, cancelled, or nonconforming run preserves current state | P3 | M3, M6 |
| S06 | `s06.optional_history` | Optional historical context | P1, P3 | M3, M4, M6 |
| S07 | `s07.evidence_revalidation` | P4 evidence revalidation | P4 | M6 |
| S08 | `s08.phase5_workflow` | P5 assembly and review-revision | P5 | M7 |
| S09 | `s09.interrupted_promotion` | Interrupted publication recovery and submitted-run preservation | P1, P2, P5 | M2, M3 |
| S10 | `s10.negative_result` | Complete negative scientific result | P3, P4, P5 | M6, M7 |
| S11 | `s11.control_commands` | User-controlled lifecycle and delegated control | Control suite | M2, M5 |
| S12 | `s12.disjoint_concurrent_publication` | Disjoint concurrent publication | P3 | M2, M3, M6 |
| S13 | `s13.role_setup_configuration` | Exact role setup through configuration | Trusted-local suite | M3 |
| S14 | `s14.first_run_clean_state` | First run starts with clean state | Trusted-local suite | M3 |
| S15 | `s15.continuation_latest_promoted_state` | Continuation sees exactly the latest promoted state | Trusted-local suite | M3 |
| S16 | `s16.fresh_reviewer_state` | Fresh reviewer state is always ephemeral | Trusted-local suite | M3 |
| S17 | `s17.invalid_output_no_state_change` | Exit zero alone never passes validation | Trusted-local suite | M3 |
| S18 | `s18.hermes_version_change_preflight` | Hermes version change surfaces at preflight | Trusted-local suite | M3 |
| S19 | `s19.cancellation_timeout_process_tree` | Cancellation and timeout terminate the complete process tree | Trusted-local suite | M3 |
| S20 | `s20.restart_reconciliation_no_relaunch` | Restart reconciliation inspects durable identity, never relaunches | Trusted-local suite | M9 |
| S21 | `s21.stale_lock_ownership` | Stale locks cannot promote or release another owner's lock | Trusted-local suite | M9 |
| S22 | `s22.failed_promotion_preserves_last_known_good` | Failed promotion preserves last known good state byte-identically | Trusted-local suite | M3 |
| S23 | `s23.bounded_logs_flood_overlong` | Bounded logs under output flood and over-long lines | Trusted-local suite | M3, M9 |
| S24 | `s24.safe_session_snapshot` | Safe session snapshot with verified SQLite backup | Trusted-local suite | M9 |
| S25 | `s25.deterministic_normalization` | Allowlisted mechanical normalization disclosed and applied | Validation suite | M3 |
| S26 | `s26.output_correction` | User-requested targeted output correction with bounded scope | Validation suite | M3 |
| S27 | `s27.revalidation` | Revalidation after validator policy change with unchanged digest | Validation suite | M3 |
| S28 | `s28.integrity_rejection` | Wrong identity, basis, or digest strictly rejected | Validation suite | M3 |
| S29 | `s29.warning_only_publication` | Honest negative or inconclusive result publishes with advisory findings | Validation suite | M6, M7 |
| S30 | `s30.broadcast_handoff_multi_role` | Broadcast handoff into a multi-role stage | Trusted-local suite | M3 |
| S31 | `s31.researcher_seed_input` | Researcher supplementary material seeds additively with researcher_seed provenance | Validation suite | M7 |
