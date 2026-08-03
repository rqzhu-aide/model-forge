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

The exact identifiers, invariant links, test groups, phase suites, and milestones are machine-checked in [`contracts/traceability.json`](../contracts/traceability.json). S11 intentionally belongs to the control-command suite rather than a phase contract.

| ID | Executable ID | Scenario | Phase contracts | Milestones |
|---|---|---|---|---|
| S01 | `s01.first_project` | First project through P1 and P2 | P1, P2 | M4, M5 |
| S02 | `s02.phase2_scopes` | Full-catalog and focused P2 reruns | P2 | M5 |
| S03 | `s03.phase4_before_phase3` | P4 runs before P3 | P3, P4 | M6 |
| S04 | `s04.method_definition_change` | Calculation-defining method change | P2, P3, P4 | M5, M6 |
| S05 | `s05.failed_run` | Failed or cancelled run preserves current state | P3 | M3, M6 |
| S06 | `s06.optional_history` | Optional historical context | P1, P3 | M3, M4, M6 |
| S07 | `s07.evidence_revalidation` | P4 evidence revalidation | P4 | M6 |
| S08 | `s08.phase5_workflow` | P5 assembly and review-revision | P5 | M7 |
| S09 | `s09.interrupted_promotion` | Interrupted publication recovery and submitted-run preservation | P1, P2, P5 | M2, M3 |
| S10 | `s10.negative_result` | Complete negative scientific result | P3, P4, P5 | M6, M7 |
| S11 | `s11.control_commands` | User-controlled lifecycle, withdrawal, and delegated control | Control suite | M2, M5 |
| S12 | `s12.disjoint_concurrent_publication` | Disjoint concurrent publication | P3 | M2, M3, M6 |
