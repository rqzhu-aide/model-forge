# ADR-001: Contract-Bound Run Choices

## Status

Accepted

## Context

A fixed command envelope represented method, scope, instructions, and history in
generic fields while phase contracts represented the same decisions with
phase-specific choice IDs. Phase 1 search scope could not be represented, and
Phase 2, Phase 4, and Phase 5 could express contradictory mode and scope values.
Programmers need one authoritative interpretation of each user decision.

## Invariants that must remain true

- The user selects every run and rerun.
- A command must not acquire a broader scientific scope during preparation.
- The selected method and history must remain exact, typed user choices.
- The Web UI and remote client must submit the same command.

## Options considered

### Option A: Fixed generic fields

Keep separate mode, scope, target method, instructions, and selected history
fields, then maintain phase-specific conditional rules in the global command
schema. This duplicates the executable phase contracts and can drift when a
phase adds or removes a choice.

### Option B: Exact contract choice map

Use mode as the sole executable selector and store other phase-defined inputs in
choice_values, keyed by the exact choice IDs in one versioned phase contract.

## Decision

Select Option B. Every RunCommand binds one phase-contract version and digest,
selects one declared mode, and supplies only that mode's required or optional
choice IDs. Each choice declares its value kind. The manifest copies the command
contract identity, mode, and choices exactly.

Phase 1 retains p1.scope because broad and focused searches share one executable
mode. Full and focused Phase 2, preliminary and comprehensive Phase 4, and
assembly and review-revision Phase 5 are distinct modes and are not duplicated
as scope choices. A method-bound mode declares its exact method choice ID.

## Consequences

### Benefits

- Phase 1 search scope is representable.
- Contradictory mode and scope pairs cannot be encoded.
- Focused Phase 2 cannot omit the method identity.
- Future choices can be added without expanding fixed command fields.
- UI controls, remote commands, harness preparation, and tests share one choice
  vocabulary.

### Costs and risks

- Command and manifest readers must resolve choice IDs through the bound
  contract.
- The command envelope and executable phase contracts advance to version 2.
- Existing version 1 commands would remain immutable and require a version 1
  reader. This greenfield package contains no persisted production commands, so
  no data migration is required now.

## Contract changes

- Research domain model and run harness define exact contract-bound choices.
- Phase contracts declare value_kind, method_choice_id, and history_choice_id.
- UI and validation specifications use one mode selector and one choice map.

## Schema changes

- RunCommand and RunManifest use choice_values and bind exact contract version
  and digest.
- Generic scope, method, instruction, and history fields are removed from those
  envelopes.
- Executable phase contracts use contract version 2.0.0.

## Scenario changes

- S01 covers both Phase 1 search-scope values.
- S02 covers full and focused Phase 2 modes and required focused-method identity.
- S03, S08, and the package probes cover the remaining mode choices.
