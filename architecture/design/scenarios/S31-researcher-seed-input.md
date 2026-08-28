# S31: Researcher Seed Input

## Purpose

Verify the researcher seed channel (ADR-018): a never-published draft can
be handed to a run as the content of a declared contract input, frozen with
researcher_seed provenance, without pretending to be published state.

## Initial state

- A project with published phases whose next run declares an input the
  researcher wants to supply directly (for example P5 assembly with
  `p5.current_manuscript`).
- The researcher holds a draft that never passed through any phase.

## User action

The researcher launches the run with `seed_inputs` in the run command:
the contract input id mapped to inline content and a media type.

## Expected behavior

- The sealed run command carries the seeds inside its content digest, so
  the seeded run is exactly reproducible.
- At preparation, each seed's bytes are content-addressed into the
  artifact store and wrapped in a synthetic record reference carrying the
  run's selected method identity.
- The frozen manifest records the input with `origin: "researcher_seed"`;
  every other input keeps `origin: "current_record"`. The audit trail
  shows exactly which inputs came from published state and which from the
  researcher.
- A seed is present for rerun detection: a seeded `required_on_rerun`
  input resolves as continuation, and required seeded inputs must stay
  selected like any required input.
- The stale-basis generation guard does not read the seed's synthetic
  generation as drift; drift on any non-seeded input is still rejected.
- A seed naming an input the contract does not declare fails preparation
  with `input.unknown_seed`; nothing else about the run proceeds.

## Negative checks

- A command whose seed has empty content fails schema validation at seal.
- A seeded run that is cancelled before execution leaves current records
  unchanged; the seed content exists only in the artifact store.

## Implementation evidence

- Input resolution: `tests/test_input_resolution.py` (seed fills the
  absent rerun slot with provenance, seed overrides a published record,
  unknown seed rejected, required seed must stay selected).
- Command sealing: `tests/test_run_command_builder.py` (seeded command
  validates and binds seeds inside the content digest; malformed seed
  rejected at seal).
- Stale-basis interaction:
  `tests/test_sealed_basis.py::test_sealed_basis_skips_generation_check_for_seeded_inputs`.
- Production: run `run.p5.p5-assembly.ba0dd8a366b44d2bb17ce049b5f4a30e`
  (2026-08-28) froze a seeded `p5.current_manuscript` with
  researcher_seed provenance and was cancelled before execution.
