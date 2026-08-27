# HV-7 Calibration Corpus

Test cases covering valid-but-diverse structures, honest scientific edge
cases, correctable packaging defects, genuine integrity violations, and
publication conflicts.

## Directory structure

Each case is a self-contained directory with:
- `input/` -- raw agent output (the bytes the agent produced)
- `expected/` -- expected validation decision and finding classes
- `description.md` -- what the case tests

## Case index

### Valid but structurally diverse
- `case-001-sparse-output/` -- minimal valid content per phase
- `case-002-dense-output/` -- complex multi-object records
- `case-003-full-pipeline/` -- full P1→P5 from a real run

### Honest scientific edge cases
- `case-010-negative-theory/` -- theory contradicted by evidence
- `case-011-null-empirical/` -- empirical null finding
- `case-012-inconclusive-proof/` -- open proof obligation
- `case-013-retracted-statement/` -- statement retracted with reason
- `case-014-failed-proof-counterexample/` -- counterexample to a conjecture
- `case-015-reviewer-no-strengths/` -- outside reviewer reports no strengths

### Correctable packaging defects
- `case-020-malformed-json/` -- JSON decode error (original preserved)
- `case-021-missing-harness-field/` -- undeclared field in closed schema
- `case-022-wrong-timestamp/` -- wrong timestamp format

### Genuine integrity violations (must reject)
- `case-030-wrong-identity/` -- wrong method identity
- `case-031-wrong-basis/` -- wrong frozen basis
- `case-032-false-provenance/` -- fabricated citation chain
- `case-033-digest-mismatch/` -- content hash mismatch
- `case-034-unsafe-path/` -- path traversal attempt

### Publication conflicts
- `case-040-head-conflict/` -- basis changed during promotion

## Notes

These cases are fixtures for the acceptance matrix tests and the shadow
comparison. They exercise the full validation pipeline end-to-end.

Cases requiring real model calls (targeted correction) use crafted fixtures
rather than live runs.
