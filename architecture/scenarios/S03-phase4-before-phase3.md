# S03: P4 Runs Before P3

## Purpose

Verify that P3 and P4 are independent after P2 while remaining aware of current
sibling information when it exists.

## Initial state

- P1 and P2 current records exist.
- The user has selected an active method.
- No P3 or P4 record exists for that method.

## User action

The user launches P4 in preliminary scope before running P3.

## Expected behavior

- The manifest records that no P3 sibling basis was available.
- Analyst, theorist, and lead execute in that fixed order.
- Each role has a validated immutable prepared context, invocation start, and terminal closure. The theorist starts only after the analyst closure fixes every accepted input, and the lead starts only after both required upstream closures validate.
- The immutable P4 submission covers all three successful closures in order and every required accepted output.
- P4 publishes a cumulative evidence record bound to the exact method identity.
- Absence of P3 is reported as missing sibling information, not as proof that the
  method lacks theoretical support.

The user then launches P3.

- P3 receives the current P4 evidence index, empirical synthesis, and implementation record as its structured sibling basis.
- The theorist uses relevant empirical information without treating it as proof.
- P3 publishes one current theory record and records the exact P4 basis considered.

## Prohibited behavior

- P4 does not automatically launch P3.
- P3 does not rewrite the P4 record.
- Neither phase substitutes its evidence type for the other.
