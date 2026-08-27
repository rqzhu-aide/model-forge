# S04: Calculation-defining method change

## Purpose

Verify exact method identity, immutable earlier generations, and event-derived
downstream alignment.

## Initial state

- One active method has current P3, P4, and P5 generations.
- Every generation refers to the same stable ID, version, and definition digest.
- Their derived record states are exact and their generation digests are known.

## User action

The user launches a P2 rerun that changes the authoritative mathematical
definition in a way that can change a calculation.

## Expected behavior

- P2 requires the next positive integer method version and a new definition
  digest.
- The stable method ID remains unchanged.
- The P2 publication appends authority events for every affected P3, P4, and P5
  generation.
- The latest P3 and P4 generations remain current in derived position, while
  their derived alignment becomes `outdated` for the new method version.
- Earlier method-dependent P4 evidence remains formal and traceable, but its
  derived evidence eligibility becomes excluded for the new method.
- The current P5 manuscript remains readable and current in position, while its
  derived alignment becomes `outdated`.
- The bytes and digests of every earlier P3, P4, P5, and evidence generation
  remain unchanged.
- None of the outdated records can satisfy the exact-method Phase 5 gate.
- The UI names the changed method identity, shows P3 and P4 as needing
  reassessment, and offers user-controlled P3, P4, and P5 reruns.

## Prohibited behavior

- No downstream rerun starts automatically.
- Old proof or empirical records do not remain aligned merely because the stable
  ID is unchanged.
- A method-version change does not delete or rewrite earlier evidence, proofs,
  or manuscripts.
- A dependency change alone does not move a current generation to history.
  Derived history changes only when a replacement generation is published.
