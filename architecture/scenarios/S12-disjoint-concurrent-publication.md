# S12: Disjoint Concurrent Publication

`scenario_id: s12.disjoint_concurrent_publication`

## Purpose

Verify that two research runs with disjoint method targets can both publish while
the authority journal retains one total order, and that two runs targeting the
same logical slot still fail closed.

## Initial formal state

- Active methods `method.alpha` and `method.beta` have exact current identities.
- Each method has an independent current Phase 3 theory slot.
- The current index is `generation.current_index.060` with digest `I60`.
- The authority journal ends at sequence 60 with root `E60`.
- No hard dependency of either theory slot is changed during the scenario.

## User actions and frozen bases

The user separately starts two eligible Phase 3 runs:

1. Run A targets the current theory slot for `method.alpha`.
2. Run B targets the current theory slot for `method.beta`.

Both commands are independently authenticated. Each run freezes its exact method
identity, phase contract, inputs, expected prior generation for its own theory
slot, and complete publication read and write sets. Neither run may read the
other run's unpublished work.

## Disjoint publication

Both runs complete the required theorist, analyst, and lead sequence and produce
valid immutable submissions. The publisher serializes their commits.

Run A commits first:

- Its target and hard dependencies still match its frozen basis.
- Its formal generation and authority events append after `E60`.
- Its receipt records the contiguous event range, new root `EA`, replacement of
  only the `method.alpha` theory slot, and current index `I61`.

Run B then enters its commit check:

- The publisher compares Run A's receipt changes with Run B's sealed target and
  hard-dependency read set and proves that they are disjoint.
- Run B's expected `method.beta` target generation and every hard dependency
  still match.
- Run B's scientific content, frozen inputs, and expected target are not rebased.
- Its events append after the actual immediately preceding root `EA`.
- Its receipt names `EA` as the prior event root and records current index `I62`,
  which contains both Run A and Run B updates.

## Expected formal state

- Both runs are `published`.
- The global authority-event sequence is contiguous and totally ordered.
- Each event appears exactly once in its publication receipt.
- The final current index contains the new `method.alpha` and `method.beta`
  theory generations, with all unrelated slots preserved.
- Replaying through Run B's receipt reproduces every affected projection and
  `I62` exactly.
- The two immutable submissions and their frozen scientific bases are unchanged.

## Same-target control case

Repeat the experiment with Runs C and D both expecting the same current
`method.alpha` theory generation. Run C commits first. Run D then observes that
its expected target generation changed, enters `conflicted`, and publishes no
generation, authority event, projection, index, or receipt. The system may offer
the user a new run on the current basis, but cannot silently rebase Run D.

## Expected UI communication

- Concurrent active runs are shown separately with their exact method targets.
- After both disjoint commits, both method rows show their new current theory
  records and publication times.
- A global journal advance alone is not described as a scientific conflict when
  the backend proves disjointness.
- The same-target conflict identifies the changed target, states that formal
  records were not changed by Run D, and offers refresh and rerun actions.

## Prohibited behavior

- The publisher cannot use last-writer-wins for the same logical slot.
- Run B cannot inherit Run A's scientific content or undeclared context.
- The second receipt cannot claim `E60` as its prior root after Run A committed.
- A client declaration of disjointness cannot replace backend read-set and
  write-set verification.
- The final index cannot omit either successful disjoint update.
