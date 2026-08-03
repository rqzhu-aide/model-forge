# S07: P4 Evidence Revalidation

## Purpose

Verify cumulative empirical evidence, immutable identity, and revalidation.

## Initial state

- A current P4 evidence index contains several current results.
- A method-definition change has made two method-dependent results outdated.

## User action

The user launches a P4 preliminary or comprehensive rerun to reassess the two
results.

## Expected behavior

- The earlier evidence IDs and artifacts remain unchanged. Their authority events preserve `outdated` derived alignment and exclude them from exact-method eligibility.
- New code, configuration, and results are stored in the new run folder.
- Successful recomputation receives new evidence IDs.
- The cumulative evidence history contains both the old lineage and the new
  evidence.
- The current evidence index treats only exact-current-method evidence as
  eligible and references the older evidence IDs only through explicit
  exclusions.
- The empirical synthesis states what changed and what remains unresolved.

## Prohibited behavior

- Evidence computed for the older method identity cannot become included for the new exact method identity.
- New evidence cannot point to an artifact outside its run or formal immutable
  source location.
- A successful computation does not automatically imply favorable evidence.
