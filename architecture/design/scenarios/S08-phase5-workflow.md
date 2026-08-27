# S08: P5 assembly and review-revision

## Purpose

Verify exact manuscript basis, same-lineage review targeting, distinct specialist
and reviewer inputs, and traceable issue disposition.

## Initial state

- Current P1 and selected-method records exist.
- Current P3 and P4 records use the exact selected method identity.
- No current manuscript exists.

## Assembly action

The user launches P5 assembly. The harness freezes the exact upstream records,
and the lead produces one complete run-local manuscript. Publication creates the
current manuscript and its exact upstream-basis record.

## Review-revision action

The user later launches review-revision for the same stable method lineage.

- The harness freezes the exact current manuscript target and verifies its
  stable method ID.
- The harness constructs immutable `p5.review_packet` only from the manuscript,
  submitted supplements, reviewer-visible cited material, and reviewer-facing
  instructions.
- The theorist receives the packet plus the exact method, current theory, and
  literature synthesis.
- The data analyst receives the packet plus the exact method, current empirical
  index and synthesis, and literature synthesis.
- The outside reviewer receives only `p5.review_packet`.
- The three roles work in one parallel execution group and cannot read one
  another's in-group outputs.
- After all three reports are fixed, the lead receives them and writes the
  revised complete manuscript plus versioned issue dispositions.
- Each parallel reviewer role closes one immutable invocation before the lead
  start is created. The lead start binds the exact three accepted reports and
  closure digests.

## Acceptance checks

- A manuscript from another stable method ID is rejected before reviewer work.
- An older manuscript version is allowed only within the selected stable method
  lineage.
- Every review issue has a stable issue ID, immutable issue-version ID, and
  disposition.
- `RunSubmission` covers the complete successful role-closure chain, final lead
  closure, and every required manuscript artifact before validation.
- Publication replaces the complete current manuscript atomically.
- The reviewed snapshot and all review reports remain immutable.
- A later upstream change appends an authority event that gives the manuscript
  outdated derived alignment without rewriting it.
- The UI distinguishes manuscript alignment, scientific outcome, review outcome,
  and submission recommendation.

## Prohibited behavior

- The outside reviewer cannot resolve theory, empirical, specialist-audit, or
  internal deliberation objects outside `p5.review_packet`.
- No review result starts another review, upstream rerun, or submission.
