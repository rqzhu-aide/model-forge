# S31: Researcher Supplementary Material

## Purpose

Verify the additive seed channel (ADR-019, superseding ADR-018): a
researcher working inside an existing, already-started project can hand
additional material to a run - for example their own partial code at
Phase 4 - frozen with researcher_seed provenance, without ever replacing
the pipeline's published state.

## Initial state

- A project with published phases whose next run declares the
  supplementary slot `pN.researcher_material` (all five phases do).
- The researcher holds material that never passed through any phase
  (their own paper at P1, partial code at P4, figures at P5).

## User action

The researcher launches the run with `seed_inputs` in the run command:
the supplementary input id mapped to inline content and a media type.

## Expected behavior

- The sealed run command carries the seeds inside its content digest, so
  the seeded run is exactly reproducible.
- At preparation, each seed's bytes are content-addressed into the
  artifact store and wrapped in a synthetic record reference carrying the
  run's selected method identity.
- The frozen manifest records the supplementary input with
  `origin: "researcher_seed"`; every required input keeps
  `origin: "current_record"` and still resolves from published current
  records. The audit trail shows exactly which material came from the
  researcher.
- A seed is additive only: it never satisfies a required input, never
  counts for rerun detection, and never turns a first run into a
  continuation.
- The stale-basis generation guard compares published inputs only; a
  frozen supplementary seed simply is not part of that comparison, and
  drift on any published input is still rejected.
- A researcher's own paper enters at P1 as seeded supplementary material;
  there is no door that lands a finished foreign manuscript in P5.

## Negative checks

- A seed naming a required published input (for example
  `p5.current_manuscript`) fails preparation with
  `input.seed_replaces_published_input`; nothing about the run proceeds.
- A seed naming an input the contract does not declare fails preparation
  with `input.unknown_seed`.
- A command whose seed has empty content fails schema validation at seal.
- A seeded run that is cancelled before execution leaves current records
  unchanged; the seed content exists only in the artifact store.

## Implementation evidence

- Input resolution: `tests/test_input_resolution.py` (seeded
  supplementary slot is additive with provenance, seed does not trigger
  rerun detection, seed targeting a required input rejected, unknown seed
  rejected, disallowed and unknown seeds reported together).
- Command sealing: `tests/test_run_command_builder.py` (seeded command
  validates and binds seeds inside the content digest; malformed seed
  rejected at seal).
- Stale-basis interaction:
  `tests/test_sealed_basis.py::test_sealed_basis_ignores_additive_seeded_inputs`.
- Superseded semantics: run
  `run.p5.p5-assembly.ba0dd8a366b44d2bb17ce049b5f4a30e` (2026-08-28)
  froze a seeded `p5.current_manuscript` under ADR-018 and was cancelled
  before execution; under ADR-019 that command shape is rejected at
  preparation.
