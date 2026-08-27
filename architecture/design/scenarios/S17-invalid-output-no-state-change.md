# S17: Exit Zero Alone Never Passes Validation

`scenario_id: s17.invalid_output_no_state_change`

## Purpose

Verify that a run whose process exited zero still fails validation when its
outputs are missing, malformed, wrong-basis, or undeclared, and that such a
run changes no current state.

## Contract under test

- ADR-012 invariant (failed, cancelled, timed-out, invalid, or unresolved
  work cannot become current): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 5, fixed rule 5, and acceptance item 6 (exit-zero with
  missing, malformed, wrong-basis, or undeclared outputs fails validation
  and changes no current state):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-65 (exit
  code zero alone is never sufficient), MF-04 (validation precedes formal
  generation) and MF-12 (invalid work cannot replace current state).
  Invariants INV-006 and INV-017.

## Setup

- A valid current project-role state and current formal records exist with
  recorded digests.
- One run declares the output contract `method_proposals` at
  `outputs/method-proposals.json`.

## Steps

Run four separate trials. Each Hermes process exits zero.

1. Missing output: the agent writes nothing to `outputs/`.
2. Malformed output: the agent writes a JSON file that fails strict parsing
   or omits a required scientific field.
3. Wrong-basis output: the agent writes a well-formed file naming a run,
   method, or phase identity that does not match the sealed manifest basis.
4. Undeclared output: the agent writes an extra file under `outputs/` that no
   contract declares.

## Expected evidence

- Every trial produces a validation verdict of `fail` with the failing check
  named (inventory, schema, identity, or undeclared-file).
- No promotion record is created; current formal records and current
  project-role memory and session state remain byte-identical.
- The raw run directory and bounded diagnostics are preserved for review.
- Pilot evidence (attempt 1): in the project-004-eld pilot, run
  `p2s1-theorist-001` exited zero but the agent wrote the declared
  `method-proposals.json` under `workspace/outputs/` instead of the declared
  `outputs/` path. Validation refused promotion
  (`"method_proposals: declared output is missing or not a regular file"` in
  `run_validation_reports`), no promotion record was created, and the
  project-role state stayed unchanged.

## Failure conditions

- An exit code of zero is treated as success.
- A missing, malformed, wrong-basis, or undeclared output is promoted.
- The failed attempt is hidden or deleted.
- Current pointers or role state change on a failed validation.
