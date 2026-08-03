# S02: Full-Catalog and Focused P2 Reruns

## Purpose

Verify that the user controls Phase 2 scope and that a focused run cannot alter
nonselected methods.

## Initial state

- A current P1 record exists.
- The P2 catalog contains at least three active methods.

## Full-catalog action

The user launches `p2.full_catalog`. The harness freezes the complete catalog
and P1 basis. The promoted result may add, revise, or retain methods and may
recommend retirement while preserving permanent identities and lineage. A
method lifecycle change requires a separate authenticated retire or reactivate
command. Method merging is outside the current contract.

## Focused action

The user later launches `p2.focused_method` for one active method. The command
must supply `p2.selected_method` in `choice_values`. The harness freezes
the selected method identity and exact bytes or digests for all catalog entries.
Only the selected method may change.

## Acceptance checks

- The focused method is copied exactly from command to run manifest under
  `p2.selected_method`.
- Full and focused work are represented only by their mode IDs; a contradictory
  second scope field is rejected.
- All nonselected method records remain unchanged.
- A mathematical-definition change requires a new version.
- A prose-only change outside the authoritative definition retains the version.
- The lead reports catalog changes and user options without choosing a branch.
- Any attempt to add, remove, merge, rename, or retire through focused scope is
  rejected.
- A retirement recommendation alone cannot change a method's lifecycle state.
