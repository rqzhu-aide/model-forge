# S29: Warning-Only Publication

## Purpose

Verify that an honest negative, inconclusive, contradictory, or open scientific
result publishes under the original launch authority when no blocking finding
remains, and that advisory findings remain visible after publication.

## Initial state

- A completed role output represents honest science with a non-positive
  outcome: a failed proof attempt with counterexample, an inconclusive
  empirical diagnostic, a contradicted statement retracted honestly, an open
  proof obligation, or a justified not-applicable category.
- The output has advisory findings (`SCIENTIFIC_ATTENTION` or `INFORMATION`
  class) but no blocking findings.

## User action

The user launched the run. No additional approval step is required.

## Expected behavior

- The run publishes under the original launch authority when all blocking
  checks pass.
- Advisory findings (`SCIENTIFIC_ATTENTION`, `INFORMATION`) are retained as
  visible warnings or attention items after publication.
- The scientific outcome is recorded with its honest label: negative,
  inconclusive, contradictory, open, or not applicable.
- The UI shows the scientific outcome and any advisory findings without
  suggesting the work failed.
- A justified empty category does not require fabricated "not applicable" prose
  to satisfy `minItems`.

## Prohibited behavior

- The harness cannot require artificial positive content (a fabricated claim,
  a forced proof, or filler prose) as a condition of publication.
- The harness cannot hide advisory findings after publication.
- The harness cannot block publication solely because the scientific outcome is
  negative, inconclusive, or contradictory when the representation is honest.
- The harness cannot add a separate post-run approval step.
