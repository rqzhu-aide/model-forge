# S10: Complete Negative Scientific Result

## Purpose

Verify that a complete negative scientific conclusion is publishable and is not
confused with an execution failure.

## Initial state

- A valid current P3 theory record exists for one exact method identity.
- No run is active.

## User action

The user launches a P3 rerun to examine one unresolved theoretical claim.

## Expected behavior

1. The theorist constructs a valid counterexample showing that the claim fails
   under the stated assumptions and produces a complete replacement theory
   record.
2. The data analyst examines the operational and empirical consequences.
3. The research lead preserves the counterexample, narrows affected claims, and
   records a `contradicted` scientific outcome.
4. The role sequence, artifacts, statements, issues, handoff, and decision brief
   satisfy the Phase 3 contract.
5. Validation passes because identity, completeness, and provenance are valid.
6. Promotion atomically replaces the previous current P3 generation.
7. The UI presents the new result as the current formal conclusion and explains
   the user-controlled options.

## Prohibited behavior

- The run cannot enter `failed` merely because its scientific conclusion is
  unfavorable.
- The previous positive conclusion cannot remain current solely because it is
  more favorable.
- The system cannot launch a Phase 2 revision or another Phase 3 run
  automatically.
