# S27: Revalidation After Validator Policy Change

## Purpose

Verify that a revalidation action re-checks unchanged output bytes against the
current policy version without a model call, records a new validation attempt,
and preserves the original output digest.

## Initial state

- A completed role output was previously withheld because one or more findings
  blocked publication under the old policy version.
- The policy registry has since been updated: a finding code was reclassified
  from blocking to non-blocking, or a schema constraint was relaxed.

## User action

The researcher requests revalidation of the unchanged output. The action
requires an explicit click but no new scientific authority.

## Expected behavior

- The harness re-runs validation against the sealed raw or last candidate
  output with the current policy version.
- The revalidation produces a new `ValidationAttempt` linked to the prior
  attempt, recording the policy version, complete findings, and overall
  conformance decision.
- The output digest is unchanged: the revalidation makes no transformation,
  model call, or content change.
- If the new policy passes all blocking checks, publication proceeds under the
  original launch authority.
- If blocking findings remain, the run stays in `needs_output_correction`.

## Prohibited behavior

- Revalidation cannot modify the output bytes.
- Revalidation cannot launch a new Hermes invocation.
- Revalidation cannot change the method, phase scope, or context basis.
- Revalidation cannot mutate the prior validation attempt.
