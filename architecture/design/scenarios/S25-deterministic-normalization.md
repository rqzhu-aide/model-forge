# S25: Deterministic Normalization Applied and Disclosed

## Purpose

Verify that an allowlisted mechanical normalization may fix a correctable
representation defect without a model call, that it does not alter primary
scientific content, and that the researcher can inspect the exact
transformation before and after it is applied.

## Initial state

- A completed role output exists with a correctable representation defect:
  for example, a missing timestamp at a schema-declared path, an unsanitized
  identifier, or a stale self-referential hash.
- The scientific content of the output is complete and correct.

## User action

The researcher requests deterministic normalization of the preserved raw
output. The action is covered by the original launch authority because it is
mechanical, not scientific.

## Expected behavior

- The harness applies only allowlisted transformation codes: timestamp
  injection at schema-declared paths, identifier sanitization, hash
  recomputation, or additional-properties stripping with a recorded finding.
- Each transformation is recorded in an immutable `OutputTransformationRecord`
  with source digest, result digest, affected paths, before and after values
  when bounded, harness version, and confirmation that no primary scientific
  artifact changed.
- The normalized candidate enters validation. If it passes all blocking checks,
  publication proceeds under the original launch authority.
- The raw output digest remains recoverable and is recorded on the role closure
  as evidence.
- The UI shows the exact diff between raw and candidate.

## Prohibited behavior

- The normalization cannot inject a field outside its schema path.
- The normalization cannot alter a scientific claim, assumption, result,
  citation, or provenance assertion.
- The normalization cannot lose useful content without a recorded finding.
- The normalization cannot silently rewrite the raw output bytes.
