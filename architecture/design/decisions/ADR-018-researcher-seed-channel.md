# ADR-018: Researcher Seed Channel for Run Inputs

Status: Superseded (2026-08-28) by ADR-019 - seeds are additive
supplementary material only; a seed can never replace a required
published input.
References: S31 (researcher supplementary material)

## Context

Run inputs resolve exclusively from published current records. A
researcher who holds a draft that never passed through a phase - written
by hand, salvaged from an earlier project, or produced outside the system
- had no legal way to make a run continue from it. The only door was
publishing the draft through a phase, which is circular when the draft is
the object the run should work on.

The P5 unification (required_on_rerun semantics) made the gap concrete:
continuation requires a current manuscript record, so a never-published
draft could never be continued.

## Decision

The run command accepts an optional `seed_inputs` map from contract input
id to inline content plus media type.

- **Sealed, not side-channelled.** Seeds live inside the run-command
  schema, so they enter the sealed command's content digest. A seeded run
  is exactly reproducible from its command alone.
- **Seed as synthetic record.** At preparation, seed bytes are
  content-addressed into the artifact store and wrapped in a record
  reference (generation `seed`, the run's selected method identity
  attached). The seed replaces current-record resolution for that input
  and counts as present for rerun detection.
- **Honest provenance.** The frozen manifest marks seeded inputs
  `origin: "researcher_seed"`; published inputs keep
  `origin: "current_record"`. The audit trail never confuses the two.
- **Declared inputs only.** A seed for an input the contract does not
  declare fails preparation with `input.unknown_seed`.
- **Stale-basis exemption, scoped.** The generation-drift guard skips
  seeded inputs - the command itself declares the override - while
  continuing to reject drift on every other input.

Rejected alternatives:

- *Publish the draft through a synthetic phase first.* Circular for the
  continuation use case and pollutes the record lineage with a
  publication nobody reviewed.
- *Seed via the workspace filesystem.* Invisible to the sealed command;
  the run would not be reproducible from its manifest.

## Consequences

- The run-command schema gains the optional `seed_inputs` object;
  seedless commands are byte-compatible with the previous shape, so no
  example or digest cascade was needed.
- The UI does not yet expose the seed channel; it is API-only until a
  phase-page affordance is designed.
- A seed is authoritative for its run only. It never becomes a current
  record by itself; publication still flows through the normal gates.
